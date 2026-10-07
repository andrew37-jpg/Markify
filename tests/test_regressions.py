import re
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Label
from sqlalchemy import select


def login(c):
    page=c.get('/login'); token=re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)
    r=c.post('/login',data={'email':'admin@markify.local','password':'ChangeMe-Please-2026!','csrf_token':token},follow_redirects=False)
    assert r.status_code==303


def csrf(c):
    r=c.get('/')
    return re.search(r'data-csrf="([^"]+)"',r.text).group(1)


def create_printer(c, token):
    r=c.post('/api/printers',headers={'X-CSRF-Token':token},json={'name':'Xprinter Test','driver':'xprinter','host':'127.0.0.1'})
    assert r.status_code==200, r.text
    return r.json()['id']


def test_web_auth_redirects_to_login():
    with TestClient(app) as c:
        r=c.get('/',follow_redirects=False)
        assert r.status_code==303
        assert r.headers['location']=='/login'


def test_product_icon_and_fallback_route():
    with TestClient(app) as c:
        login(c)
        p=c.get('/api/products').json()['items'][0]
        r=c.get(p['image'])
        assert r.status_code==200
        assert r.headers['content-type'].startswith('image/svg+xml')
        assert '<svg' in r.text


def test_local_manual_expiry_is_interpreted_in_restaurant_timezone():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        printer_id=create_printer(c, token)
        p=c.get('/api/products').json()['items'][0]
        future_local=(datetime.now(timezone.utc)+timedelta(hours=5)).astimezone(timezone(timedelta(hours=3))).replace(tzinfo=None).replace(second=0,microsecond=0)
        local_value=future_local.isoformat(timespec='minutes')
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'quantity':1,'printer_id':printer_id,'expires_at':local_value})
        assert r.status_code==200, r.text
        job_id=r.json()['job_id']
        db=SessionLocal(); label=db.scalar(select(Label).where(Label.print_job_id==job_id));
        expected_utc=future_local.replace(tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc).replace(tzinfo=None)
        assert label.expires_at == expected_utc
        db.close()


def test_reprint_preview_uses_get():
    with TestClient(app) as c:
        login(c); token=csrf(c)
        printer_id=create_printer(c, token)
        p=c.get('/api/products').json()['items'][0]
        future=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        r=c.post('/api/print-jobs',headers={'X-CSRF-Token':token},json={'product_id':p['id'],'quantity':1,'printer_id':printer_id,'expires_at':future})
        assert r.status_code==200
        job_id=r.json()['job_id']
        db=SessionLocal(); label=db.scalar(select(Label).where(Label.print_job_id==job_id)); lid=label.id; db.close()
        preview=c.get(f'/api/labels/{lid}/reprint')
        assert preview.status_code==200
        assert preview.json()['reprint'] is True


def test_all_product_icon_urls_are_available():
    with TestClient(app) as c:
        login(c)
        products=c.get('/api/products').json()['items']
        assert len(products)==147
        for product in products:
            r=c.get(product['image'])
            assert r.status_code==200
            assert '<svg' in r.text


def test_products_page_renders_after_login():
    with TestClient(app) as c:
        login(c)
        r=c.get('/products')
        assert r.status_code==200
        assert 'Каталог продуктов' in r.text
