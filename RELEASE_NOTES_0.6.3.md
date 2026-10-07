# Markify 0.6.3 — beta hardening release

Дата: 01.10.2026

## Исправления после пользовательского beta-прохождения

- Добавлен отсутствовавший `printers.html` и runtime-проверка обязательных шаблонов.
- Исправлен CSRF middleware order: защищенные POST/PATCH/DELETE теперь корректно видят session.
- Добавлена CSRF-защита формы входа и выхода; неавторизованные API POST теперь доходят до 401, а не блокируются CSRF.
- Исправлен относительный путь SQLite: база определяется относительно каталога проекта, а не текущей рабочей директории.
- Добавлена совместимая SQLite schema migration для старых баз.
- Исправлен PATCH продуктов: отсутствующие поля больше не сбрасываются.
- Исправлена перепечатка: API-ответ нормализуется на frontend, а новая маркировка сохраняет `reprint_of_id`.
- Исправлен agent claim: захват задания выполняется атомарным UPDATE.
- Исправлен Print Agent: ошибка получения payload больше не оставляет job в `printing` навсегда; для CUPS используются временные файлы.
- Исправлен поздний callback `fail`: завершенное задание нельзя перевести обратно в `failed`.
- Исправлена повторная загрузка seed-каталога после переименования продукта: добавлен `catalog_seed_version`.
- Dashboard корректно считает статусы по всему набору этикеток, а таблица остается ограниченной для производительности.
- Время хранения и отображения разделено: БД хранит UTC, интерфейс показывает timezone точки.
- Все продуктовые изображения встроены в проект как SVG-иконки; внешние изображения не требуются.

## Beta verification

- Python/ASGI compile: passed.
- Automated test suite: **24 passed**.
- HTML page smoke: `/`, `/products`, `/history`, `/printers` → HTTP 200 after login.
- Static assets smoke: all referenced local CSS/JS and product icon routes returned HTTP 200.
- Print workflow: manual expiry, multi-label job, print page and opened callback passed.
- Reprint chain: old label unchanged, new label links via `reprint_of_id`.
- Print Agent integration: fake TCP ZPL printer accepted 2 labels and job reached `completed`.
- Legacy SQLite migration: v0.4-era database upgraded and served all main pages with 147 products.
- Browser automation in this sandbox was attempted with Chromium but local navigation was blocked by the environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so final browser UX still requires a real local browser check on the user's Mac.

## Explicit product limitation

Direct thermal printing is code-integrated for Browser / Raw TCP 9100 / ZPL / TSPL / CUPS, but a physical printer model has not been certified in this environment. Cyrillic rendering and paper/layout must be tested on the exact printer used by a restaurant.

## Shelf-life policy

The supplied product list is not a source of exact shelf-life values per SKU. Markify therefore keeps imported products in `needs_confirmation` / `manual_expiry` until the restaurant confirms the exact shelf-life rule from manufacturer labeling and/or approved internal documentation.
