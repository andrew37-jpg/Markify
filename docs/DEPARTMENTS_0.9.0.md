# Departments / Цеха — v0.9.0

## Data model

`departments` belongs to an organization and location. `products.department_id` points to one active department. `labels.department_name_snapshot` stores the department at print time.

## Safety

A product is never automatically guessed into a department. Built-in departments are created, but product assignment is an explicit restaurant decision.

## Batch printing

`POST /api/print-jobs/batch` accepts a department and printer. It creates one print job per product only when the product has a verified automatic shelf life. Manual-expiry products are returned as skipped with a reason.
