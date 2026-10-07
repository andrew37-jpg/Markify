# Markify 0.7.0 — Beta test report

## Test environment

- Python 3.12
- FastAPI + SQLAlchemy + SQLite
- TestClient / live Uvicorn smoke
- Chromium/Playwright attempt
- Fake TCP printer on localhost for ZPL agent integration

## Results

### Automated regression suite

**24 passed**.

Coverage includes:

- authentication and CSRF;
- page rendering;
- API authorization;
- product PATCH semantics;
- manual print workflow;
- UTC/local timezone conversion;
- reprint chain;
- printer create/update/archive;
- agent token hashing;
- atomic agent claim;
- agent complete/fail state transitions;
- product icon routes;
- seeded catalog stability.

### Live HTTP smoke

Verified after login:

- `/` → 200
- `/products` → 200
- `/history` → 200
- `/printers` → 200
- `/api/health` → 200
- `/api/products` → 147 active products

Referenced local CSS/JS assets resolved successfully.

### Print workflow

A manual-expiry job with quantity 2 was created, print page rendered two labels, and the `opened` callback changed the job to `browser_ready`.

### Reprint

A source label was expired, a reprint preview was opened, and a new job was created. The original label remained unchanged and the new label stored `reprint_of_id`.

### Print Agent

A fake TCP listener accepted a ZPL payload for two labels. The payload contained two `^XA` blocks and the server job transitioned to `completed`.

### Legacy database migration

A v0.4-era SQLite database was used as the migration source. The current application upgraded the schema and successfully served all primary pages with 147 products.

### Browser automation

Playwright with system Chromium was attempted against the local Uvicorn server. The environment blocked localhost navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`. Therefore the final release does not claim a completed automated browser E2E run. Frontend behavior was additionally validated through template rendering, asset smoke tests, JavaScript syntax checks, and the user's supplied screen recording.

## Release state

The application is suitable for a controlled single-location pilot after printer-specific validation. It is not represented as fully production-certified for all thermal printer models or as a finished public multi-tenant SaaS with billing, cloud deployment, backups, and observability.
