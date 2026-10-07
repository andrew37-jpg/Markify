from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import logging
import secrets

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, joinedload, selectinload
from starlette.middleware.sessions import SessionMiddleware

from scripts.data_seed import PRODUCTS
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .icon_service import product_icon_svg
from .migrations import ensure_schema
from .models import AuthSession, LoginAttempt, AuditLog, Department, Label, Location, Organization, Printer, PrintJob, Product, User
from .schemas import BatchPrintCreate, DepartmentCreate, DepartmentProductsUpdate, DepartmentUpdate, PrintJobCreate, ProductCreate, ProductUpdate, PrinterCreate, PrinterUpdate
from .printer_adapters import ADAPTERS
from .print_requests import reserve_print_request, finish_print_request
from .services import (
    STATUS_LABELS,
    calculate_expiry,
    create_print_job,
    new_agent_token,
    password_hash,
    password_verify,
    status_for,
    token_hash,
    to_local,
    utcnow,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
logger = logging.getLogger('markify')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')



def slug_name(name: str) -> str:
    import re
    s = name.lower().replace('ё', 'е')
    return re.sub(r'[^a-z0-9а-я]+', '-', s).strip('-') or 'product'


def fmtdt(value: datetime | None, tz_name: str | None = None) -> str:
    local = to_local(value, tz_name)
    return local.strftime('%d.%m.%Y %H:%M') if local else '—'


def bootstrap_schema_and_migrate() -> None:
    ensure_schema()
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE labels SET product_name_snapshot=(SELECT name FROM products WHERE products.id=labels.product_id) WHERE product_name_snapshot='' AND EXISTS (SELECT 1 FROM products WHERE products.id=labels.product_id)")


def ensure_bootstrap_data() -> None:
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.name == settings.bootstrap_org_name))
        if not org:
            org = Organization(name=settings.bootstrap_org_name, plan='pilot')
            db.add(org)
            db.flush()

        location = db.scalar(
            select(Location)
            .where(Location.organization_id == org.id)
            .order_by(Location.id)
        )
        if not location:
            location = Location(
                organization_id=org.id,
                name=settings.bootstrap_location_name,
                timezone=settings.timezone,
            )
            db.add(location)
            db.flush()

        user = db.scalar(select(User).where(User.email == settings.bootstrap_admin_email.lower()))
        if not user:
            user = User(
                organization_id=org.id,
                name=settings.bootstrap_admin_name,
                email=settings.bootstrap_admin_email.lower(),
                password_hash=password_hash(settings.bootstrap_admin_password),
                role='admin',
                location_id=location.id,
            )
            db.add(user)

        # Repair legacy rows that pre-date multi-location support.
        if user.location_id is None:
            user.location_id = location.id

        # Built-in restaurant departments are created once. Products are intentionally
        # not auto-assigned: department membership is a restaurant-specific decision.
        default_departments = ['Горячий цех', 'Пицца', 'Сушибар', 'Холодный цех']
        existing_departments = {d.name for d in db.scalars(select(Department).where(Department.location_id == location.id)).all()}
        for order, name in enumerate(default_departments, start=1):
            if name not in existing_departments:
                db.add(Department(organization_id=org.id, location_id=location.id, name=name, sort_order=order, active=True))

        for table in ('products', 'labels', 'print_jobs', 'audit_logs'):
            db.execute(text(f'UPDATE {table} SET location_id=:loc WHERE location_id IS NULL'), {'loc': location.id})

        # Seed the built-in catalog once. A version flag prevents a renamed/archived
        # product from being re-created on every application restart.
        if location.catalog_seed_version != 1:
            current = {
                (p.name, p.category): p
                for p in db.scalars(select(Product).where(Product.location_id == location.id)).all()
            }
            page1_categories = {
                'Бакалея, крупы, мука',
                'Масла и соусы',
                'Молочные продукты и сыры',
                'Заморозка, мясо и полуфабрикаты',
            }
            for category, name in PRODUCTS:
                product = current.get((name, category))
                if product is None:
                    db.add(Product(
                        location_id=location.id,
                        name=name,
                        category=category,
                        source_page=1 if category in page1_categories else 2,
                        shelf_life_status='needs_confirmation',
                        label_mode='manual_expiry',
                        shelf_life_minutes=None,
                        warning_before_minutes=None,
                        critical_before_minutes=None,
                        storage_condition='',
                        technology_card='',
                        shelf_life_basis='Срок не установлен автоматически. Подтвердить по маркировке изготовителя и/или утвержденной документации ресторана.',
                        verification_note='Источник: предоставленный перечень продуктов. Точный срок зависит от конкретной продукции, упаковки, состояния и условий хранения.',
                        image_name=f'{slug_name(name)}.svg',
                        active=True,
                    ))
                else:
                    changed = False
                    if not product.image_name:
                        product.image_name = f'{slug_name(name)}.svg'; changed = True
                    if not product.shelf_life_status:
                        product.shelf_life_status = 'needs_confirmation'; changed = True
                    if not product.label_mode:
                        product.label_mode = 'manual_expiry'; changed = True
                    if changed:
                        product.updated_at = utcnow()
            location.catalog_seed_version = 1

        # Browser/PDF printing is intentionally disabled as the primary restaurant workflow.
        # Keep legacy browser printers for audit/history, but archive them so they cannot be selected.
        db.execute(update(Printer).where(
            Printer.location_id == location.id,
            Printer.driver == 'browser',
            Printer.active.is_(True),
        ).values(active=False))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_runtime_assets() -> None:
    required_templates = ['base.html', 'dashboard.html', 'products.html', 'departments.html', 'history.html', 'printers.html', 'print.html', 'login.html', 'error.html']
    missing = [name for name in required_templates if not (BASE_DIR / 'templates' / name).is_file()]
    if missing:
        raise RuntimeError('Не хватает шаблонов приложения: ' + ', '.join(missing))
    if not STATIC_DIR.is_dir():
        raise RuntimeError('Не найдена папка static')


def startup() -> None:
    if settings.environment.lower() == 'production':
        if len(settings.session_secret) < 32 or settings.session_secret in {'change-this-session-secret-before-production', 'replace-with-a-long-random-secret'}:
            raise RuntimeError('MARKIFY_SESSION_SECRET must be changed in production')
        if len(settings.bootstrap_admin_password) < settings.min_password_length or settings.bootstrap_admin_password == 'ChangeMe-Please-2026!':
            raise RuntimeError('MARKIFY_BOOTSTRAP_ADMIN_PASSWORD must be changed in production')
        if not settings.session_https_only:
            raise RuntimeError('MARKIFY_SESSION_HTTPS_ONLY=true is required in production')
    validate_runtime_assets()
    bootstrap_schema_and_migrate()
    ensure_bootstrap_data()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        method = scope.get('method', '')
        path = scope.get('path', '')
        headers = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
        authorization = headers.get('authorization', '')
        needs_csrf = method in {'POST', 'PUT', 'PATCH', 'DELETE'} and (
            path.startswith('/api/')
        ) and not path.startswith('/api/agent/') and bool(scope.get('session', {}).get('user_id'))
        if needs_csrf:
            session = scope.get('session', {})
            expected = session.get('csrf', '')
            supplied = headers.get('x-csrf-token', '')
            if not expected or not supplied or not secrets.compare_digest(expected, supplied):
                body = b'{"detail":"CSRF token missing or invalid"}'
                await send({'type': 'http.response.start', 'status': 403,
                            'headers': [(b'content-type', b'application/json'),
                                        (b'content-length', str(len(body)).encode())]})
                await send({'type': 'http.response.body', 'body': body})
                return
        await self.app(scope, receive, send)


