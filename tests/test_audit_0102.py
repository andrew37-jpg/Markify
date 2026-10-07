"""Regressions reproduced during the audit of the supplied 0.10.0 archive."""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import SessionLocal
from app.models import Label, PrintJob, Printer, Product, User, Location, Organization
from app.services import utcnow, token_hash, password_hash


@pytest.fixture
def web():
    with TestClient(app) as client:
        page = client.get('/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        assert client.post('/login', data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!','csrf_token':token}, follow_redirects=False).status_code == 303
        token = re.search(r'data-csrf="([^"]+)"', client.get('/').text)[1]
        client.headers['X-CSRF-Token'] = token
        yield client


def setup_print(web, driver='xprinter', **config):
    response = web.post('/api/printers', json={'name':'Audit', 'driver':driver, 'host':'127.0.0.1', **config})
    assert response.status_code == 200, response.text
    p = web.get('/api/products').json()['items'][0]
    return p['id'], response.json()


def create_job(web, product_id, printer_id=None):
    payload = {'product_id':product_id, 'expires_at':(utcnow()+timedelta(hours=2)).isoformat()+'Z', 'quantity':2}
    if printer_id: payload['printer_id'] = printer_id
    response = web.post('/api/print-jobs', json=payload)
    assert response.status_code == 200, response.text
    return response.json()['job_id']


def claim(web, printer, job):
    headers={'Authorization':'Bearer '+printer['agent_token']}
    response=web.post(f'/api/agent/jobs/{job}/claim',headers=headers)
    assert response.json()['ok'], response.text
    headers['X-Print-Claim']=response.json()['claim_token']
    return headers


def test_default_printer_is_persisted_and_delivered(web):
    pid, pr = setup_print(web)
    job = create_job(web, pid)
    with SessionLocal() as db:
        assert db.get(PrintJob,job).printer_id == pr['id']
    queue=web.get('/api/agent/jobs',headers={'Authorization':'Bearer '+pr['agent_token']}).json()
    assert [x['id'] for x in queue['jobs']] == [job]


def test_auto_exact_copy_preserves_all_label_fields_after_product_edit(web):
    pid, pr=setup_print(web)
    assert web.patch(f'/api/products/{pid}',json={'shelf_life_minutes':120,'shelf_life_status':'verified','label_mode':'auto_from_shelf_life','shelf_life_basis':'Audit','storage_condition':'+2…+4 °C'}).status_code == 200
    job=create_job(web,pid,pr['id']); h=claim(web,pr,job)
    assert web.post(f'/api/agent/jobs/{job}/complete',headers=h).json()['ok']
    with SessionLocal() as db:
        original=db.scalar(select(Label).where(Label.print_job_id==job))
        original.created_at -= timedelta(minutes=10)
        original.expires_at -= timedelta(minutes=10)
        db.commit()
        fields=['created_at','expires_at','operator_name','department_id','department_name_snapshot','storage_condition_snapshot','shelf_life_snapshot_minutes','product_name_snapshot']
        expected={k:getattr(original,k) for k in fields}
    assert web.patch(f'/api/products/{pid}',json={'name':'Новое название','shelf_life_minutes':240,'storage_condition':'Новое условие'}).status_code==200
    response=web.post(f'/api/print-jobs/{job}/repeat'); assert response.status_code==200,response.text
    new=response.json()['job_id']
    with SessionLocal() as db:
        copied=db.scalar(select(Label).where(Label.print_job_id==new))
        assert {k:getattr(copied,k) for k in fields} == expected
        assert copied.status == 'copy'
    h=claim(web,pr,new)
    assert web.get(f'/api/agent/jobs/{new}/payload',headers=h).json()['product']['name']==expected['product_name_snapshot']
    assert len(web.get('/api/dashboard/state').json()['labels'])==2


