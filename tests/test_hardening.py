import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Label, PrintJob, Product, Printer


def login(client):
    page = client.get('/login'); token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post('/login', data={'email': 'admin@markify.local', 'password': 'ChangeMe-Please-2026!', 'csrf_token': token}, follow_redirects=False)
    assert r.status_code == 303


def csrf(client):
    r = client.get('/')
    assert r.status_code == 200
    m = re.search(r'data-csrf="([^"]+)"', r.text)
    assert m
    return m.group(1)


def test_all_main_pages_are_renderable():
    with TestClient(app) as c:
        login(c)
        for path in ['/', '/products', '/history', '/printers']:
            r = c.get(path)
            assert r.status_code == 200, (path, r.text[:500])


def test_patch_update_does_not_reset_unsent_fields():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        products = c.get('/api/products').json()['items']
        pid = products[0]['id']
        original = products[0]
        r = c.patch(f'/api/products/{pid}', headers={'X-CSRF-Token': token}, json={'name': original['name'] + ' X'})
        assert r.status_code == 200, r.text
        db = SessionLocal()
        try:
            p = db.get(Product, pid)
            assert p.label_mode == original['label_mode']
            assert p.shelf_life_status == original['shelf_life_status']
        finally:
            db.close()


def test_manual_print_flow_creates_labels_and_print_page():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        pr = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Xprinter Test','driver':'xprinter','host':'127.0.0.1'}); assert pr.status_code == 200
        printer_id = pr.json()['id']
        p = c.get('/api/products').json()['items'][0]
        future_local = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None, second=0, microsecond=0)
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id': p['id'], 'quantity': 3, 'printer_id': printer_id, 'expires_at': future_local.isoformat(timespec='minutes')})
        assert r.status_code == 200, r.text
        job_id = r.json()['job_id']
        page = c.get(f'/print/job/{job_id}')
        assert page.status_code == 200
        assert page.text.count('class="sheet"') == 3
        db = SessionLocal()
        try:
            labels = db.scalars(select(Label).where(Label.print_job_id == job_id)).all()
            assert len(labels) == 3
        finally:
            db.close()


def test_reprint_creates_new_chain():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        pr = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Xprinter Test','driver':'xprinter','host':'127.0.0.1'}); assert pr.status_code == 200
        printer_id = pr.json()['id']
        p = c.get('/api/products').json()['items'][0]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id': p['id'], 'quantity': 1, 'printer_id': printer_id, 'expires_at': future})
        assert r.status_code == 200
        job_id = r.json()['job_id']
        db = SessionLocal(); src = db.scalar(select(Label).where(Label.print_job_id == job_id)); src_id = src.id; db.close()
        db = SessionLocal(); src = db.get(Label, src_id); src.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1); db.commit(); db.close()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id': p['id'], 'quantity': 1, 'reprint_of_label_id': src_id, 'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        assert r.status_code == 200, r.text
        new_job = r.json()['job_id']
        db = SessionLocal();
        try:
            new_label = db.scalar(select(Label).where(Label.print_job_id == new_job))
            assert new_label.reprint_of_id == src_id
            assert db.get(Label, src_id).expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
        finally:
            db.close()


def test_printer_crud_and_token_is_not_stored_plaintext():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        r = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Beta ZPL','driver':'zpl','host':'127.0.0.1','port':9100})
        assert r.status_code == 200, r.text
        data = r.json(); assert data['agent_token']
        db = SessionLocal()
        try:
            p = db.get(Printer, data['id'])
            assert p.agent_token_hash != data['agent_token']
            assert len(p.agent_token_hash) == 64
        finally: db.close()
        r = c.patch(f"/api/printers/{data['id']}", headers={'X-CSRF-Token': token}, json={'name':'Beta ZPL 2'})
        assert r.status_code == 200, r.text
        r = c.delete(f"/api/printers/{data['id']}", headers={'X-CSRF-Token': token})
        assert r.status_code == 200, r.text


