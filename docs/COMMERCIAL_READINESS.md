# Commercial readiness checklist

## Ready in v0.5
- core workflow;
- local abstract assets;
- SQLite + PostgreSQL-compatible SQLAlchemy setup;
- authentication session;
- roles;
- organization/location boundary;
- audit log;
- reprint relation;
- timezone-aware display / UTC storage;
- print agent architecture;
- browser fallback.

## Before paid production
- replace demo bootstrap credentials;
- HTTPS / reverse proxy;
- PostgreSQL managed instance;
- centralized secrets;
- backup/restore verification;
- rate limiting;
- CSRF middleware for all state-changing routes (JSON endpoints already expect X-CSRF-Token where used in UI);
- password reset / email verification;
- E2E browser tests;
- real printer validation for each model;
- monitoring and error alerting;
- billing/subscriptions;
- integration contracts (iiko/r_keeper/etc.);
- legal review of retention and processing policies.
