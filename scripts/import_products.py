from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import bootstrap_schema_and_migrate, ensure_bootstrap_data, slug_name
from app.models import Product
from scripts.data_seed import PRODUCTS


if __name__ == '__main__':
    bootstrap_schema_and_migrate()
    ensure_bootstrap_data()
    db = SessionLocal()
    try:
        existing = {(p.name, p.category) for p in db.scalars(select(Product)).all()}
        added = 0
        for category, name in PRODUCTS:
            if (name, category) in existing:
                continue
            db.add(Product(
                name=name, category=category,
                shelf_life_minutes=None, label_mode='manual_expiry', shelf_life_status='needs_confirmation',
                technology_card='', shelf_life_basis='Подтвердить по маркировке изготовителя / утвержденной ТД.',
                verification_note='Импортировано из предоставленного перечня.',
                image_name=f'{slug_name(name)}.svg', active=True,
            ))
            added += 1
        db.commit()
        total = db.scalar(select(func.count(Product.id))) or 0
        print(f'Imported: {added}; total: {total}')
    finally:
        db.close()
