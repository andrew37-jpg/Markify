# Markify v0.8.0 — Restaurant Direct Printing

## Main change
The kitchen workflow no longer opens the browser print dialog or offers Save as PDF.

### Direct Xprinter workflow
1. Operator selects a product.
2. Markify creates a print job.
3. Print Agent claims the job.
4. The Xprinter driver sends TSPL directly over TCP to the configured printer host/port (normally 9100).
5. Agent confirms the job as `completed` or reports `failed`.
6. The kitchen UI polls the job and shows the final status.

## UX improvements
- Quick/recent products.
- Popular products.
- Product search with Cmd/Ctrl+K.
- Enter to print from the modal.
- +/- quantity shortcuts.
- One-click exact repeat for a completed/failed/attention job.
- Printer readiness indicator.
- Clear no-printer state instead of silently falling back to PDF/browser printing.

## Safety / reliability
- Legacy browser printers are archived on startup and are not selectable in the kitchen workflow.
- Exact repeat preserves the original expiry timestamp and printer.
- Existing lease/attention/retry logic remains active for Print Agent failures.
- Browser print preview no longer calls `window.print()`.

## Verification
- Python/HTTP regression suite: **33 passed**.
- JavaScript syntax checks: dashboard.js and printers.js pass Node `--check`.
- Direct Xprinter/TSPL payload test: TCP payload successfully delivered to a local test listener.
- Live API flow verified: create Xprinter → create job → claim → payload → complete → status → repeat.

## Physical hardware limitation
The software path is implemented and tested with a TCP test listener. Physical printing, Cyrillic glyph rendering and exact label positioning still require testing with the user's exact Xprinter model and label stock. The Xprinter driver currently uses TSPL.
