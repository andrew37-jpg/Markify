import re
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app

def login(client):
    page=client.get('/login')
    token=re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r=client.post('/login',data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!','csrf_token':token},follow_redirects=False)
    assert r.status_code==303

def csrf(client):
    r=client.get('/')
    return re.search(r'data-csrf="([^"]+)"',r.text).group(1)

def test_departments_are_seeded_and_manageable():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        names=[x['name'] for x in c.get('/api/departments').json()['items']]
        assert {'Горячий цех','Пицца','Сушибар','Холодный цех'} <= set(names)
        r=c.post('/api/departments',headers={'X-CSRF-Token':token},json={'name':'Бар'})
        assert r.status_code==200
        assert any(x['name']=='Бар' for x in c.get('/api/departments').json()['items'])

def test_product_assignment_and_legacy_label_department_are_visible():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        dep=next(x for x in c.get('/api/departments').json()['items'] if x['name']=='Горячий цех')
        product=c.get('/api/products').json()['items'][0]
        r=c.patch(f'/api/departments/{dep["id"]}/products',headers={'X-CSRF-Token':token},json={'product_ids':[product['id']]})
        assert r.status_code==200
        assert c.get('/api/products').json()['items'][0]['department_name']=='Горячий цех'
        page=c.get('/')
        assert 'Горячий цех' in page.text

def test_batch_print_creates_jobs_only_for_auto_products():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        dep=next(x for x in c.get('/api/departments').json()['items'] if x['name']=='Пицца')
        p=c.get('/api/products').json()['items'][0]
        r=c.patch(f'/api/products/{p["id"]}',headers={'X-CSRF-Token':token},json={'department_id':dep['id'],'shelf_life_minutes':120,'shelf_life_status':'verified','label_mode':'auto_from_shelf_life','shelf_life_basis':'Тестовое подтверждение'})
        assert r.status_code==200
        pr=c.post('/api/printers',headers={'X-CSRF-Token':token},json={'name':'Xprinter Batch','driver':'xprinter','host':'127.0.0.1'}); assert pr.status_code==200
        result=c.post('/api/print-jobs/batch',headers={'X-CSRF-Token':token},json={'department_id':dep['id'],'printer_id':pr.json()['id']})
        assert result.status_code==200
        data=result.json(); assert data['created_count']==1
        assert data['skipped_count']==0

def test_dashboard_expired_rows_include_department_name():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        dep=next(x for x in c.get('/api/departments').json()['items'] if x['name']=='Сушибар')
        p=c.get('/api/products').json()['items'][0]
        c.patch(f'/api/departments/{dep["id"]}/products',headers={'X-CSRF-Token':token},json={'product_ids':[p['id']]})
        pr=c.post('/api/printers',headers={'X-CSRF-Token':token},json={'name':'Xprinter Expired','driver':'xprinter','host':'127.0.0.1'}).json()['id']
        exp=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
        job=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'printer_id':pr,'expires_at':exp}).json()['job_id']
        from app.db import SessionLocal
        from app.models import Label
        db=SessionLocal(); label=db.query(Label).filter(Label.print_job_id==job).first(); label.expires_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(minutes=1); db.commit(); db.close()
        state=c.get('/api/dashboard/state').json(); row=next(x for x in state['labels'] if x['print_job_id']==job)
        assert row['status']=='expired' and row['department_name']=='Сушибар'