# Session middleware must be outside the CSRF layer so scope['session'] exists.
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site='lax',
    max_age=settings.session_max_age_seconds,
    https_only=settings.session_https_only,
)
@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if not request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))
templates.env.filters['formatdt'] = lambda v, tz_name=None: fmtdt(v, tz_name)
templates.env.globals['status_for'] = status_for
templates.env.globals['STATUS_LABELS'] = STATUS_LABELS
templates.env.globals['utc_timestamp'] = lambda: datetime.now(timezone.utc).timestamp()
templates.env.globals['min_password_length'] = settings.min_password_length


def page_script(name: str):
    from markupsafe import Markup
    if name not in {'dashboard', 'products', 'departments', 'printers'}:
        raise ValueError('Unknown page script')
    # Trusted source code only. Escape closing tags so source stays inside script.
    return Markup((STATIC_DIR / 'js' / (name + '.js')).read_text(encoding='utf-8').replace('</', '<\\/'))


templates.env.globals['page_script'] = page_script


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and not request.url.path.startswith('/api/') and request.url.path not in {'/login'}:
        return RedirectResponse('/login', status_code=303)
    if request.url.path.startswith('/api/'):
        return JSONResponse(status_code=exc.status_code, content={'detail': str(exc.detail)})
    return templates.TemplateResponse(
        request=request,
        name='error.html',
        context={'request': request, 'error_title': f'Ошибка {exc.status_code}', 'error_message': str(exc.detail)},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception('Unhandled error on %s', request.url.path)
    if request.url.path.startswith('/api/'):
        detail = str(exc) if settings.debug else 'Внутренняя ошибка сервера. Попробуйте еще раз.'
        return JSONResponse(status_code=500, content={'detail': detail})
    return templates.TemplateResponse(
        request=request,
        name='error.html',
        context={'request': request, 'error_title': 'Ошибка сервера', 'error_message': 'Попробуйте обновить страницу.'},
        status_code=500,
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get('user_id')
    if not uid:
        raise HTTPException(status_code=401, detail='Требуется авторизация')
    session = db.get(AuthSession, token_hash(request.session.get('session_id', '')))
    if not session or session.user_id != int(uid) or session.expires_at <= utcnow():
        request.session.clear()
        raise HTTPException(401, 'Сессия завершена. Войдите снова.')
    user = db.get(User, int(uid))
    if not user or not user.active or request.session.get('auth_version') != token_hash(user.password_hash):
        request.session.clear()
        raise HTTPException(status_code=401, detail='Сессия недействительна')
    if not user.organization or not user.organization.active:
        raise HTTPException(403, 'Организация отключена')
    return user


def current_location(db: Session, user: User, request: Request | None = None) -> Location:
    # Operators are pinned to their assigned location. Admins/managers may switch
    # among active locations of their organization through the session selector.
    if user.role in {'admin', 'manager'} and request is not None:
        selected_id = request.session.get('location_id')
        if selected_id:
            loc = db.scalar(select(Location).where(
                Location.id == int(selected_id),
                Location.organization_id == user.organization_id,
                Location.active.is_(True),
            ))
            if loc:
                return loc
            request.session.pop('location_id', None)
    if user.location_id:
        loc = db.scalar(select(Location).where(
            Location.id == user.location_id,
            Location.organization_id == user.organization_id,
            Location.active.is_(True),
        ))
        if loc:
            return loc
    if user.role == 'operator':
        raise HTTPException(403, 'Оператору не назначена активная точка')
    loc = db.scalar(select(Location).where(
        Location.organization_id == user.organization_id, Location.active.is_(True)
    ).order_by(Location.id))
    if not loc:
        raise HTTPException(status_code=500, detail='Для организации не настроена точка')
    return loc


def check_role(user: User, roles: set[str]) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail='Недостаточно прав')


def serialize_product(p: Product) -> dict:
    return {
        'id': p.id,
        'name': p.name,
        'category': p.category,
        'unit': p.source_unit,
        'shelf_life_minutes': p.shelf_life_minutes,
        'warning_before_minutes': p.warning_before_minutes,
        'critical_before_minutes': p.critical_before_minutes,
        'storage_condition': p.storage_condition,
        'shelf_life_status': p.shelf_life_status,
        'label_mode': p.label_mode,
        'shelf_life_basis': p.shelf_life_basis,
        'shelf_life_source_url': p.shelf_life_source_url,
        'verification_note': p.verification_note,
        'technology_card': p.technology_card,
        'image': f'/product-icons/{p.id}.svg',
        'active': p.active,
        'department_id': p.department_id,
        'department_name': p.department.name if p.department else 'Без цеха',
    }


def serialize_label(l: Label, tz_name: str | None = None) -> dict:
    return {
        'id': l.id,
        'product_id': l.product_id,
        'product': l.product_name_snapshot or l.product.name,
        'category': l.product.category,
        'created_at': fmtdt(l.created_at, tz_name),
        'expires_at': fmtdt(l.expires_at, tz_name),
        'expires_at_iso': l.expires_at.replace(tzinfo=timezone.utc).isoformat(),
        'operator_name': l.operator_name,
        'status': status_for(l),
        'mode': 'Авто' if l.shelf_life_snapshot_minutes else 'Вручную',
        'print_job_id': l.print_job_id,
        'print_status': l.print_job.status if l.print_job else 'legacy',
        'department_id': l.department_id,
        'department_name': l.department_name_snapshot or (l.product.department.name if l.product.department else 'Без цеха'),
    }


def _validate_product_values(name, category, shelf, warning, critical, status, mode, basis):
    if not name or not name.strip():
        raise HTTPException(422, 'Название продукта не может быть пустым')
    if warning is not None and shelf is not None and warning > shelf:
        raise HTTPException(422, 'Желтая зона не может быть больше срока хранения')
    if critical is not None and warning is not None and critical > warning:
        raise HTTPException(422, 'Критический порог не может быть больше желтой зоны')
    if critical is not None and shelf is not None and critical > shelf:
        raise HTTPException(422, 'Красная зона не может быть больше срока хранения')
    if status == 'verified':
        if not shelf:
            raise HTTPException(422, 'Для подтвержденного срока укажите длительность')
        if not (basis or '').strip():
            raise HTTPException(422, 'Для подтвержденного срока укажите основание/документ')
    if mode == 'auto_from_shelf_life' and status != 'verified':
        raise HTTPException(422, 'Автоматический режим доступен только для подтвержденного срока')


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse('/', 303)
    csrf = request.session.get('csrf') or secrets.token_urlsafe(24)
    request.session['csrf'] = csrf
    return templates.TemplateResponse(request=request, name='login.html', context={'request': request, 'csrf': csrf})


@app.post('/login')
def login(request: Request, email: str = Form(...), password: str = Form(...), csrf_token: str = Form(''), db: Session = Depends(get_db)):
    expected_csrf = request.session.get('csrf', '')
    if not expected_csrf or not csrf_token or not secrets.compare_digest(expected_csrf, csrf_token):
        return templates.TemplateResponse(request=request, name='login.html', context={'request': request, 'error': 'Сессия входа недействительна. Обновите страницу.', 'csrf': expected_csrf or secrets.token_urlsafe(24)}, status_code=403)
    # Shared DB counters work across application workers. Do not trust arbitrary X-Forwarded-For.
    cutoff = utcnow() - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    keys = [token_hash('ip:' + (request.client.host if request.client else 'unknown')), token_hash('email:' + email.strip().lower())]
    if any((db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.key == key)) or 0) >= 10 for key in keys):
        db.commit()
        return templates.TemplateResponse(request=request, name='login.html', context={'request': request, 'csrf': expected_csrf, 'error': 'Слишком много попыток входа. Повторите через 15 минут.'}, status_code=429)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not user.active or not password_verify(password, user.password_hash):
        for key in keys: db.add(LoginAttempt(key=key))
        db.commit()
        return templates.TemplateResponse(
            request=request,
            name='login.html',
            context={'request': request, 'error': 'Неверный email или пароль', 'csrf': expected_csrf},
            status_code=401,
        )
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
    session_id = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=token_hash(session_id), user_id=user.id, expires_at=utcnow()+timedelta(seconds=settings.session_max_age_seconds)))
    db.commit()
    request.session.clear()
    request.session['session_id'] = session_id
    request.session['user_id'] = user.id
    request.session['auth_version'] = token_hash(user.password_hash)
    request.session['csrf'] = secrets.token_urlsafe(24)
    return RedirectResponse('/', 303)


