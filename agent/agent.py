"""Local direct-print worker. Run from the project root OR the agent directory."""
import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import httpx
from app.printer_adapters import send, tspl, zpl, raw_text, send_tcp

load_dotenv(Path(__file__).with_name('.env'), override=False)
BASE = os.getenv('MARKIFY_URL', 'http://127.0.0.1:8000').rstrip('/')
TOKEN = os.getenv('MARKIFY_AGENT_TOKEN', '')
POLL = max(0.5, float(os.getenv('MARKIFY_AGENT_POLL_SECONDS', '2')))
HEAD = {'Authorization': f'Bearer {TOKEN}'}


def print_job(client: httpx.Client, job_id: int) -> None:
    claimed = client.post(f'{BASE}/api/agent/jobs/{job_id}/claim', headers=HEAD, timeout=10)
    claimed.raise_for_status()
    claim = claimed.json()
    if not claim.get('ok'):
        return
    headers = {**HEAD, 'X-Print-Claim': claim['claim_token']}
    sending = False
    try:
        heartbeat = client.post(f'{BASE}/api/agent/jobs/{job_id}/heartbeat', headers=headers, timeout=10)
        heartbeat.raise_for_status()
        if not heartbeat.json().get('ok'):
            return
        response = client.get(f'{BASE}/api/agent/jobs/{job_id}/payload', headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        sending = True
        # One bounded send (TCP 7 seconds / CUPS 20 seconds) per job; no auto retry.
        send(payload['printer']['driver'], payload)
    except Exception as exc:
        try:
            failed = client.post(f'{BASE}/api/agent/jobs/{job_id}/fail', headers=headers,
                                 json={'error': str(exc), 'uncertain': sending}, timeout=10)
            failed.raise_for_status()
        except Exception as report_exc:
            print('Agent: failed to report error:', report_exc, file=sys.stderr)
        return
    # Never send the print data twice because an HTTP callback failed.
    try:
        response = client.post(f'{BASE}/api/agent/jobs/{job_id}/complete', headers=headers, timeout=10)
        response.raise_for_status()
        if not response.json().get('ok'):
            raise RuntimeError('Сервер не подтвердил завершение; нужна проверка задания')
    except Exception as exc:
        print('Agent: bytes sent, confirmation failed; inspect printer before retry:', exc, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description='Markify Print Agent')
    parser.add_argument('--check', action='store_true', help='Проверить подключение без печати')
    args = parser.parse_args()
    if not TOKEN:
        raise SystemExit('Укажите MARKIFY_AGENT_TOKEN в agent/.env')
    with httpx.Client(follow_redirects=False) as client:
        if args.check:
            response = client.get(f'{BASE}/api/agent/jobs', headers=HEAD, timeout=10)
            response.raise_for_status()
            print(f"Агент подключен, принтер #{response.json()['printer_id']}. Печать не выполнялась.")
            return
        while True:
            try:
                response = client.get(f'{BASE}/api/agent/jobs', headers=HEAD, timeout=10)
                response.raise_for_status()
                for job in response.json().get('jobs', []):
                    print_job(client, job['id'])
            except Exception as exc:
                print('Agent:', exc, file=sys.stderr)
            time.sleep(POLL)


if __name__ == '__main__':
    main()
