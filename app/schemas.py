from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str


class PrintJobCreate(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=100)
    expires_at: datetime | None = None
    printer_id: int | None = None
    reprint_of_label_id: int | None = None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None

class DepartmentProductsUpdate(BaseModel):
    product_ids: list[int] = Field(default_factory=list)

class BatchPrintCreate(BaseModel):
    department_id: int
    printer_id: int | None = None

class ProductUpdate(BaseModel):
    # All fields are optional because this schema is used for PATCH semantics.
    name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    source_unit: str | None = Field(default=None, max_length=30)
    department_id: int | None = None
    shelf_life_minutes: int | None = Field(default=None, ge=1)
    warning_before_minutes: int | None = Field(default=None, ge=0)
    critical_before_minutes: int | None = Field(default=None, ge=0)
    storage_condition: str | None = Field(default=None, max_length=200)
    shelf_life_status: str | None = None
    label_mode: str | None = None
    shelf_life_basis: str | None = None
    shelf_life_source_url: str | None = None
    verification_note: str | None = None

    @field_validator('name', 'category', 'storage_condition', 'shelf_life_status', 'label_mode', 'shelf_life_basis', 'shelf_life_source_url', 'verification_note')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('Поле не может быть null')
        return value

    @field_validator('shelf_life_status')
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in {'verified', 'needs_confirmation', 'manual'}:
            raise ValueError('invalid shelf_life_status')
        return v

    @field_validator('label_mode')
    @classmethod
    def validate_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in {'auto_from_shelf_life', 'manual_expiry'}:
            raise ValueError('invalid label_mode')
        return v


class ProductCreate(ProductUpdate):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default='Без категории', max_length=120)
    label_mode: str | None = 'manual_expiry'
    shelf_life_status: str | None = 'needs_confirmation'


class PrinterCreate(BaseModel):
    dpi: int = Field(default=203, ge=150, le=600)
    name: str = Field(default='Кухня 1', min_length=1, max_length=160)
    driver: str = 'xprinter'
    host: str = ''
    port: int = Field(default=9100, ge=1, le=65535)
    queue_name: str = ''
    label_width_mm: int = Field(default=58, ge=20, le=120)
    label_height_mm: int = Field(default=40, ge=15, le=120)

    @field_validator('driver')
    @classmethod
    def validate_driver(cls, v: str) -> str:
        allowed = {'browser', 'xprinter', 'raw9100', 'zpl', 'tspl', 'tsc', 'godex', 'atol', 'escpos', 'cups', 'windows'}
        if v not in allowed:
            raise ValueError('Недопустимый тип принтера')
        return v


class PrinterUpdate(BaseModel):
    dpi: int | None = Field(default=None, ge=150, le=600)
    @field_validator('*')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('Поле не может быть null')
        return value

    name: str | None = Field(default=None, min_length=1, max_length=160)
    driver: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    queue_name: str | None = None
    label_width_mm: int | None = Field(default=None, ge=20, le=120)
    label_height_mm: int | None = Field(default=None, ge=15, le=120)
    active: bool | None = None

    @field_validator('driver')
    @classmethod
    def validate_driver(cls, v: str | None) -> str | None:
        allowed = {'browser', 'xprinter', 'raw9100', 'zpl', 'tspl', 'tsc', 'godex', 'atol', 'escpos', 'cups', 'windows'}
        if v is not None and v not in allowed:
            raise ValueError('Недопустимый тип принтера')
        return v