@app.post('/logout')
def logout(request: Request, csrf_token: str = Form(''), db: Session = Depends(get_db)):
    expected_csrf = request.session.get('csrf', '')
    if not expected_csrf or not csrf_token or not secrets.compare_digest(expected_csrf, csrf_token):
        raise HTTPException(status_code=403, detail='CSRF token missing or invalid')
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(request.session.get('session_id', ''))))
    db.commit()
    request.session.clear()
    return RedirectResponse('/login', 303)


@app.get('/product-icons/{product_id}.svg')
def product_icon(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    product = db.scalar(select(Product).where(Product.id == product_id, Product.location_id == loc.id, Product.active.is_(True)))
    if not product:
        raise HTTPException(404, 'Продукт не найден')
    return Response(
        content=product_icon_svg(product.name, product.category),
        media_type='image/svg+xml',
        headers={'Cache-Control': 'private, max-age=86400'},
    )


@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    products = db.scalars(select(Product).where(Product.location_id == loc.id, Product.active.is_(True)).order_by(Product.category, Product.name)).all()
    labels = db.scalars(
        select(Label).options(joinedload(Label.product)).where(Label.location_id == loc.id, Label.status == 'active').order_by(Label.expires_at.asc()).limit(300)
    ).all()
    all_labels = db.scalars(select(Label).options(joinedload(Label.product)).where(Label.location_id == loc.id, Label.status == 'active')).all()
    counts = {k: 0 for k in STATUS_LABELS}
    for label in all_labels:
        counts[status_for(label)] += 1
    categories = [r[0] for r in db.execute(
        select(Product.category).where(Product.location_id == loc.id, Product.active.is_(True)).distinct().order_by(Product.category)
    ).all()]
    departments = db.scalars(select(Department).where(Department.location_id == loc.id, Department.active.is_(True)).order_by(Department.sort_order, Department.name)).all()
    printers = db.scalars(select(Printer).where(Printer.location_id == loc.id, Printer.active.is_(True), Printer.driver != 'browser').order_by(Printer.name)).all()
    recent_jobs = db.scalars(select(PrintJob).options(joinedload(PrintJob.product)).where(
        PrintJob.location_id == loc.id, PrintJob.status == 'completed'
    ).order_by(PrintJob.completed_at.desc()).limit(8)).all()
    recent_ids = []
    for job in recent_jobs:
        if job.product_id not in recent_ids:
            recent_ids.append(job.product_id)
    popular_rows = db.execute(select(PrintJob.product_id, func.count(PrintJob.id).label('cnt')).where(
        PrintJob.location_id == loc.id
    ).group_by(PrintJob.product_id).order_by(func.count(PrintJob.id).desc()).limit(8)).all()
    popular_ids = [row[0] for row in popular_rows]
    by_id = {p.id: p for p in products}
    recent_products = [by_id[i] for i in recent_ids if i in by_id]
    popular_products = [by_id[i] for i in popular_ids if i in by_id]
    return templates.TemplateResponse(request=request, name='dashboard.html', context={
        'request': request, 'products': products, 'labels': labels, 'categories': categories, 'departments': departments, 'status_counts': counts,
        'printers': printers, 'recent_products': recent_products, 'popular_products': popular_products,
        'location': loc, 'user': user, 'timezone': loc.timezone,
        'csrf': request.session.get('csrf', ''), 'auto_refresh_seconds': settings.auto_refresh_seconds,
        'server_now_utc': utcnow().replace(tzinfo=timezone.utc).isoformat(),
    })


@app.get('/products', response_class=HTMLResponse)
def products_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    products = db.scalars(select(Product).where(Product.location_id == loc.id).order_by(Product.category, Product.name)).all()
    departments = db.scalars(select(Department).where(Department.location_id == loc.id, Department.active.is_(True)).order_by(Department.sort_order, Department.name)).all()
    return templates.TemplateResponse(request=request, name='products.html', context={
        'request': request, 'products': products, 'departments': departments, 'location': loc, 'user': user, 'csrf': request.session.get('csrf', '')
    })


@app.get('/departments', response_class=HTMLResponse)
def departments_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    departments = db.scalars(select(Department).where(Department.location_id == loc.id, Department.active.is_(True)).order_by(Department.sort_order, Department.name)).all()
    products = db.scalars(select(Product).where(Product.location_id == loc.id, Product.active.is_(True)).order_by(Product.name)).all()
    return templates.TemplateResponse(request=request, name='departments.html', context={
        'request': request, 'departments': departments, 'products': products, 'location': loc, 'user': user,
        'csrf': request.session.get('csrf', ''), 'can_manage': user.role in {'admin', 'manager'}
    })


@app.get('/history', response_class=HTMLResponse)
def history_page(request: Request, page: int = Query(default=1, ge=1), db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    expire_print_leases(db, loc.id)
    total = db.scalar(select(func.count(PrintJob.id)).where(PrintJob.location_id == loc.id)) or 0
    pages = max(1, (total + 49) // 50)
    page = min(page, pages)
    jobs = db.scalars(
        select(PrintJob).options(joinedload(PrintJob.product).joinedload(Product.department), selectinload(PrintJob.labels)).where(PrintJob.location_id == loc.id).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).offset((page - 1) * 50).limit(50)
    ).all()
    return templates.TemplateResponse(request=request, name='history.html', context={
        'request': request, 'jobs': jobs, 'location': loc, 'user': user, 'csrf': request.session.get('csrf', ''),
        'page': page, 'pages': pages, 'total': total,
    })


@app.get('/printers', response_class=HTMLResponse)
def printers_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    printers = db.scalars(select(Printer).where(Printer.location_id == loc.id).order_by(Printer.name)).all()
    return templates.TemplateResponse(request=request, name='printers.html', context={
        'request': request, 'printers': printers, 'location': loc, 'user': user, 'csrf': request.session.get('csrf', '')
    })


@app.get('/api/health')
def health():
    return {'status': 'ok'}


def printer_online(printer):
    return bool(printer.active and printer.last_seen_at and
                (utcnow() - printer.last_seen_at).total_seconds() <= settings.agent_online_seconds)


def expire_print_leases(db, location_id):
    now = utcnow()
    result = db.execute(update(PrintJob).where(
        PrintJob.location_id == location_id, PrintJob.status == 'printing',
        PrintJob.lease_expires_at < now,
    ).values(status='attention', lease_expires_at=None,
             error_message='Связь с агентом потеряна. Проверьте, вышла ли этикетка, прежде чем повторять.'))
    if result.rowcount:
        db.commit()


templates.env.globals['printer_online'] = printer_online


@app.get('/api/dashboard/state')
def dashboard_state(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    expire_print_leases(db, loc.id)
    labels = db.scalars(select(Label).options(joinedload(Label.product)).where(Label.location_id == loc.id, Label.status == 'active').order_by(Label.expires_at.asc()).limit(300)).all()
    all_labels = db.scalars(select(Label).options(joinedload(Label.product)).where(Label.location_id == loc.id, Label.status == 'active')).all()
    counts = {k: 0 for k in STATUS_LABELS}
    for label in all_labels:
        counts[status_for(label)] += 1
    printers = db.scalars(select(Printer).where(
        Printer.location_id == loc.id, Printer.active.is_(True), Printer.driver != 'browser'
    ).order_by(Printer.name)).all()
    departments = db.scalars(select(Department).where(Department.location_id == loc.id, Department.active.is_(True)).order_by(Department.sort_order, Department.name)).all()
    jobs = db.scalars(select(PrintJob).options(joinedload(PrintJob.product)).where(
        PrintJob.location_id == loc.id
    ).order_by(PrintJob.created_at.desc()).limit(12)).all()
    return {
        'server_now_utc': utcnow().replace(tzinfo=timezone.utc).isoformat(),
        'timezone': loc.timezone,
        'counts': counts,
        'departments': [{'id': d.id, 'name': d.name, 'product_count': db.scalar(select(func.count(Product.id)).where(Product.location_id == loc.id, Product.active.is_(True), Product.department_id == d.id)) or 0} for d in departments],
        'labels': [serialize_label(l, loc.timezone) for l in labels],
        'printers': [{'id': p.id, 'name': p.name, 'driver': p.driver, 'online': printer_online(p), 'last_seen_at': fmtdt(p.last_seen_at, loc.timezone)} for p in printers],
        'jobs': [{'id': j.id, 'status': j.status, 'product': j.product.name, 'quantity': j.quantity, 'error': j.error_message or ''} for j in jobs],
    }


@app.get('/api/products')
def products_api(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    products = db.scalars(select(Product).where(Product.location_id == loc.id, Product.active.is_(True)).order_by(Product.category, Product.name)).all()
    return {'items': [serialize_product(p) for p in products]}


@app.patch('/api/products/{product_id}')
def update_product(product_id: int, payload: ProductUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    product = db.scalar(select(Product).where(Product.id == product_id, Product.location_id == loc.id))
    if not product:
        raise HTTPException(404, 'Продукт не найден')

    changes = payload.model_dump(exclude_unset=True)
    proposed = {
        'name': changes.get('name', product.name),
        'category': changes.get('category', product.category),
        'source_unit': (changes.get('source_unit', product.source_unit) or None),
        'department_id': changes.get('department_id', product.department_id),
        'shelf_life_minutes': changes.get('shelf_life_minutes', product.shelf_life_minutes),
        'warning_before_minutes': changes.get('warning_before_minutes', product.warning_before_minutes),
        'critical_before_minutes': changes.get('critical_before_minutes', product.critical_before_minutes),
        'storage_condition': changes.get('storage_condition', product.storage_condition),
        'shelf_life_status': changes.get('shelf_life_status', product.shelf_life_status),
        'label_mode': changes.get('label_mode', product.label_mode),
        'shelf_life_basis': changes.get('shelf_life_basis', product.shelf_life_basis),
        'shelf_life_source_url': changes.get('shelf_life_source_url', product.shelf_life_source_url),
        'verification_note': changes.get('verification_note', product.verification_note),
    }
    name = proposed['name'].strip()
    category = (proposed['category'] or 'Без категории').strip() or 'Без категории'
    duplicate = db.scalar(select(Product).where(
        Product.location_id == loc.id,
        Product.id != product.id,
        Product.name == name,
        Product.active.is_(True),
    ))
    if duplicate:
        raise HTTPException(409, 'Продукт с таким названием уже существует')
    _validate_product_values(name, category, proposed['shelf_life_minutes'], proposed['warning_before_minutes'], proposed['critical_before_minutes'], proposed['shelf_life_status'], proposed['label_mode'], proposed['shelf_life_basis'])
    if proposed['department_id'] is not None:
        dep = db.scalar(select(Department).where(Department.id == proposed['department_id'], Department.location_id == loc.id, Department.active.is_(True)))
        if not dep:
            raise HTTPException(422, 'Выбранный цех не найден')

    for key, value in proposed.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(product, key, value)
    product.name = name
    product.category = category
    product.updated_at = utcnow()
    db.add(AuditLog(
        location_id=loc.id, user_id=user.id, action='UPDATE_PRODUCT', entity_type='product', entity_id=product.id,
        operator_name=user.name, details=json.dumps(proposed, ensure_ascii=False),
    ))
    db.commit(); db.refresh(product)
    return serialize_product(product)


@app.delete('/api/products/{product_id}')
def archive_product(product_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    product = db.scalar(select(Product).where(Product.id == product_id, Product.location_id == loc.id))
    if not product:
        raise HTTPException(404, 'Продукт не найден')
    product.active = False
    product.updated_at = utcnow()
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='ARCHIVE_PRODUCT', entity_type='product', entity_id=product.id, operator_name=user.name, details=product.name))
    db.commit()
    return {'ok': True, 'id': product.id, 'active': False}


@app.post('/api/products')
def create_product(payload: ProductCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    name = payload.name.strip()
    category = (payload.category or 'Без категории').strip() or 'Без категории'
    status = payload.shelf_life_status or 'needs_confirmation'
    mode = payload.label_mode or 'manual_expiry'
    _validate_product_values(name, category, payload.shelf_life_minutes, payload.warning_before_minutes, payload.critical_before_minutes, status, mode, payload.shelf_life_basis)
    if payload.department_id is not None and not db.scalar(select(Department.id).where(Department.id == payload.department_id, Department.location_id == loc.id, Department.active.is_(True))):
        raise HTTPException(422, 'Выбранный цех не найден')
    if db.scalar(select(Product).where(Product.location_id == loc.id, Product.name == name, Product.active.is_(True))):
        raise HTTPException(409, 'Продукт с таким названием уже существует')
    p = Product(
        location_id=loc.id, department_id=payload.department_id, name=name, category=category, source_unit=payload.source_unit,
        image_name=f'{slug_name(name)}.svg', shelf_life_status=status, label_mode=mode,
        shelf_life_minutes=payload.shelf_life_minutes, warning_before_minutes=payload.warning_before_minutes,
        critical_before_minutes=payload.critical_before_minutes, storage_condition=payload.storage_condition or '',
        shelf_life_basis=payload.shelf_life_basis or '', shelf_life_source_url=payload.shelf_life_source_url or '',
        verification_note=payload.verification_note or 'Создан вручную в каталоге', active=True,
    )
    db.add(p); db.flush()
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='CREATE_PRODUCT', entity_type='product', entity_id=p.id, operator_name=user.name, details=p.name))
    db.commit(); db.refresh(p)
    return serialize_product(p)


@app.post('/api/print-jobs')
def make_print_job(payload: PrintJobCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    reservation, replay = reserve_print_request(db, request, user.id, loc.id, payload.model_dump(mode='json'))
    if replay is not None:
        return replay
    product = db.scalar(select(Product).where(Product.id == payload.product_id, Product.location_id == loc.id, Product.active.is_(True)))
    if not product:
        raise HTTPException(404, 'Продукт не найден')
    selected_printer = None
    if payload.printer_id:
        selected_printer = db.scalar(select(Printer).where(Printer.id == payload.printer_id, Printer.location_id == loc.id, Printer.active.is_(True), Printer.driver != 'browser'))
        if not selected_printer:
            raise HTTPException(404, 'Рабочий термопринтер не найден')
    else:
        selected_printer = db.scalar(select(Printer).where(
            Printer.location_id == loc.id, Printer.active.is_(True), Printer.driver != 'browser'
        ).order_by(Printer.name))
        if not selected_printer:
            raise HTTPException(409, 'Сначала подключите рабочий термопринтер (например, Xprinter) в разделе «Принтеры»')
    if payload.reprint_of_label_id is not None:
        source = db.scalar(select(Label).where(Label.id == payload.reprint_of_label_id, Label.location_id == loc.id))
        if not source:
            raise HTTPException(404, 'Исходная маркировка для перепечатки не найдена')
        if source.product_id != product.id:
            raise HTTPException(422, 'Перепечатка должна относиться к тому же продукту')
    try:
        job = create_print_job(
            db, product, payload.quantity, user.name, loc.id, user.id, payload.expires_at,
            selected_printer.id, payload.reprint_of_label_id, loc.timezone, product.department_id,
            (db.get(Department, product.department_id).name if product.department_id and db.get(Department, product.department_id) else 'Без цеха'),
            commit=False,
        )
    except ValueError as e:
        db.rollback(); raise HTTPException(422, str(e))
    return finish_print_request(db, reservation, {
        'job_id': job.id,
        'quantity': job.quantity,
        'mode': job.mode,
        'printer_id': selected_printer.id,
        'printer_name': selected_printer.name,
        'print_method': 'agent',
        'status': job.status,
    })


@app.post('/api/print-jobs/batch')
def batch_print_jobs(payload: BatchPrintCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    reservation, replay = reserve_print_request(db, request, user.id, loc.id, payload.model_dump(mode='json'))
    if replay is not None:
        return replay
    dep = db.scalar(select(Department).where(Department.id == payload.department_id, Department.location_id == loc.id, Department.active.is_(True)))
    if not dep:
        raise HTTPException(404, 'Цех не найден')
    printer = db.scalar(select(Printer).where(
        Printer.id == payload.printer_id if payload.printer_id else Printer.id.is_not(None),
        Printer.location_id == loc.id, Printer.active.is_(True), Printer.driver != 'browser'
    ).order_by(Printer.name))
    if not printer:
        raise HTTPException(409, 'Подключите рабочий термопринтер (например, Xprinter)')
    products = db.scalars(select(Product).where(
        Product.location_id == loc.id, Product.department_id == dep.id, Product.active.is_(True)
    ).order_by(Product.name)).all()
    created, skipped = [], []
    for product in products:
        if not (product.shelf_life_status == 'verified' and product.label_mode == 'auto_from_shelf_life' and product.shelf_life_minutes):
            skipped.append({'id': product.id, 'name': product.name, 'reason': 'Нет подтвержденного автоматического срока'})
            continue
        try:
            job = create_print_job(db, product, 1, user.name, loc.id, user.id, None, printer.id, None, loc.timezone, dep.id, dep.name, commit=False)
            created.append({'id': job.id, 'product': product.name})
        except ValueError as exc:
            db.rollback()
            raise HTTPException(422, str(exc))
    return finish_print_request(db, reservation, {'ok': True, 'department': dep.name, 'printer_name': printer.name, 'created': created, 'skipped': skipped, 'created_count': len(created), 'skipped_count': len(skipped)})


@app.post('/api/labels/{label_id}/close')
def close_label(label_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    label = db.scalar(select(Label).where(Label.id == label_id, Label.location_id == loc.id))
    if not label:
        raise HTTPException(404, 'Маркировка не найдена')
    label.status = 'closed'
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='CLOSE_LABEL', entity_type='label', entity_id=label.id, operator_name=user.name, details='Продукция использована или списана; история сохранена'))
    db.commit()
    return {'ok': True}


@app.get('/api/labels/{label_id}/reprint')
def reprint_label(label_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    label = db.scalar(select(Label).options(joinedload(Label.product)).where(Label.id == label_id, Label.location_id == loc.id))
    if not label:
        raise HTTPException(404, 'Маркировка не найдена')
    return {'label_id': label.id, 'product': serialize_product(label.product), 'reprint': True, 'source_expires_at': fmtdt(label.expires_at, loc.timezone)}


@app.get('/api/print-jobs/{job_id}/status')
def print_job_status(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    expire_print_leases(db, loc.id)
    job = db.scalar(select(PrintJob).options(joinedload(PrintJob.product), joinedload(PrintJob.labels)).where(
        PrintJob.id == job_id, PrintJob.location_id == loc.id
    ))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    printer = db.get(Printer, job.printer_id) if job.printer_id else None
    return {
        'id': job.id, 'status': job.status, 'product': (job.labels[0].product_name_snapshot if job.labels else '') or job.product.name, 'quantity': job.quantity,
        'printer': printer.name if printer else None,
        'error': job.error_message or '',
        'attempt_count': job.attempt_count or 0,
    }


@app.get('/print/job/{job_id}', response_class=HTMLResponse)
def print_job_page(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    job = db.scalar(select(PrintJob).options(joinedload(PrintJob.product)).where(PrintJob.id == job_id, PrintJob.location_id == loc.id))
    if not job:
        raise HTTPException(404, 'Задание не найдено')
    labels = db.scalars(select(Label).where(Label.print_job_id == job.id).order_by(Label.id)).all()
    printer = db.get(Printer, job.printer_id) if job.printer_id else None
    return templates.TemplateResponse(request=request, name='print.html', context={
        'request': request, 'job': job, 'labels': labels, 'location': loc, 'user': user,
        'csrf': request.session.get('csrf', ''), 'settings': settings,
        'print_width_mm': printer.label_width_mm if printer else settings.label_width_mm,
        'print_height_mm': printer.label_height_mm if printer else settings.label_height_mm,
    })


# ---- Print Agent API ----

def agent_printer(request: Request, db: Session) -> Printer:
    auth = request.headers.get('authorization', '')
    if not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing agent token')
    token = auth.split(' ', 1)[1].strip()
    if not token:
        raise HTTPException(401, 'Missing agent token')
    printer = db.scalar(select(Printer).where(Printer.agent_token_hash == token_hash(token), Printer.active.is_(True)))
    if not printer:
        raise HTTPException(401, 'Invalid agent token')
    location = db.get(Location, printer.location_id)
    organization = db.get(Organization, location.organization_id) if location else None
    if not location or not location.active or not organization or not organization.active:
        raise HTTPException(403, 'Точка или организация отключена')
    printer.last_seen_at = utcnow()
    db.commit()
    return printer


@app.get('/api/agent/jobs')
def agent_jobs(request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    now = utcnow()
    expire_print_leases(db, printer.location_id)
    jobs = db.scalars(
        select(PrintJob).options(joinedload(PrintJob.product)).where(
            PrintJob.printer_id == printer.id, PrintJob.status == 'created'
        ).order_by(PrintJob.created_at).limit(10)
    ).all()
    printer.last_seen_at = now
    db.commit()
    return {'printer_id': printer.id, 'jobs': [
        {'id': j.id, 'quantity': j.quantity, 'product': j.product.name,
         'created_at': j.created_at.replace(tzinfo=timezone.utc).isoformat()}
        for j in jobs
    ]}


@app.post('/api/print-jobs/{job_id}/opened')
def print_job_opened(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.location_id == loc.id))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    if job.printer_id and db.get(Printer, job.printer_id).driver != 'browser':
        raise HTTPException(409, 'Статус прямой печати изменяет только Print Agent')
    if job.status in {'created', 'browser_ready'}:
        job.status = 'browser_ready'
        job.claimed_at = job.claimed_at or utcnow()
        db.add(AuditLog(location_id=loc.id, user_id=user.id, action='PRINT_DIALOG_OPENED', entity_type='print_job', entity_id=job.id, operator_name=user.name, details=f'quantity={job.quantity}'))
        db.commit()
    return {'ok': True, 'status': job.status}


@app.post('/api/print-jobs/{job_id}/completed')
def print_job_completed(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.location_id == loc.id))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    if job.printer_id and db.get(Printer, job.printer_id).driver != 'browser':
        raise HTTPException(409, 'Статус прямой печати изменяет только Print Agent')
    if job.status in {'created', 'browser_ready'}:
        job.status = 'completed'; job.completed_at = utcnow()
        db.add(AuditLog(location_id=loc.id, user_id=user.id, action='PRINT_COMPLETED', entity_type='print_job', entity_id=job.id, operator_name=user.name, details=f'quantity={job.quantity}'))
        db.commit()
    return {'ok': True, 'status': job.status}


@app.post('/api/print-jobs/{job_id}/cancelled')
def print_job_cancelled(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), request: Request = None):
    loc = current_location(db, user, request)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.location_id == loc.id))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    result = db.execute(update(PrintJob).where(
        PrintJob.id == job_id, PrintJob.status.in_(['created', 'browser_ready'])
    ).values(status='cancelled', completed_at=utcnow()))
    if result.rowcount != 1:
        raise HTTPException(409, 'Задание уже принято агентом; отмена не гарантирует остановку принтера')
    db.execute(update(Label).where(Label.print_job_id == job_id).values(status='cancelled'))
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='PRINT_CANCELLED', entity_type='print_job', entity_id=job.id, operator_name=user.name, details='cancelled before claim'))
    db.commit()
    return {'ok': True, 'status': 'cancelled'}



@app.post('/api/print-jobs/{job_id}/repeat')
def repeat_print_job(job_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    reservation, replay = reserve_print_request(db, request, user.id, loc.id, {})
    if replay is not None:
        return replay
    job = db.scalar(select(PrintJob).options(joinedload(PrintJob.product)).where(
        PrintJob.id == job_id, PrintJob.location_id == loc.id
    ))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    source = db.scalar(select(Label).where(Label.print_job_id == job.id).order_by(Label.id))
    if not source:
        raise HTTPException(409, 'У задания нет исходной маркировки')
    if source.expires_at <= utcnow():
        raise HTTPException(422, 'Нельзя повторно печатать просроченную маркировку.')
    if job.status != 'completed':
        raise HTTPException(409, 'Точную копию можно отправить после завершения. При ошибке сначала проверьте исходное задание в истории.')
    printer = db.scalar(select(Printer).where(
        Printer.id == job.printer_id, Printer.location_id == loc.id,
        Printer.active.is_(True), Printer.driver != 'browser'
    ))
    if not printer:
        raise HTTPException(409, 'Рабочий термопринтер для этого задания недоступен')
    try:
        new_job = create_print_job(
            db, job.product, job.quantity, user.name, loc.id, user.id, source.expires_at,
            printer.id, source.id, 'UTC', source.department_id, source.department_name_snapshot, exact_source=source,
            commit=False,
        )
    except ValueError as e:
        db.rollback(); raise HTTPException(422, str(e))
    return finish_print_request(db, reservation, {'ok': True, 'job_id': new_job.id, 'status': new_job.status, 'printer_name': printer.name})


@app.post('/api/print-jobs/{job_id}/retry')
def retry_print_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user), request: Request = None):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.location_id == loc.id))
    if not job:
        raise HTTPException(404, 'Задание печати не найдено')
    now = utcnow()
    if db.scalar(select(Label.id).where(Label.print_job_id == job.id, Label.expires_at <= now)):
        raise HTTPException(409, 'Срок маркировки истёк. Повторная отправка запрещена.')
    stale = job.status == 'printing' and job.lease_expires_at and job.lease_expires_at <= now
    if job.status not in {'failed', 'attention'} and not stale:
        raise HTTPException(409, 'Повторить можно только задание с ошибкой или зависшее задание')
    job.status = 'created'
    job.claim_token = ''
    job.error_message = ''
    job.claimed_at = None
    job.lease_expires_at = None
    job.completed_at = None
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='RETRY_PRINT_JOB', entity_type='print_job', entity_id=job.id, operator_name=user.name, details=f'attempt={job.attempt_count}'))
    db.commit()
    return {'ok': True, 'status': 'created', 'attempt_count': job.attempt_count}


