
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Location, PrintJob, Product


def login(c, password='ChangeMe-Please-2026!'):
    page = c.get('/login')
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = c.post('/login', data={
        'email': 'admin@markify.local', 'password': password,
        'csrf_token': token
    }, follow_redirects=False)
    assert r.status_code == 303


def csrf(c):
    r = c.get('/')
    return re.search(r'data-csrf="([^"]+)"', r.text).group(1)


def test_health_is_minimal_and_public():
    with TestClient(app) as c:
        r = c.get('/api/health')
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}


def test_direct_xprinter_job_never_opens_browser_print():
    with TestClient(app) as c:
        login(c)
        token = csrf(c)
        pr = c.post('/api/printers', headers={'X-CSRF-Token': token}, json={'name':'Xprinter','driver':'xprinter','host':'127.0.0.1'})
        assert pr.status_code == 200
        printer_id = pr.json()['id']
        p = c.get('/api/products').json()['items'][0]
        exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id': p['id'], 'quantity': 1, 'printer_id': printer_id, 'expires_at': exp})
        assert r.status_code == 200
        data = r.json()
        assert data['print_method'] == 'agent'
        assert 'print_url' not in data


def test_no_printer_means_no_pdf_fallback():
    with TestClient(app) as c:
        login(c)
        token = csrf(c)
        p = c.get('/api/products').json()['items'][0]
        exp = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token}, json={'product_id': p['id'], 'quantity': 1, 'expires_at': exp})
        assert r.status_code == 409
        assert 'Xprinter' in r.json()['detail']


def test_stale_agent_job_requires_review_before_retry():
    with TestClient(app) as c:
        login(c)
        token = csrf(c)
        r = c.post('/api/printers', headers={'X-CSRF-Token': token},
                   json={'name': 'Lease Test', 'driver': 'zpl', 'host': '127.0.0.1'})
        printer_id, agent_token = r.json()['id'], r.json()['agent_token']
        p = c.get('/api/products').json()['items'][0]
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = c.post('/api/print-jobs', headers={'X-CSRF-Token': token},
                   json={'product_id': p['id'], 'quantity': 1, 'printer_id': printer_id, 'expires_at': exp})
        jid = r.json()['job_id']
        h = {'Authorization': f'Bearer {agent_token}'}
        claim = c.post(f'/api/agent/jobs/{jid}/claim', headers=h).json(); assert claim['ok']
        h['X-Print-Claim'] = claim['claim_token']

        db = SessionLocal()
        try:
            job = db.get(PrintJob, jid)
            job.lease_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        queue = c.get('/api/agent/jobs', headers=h)
        assert queue.status_code == 200
        db = SessionLocal()
        try:
            assert db.get(PrintJob, jid).status == 'attention'
        finally:
            db.close()

        retry = c.post(f'/api/print-jobs/{jid}/retry',
                       headers={'X-CSRF-Token': csrf(c)})
        assert retry.status_code == 200
        assert retry.json()['status'] == 'created'


def test_manager_can_switch_location_and_catalog_can_be_cloned():
    with TestClient(app) as c:
        login(c)
        token = csrf(c)
        original_count = len(c.get('/api/products').json()['items'])
        r = c.post('/api/locations', headers={'X-CSRF-Token': token},
                   json={'name': 'Точка 2', 'address': 'Тест', 'timezone': 'Europe/Moscow'})
        assert r.status_code == 200
        loc2 = r.json()['id']
        r = c.post(f'/api/locations/{loc2}/clone-catalog',
                   headers={'X-CSRF-Token': token})
        assert r.status_code == 200
        assert r.json()['copied'] == original_count
        token = csrf(c)
        r = c.post('/api/locations/switch', headers={'X-CSRF-Token': token},
                   json={'location_id': loc2})
        assert r.status_code == 200
        assert len(c.get('/api/products').json()['items']) == original_count


def test_password_can_be_changed_from_current_password():
    with TestClient(app) as c:
        login(c)
        token = csrf(c)
        r = c.post('/api/account/password', headers={'X-CSRF-Token': token},
                   json={'current_password': 'ChangeMe-Please-2026!', 'new_password': 'MarkifyPilot-2026!'})
        assert r.status_code == 200
        c.post('/logout', data={'csrf_token': csrf(c)}, follow_redirects=False)
        login(c, password='MarkifyPilot-2026!')


def test_exact_repeat_creates_new_job_on_same_printer():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        pr=c.post('/api/printers',headers={'X-CSRF-Token':token},json={'name':'Xprinter','driver':'xprinter','host':'127.0.0.1'}); assert pr.status_code==200
        printer_id=pr.json()['id']; p=c.get('/api/products').json()['items'][0]
        exp=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'quantity':2,'printer_id':printer_id,'expires_at':exp}); assert r.status_code==200
        jid=r.json()['job_id']
        h={'Authorization':f"Bearer {pr.json()['agent_token']}"}
        claim = c.post(f'/api/agent/jobs/{jid}/claim', headers=h).json(); assert claim['ok']
        h['X-Print-Claim'] = claim['claim_token']
        assert c.post(f'/api/agent/jobs/{jid}/complete',headers=h).json()['status']=='completed'
        rr=c.post(f'/api/print-jobs/{jid}/repeat',headers={'X-CSRF-Token':token}); assert rr.status_code==200
        assert rr.json()['job_id'] != jid
