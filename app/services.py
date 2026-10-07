from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import hashlib, hmac, secrets
from sqlalchemy.orm import Session
from .config import settings
from .models import AuditLog, Label, PrintJob, Product, Department

STATUS_LABELS={'active':'Активна','warning':'Скоро заменить','critical':'Пора менять','expired':'Просрочено'}

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

def to_local(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    if dt is None: return None
    z=ZoneInfo(tz_name or settings.timezone)
    return dt.replace(tzinfo=timezone.utc).astimezone(z)

def parse_local_datetime(value: datetime | None, tz_name: str | None = None) -> datetime | None:
    if value is None: return None
    if value.tzinfo is None:
        zone = ZoneInfo(tz_name) if tz_name else timezone.utc
        return value.replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)

def status_for(label: Label, now: datetime | None = None) -> str:
    now=now or utcnow()
    remaining=(label.expires_at-now).total_seconds()/60
    product=label.product
    warning=product.warning_before_minutes if product.warning_before_minutes is not None else settings.default_warning_minutes
    critical=product.critical_before_minutes if product.critical_before_minutes is not None else settings.default_critical_minutes
    if remaining<=0:return 'expired'
    if remaining<=critical:return 'critical'
    if remaining<=warning:return 'warning'
    return 'active'

def calculate_expiry(product: Product, expires_at: datetime|None, tz_name: str|None=None):
    now=utcnow()
    if product.label_mode=='auto_from_shelf_life' and product.shelf_life_status=='verified' and product.shelf_life_minutes:
        return 'auto', now+timedelta(minutes=product.shelf_life_minutes)
    exp=parse_local_datetime(expires_at,tz_name)
    if exp is None: raise ValueError('Укажите «Годен до» по маркировке изготовителя или утвержденной технологической документации.')
    if exp<=now: raise ValueError('Дата «Годен до» должна быть в будущем.')
    return 'manual_expiry',exp

def create_print_job(db: Session, product: Product, quantity: int, operator_name: str, location_id: int, user_id: int|None=None, expires_at: datetime|None=None, printer_id: int|None=None, reprint_of_label_id: int|None=None, tz_name: str|None=None, department_id: int|None=None, department_name: str='Без цеха', exact_source: Label|None=None, commit: bool=True):
    if quantity < 1 or quantity > 100:
        raise ValueError('Количество должно быть от 1 до 100.')
    if exact_source is not None:
        if exact_source.product_id != product.id or exact_source.location_id != location_id:
            raise ValueError('Исходная маркировка не относится к этому продукту/точке')
        if exact_source.expires_at <= utcnow():
            raise ValueError('Нельзя повторно печатать просроченную маркировку.')
        mode, expiry = 'exact_copy', exact_source.expires_at
    else:
        mode,expiry=calculate_expiry(product,expires_at,tz_name)
    now=utcnow()
    department_id = department_id if department_id is not None else product.department_id
    if department_id is not None and department_name == 'Без цеха':
        dep = db.get(Department, department_id)
        department_name = dep.name if dep else 'Без цеха'
    job=PrintJob(location_id=location_id,product_id=product.id,printer_id=printer_id,quantity=quantity,operator_name=operator_name,user_id=user_id,mode=mode,manual_expires_at=expiry if mode=='manual_expiry' else None,reprint_of_label_id=reprint_of_label_id,department_id=department_id,created_at=now,status='created')
    db.add(job); db.flush()
    for _ in range(quantity):
        db.add(Label(location_id=location_id,print_job_id=job.id,product_id=product.id,created_at=exact_source.created_at if exact_source else now,expires_at=expiry,operator_name=exact_source.operator_name if exact_source else operator_name,reprint_of_id=reprint_of_label_id,department_id=exact_source.department_id if exact_source else department_id,department_name_snapshot=exact_source.department_name_snapshot if exact_source else department_name,storage_condition_snapshot=exact_source.storage_condition_snapshot if exact_source else product.storage_condition,shelf_life_snapshot_minutes=exact_source.shelf_life_snapshot_minutes if exact_source else (product.shelf_life_minutes if mode=='auto' else None),product_name_snapshot=exact_source.product_name_snapshot or product.name if exact_source else product.name,status='copy' if exact_source else 'active'))
    action='REPRINT_LABEL' if reprint_of_label_id else 'CREATE_PRINT_JOB'
    db.add(AuditLog(location_id=location_id,user_id=user_id,action=action,entity_type='print_job',entity_id=job.id,operator_name=operator_name,details=f'product={product.name}; quantity={quantity}; mode={mode}; expires_at={expiry.isoformat()}; reprint_of={reprint_of_label_id or ""}'))
    db.flush()
    if commit:
        db.commit(); db.refresh(job)
    return job

def password_hash(password: str) -> str:
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode('utf-8'),salt=salt,n=2**14,r=8,p=1)
    return 'scrypt$'+salt.hex()+'$'+digest.hex()

def password_verify(password: str, stored: str) -> bool:
    try:
        scheme,salt_hex,digest_hex=stored.split('$',2)
        if scheme!='scrypt': return False
        digest=hashlib.scrypt(password.encode('utf-8'),salt=bytes.fromhex(salt_hex),n=2**14,r=8,p=1)
        return hmac.compare_digest(digest.hex(),digest_hex)
    except Exception:return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def new_agent_token()->str:
    return secrets.token_urlsafe(32)
