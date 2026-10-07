import json
import re

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import PrintRequest
from .services import token_hash


def reserve_print_request(db, request: Request, user_id: int, location_id: int, body: dict):
    """Return (reservation, replay). A UNIQUE insert serializes concurrent retries."""
    key = request.headers.get('Idempotency-Key')
    if key is None:
        return None, None  # Older API clients remain compatible.
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key):
        raise HTTPException(422, 'Некорректный ключ запроса печати')
    fingerprint = token_hash(request.url.path + '\n' + json.dumps(body, sort_keys=True, separators=(',', ':')))
    query = select(PrintRequest).where(
        PrintRequest.user_id == user_id, PrintRequest.location_id == location_id, PrintRequest.key == key
    )
    existing = db.scalar(query)
    if existing is None:
        reservation = PrintRequest(user_id=user_id, location_id=location_id, key=key, fingerprint=fingerprint)
        db.add(reservation)
        try:
            db.flush()
            return reservation, None
        except IntegrityError:
            db.rollback()
            existing = db.scalar(query)
            if existing is None:
                raise
    if existing.fingerprint != fingerprint:
        raise HTTPException(409, 'Этот ключ уже использован для другого запроса печати')
    if existing.response_json is None:
        raise HTTPException(409, 'Запрос печати ещё обрабатывается')
    return None, json.loads(existing.response_json)


def finish_print_request(db, reservation, response: dict):
    if reservation is not None:
        reservation.response_json = json.dumps(response, ensure_ascii=False)
    db.commit()
    return response
