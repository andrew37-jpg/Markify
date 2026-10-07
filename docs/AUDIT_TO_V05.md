# Work completed after the v0.4 audit

## Fixed
- local abstract product icons, no external product photos required;
- timezone handling: UTC in database, restaurant timezone for display and manual datetime conversion;
- browser printing fallback now opens the browser print dialog automatically;
- PrintJob/Label reprint linkage and audit history;
- authentication and role-based access;
- organization/location isolation foundation;
- product create/edit/archive controls;
- product units/source page metadata fields;
- printers screen with browser and local Print Agent configuration;
- dynamic dashboard status refresh without page reload;
- print history screen;
- CSRF checks on state-changing authenticated API endpoints;
- 147 imported source products retained in the database;
- no automatic shelf-life values are invented for products whose source document does not specify them.

## Intentional limitations
- exact shelf-life values remain `needs_confirmation` until verified against the manufacturer's label and/or approved restaurant technology documentation;
- direct printer support is driver/model dependent and requires a real-device check;
- billing, password reset, email verification and enterprise integrations are not included in the local pilot package.
