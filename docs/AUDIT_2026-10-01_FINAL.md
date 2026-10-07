# Markify final audit — 01.10.2026

## Scope

Audit based on the latest user screen recording, current application source, SQLite schema, API behavior, static assets, regression tests, legacy database migration, and a local Print Agent smoke test.

## Bugs found and fixed

1. `/printers` returned HTTP 500 when `printers.html` was missing. Fixed by restoring the template and adding startup asset validation.
2. Protected API writes returned HTTP 403 because middleware order prevented CSRF from seeing the session. Fixed middleware order and added regression coverage.
3. Login/logout did not have an explicit CSRF contract. Fixed with session token validation and hidden form token.
4. SQLite database path depended on the current working directory. Fixed to resolve relative paths from project root.
5. Old SQLite databases could miss new columns. Added idempotent schema migration.
6. Product PATCH could reset omitted fields. Fixed with `exclude_unset=True` and merged validation.
7. Reprint frontend used camelCase while API used snake_case. Added normalizer on the client.
8. Product seed ran on every startup and could recreate renamed source products. Added `catalog_seed_version`.
9. Agent claim was race-prone. Fixed with an atomic conditional UPDATE.
10. Agent could leave a job stuck in `printing` if payload retrieval failed. Fixed error handling.
11. Agent failure callback could overwrite `completed`. Fixed status guard.
12. Browser time and manual expiry handling were made timezone-aware for the restaurant location.
13. Dashboard counters previously risked undercounting due to a table-only limit; counts are now calculated over the full location set.
14. External product photos were removed from the runtime path; product icons are embedded SVG assets.

## Current verification

- 24 automated tests passed.
- All four primary HTML pages render after login.
- 147 active product records are present in the clean release database.
- All 147 product icon routes resolve.
- Manual print flow works.
- Reprint chain works.
- Printer CRUD and token hashing work.
- Agent claim/complete/fail state machine is covered by tests.
- Legacy v0.4 SQLite database migration was verified against the current application.
- Fake TCP ZPL printer beta test completed two labels and the server marked the job completed.

## Remaining non-code validation

Physical printer certification is hardware-dependent. The exact printer, label material, paper dimensions, DPI, installed fonts and Cyrillic support must be tested before commercial deployment.

Full Playwright browser automation could not be completed in the sandbox because local navigation was blocked by the environment. The application was therefore additionally validated through TestClient, live HTTP smoke tests, and the user's supplied screen recording.

## Readiness

- Core MVP: ready.
- Single-location pilot: ready for controlled pilot after printer-specific validation.
- Public multi-tenant SaaS: not yet final; billing, full organization/location administration, production secrets management, observability, backups, and deployment hardening remain separate production workstreams.
