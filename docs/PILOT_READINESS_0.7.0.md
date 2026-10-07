# Markify 0.7.0 — Pilot Readiness

## Что исправлено в этой версии

1. Browser print:
   - `browser_ready` больше не считается `completed`;
   - оператор явно подтверждает «Печать выполнена» или «Не напечатано»;
   - добавлены audit actions `PRINT_COMPLETED` / `PRINT_CANCELLED`.

2. Print Agent:
   - job получает lease;
   - agent отправляет heartbeat;
   - истекший lease переводится в `attention`;
   - автоматического повторного физического задания после неопределенного результата нет;
   - retry выполняется вручную admin/manager после проверки принтера;
   - если отправка на принтер состоялась, но callback `complete` не дошел, job не помечается `failed`, чтобы не создавать ложную повторную печать.

3. Multi-location:
   - пользователь имеет `location_id`;
   - admin/manager могут переключать активные точки своей организации;
   - добавлены создание точки и клонирование каталога;
   - оператор работает в назначенной точке.

4. Security:
   - публичный `/api/health` возвращает только `status`;
   - добавлена смена пароля;
   - production startup блокирует стандартные session/admin secrets;
   - production требует HTTPS-only session cookie.

## Проверено

- Python compilation: OK.
- Regression + hardening tests: **29 passed**.
- Legacy SQLite migration: OK; существующая база получила новые поля `users.location_id`, `print_jobs.lease_expires_at`, `print_jobs.attempt_count`.

## Что всё еще нельзя честно назвать 100% подтвержденным

- Физическая печать на конкретной модели Zebra/TSC/Xprinter.
- Фактическая кириллица, DPI, шрифты и позиционирование на конкретном расходнике.
- Полный Chromium E2E с реальным системным print dialog.
- Автоматические сроки для 147 продуктов: Markify намеренно не выдумывает их без подтвержденных правил.
- Production deployment с HTTPS, PostgreSQL, резервным копированием и мониторингом в реальной инфраструктуре.

Эти пункты требуют внешней инфраструктуры/оборудования и не должны подменяться тестовым TCP listener.