@app.post('/api/agent/jobs/{job_id}/claim')
def agent_claim(job_id: int, request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    job_exists = db.scalar(select(PrintJob.id).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
    if not job_exists:
        raise HTTPException(404, 'Job not found')
    now = utcnow()
    if db.scalar(select(Label.id).where(Label.print_job_id == job_id, Label.expires_at <= now)):
        db.execute(update(PrintJob).where(PrintJob.id == job_id, PrintJob.status == 'created').values(status='failed', error_message='Срок маркировки истёк до отправки.'))
        db.commit()
        return {'ok': False, 'status': 'failed'}
    claim_token = secrets.token_urlsafe(32)
    # A printing job is leased to one agent. Expired leases are moved to
    # attention by the queue endpoint rather than silently reprinted.
    result = db.execute(
        update(PrintJob)
        .where(PrintJob.id == job_id, PrintJob.printer_id == printer.id, PrintJob.status == 'created')
        .values(status='printing', claimed_at=now, claim_token=claim_token,
                lease_expires_at=now + timedelta(seconds=settings.print_lease_seconds),
                attempt_count=PrintJob.attempt_count + 1)
    )
    db.commit()
    if result.rowcount != 1:
        current = db.scalar(select(PrintJob.status).where(PrintJob.id == job_id))
        return {'ok': False, 'status': current or 'unknown'}
    return {'ok': True, 'status': 'printing', 'claim_token': claim_token}


def check_claim(request, job):
    supplied = request.headers.get('X-Print-Claim', '')
    if not job.claim_token or not secrets.compare_digest(job.claim_token, supplied):
        raise HTTPException(409, 'Устаревший или отсутствующий захват задания. Обновите Print Agent.')


@app.get('/api/agent/jobs/{job_id}/payload')
def agent_payload(job_id: int, request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    job = db.scalar(select(PrintJob).options(joinedload(PrintJob.product)).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
    if not job:
        raise HTTPException(404, 'Job not found')
    check_claim(request, job)
    if job.status != 'printing':
        raise HTTPException(409, f'Job is not printable in status {job.status}')
    labels = db.scalars(select(Label).where(Label.print_job_id == job.id).order_by(Label.id)).all()
    location = db.get(Location, printer.location_id)
    return {
        'job_id': job.id,
        'printer': {'driver': printer.driver, 'host': printer.host, 'port': printer.port, 'queue_name': printer.queue_name, 'dpi': printer.dpi, 'width_mm': printer.label_width_mm, 'height_mm': printer.label_height_mm},
        'timezone': location.timezone,
        'product': {'name': (labels[0].product_name_snapshot if labels else '') or job.product.name, 'storage_condition': job.product.storage_condition},
        'labels': [{'created_at': x.created_at.replace(tzinfo=timezone.utc).isoformat(), 'expires_at': x.expires_at.replace(tzinfo=timezone.utc).isoformat(), 'storage': x.storage_condition_snapshot, 'operator': x.operator_name, 'department': x.department_name_snapshot, 'name': x.product_name_snapshot or job.product.name} for x in labels],
    }


@app.post('/api/agent/jobs/{job_id}/heartbeat')
def agent_heartbeat(job_id: int, request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
    if not job:
        raise HTTPException(404, 'Job not found')
    check_claim(request, job)
    if job.status != 'printing':
        return {'ok': False, 'status': job.status}
    now = utcnow()
    expiry = now + timedelta(seconds=settings.print_lease_seconds)
    result = db.execute(update(PrintJob).where(
        PrintJob.id == job_id, PrintJob.status == 'printing',
        PrintJob.claim_token == request.headers.get('X-Print-Claim', ''),
    ).values(lease_expires_at=expiry))
    db.commit()
    return {'ok': result.rowcount == 1, 'lease_expires_at': expiry.isoformat()}



@app.post('/api/agent/jobs/{job_id}/complete')
def agent_complete(job_id: int, request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
    if not job:
        raise HTTPException(404, 'Job not found')
    check_claim(request, job)
    now = utcnow()
    result = db.execute(
        update(PrintJob)
        .where(PrintJob.id == job_id, PrintJob.printer_id == printer.id, PrintJob.status == 'printing', PrintJob.claim_token == request.headers.get('X-Print-Claim', ''))
        .values(status='completed', completed_at=now, lease_expires_at=None)
    )
    db.commit()
    if result.rowcount != 1:
        current = db.scalar(select(PrintJob.status).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
        if current is None:
            raise HTTPException(404, 'Job not found')
        return {'ok': False, 'status': current}
    return {'ok': True, 'status': 'completed'}


@app.post('/api/agent/jobs/{job_id}/fail')
async def agent_fail(job_id: int, request: Request, db: Session = Depends(get_db)):
    printer = agent_printer(request, db)
    job = db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.printer_id == printer.id))
    if not job:
        raise HTTPException(404, 'Job not found')
    check_claim(request, job)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if job.status != 'printing':
        return {'ok': False, 'status': job.status}
    state = 'attention' if body.get('uncertain') else 'failed'
    result = db.execute(update(PrintJob).where(
        PrintJob.id == job_id, PrintJob.status == 'printing',
        PrintJob.claim_token == request.headers.get('X-Print-Claim', ''),
    ).values(status=state, error_message=str(body.get('error', 'Ошибка печати'))[:2000],
             completed_at=utcnow(), lease_expires_at=None))
    db.commit()
    return {'ok': result.rowcount == 1, 'status': state if result.rowcount == 1 else 'unchanged'}



@app.get('/api/departments')
def departments_api(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    loc = current_location(db, user, request)
    departments = db.scalars(select(Department).where(Department.location_id == loc.id, Department.active.is_(True)).order_by(Department.sort_order, Department.name)).all()
    items=[]
    for d in departments:
        count=db.scalar(select(func.count(Product.id)).where(Product.location_id==loc.id, Product.active.is_(True), Product.department_id==d.id)) or 0
        items.append({'id':d.id,'name':d.name,'product_count':count})
    return {'items':items}

@app.post('/api/departments')
def create_department(payload: DepartmentCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin','manager'})
    loc=current_location(db,user,request); name=payload.name.strip()
    if not name: raise HTTPException(422,'Название цеха не может быть пустым')
    if db.scalar(select(Department).where(Department.location_id==loc.id, Department.name==name)):
        raise HTTPException(409,'Такой цех уже существует')
    max_order=db.scalar(select(func.max(Department.sort_order)).where(Department.location_id==loc.id)) or 0
    d=Department(organization_id=user.organization_id,location_id=loc.id,name=name,sort_order=max_order+1,active=True)
    db.add(d); db.flush()
    db.add(AuditLog(location_id=loc.id,user_id=user.id,action='CREATE_DEPARTMENT',entity_type='department',entity_id=d.id,operator_name=user.name,details=name))
    db.commit(); db.refresh(d)
    return {'id':d.id,'name':d.name,'product_count':0}

@app.patch('/api/departments/{department_id}')
def update_department(department_id:int,payload:DepartmentUpdate,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    check_role(user, {'admin','manager'}); loc=current_location(db,user,request)
    d=db.scalar(select(Department).where(Department.id==department_id,Department.location_id==loc.id))
    if not d: raise HTTPException(404,'Цех не найден')
    if payload.name is not None:
        name=payload.name.strip()
        if not name: raise HTTPException(422,'Название цеха не может быть пустым')
        dup=db.scalar(select(Department).where(Department.location_id==loc.id,Department.name==name,Department.id!=d.id))
        if dup: raise HTTPException(409,'Такой цех уже существует')
        d.name=name
    if payload.active is not None: d.active=payload.active
    db.add(AuditLog(location_id=loc.id,user_id=user.id,action='UPDATE_DEPARTMENT',entity_type='department',entity_id=d.id,operator_name=user.name,details=d.name))
    db.commit(); return {'ok':True,'id':d.id,'name':d.name,'active':d.active}

@app.delete('/api/departments/{department_id}')
def archive_department(department_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    check_role(user, {'admin','manager'}); loc=current_location(db,user,request)
    d=db.scalar(select(Department).where(Department.id==department_id,Department.location_id==loc.id))
    if not d: raise HTTPException(404,'Цех не найден')
    db.execute(update(Product).where(Product.location_id==loc.id,Product.department_id==d.id).values(department_id=None,updated_at=utcnow()))
    d.active=False
    db.add(AuditLog(location_id=loc.id,user_id=user.id,action='ARCHIVE_DEPARTMENT',entity_type='department',entity_id=d.id,operator_name=user.name,details=d.name))
    db.commit(); return {'ok':True,'id':d.id,'active':False}

@app.patch('/api/departments/{department_id}/products')
def assign_department_products(department_id:int,payload:DepartmentProductsUpdate,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    check_role(user, {'admin','manager'}); loc=current_location(db,user,request)
    d=db.scalar(select(Department).where(Department.id==department_id,Department.location_id==loc.id,Department.active.is_(True)))
    if not d: raise HTTPException(404,'Цех не найден')
    ids=set(payload.product_ids)
    if ids:
        valid=set(db.scalars(select(Product.id).where(Product.id.in_(ids),Product.location_id==loc.id,Product.active.is_(True))).all())
        if valid != ids: raise HTTPException(422,'Один или несколько продуктов не принадлежат текущей точке')
    db.execute(update(Product).where(Product.location_id==loc.id,Product.department_id==d.id).values(department_id=None,updated_at=utcnow()))
    if ids:
        db.execute(update(Product).where(Product.location_id==loc.id,Product.id.in_(ids)).values(department_id=d.id,updated_at=utcnow()))
    db.add(AuditLog(location_id=loc.id,user_id=user.id,action='ASSIGN_DEPARTMENT_PRODUCTS',entity_type='department',entity_id=d.id,operator_name=user.name,details=f'products={sorted(ids)}'))
    db.commit(); return {'ok':True,'department_id':d.id,'product_ids':sorted(ids),'count':len(ids)}

@app.get('/api/locations')
def locations_api(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    locations = db.scalars(select(Location).where(
        Location.organization_id == user.organization_id, Location.active.is_(True)
    ).order_by(Location.name)).all()
    current = current_location(db, user, request)
    return {'items': [{'id': x.id, 'name': x.name, 'address': x.address, 'timezone': x.timezone, 'current': x.id == current.id} for x in locations]}


@app.post('/api/locations')
async def create_location(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin'})
    body = await request.json()
    name = str(body.get('name') or '').strip()
    address = str(body.get('address') or '').strip()
    timezone_name = str(body.get('timezone') or settings.timezone).strip()
    if not name:
        raise HTTPException(422, 'Укажите название точки')
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(timezone_name)
    except Exception:
        raise HTTPException(422, 'Некорректный часовой пояс')
    loc = Location(organization_id=user.organization_id, name=name, address=address, timezone=timezone_name, active=True)
    db.add(loc); db.flush()
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='CREATE_LOCATION', entity_type='location', entity_id=loc.id, operator_name=user.name, details=name))
    db.commit()
    return {'id': loc.id, 'name': loc.name, 'address': loc.address, 'timezone': loc.timezone}


@app.post('/api/locations/{location_id}/clone-catalog')
def clone_catalog(location_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin'})
    target = db.scalar(select(Location).where(Location.id == location_id, Location.organization_id == user.organization_id, Location.active.is_(True)))
    if not target:
        raise HTTPException(404, 'Точка не найдена')
    source = db.scalar(select(Location).where(Location.organization_id == user.organization_id, Location.id != target.id, Location.active.is_(True)).order_by(Location.id))
    if not source:
        raise HTTPException(409, 'Нет точки-источника каталога')
    existing_names = {x.name for x in db.scalars(select(Product).where(Product.location_id == target.id)).all()}
    source_products = db.scalars(select(Product).where(Product.location_id == source.id, Product.active.is_(True))).all()
    copied = 0
    for src in source_products:
        if src.name in existing_names:
            continue
        db.add(Product(
            location_id=target.id, name=src.name, category=src.category, source_page=src.source_page,
            source_unit=src.source_unit, label_mode=src.label_mode, shelf_life_minutes=src.shelf_life_minutes,
            warning_before_minutes=src.warning_before_minutes, critical_before_minutes=src.critical_before_minutes,
            storage_condition=src.storage_condition, technology_card=src.technology_card,
            shelf_life_status=src.shelf_life_status, shelf_life_basis=src.shelf_life_basis,
            shelf_life_source_url=src.shelf_life_source_url, verification_note=src.verification_note,
            image_name=src.image_name, active=True
        ))
        copied += 1
    target.catalog_seed_version = 1
    db.add(AuditLog(location_id=target.id, user_id=user.id, action='CLONE_CATALOG', entity_type='location', entity_id=target.id, operator_name=user.name, details=f'source={source.id}; copied={copied}'))
    db.commit()
    return {'ok': True, 'source_location_id': source.id, 'copied': copied}


@app.post('/api/locations/switch')
async def switch_location(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    body = await request.json()
    try:
        location_id = int(body.get('location_id'))
    except Exception:
        raise HTTPException(422, 'Некорректная точка')
    loc = db.scalar(select(Location).where(
        Location.id == location_id, Location.organization_id == user.organization_id, Location.active.is_(True)
    ))
    if not loc:
        raise HTTPException(404, 'Точка не найдена')
    request.session['location_id'] = loc.id
    request.session['csrf'] = secrets.token_urlsafe(24)
    return {'ok': True, 'location': {'id': loc.id, 'name': loc.name, 'timezone': loc.timezone}, 'csrf': request.session['csrf']}


@app.get('/api/printers')
def printers_api(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    printers = db.scalars(select(Printer).where(Printer.location_id == loc.id).order_by(Printer.name)).all()
    return {'items': [
        {'id': p.id, 'name': p.name, 'driver': p.driver, 'host': p.host, 'port': p.port, 'queue_name': p.queue_name,
         'dpi': p.dpi, 'label_width_mm': p.label_width_mm, 'label_height_mm': p.label_height_mm, 'active': p.active,
         'last_seen_at': fmtdt(p.last_seen_at, loc.timezone)} for p in printers
    ]}


def validate_printer_config(driver, name, host, queue):
    adapter = ADAPTERS.get(driver)
    if not adapter:
        raise HTTPException(422, 'Выберите поддерживаемый прямой драйвер')
    if not name or not name.strip():
        raise HTTPException(422, 'Укажите название принтера')
    if adapter.requires_host and not (host or '').strip():
        raise HTTPException(422, 'Для сетевого принтера укажите IP/host')
    if adapter.requires_queue and not (queue or '').strip():
        raise HTTPException(422, 'Укажите системную очередь принтера')


@app.post('/api/printers')
def create_printer(payload: PrinterCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    name = payload.name.strip()
    validate_printer_config(payload.driver, name, payload.host, payload.queue_name)
    token = new_agent_token()
    p = Printer(location_id=loc.id, name=name, driver=payload.driver, host=payload.host.strip(), port=payload.port, queue_name=payload.queue_name.strip(), dpi=payload.dpi, label_width_mm=payload.label_width_mm, label_height_mm=payload.label_height_mm, agent_token_hash=token_hash(token), active=True)
    db.add(p); db.flush()
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='CREATE_PRINTER', entity_type='printer', entity_id=p.id, operator_name=user.name, details=p.name))
    db.commit()
    return {'id': p.id, 'name': p.name, 'agent_token': token}


@app.patch('/api/printers/{printer_id}')
def update_printer(printer_id: int, payload: PrinterUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    printer = db.scalar(select(Printer).where(Printer.id == printer_id, Printer.location_id == loc.id))
    if not printer:
        raise HTTPException(404, 'Принтер не найден')
    if db.scalar(select(PrintJob.id).where(PrintJob.printer_id == printer.id, PrintJob.status.in_(['created', 'printing', 'attention']))):
        raise HTTPException(409, 'Сначала завершите или отмените задания этого принтера')
    data = payload.model_dump(exclude_unset=True)
    proposed_driver = data.get('driver', printer.driver)
    proposed_host = data.get('host', printer.host) or ''
    proposed_queue = data.get('queue_name', printer.queue_name) or ''
    validate_printer_config(proposed_driver, data.get('name', printer.name), proposed_host, proposed_queue)
    for key, value in data.items():
        setattr(printer, key, value.strip() if isinstance(value, str) else value)
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='UPDATE_PRINTER', entity_type='printer', entity_id=printer.id, operator_name=user.name, details=json.dumps(data, ensure_ascii=False)))
    db.commit(); db.refresh(printer)
    return {'ok': True, 'id': printer.id}


@app.delete('/api/printers/{printer_id}')
def archive_printer(printer_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin'})
    loc = current_location(db, user, request)
    printer = db.scalar(select(Printer).where(Printer.id == printer_id, Printer.location_id == loc.id))
    if not printer:
        raise HTTPException(404, 'Принтер не найден')
    if db.scalar(select(PrintJob.id).where(PrintJob.printer_id == printer.id, PrintJob.status.in_(['created', 'printing', 'attention']))):
        raise HTTPException(409, 'Сначала завершите или отмените задания этого принтера')
    printer.active = False
    db.add(AuditLog(location_id=loc.id, user_id=user.id, action='ARCHIVE_PRINTER', entity_type='printer', entity_id=printer.id, operator_name=user.name, details=printer.name))
    db.commit()
    return {'ok': True, 'id': printer.id, 'active': False}


@app.post('/api/account/password')
async def change_password(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    body = await request.json()
    current = str(body.get('current_password') or '')
    new_password = str(body.get('new_password') or '')
    if not password_verify(current, user.password_hash):
        raise HTTPException(403, 'Текущий пароль неверен')
    if len(new_password) < settings.min_password_length:
        raise HTTPException(422, f'Новый пароль должен содержать минимум {settings.min_password_length} символов')
    if new_password == current:
        raise HTTPException(422, 'Новый пароль должен отличаться от текущего')
    user.password_hash = password_hash(new_password)
    request.session['auth_version'] = token_hash(user.password_hash)
    request.session['csrf'] = secrets.token_urlsafe(24)
    db.add(AuditLog(location_id=current_location(db, user, request).id, user_id=user.id, action='CHANGE_PASSWORD', entity_type='user', entity_id=user.id, operator_name=user.name, details='password changed'))
    db.commit()
    return {'ok': True, 'csrf': request.session['csrf']}


@app.get('/api/audit')
def audit_api(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    check_role(user, {'admin', 'manager'})
    loc = current_location(db, user, request)
    logs = db.scalars(select(AuditLog).where(AuditLog.location_id == loc.id).order_by(AuditLog.created_at.desc()).limit(300)).all()
    return {'items': [{'id': x.id, 'action': x.action, 'entity': x.entity_type, 'entity_id': x.entity_id, 'operator': x.operator_name, 'details': x.details, 'created_at': fmtdt(x.created_at, loc.timezone)} for x in logs]}


@app.get('/api/agent/download')
def download_agent(user: User = Depends(current_user)):
    """Only portable print-worker sources; excludes server secrets and databases."""
    import io
    import zipfile
    root = BASE_DIR.parent
    files = ['agent/agent.py', 'agent/.env.example', 'requirements-agent.txt',
             'app/printer_adapters.py', 'app/label_render.py',
             'app/fonts/DejaVuSans.ttf', 'app/fonts/DejaVuSans-Bold.ttf', 'app/fonts/LICENSE.txt',
             'docs/WINDOWS_PILOT.md']
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root / name, name)
    return Response(buffer.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="Markify-Windows-Agent.zip"',
                             'Cache-Control': 'no-store'})
