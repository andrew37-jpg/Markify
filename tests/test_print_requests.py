from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from test_audit_0102 import web, setup_print
from app.db import SessionLocal
from app.models import Label, PrintJob, PrintRequest, Product
from app.services import utcnow


def payload(pid):
    return {'product_id': pid, 'quantity': 2, 'expires_at': (utcnow() + timedelta(hours=2)).isoformat() + 'Z'}


def counts():
    with SessionLocal() as db:
        return tuple(db.scalar(select(func.count(model.id))) for model in (PrintJob, Label, PrintRequest))


def test_retry_returns_same_job_and_rejects_changed_body(web):
    pid, _ = setup_print(web)
    body = payload(pid)
    headers = {'Idempotency-Key': 'single-print-request-001'}
    first = web.post('/api/print-jobs', json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = web.post('/api/print-jobs', json=body, headers=headers)
    assert second.json() == first.json()
    assert counts() == (1, 2, 1)
    changed = web.post('/api/print-jobs', json={**body, 'quantity': 3}, headers=headers)
    assert changed.status_code == 409
    assert counts() == (1, 2, 1)


def test_concurrent_requests_create_one_job(web):
    pid, _ = setup_print(web)
    body = payload(pid)
    headers = {'Idempotency-Key': 'concurrent-print-request-001'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: web.post('/api/print-jobs', json=body, headers=headers), range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()['job_id'] for r in responses}) == 1
    assert counts() == (1, 2, 1)


def test_failed_validation_does_not_consume_key(web):
    pid, printer = setup_print(web)
    body = payload(pid)
    headers = {'Idempotency-Key': 'recoverable-print-request-001'}
    assert web.post('/api/print-jobs', json={**body, 'printer_id': 999999}, headers=headers).status_code == 404
    assert counts() == (0, 0, 0)
    assert web.post('/api/print-jobs', json={**body, 'printer_id': printer['id']}, headers=headers).status_code == 200


def test_same_key_is_isolated_between_locations(web):
    pid, _ = setup_print(web)
    headers = {'Idempotency-Key': 'location-print-request-001'}
    original = web.post('/api/print-jobs', json=payload(pid), headers=headers)
    assert original.status_code == 200
    location = web.post('/api/locations', json={'name': 'Other kitchen'}).json()['id']
    switched = web.post('/api/locations/switch', json={'location_id': location})
    assert switched.status_code == 200
    web.headers['X-CSRF-Token'] = switched.json()['csrf']
    # A valid session in another location must not get the original response.
    assert web.post('/api/print-jobs', json=payload(pid), headers=headers).status_code == 404
    printer = web.post('/api/printers', json={'name': 'Other printer', 'host': '127.0.0.1'})
    assert printer.status_code == 200
    product = web.post('/api/products', json={'name': 'Other product'})
    assert product.status_code == 200
    other = web.post('/api/print-jobs', json=payload(product.json()['id']), headers=headers)
    assert other.status_code == 200, other.text
    assert other.json()['job_id'] != original.json()['job_id']
    assert counts() == (2, 4, 2)


def test_batch_is_atomic_and_replay_does_not_print_again(web):
    pid, _ = setup_print(web)
    dep = web.get('/api/departments').json()['items'][0]['id']
    with SessionLocal() as db:
        products = db.scalars(select(Product).limit(2)).all()
        for product in products:
            product.department_id = dep
            product.label_mode = 'auto_from_shelf_life'
            product.shelf_life_status = 'verified'
            product.shelf_life_minutes = 120
        db.commit()
    headers = {'Idempotency-Key': 'batch-print-request-001'}
    body = {'department_id': dep}
    from app.main import create_print_job
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError('Injected failure')
        return create_print_job(*args, **kwargs)
    with patch('app.main.create_print_job', side_effect=fail_second):
        assert web.post('/api/print-jobs/batch', json=body, headers=headers).status_code == 422
    assert counts() == (0, 0, 0)
    first = web.post('/api/print-jobs/batch', json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()['created_count'] == 2
    assert web.post('/api/print-jobs/batch', json=body, headers=headers).json() == first.json()
    assert counts() == (2, 2, 1)


def test_exact_repeat_has_idempotency_and_requires_completed_source(web):
    pid, _ = setup_print(web)
    job = web.post('/api/print-jobs', json=payload(pid)).json()['job_id']
    with SessionLocal() as db:
        db.get(PrintJob, job).status = 'attention'
        db.commit()
    headers = {'Idempotency-Key': 'repeat-print-request-001'}
    path = f'/api/print-jobs/{job}/repeat'
    assert web.post(path, headers=headers).status_code == 409
    with SessionLocal() as db:
        db.get(PrintJob, job).status = 'completed'
        db.commit()
    first = web.post(path, headers=headers)
    assert first.status_code == 200, first.text
    assert web.post(path, headers=headers).json() == first.json()
    assert counts() == (2, 4, 1)


@pytest.mark.parametrize('key', ['', 'short', ' ' * 20, 'x' * 129])
def test_invalid_key_is_rejected(web, key):
    pid, _ = setup_print(web)
    assert web.post('/api/print-jobs', json=payload(pid), headers={'Idempotency-Key': key}).status_code == 422
    assert counts() == (0, 0, 0)


def test_history_pages_expose_old_jobs_and_validate_page(web):
    pid, _ = setup_print(web)
    with SessionLocal() as db:
        product = db.get(Product, pid)
        db.add_all([PrintJob(location_id=product.location_id, product_id=pid, quantity=1,
                            operator_name='Pagination', mode='auto', status='created') for _ in range(305)])
        db.commit()
    newest = web.get('/history').text
    oldest = web.get('/history?page=7').text
    assert 'Страница 1 из 7' in newest
    assert 'Всего заданий: 305' in newest
    assert 'Страница 7 из 7' in oldest
    assert newest.count('cancel-job" data-id=') == 50
    assert oldest.count('cancel-job" data-id=') == 5
    assert web.get('/history?page=0').status_code == 422
    assert 'Страница 7 из 7' in web.get('/history?page=999').text
