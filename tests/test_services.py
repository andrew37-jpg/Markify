from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.models import Product
from app.services import calculate_expiry, create_print_job, status_for, parse_local_datetime

def make_db():
    e=create_engine('sqlite+pysqlite:///:memory:',connect_args={'check_same_thread':False})
    Base.metadata.create_all(e); return sessionmaker(bind=e)()

def test_auto_expiry():
    db=make_db(); p=Product(name='Test',category='X',label_mode='auto_from_shelf_life',shelf_life_status='verified',shelf_life_minutes=60); db.add(p); db.commit(); mode,exp=calculate_expiry(p,None); assert mode=='auto'; assert 59.9 <= (exp-datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()/60 <= 60.1

def test_manual_requires_date():
    db=make_db(); p=Product(name='Test',category='X'); db.add(p); db.commit()
    try: calculate_expiry(p,None)
    except ValueError as e: assert 'Годен до' in str(e)
    else: raise AssertionError('expected ValueError')

def test_print_job_creates_each_label():
    db=make_db(); p=Product(name='Test',category='X'); db.add(p); db.commit(); job=create_print_job(db,p,3,'Op',1,expires_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=2)); assert len(job.labels)==3

def test_status_expired():
    db=make_db(); p=Product(name='Test',category='X',warning_before_minutes=30,critical_before_minutes=10); db.add(p); db.commit(); job=create_print_job(db,p,1,'Op',1,expires_at=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(minutes=1)); l=job.labels[0]; l.expires_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1); assert status_for(l)=='expired'

def test_local_datetime_to_utc():
    v=datetime(2026,9,29,18,0)
    u=parse_local_datetime(v,'Europe/Moscow'); assert u.hour==15
