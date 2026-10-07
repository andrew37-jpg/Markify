#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp -n .env.example .env 2>/dev/null || true
python scripts/init_db.py
printf '\nMarkify is ready.\nOpen: http://127.0.0.1:8000\nLogin: admin@markify.local\nPassword: see .env / README.md\n\n'
python run.py
