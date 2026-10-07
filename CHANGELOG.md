# 0.10.2

См. RELEASE_NOTES_0.10.2.md и docs/AUDIT_2026-10-04.md.

# Markify Changelog

## 0.10.0 — 2026-10-04
- Added universal printer adapter layer for Xprinter, Zebra/ZPL, TSC/TSPL, Godex, Atol/CUPS, ESC/POS, Generic RAW and CUPS.
- Kept the existing print queue and duplicate-safe completion semantics.
- Updated printer setup UI and generic printer error messages.
- 42 automated tests passing.

# CHANGELOG

## v0.9.0 — Departments & Batch Printing

- Added restaurant departments with default Hot Kitchen / Pizza / Sushi Bar / Cold Kitchen.
- Added product-to-department assignment and department management.
- Added department snapshots to labels so expired labels show the production area used at print time.
- Added department tabs and filtering to the main printing screen.
- Moved expiry statistics to the top of the dashboard and added a prominent expired alert.
- Added department column to control and history tables.
- Added safe batch printing for products with verified automatic shelf life.
- Added explicit reporting of skipped manual-expiry products in batch printing.
- Added migration support for `departments`, `products.department_id`, `print_jobs.department_id`, `labels.department_id`, and `labels.department_name_snapshot`.

## v0.8.0 — Restaurant direct printing

- Direct Xprinter/TSPL printing through Print Agent.
- Browser/PDF printing removed from the primary workflow.
- Print queue, lease/heartbeat, retry and direct-print status handling.
