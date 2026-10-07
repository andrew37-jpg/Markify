from pathlib import Path
import os
import sys
import tempfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Each run owns its database; never load a pilot/production DB from .env or
# delete another concurrent run's database. Set both supported env aliases.
TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix='markify-tests-')
TEST_DB = Path(TEST_DIRECTORY.name) / 'test.db'
TEST_SETTINGS = {
    'DATABASE_URL': f'sqlite:///{TEST_DB}',
    'ENVIRONMENT': 'development',
    'SESSION_HTTPS_ONLY': 'false',
    'SESSION_SECRET': 'isolated-markify-test-session-secret',
    'BOOTSTRAP_ADMIN_EMAIL': 'admin@markify.local',
    'BOOTSTRAP_ADMIN_PASSWORD': 'ChangeMe-Please-2026!',
    'BOOTSTRAP_ORG_NAME': 'Markify Test Restaurant',
    'BOOTSTRAP_LOCATION_NAME': 'Основная кухня',
    'BOOTSTRAP_ADMIN_NAME': 'Администратор',
    'TIMEZONE': 'Europe/Moscow',
}
for key, value in TEST_SETTINGS.items():
    os.environ[key] = os.environ['MARKIFY_' + key] = value


@pytest.fixture(autouse=True)
def clean_test_db():
    yield
    try:
        from sqlalchemy import text
        from app.db import engine
        with engine.begin() as conn:
            for table in ('print_requests','auth_sessions','login_attempts','labels','print_jobs','audit_logs','printers','products','departments','users','locations','organizations'):
                conn.exec_driver_sql(f'DELETE FROM {table}')
    except Exception:
        pass
