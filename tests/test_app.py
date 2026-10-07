import re
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app

def login(client):
    page=client.get('/login'); token=re.search(r'name=\"csrf_token\" value=\"([^\"]+)\"', page.text).group(1)
    r=client.post('/login',data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!','csrf_token':token},follow_redirects=False)
    assert r.status_code==303

def test_login_dashboard_print_flow():
    with TestClient(app) as c:
        login(c)
        r=c.get('/'); assert r.status_code==200
        csrf=re.search(r'data-csrf="([^"]+)"',r.text).group(1); assert csrf
        pr=c.post('/api/printers',headers={'X-CSRF-Token':csrf},json={'name':'Xprinter Test','driver':'xprinter','host':'127.0.0.1'}); assert pr.status_code==200
        printer_id=pr.json()['id']
        p=c.get('/api/products').json()['items'][0]
        exp=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':csrf},json={'product_id':p['id'],'quantity':2,'printer_id':printer_id,'expires_at':exp}); assert r.status_code==200
        job=r.json()['job_id']
        r=c.get(f'/print/job/{job}'); assert r.status_code==200 and r.text.count('class="sheet"')==2
        r=c.post(f'/api/print-jobs/{job}/opened',headers={'X-CSRF-Token':csrf}); assert r.status_code==409

def test_csrf_required():
    with TestClient(app) as c:
        login(c)
        r=c.post('/api/print-jobs',json={'product_id':1,'quantity':1})
        assert r.status_code==403
