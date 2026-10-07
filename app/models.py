from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utc_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default='pilot')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    locations: Mapped[list['Location']] = relationship(back_populates='organization', cascade='all, delete-orphan')
    users: Mapped[list['User']] = relationship(back_populates='organization', cascade='all, delete-orphan')

class Location(Base):
    __tablename__ = 'locations'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    address: Mapped[str] = mapped_column(String(240), nullable=False, default='')
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default='Europe/Moscow')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    catalog_seed_version: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    organization: Mapped['Organization'] = relationship(back_populates='locations')
    products: Mapped[list['Product']] = relationship(back_populates='location')
    printers: Mapped[list['Printer']] = relationship(back_populates='location')

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), nullable=False, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default='operator')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    organization: Mapped['Organization'] = relationship(back_populates='users')
    location: Mapped['Location | None'] = relationship()

class Department(Base):
    __tablename__ = 'departments'
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    location: Mapped['Location'] = relationship()
    products: Mapped[list['Product']] = relationship(back_populates='department')
    __table_args__ = (UniqueConstraint('location_id', 'name', name='uq_departments_location_name'),)

class Product(Base):
    __tablename__ = 'products'
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey('departments.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    label_mode: Mapped[str] = mapped_column(String(30), nullable=False, default='manual_expiry')
    shelf_life_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_before_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critical_before_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_condition: Mapped[str] = mapped_column(String(200), nullable=False, default='')
    technology_card: Mapped[str] = mapped_column(String(120), nullable=False, default='')
    shelf_life_status: Mapped[str] = mapped_column(String(30), nullable=False, default='needs_confirmation')
    shelf_life_basis: Mapped[str] = mapped_column(Text, nullable=False, default='')
    shelf_life_source_url: Mapped[str] = mapped_column(Text, nullable=False, default='')
    verification_note: Mapped[str] = mapped_column(Text, nullable=False, default='')
    image_name: Mapped[str] = mapped_column(String(220), nullable=False, default='placeholder.svg')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, onupdate=utc_naive, nullable=False)
    location: Mapped['Location | None'] = relationship(back_populates='products')
    department: Mapped['Department | None'] = relationship(back_populates='products')
    labels: Mapped[list['Label']] = relationship(back_populates='product')
    __table_args__ = (Index('ix_products_location_name','location_id','name'),)

class Printer(Base):
    __tablename__ = 'printers'
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    driver: Mapped[str] = mapped_column(String(30), nullable=False, default='browser')
    host: Mapped[str] = mapped_column(String(180), nullable=False, default='')
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=9100)
    queue_name: Mapped[str] = mapped_column(String(180), nullable=False, default='')
    dpi: Mapped[int] = mapped_column(Integer, nullable=False, default=203)
    label_width_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=58)
    label_height_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    agent_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, default='')
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped['Location'] = relationship(back_populates='printers')

class PrintJob(Base):
    __tablename__ = 'print_jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False, index=True)
    printer_id: Mapped[int | None] = mapped_column(ForeignKey('printers.id'), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    operator_name: Mapped[str] = mapped_column(String(120), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    manual_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reprint_of_label_id: Mapped[int | None] = mapped_column(ForeignKey('labels.id'), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey('departments.id'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claim_token: Mapped[str] = mapped_column(String(64), nullable=False, default='')
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default='created')
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default='')
    product: Mapped['Product'] = relationship()
    labels: Mapped[list['Label']] = relationship(back_populates='print_job', cascade='all, delete-orphan', foreign_keys='Label.print_job_id')

class Label(Base):
    __tablename__ = 'labels'
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True, index=True)
    print_job_id: Mapped[int | None] = mapped_column(ForeignKey('print_jobs.id'), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    operator_name: Mapped[str] = mapped_column(String(120), nullable=False)
    reprint_of_id: Mapped[int | None] = mapped_column(ForeignKey('labels.id'), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey('departments.id'), nullable=True, index=True)
    department_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False, default='Без цеха')
    product_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False, default='')
    storage_condition_snapshot: Mapped[str] = mapped_column(String(200), nullable=False, default='')
    shelf_life_snapshot_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='active')
    product: Mapped['Product'] = relationship(back_populates='labels')
    print_job: Mapped['PrintJob'] = relationship(back_populates='labels', foreign_keys=[print_job_id])

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey('locations.id'), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator_name: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_naive)


class PrintRequest(Base):
    """An operation and its response commit atomically with its print jobs."""
    __tablename__ = 'print_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey('locations.id'), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_naive, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'location_id', 'key', name='uq_print_request_scope'),)
