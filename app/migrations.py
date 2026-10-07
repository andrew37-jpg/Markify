from datetime import datetime, timezone
from sqlalchemy import inspect, text
from .db import Base, engine


def _now_sql() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')


# SQLite's CREATE TABLE IF NOT EXISTS does not alter an existing table.  The
# project has intentionally kept a small, dependency-free migration layer for
# local installs so older Markify databases can be upgraded in place.
SQLITE_COLUMNS = {
    'departments': {
        'organization_id': 'INTEGER NOT NULL DEFAULT 1',
        'location_id': 'INTEGER NOT NULL DEFAULT 1',
        'name': "VARCHAR(120) NOT NULL DEFAULT 'Без цеха'",
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'sort_order': 'INTEGER NOT NULL DEFAULT 0',
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
    },
    'organizations': {
        'name': "VARCHAR(180) NOT NULL DEFAULT 'Markify'",
        'plan': "VARCHAR(30) NOT NULL DEFAULT 'pilot'",
        'active': "BOOLEAN NOT NULL DEFAULT 1",
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
    },
    'locations': {
        'organization_id': 'INTEGER NOT NULL DEFAULT 1',
        'name': "VARCHAR(180) NOT NULL DEFAULT 'Основная кухня'",
        'address': "VARCHAR(240) NOT NULL DEFAULT ''",
        'timezone': "VARCHAR(80) NOT NULL DEFAULT 'Europe/Moscow'",
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'catalog_seed_version': 'INTEGER',
    },
    'users': {
        'location_id': 'INTEGER',
        'organization_id': 'INTEGER NOT NULL DEFAULT 1',
        'name': "VARCHAR(120) NOT NULL DEFAULT 'Оператор'",
        'email': "VARCHAR(180) NOT NULL DEFAULT 'operator@markify.local'",
        'password_hash': "VARCHAR(300) NOT NULL DEFAULT ''",
        'role': "VARCHAR(30) NOT NULL DEFAULT 'operator'",
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
    },
    'products': {
        'location_id': 'INTEGER',
        'department_id': 'INTEGER',
        'name': "VARCHAR(200) NOT NULL DEFAULT 'Продукт'",
        'category': "VARCHAR(120) NOT NULL DEFAULT 'Без категории'",
        'source_page': 'INTEGER',
        'source_unit': 'VARCHAR(30)',
        'label_mode': "VARCHAR(30) NOT NULL DEFAULT 'manual_expiry'",
        'shelf_life_minutes': 'INTEGER',
        'warning_before_minutes': 'INTEGER',
        'critical_before_minutes': 'INTEGER',
        'storage_condition': "VARCHAR(200) NOT NULL DEFAULT ''",
        'technology_card': "VARCHAR(120) NOT NULL DEFAULT ''",
        'shelf_life_status': "VARCHAR(30) NOT NULL DEFAULT 'needs_confirmation'",
        'shelf_life_basis': "TEXT NOT NULL DEFAULT ''",
        'shelf_life_source_url': "TEXT NOT NULL DEFAULT ''",
        'verification_note': "TEXT NOT NULL DEFAULT ''",
        'image_name': "VARCHAR(220) NOT NULL DEFAULT 'placeholder.svg'",
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
        'updated_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
    },
    'printers': {
        'location_id': 'INTEGER NOT NULL DEFAULT 1',
        'name': "VARCHAR(160) NOT NULL DEFAULT 'Системная печать'",
        'driver': "VARCHAR(30) NOT NULL DEFAULT 'browser'",
        'host': "VARCHAR(180) NOT NULL DEFAULT ''",
        'port': 'INTEGER NOT NULL DEFAULT 9100',
        'queue_name': "VARCHAR(180) NOT NULL DEFAULT ''",
        'dpi': 'INTEGER NOT NULL DEFAULT 203',
        'label_width_mm': 'INTEGER NOT NULL DEFAULT 58',
        'label_height_mm': 'INTEGER NOT NULL DEFAULT 40',
        'agent_token_hash': "VARCHAR(64) NOT NULL DEFAULT ''",
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'last_seen_at': 'DATETIME',
    },
    'print_jobs': {
        'department_id': 'INTEGER',
        'lease_expires_at': 'DATETIME',
        'claim_token': "VARCHAR(64) NOT NULL DEFAULT ''",
        'attempt_count': 'INTEGER NOT NULL DEFAULT 0',
        'location_id': 'INTEGER',
        'product_id': 'INTEGER NOT NULL DEFAULT 1',
        'printer_id': 'INTEGER',
        'quantity': 'INTEGER NOT NULL DEFAULT 1',
        'operator_name': "VARCHAR(120) NOT NULL DEFAULT 'Оператор'",
        'user_id': 'INTEGER',
        'mode': "VARCHAR(30) NOT NULL DEFAULT 'manual_expiry'",
        'manual_expires_at': 'DATETIME',
        'reprint_of_label_id': 'INTEGER',
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
        'claimed_at': 'DATETIME',
        'completed_at': 'DATETIME',
        'status': "VARCHAR(30) NOT NULL DEFAULT 'created'",
        'error_message': "TEXT NOT NULL DEFAULT ''",
    },
    'labels': {
        'location_id': 'INTEGER',
        'department_id': 'INTEGER',
        'department_name_snapshot': "VARCHAR(120) NOT NULL DEFAULT 'Без цеха'",
        'print_job_id': 'INTEGER',
        'product_id': 'INTEGER NOT NULL DEFAULT 1',
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
        'expires_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
        'operator_name': "VARCHAR(120) NOT NULL DEFAULT 'Оператор'",
        'reprint_of_id': 'INTEGER',
        'product_name_snapshot': "VARCHAR(200) NOT NULL DEFAULT ''",
        'storage_condition_snapshot': "VARCHAR(200) NOT NULL DEFAULT ''",
        'shelf_life_snapshot_minutes': 'INTEGER',
        'status': "VARCHAR(20) NOT NULL DEFAULT 'active'",
    },
    'audit_logs': {
        'location_id': 'INTEGER',
        'user_id': 'INTEGER',
        'action': "VARCHAR(60) NOT NULL DEFAULT 'UNKNOWN'",
        'entity_type': "VARCHAR(60) NOT NULL DEFAULT 'unknown'",
        'entity_id': 'INTEGER',
        'operator_name': "VARCHAR(120) NOT NULL DEFAULT 'System'",
        'details': "TEXT NOT NULL DEFAULT ''",
        'created_at': "DATETIME NOT NULL DEFAULT '__NOW__'",
    },
}


def _add_sqlite_columns() -> None:
    insp = inspect(engine)
    now = _now_sql()
    with engine.begin() as conn:
        for table, columns in SQLITE_COLUMNS.items():
            if table not in insp.get_table_names():
                continue
            existing = {c['name'] for c in inspect(conn).get_columns(table)}
            for name, definition in columns.items():
                if name in existing:
                    continue
                ddl = definition.replace('__NOW__', now.replace("'", "''"))
                if engine.dialect.name == 'postgresql':
                    ddl = ddl.replace('DATETIME', 'TIMESTAMP').replace('BOOLEAN NOT NULL DEFAULT 1', 'BOOLEAN NOT NULL DEFAULT TRUE').replace('BOOLEAN NOT NULL DEFAULT 0', 'BOOLEAN NOT NULL DEFAULT FALSE')
                conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name in {'sqlite', 'postgresql'}:
        _add_sqlite_columns()
