"""Create a consistent SQLite backup, including committed WAL data."""
import argparse
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import engine


def main():
    parser = argparse.ArgumentParser(description='Резервная копия базы Markify SQLite')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if engine.dialect.name != 'sqlite':
        parser.error('Для PostgreSQL используйте pg_dump и процедуру восстановления вашего сервера.')
    output=args.output.resolve()
    if output.exists():
        parser.error('Файл назначения уже существует; выберите новое имя.')
    output.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(engine.url.database) as source, sqlite3.connect(output) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Копия не прошла integrity_check')
    print(f'Резервная копия проверена: {output}')


if __name__ == '__main__':
    main()