def test_stale_claim_cannot_finish_retry(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id']); old=claim(web,pr,job)
    assert web.post(f'/api/agent/jobs/{job}/fail',headers=old,json={'error':'wire interrupted','uncertain':True}).json()['status']=='attention'
    assert web.post(f'/api/print-jobs/{job}/retry').status_code==200
    new=claim(web,pr,job)
    for action in ['heartbeat','complete','fail']:
        assert web.post(f'/api/agent/jobs/{job}/{action}',headers=old,json={}).status_code==409
    assert web.post(f'/api/agent/jobs/{job}/complete',headers=new).json()['ok']
    with SessionLocal() as db: assert db.get(PrintJob,job).attempt_count==2


def test_watchdog_works_without_agent_and_online_expires(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id']);claim(web,pr,job)
    with SessionLocal() as db:
        db.get(PrintJob,job).lease_expires_at=utcnow()-timedelta(seconds=1)
        db.get(Printer,pr['id']).last_seen_at=utcnow()-timedelta(minutes=2);db.commit()
    state=web.get('/api/dashboard/state').json()
    assert state['printers'][0]['online'] is False
    assert state['jobs'][0]['status']=='attention'


def test_expired_job_is_not_sent_or_retried(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id'])
    with SessionLocal() as db:
        for label in db.scalars(select(Label).where(Label.print_job_id==job)):label.expires_at=utcnow()-timedelta(seconds=1)
        db.commit()
    response=web.post(f'/api/agent/jobs/{job}/claim',headers={'Authorization':'Bearer '+pr['agent_token']})
    assert response.json()['ok'] is False
    assert web.post(f'/api/print-jobs/{job}/retry').status_code==409
    assert web.post(f'/api/print-jobs/{job}/repeat').status_code==422


@pytest.mark.parametrize('driver',['tsc','tspl','escpos','zpl','xprinter','raw9100'])
def test_all_network_drivers_require_host(web,driver):
    assert web.post('/api/printers',json={'name':'Bad','driver':driver}).status_code==422


@pytest.mark.parametrize('driver',['cups','atol','godex'])
def test_system_drivers_require_queue(web,driver):
    assert web.post('/api/printers',json={'name':'Bad','driver':driver}).status_code==422


def test_csrf_bearer_header_does_not_bypass_cookie_protection(web):
    token=web.headers.pop('X-CSRF-Token')
    assert web.post('/api/products',headers={'Authorization':'Bearer nonsense'},json={'name':'bypass'}).status_code==403
    web.headers['X-CSRF-Token']=token


def test_failed_login_preserves_csrf_and_rate_limits():
    with TestClient(app) as web:
        token=re.search(r'name="csrf_token" value="([^"]+)"',web.get('/login').text)[1]
        for _ in range(10):
            response=web.post('/login',data={'email':'unknown@example.invalid','password':'wrong','csrf_token':token})
            assert response.status_code==401
            assert f'value="{token}"' in response.text
        assert web.post('/login',data={'email':'unknown@example.invalid','password':'wrong','csrf_token':token}).status_code==429


def test_logout_revokes_copied_cookie(web):
    cookie=web.cookies.get('session');csrf=web.headers['X-CSRF-Token']
    assert web.post('/logout',data={'csrf_token':csrf},follow_redirects=False).status_code==303
    web.cookies.clear();web.cookies.set('session',cookie)
    assert web.get('/api/products').status_code==401


def test_password_rotation_revokes_old_cookie_and_returns_fresh_csrf(web):
    old=web.cookies.get('session')
    response=web.post('/api/account/password',json={'current_password':'ChangeMe-Please-2026!','new_password':'Audit-Secure-Password-2026'})
    assert response.status_code==200
    web.headers['X-CSRF-Token']=response.json()['csrf']
    assert web.post('/api/products',json={'name':'After password change'}).status_code==200
    web.cookies.clear();web.cookies.set('session',old)
    assert web.get('/api/products').status_code==401


@pytest.mark.parametrize('field',['name','category','storage_condition','label_mode','shelf_life_status'])
def test_product_null_returns_validation_error(web,field):
    pid=web.get('/api/products').json()['items'][0]['id']
    assert web.patch(f'/api/products/{pid}',json={field:None}).status_code==422


def test_browser_cannot_complete_direct_job_or_steal_claim(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id'])
    for action in ['opened','completed']:
        assert web.post(f'/api/print-jobs/{job}/{action}').status_code==409
    h={'Authorization':'Bearer '+pr['agent_token']}
    assert web.get(f'/api/agent/jobs/{job}/payload',headers=h).status_code==409
    assert web.post(f'/api/agent/jobs/{job}/complete',headers=h).status_code==409


def test_cancel_and_close_remove_from_control_preserve_history(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id'])
    assert web.post(f'/api/print-jobs/{job}/cancelled').status_code==200
    assert not web.get('/api/dashboard/state').json()['labels']
    job=create_job(web,pid,pr['id'])
    label=web.get('/api/dashboard/state').json()['labels'][0]['id']
    assert web.post(f'/api/labels/{label}/close').status_code==200
    assert len(web.get('/api/dashboard/state').json()['labels'])==1
    assert f'#{job}' in web.get('/history').text


def test_department_assignment_does_not_rewrite_label_history(web):
    pid,pr=setup_print(web);job=create_job(web,pid,pr['id'])
    dep=web.get('/api/departments').json()['items'][0]['id']
    assert web.patch(f'/api/departments/{dep}/products',json={'product_ids':[pid]}).status_code==200
    row=web.get('/api/dashboard/state').json()['labels'][0]
    assert row['department_name']=='Без цеха' and row['department_id'] is None


def test_real_agent_to_tcp_receiver_end_to_end(web,monkeypatch):
    from agent import agent
    received=[]
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);server.settimeout(10)
    def receive():
        conn,_=server.accept()
        with conn:
            chunks=[]
            while True:
                part=conn.recv(65536)
                if not part:break
                chunks.append(part)
            received.append(b''.join(chunks))
    thread=threading.Thread(target=receive,daemon=True);thread.start()
    try:
        pid,pr=setup_print(web,port=server.getsockname()[1]);job=create_job(web,pid)
        monkeypatch.setattr(agent,'HEAD',{'Authorization':'Bearer '+pr['agent_token']})
        agent.print_job(web,job)
        thread.join(10)
        assert received and received[0].count(b'PRINT 1,1')==2
        assert b'BITMAP' in received[0]
        assert web.get(f'/api/print-jobs/{job}/status').json()['status']=='completed'
    finally:server.close()


def test_cups_uses_driver_and_multi_page_layout(monkeypatch):
    from app.printer_adapters import send_cups
    from test_printer_adapters import payload
    p=payload('cups');p['printer']['queue_name']='Audit';p['labels']*=2
    captured=[]
    def run(args,**kwargs):
        assert 'raw' not in args
        assert args[0:3]==['lp','-d','Audit']
        captured.append(Path(args[-1]).read_bytes())
    monkeypatch.setattr(subprocess,'run',run)
    send_cups(p)
    assert captured[0].startswith(b'%!PS-Adobe-3.0')
    assert captured[0].count(b'showpage')==2


def test_agent_launch_and_prefixed_settings(tmp_path):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'agent/agent.py'),'--help'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    env={**os.environ,'PYTHONPATH':str(root),'MARKIFY_BOOTSTRAP_ADMIN_EMAIL':'audit@example.invalid'}
    result=subprocess.run([sys.executable,'-c','from app.config import Settings; print(Settings(_env_file=None).bootstrap_admin_email)'],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert result.stdout.strip()=='audit@example.invalid',result.stderr


def test_tenant_isolation_and_operator_permissions(web):
    with SessionLocal() as db:
        org=Organization(name='Другой ресторан');db.add(org);db.flush()
        loc=Location(name='Другая кухня',organization_id=org.id);db.add(loc);db.flush()
        p=Product(name='Чужой продукт',category='X',location_id=loc.id);db.add(p);db.flush();other_id=p.id
        own=db.scalar(select(User).where(User.email=='admin@markify.local'));own.role='operator';db.commit()
    assert web.patch(f'/api/products/{other_id}',json={'name':'test'}).status_code==403
    assert web.post('/api/print-jobs',json={'product_id':other_id}).status_code==404
    assert web.get('/printers').status_code==403
    assert 'id="addProductBtn"' not in web.get('/products').text
    with SessionLocal() as db:
        own=db.scalar(select(User).where(User.email=='admin@markify.local'));own.location_id=None;db.commit()
    assert web.get('/api/products').status_code==403


def test_printer_layout_has_independent_pages_and_refuses_overflow():
    from app.label_render import label_image,bitmap
    from app.printer_adapters import escpos,zpl,tspl
    from test_printer_adapters import payload
    p=payload();p['labels']*=2
    image=label_image(p,p['labels'][0]);assert image.size==(464,320)
    row,data=bitmap(image);_,inverse=bitmap(image,True)
    assert row==58 and len(data)==58*320
    assert all(a^b==255 for a,b in zip(data,inverse))
    assert zpl(p).count(b'^XA')==2
    assert escpos(p).count(b'\x1dV\x00')==2
    assert tspl(p).count(b'PRINT 1,1')==2
    p['printer'].update(width_mm=20,height_mm=15);p['product']['name']='Очень длинное название ' * 20
    with pytest.raises(ValueError,match='не помещается'):label_image(p,p['labels'][0])


def test_production_rejects_example_secret(monkeypatch):
    from app.main import settings,startup
    monkeypatch.setattr(settings,'environment','production')
    monkeypatch.setattr(settings,'session_secret','replace-with-a-long-random-secret')
    with pytest.raises(RuntimeError,match='SECRET'):startup()