def test_agent_claim_is_single_owner():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        r = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Race','driver':'zpl','host':'127.0.0.1'})
        assert r.status_code == 200
        printer_id, agent_token = r.json()['id'], r.json()['agent_token']
        p = c.get('/api/products').json()['items'][0]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id':p['id'],'quantity':1,'printer_id':printer_id,'expires_at':future})
        assert r.status_code == 200; job_id=r.json()['job_id']
        h={'Authorization':f'Bearer {agent_token}'}
        first=c.post(f'/api/agent/jobs/{job_id}/claim',headers=h); second=c.post(f'/api/agent/jobs/{job_id}/claim',headers=h)
        assert first.json()['ok'] is True
        assert second.json()['ok'] is False
        assert second.json()['status'] == 'printing'


def test_agent_complete_and_fail_are_idempotent_enough():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        r = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Agent','driver':'zpl','host':'127.0.0.1'}); assert r.status_code == 200
        pid, agent_token = r.json()['id'], r.json()['agent_token']
        p = c.get('/api/products').json()['items'][0]
        future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'quantity':1,'printer_id':pid,'expires_at':future}); assert r.status_code==200
        jid=r.json()['job_id']; h={'Authorization':f'Bearer {agent_token}'}
        claim = c.post(f'/api/agent/jobs/{jid}/claim', headers=h).json(); assert claim['ok']
        h['X-Print-Claim'] = claim['claim_token']
        assert c.post(f'/api/agent/jobs/{jid}/complete',headers=h).json()['status']=='completed'
        assert c.post(f'/api/agent/jobs/{jid}/complete',headers=h).json()['ok'] is False


def test_unauthorized_pages_redirect_and_api_is_401():
    with TestClient(app) as c:
        r=c.get('/',follow_redirects=False); assert r.status_code==303 and r.headers['location']=='/login'
        r=c.get('/api/products'); assert r.status_code==401


def test_seeded_catalog_is_not_recreated_after_product_rename():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        products = c.get('/api/products').json()['items']
        assert len(products) == 147
        pid = products[0]['id']
        original = products[0]['name']
        r = c.patch(f'/api/products/{pid}', headers={'X-CSRF-Token': token}, json={'name': original + ' (тест)'})
        assert r.status_code == 200
        # Startup of another client must not add the original seeded product back.
        with TestClient(app) as c2:
            login(c2)
            assert len(c2.get('/api/products').json()['items']) == 147
            assert any(x['name'] == original + ' (тест)' for x in c2.get('/api/products').json()['items'])


def test_agent_fail_does_not_overwrite_completed_job():
    with TestClient(app) as c:
        login(c); token = csrf(c)
        r = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'FailGuard','driver':'zpl','host':'127.0.0.1'}); assert r.status_code == 200
        printer_id, agent_token = r.json()['id'], r.json()['agent_token']
        p = c.get('/api/products').json()['items'][0]
        future=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'quantity':1,'printer_id':printer_id,'expires_at':future}); assert r.status_code==200
        jid=r.json()['job_id']; h={'Authorization':f'Bearer {agent_token}'}
        claim = c.post(f'/api/agent/jobs/{jid}/claim', headers=h).json(); assert claim['ok']
        h['X-Print-Claim'] = claim['claim_token']
        assert c.post(f'/api/agent/jobs/{jid}/complete',headers=h).json()['status']=='completed'
        r=c.post(f'/api/agent/jobs/{jid}/fail',headers=h,json={'error':'late error'})
        assert r.status_code==200 and r.json()['ok'] is False and r.json()['status']=='completed'


def test_login_csrf_and_logout_protection():
    with TestClient(app) as c:
        page = c.get('/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        bad = c.post('/login', data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!'}, follow_redirects=False)
        assert bad.status_code == 403
        good = c.post('/login', data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!','csrf_token':token}, follow_redirects=False)
        assert good.status_code == 303
        bad_logout = c.post('/logout', data={'csrf_token':'bad'}, follow_redirects=False)
        assert bad_logout.status_code == 403
        page = c.get('/')
        token2 = re.search(r'data-csrf="([^"]+)"', page.text).group(1)
        good_logout = c.post('/logout', data={'csrf_token':token2}, follow_redirects=False)
        assert good_logout.status_code == 303 and good_logout.headers['location'] == '/login'
