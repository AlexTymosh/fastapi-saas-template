# Security review: Rate-limit этап

---

## 1. Roadmap завершения rate-limit этапа

| Step | Action | Files / areas | Ожидаемый результат | Приоритет |
|---|---|---|---|---|
| 1 | [Fixed] Добавить фактические тесты порядка зависимостей endpoint для invite create/accept/resend | `backend/tests/api/test_rate_limiting.py` | 429 до тела endpoint и до DB I/O на реальных маршрутах | Fixed |
| 2 | Добавить таксономию политик | `policies.py`, `registry.py` | authenticated_default, tenant_write, platform_read, platform_write, audit_read, invite_create, invite_accept | P1 |
| 3 | Привязать settings к политикам или удалить неиспользуемые settings | `settings.py`, `policies.py` | Нет вводящей в заблуждение конфигурации; fail-open/closed контролируется согласованно | P1 |
| 4 | Добавить вариант dependency для публичного/опционального principal | `dependencies.py`, `identifiers.py` | Будущие публичные endpoints могут иметь IP-ограничение | P1 |
| 5 | Применить rate limit к высокорисковым endpoints | `organisations.py`, `platform/api/*.py`, `users.py` | Матрица endpoints в основном защищена | P1 |
| 6 | Добавить тест матрицы маршрут-политика | `tests/rate_limit/test_endpoint_protection.py` | CI падает, когда чувствительный endpoint не имеет политики | P1 |
| 7 | Добавить integration tests для Redis timeout/failure | `tests/api/test_rate_limiting_integration.py` | Поведение при таймауте/недоступности Redis проверено | P1 |
| 8 | Улучшить семантику readiness | `health/services/health.py`, tests | Readiness Redis соответствует включённым функциям | P2 |
| 9 | Добавить выборочные security logs | `dependencies.py` | 429/backend_error наблюдаемы без переполнения логов | P2 |
| 10 | Добавить HMAC/pepper для identifiers | `identifiers.py`, settings | Redis ключи менее обратимы при утечке | P2 |
| 11 | Добавить глобальную CORS конфигурацию при запуске frontend | `main.py`, settings/tests | Браузер может читать Retry-After согласованно | P2 |
| 12 | Убрать дублирующуюся документацию | `backend/docs/rate-limiting.md`, `rate_limiting.md` | Один канонический документ | P3 |

---

## 2. Точные инструкции по файлам

| File | Необходимое изменение | Причина | Тесты для добавления/обновления |
|---|---|---|---|
| `backend/app/core/rate_limit/policies.py` | Заменить только хардкодированные политики на settings-aware factory или добавить явные статические политики для всех классов endpoints. | Текущие settings частично не используются; покрытие слишком узкое. | `tests/rate_limit/test_policy_registry.py` |
| `backend/app/core/rate_limit/registry.py` | Зарегистрировать новые политики и предоставить канонические имена политик. | Предотвратить опечатки/дрейф на уровне роутера. | Добавить тесты на дубликаты/неизвестные + все ожидаемые имена. |
| `backend/app/core/rate_limit/dependencies.py` | Добавить вариант optional/public dependency; рассмотреть опцию scope по маршруту/методу; логировать выборочно blocked/backend_error. | Необходимо для будущих публичных endpoints и улучшения наблюдаемости безопасности. | Добавить тесты public IP keying, тесты timeout. |
| `backend/app/core/rate_limit/identifiers.py` | Заменить простой SHA-256 на HMAC-SHA256 с секретным pepper; не хранить сырые PII. | Лучшая приватность Redis ключей. | Добавить детерминированный HMAC тест с настроенным test secret. |
| `backend/app/invites/api/invites.py` | [Fixed] Фактический порядок протестирован для create/accept/resend без изменения бизнес-логики маршрутов. | Избежать DB/session работы до раннего 429. | Добавлены фактические invite endpoint tests: 429 без DB/session и без service instantiation. |
| `backend/app/organisations/api/organisations.py` | Применить `tenant_write` к create/update/delete/membership мутациям; применить default read политику при необходимости. | Поверхность злоупотребления org/membership в настоящее время открыта. | Тесты матрицы защиты endpoints. |
| `backend/app/platform/api/users.py` | Применить `platform_read` и `platform_write`. | Admin endpoints имеют высокое воздействие. | Тесты матрицы защиты endpoints. |
| `backend/app/platform/api/organisations.py` | Применить `platform_read` и `platform_write`. | Операции admin org имеют высокое воздействие. | Тесты матрицы защиты endpoints. |
| `backend/app/platform/api/audit_events.py` | Применить `audit_read` / expensive read политику. | Запрос может быть использован для давления на БД. | Тест over-limit + тест матрицы. |
| `backend/app/platform/api/staff.py` | Применить `platform_read` и `platform_write`. | Управление staff имеет высокое воздействие. | Тесты матрицы. |
| `backend/app/health/services/health.py` | Сделать Redis readiness условным по включённым функциям приложения, или задокументировать Redis как обязательный при наличии URL. | Текущий readiness может быть слишком строгим. | Добавить сценарии readiness для RL disabled + Redis URL down. |
| `backend/app/main.py` | Позже: добавить явные CORS настройки/middleware при наличии frontend/браузерных клиентов. | Браузерный доступ к Retry-After должен быть глобальным и предсказуемым. | Тест CORS expose headers. |
| `backend/tests/rate_limit/test_endpoint_protection.py` | Расширить до полной матрицы endpoint-политика. | Предотвратить появление в будущем чувствительного endpoint без политики. | Включить все строки из матрицы endpoints. |
| `backend/tests/api/test_rate_limiting_integration.py` | Добавить тесты Redis unavailable/timeout/invalid URL. | Синтетического fake limiter недостаточно. | Использовать невозможный Redis URL + зависающий fake limiter. |
| `backend/docs/rate-limiting.md` | Оставить как канонический doc; слить/удалить `rate_limiting.md`. | Избежать конфликтующей документации. | n/a |
| `.env.example` | Уточнить, какие настройки `RATE_LIMITING__DEFAULT_*` фактически используются после рефакторинга. | Предотвратить путаницу оператора. | Тесты конфигурации. |

---

## 3. Testing review

| Тестовый сценарий | Покрыт? | Существующие тесты | Недостающий тест | Приоритет |
|---|---|---|---|---|
| Ниже лимита — возвращает успех | Да | `test_rate_limiting.py`, integration | Фактический invite endpoint ниже лимита с Redis | P2 |
| Выше лимита — возвращает 429 | Да | Unit + Redis integration + фактические invite endpoint tests | — для invite create/accept/resend dependency-order сценария | OK |
| Retry-After присутствует | Да | Unit/integration | Fallback path при сбое window stats | P2 |
| Целые секунды | Да | Unit/integration | — | OK |
| CORS раскрывает Retry-After | Да для 429 | Unit | Глобальная CORS конфигурация при добавлении | P2 |
| Redis недоступен | Частично | fake RuntimeError | Реальный недоступный Redis URL / connection refused | P1 |
| Redis таймаут | Частично | `wait_for` существует | Тест зависающего limiter timeout | P1 |
| Режим fail-open | Да синтетически | Unit | Построение политики fail-open управляемое settings | P1 |
| Режим fail-closed | Да синтетически | Unit | Реальный путь сбоя Redis | P1 |
| Отключённый rate limiting | Да | Unit/lifespan | — | OK |
| Отсутствующий Redis URL | Да | lifespan test | Вариант для prod окружения | P2 |
| Порядок зависимостей | Да | `test_over_limit_invite_create_returns_429_before_db_or_service`, `test_over_limit_invite_accept_returns_429_before_db_or_service`, `test_over_limit_invite_resend_returns_429_before_db_or_service` | — | Fixed / OK |
| Keying по пользователю | Да | Unit | — | OK |
| Keying по IP | Нет практического пути dependency | функция identifiers существует | Тесты public dependency | P1 |
| Лимиты per-policy | Да | тесты policy | Тесты policy управляемые settings | P1 |
| Invite-специфичные лимиты | Да | policy + endpoint protection | Фактическая integration на invite маршрутах | P1 |
| Readiness включает Redis | Да | health tests | Readiness, условный по функциям | P2 |
| Сброс кэша settings | Да | fixtures/reset helper | — | OK |
| Сбои метрик не блокируют | Да | unit + OTLP | — | OK |

---

## 4. Dependency order review

| Endpoint / dependency | Текущий порядок | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|
| `rate_limit_dependency()` | Зависит от `require_authenticated_principal`, поэтому auth идёт до limiter. | Хорошо для защищённых endpoints. | Сохранить. | OK |
| Реальные invite endpoints | Архитектурное правило для защищённых invite маршрутов: auth → rate-limit → DB/session/body. Фактические tests для create/accept/resend добавлены на production routes. | Регрессия порядка зависимостей теперь должна падать, если `get_db_session` или service создаются до 429. | Сохранить порядок auth → rate-limit → DB/session/body и поддерживать новые regression tests. | Fixed / OK |
| Синтетические тесты | Route-level dependency остаётся полезной для изолированной проверки limiter contract. | Риск расхождения с production dependency graph закрыт фактическими invite endpoint tests для create/accept/resend. | Сохранять синтетические тесты как unit-level guard и реальные invite tests как production-route guard. | OK |
| DB session dependency | Lazy session, нет DB I/O по дизайну. | Создание engine/session factory всё равно может произойти до limiter при изменении порядка. | Сохранить правило no-I/O; протестировать на реальных маршрутах. | P2 |

---

## 5. Fail-open / fail-closed review

| Сценарий сбоя | Текущее поведение | Риск | Рекомендуемое поведение | Приоритет |
|---|---|---|---|---|
| Redis недоступен | Перехватывается как Redis connection/timeout/runtime ошибки; fail-closed возвращает 503, fail-open разрешает. | Хорошо. | Сохранить. | OK |
| Redis таймаут | Используется `asyncio.wait_for`. | Хорошо, но тест явной зависающей coroutine отсутствует. | Добавить тест. | P1 |
| Невалидный Redis URL | Вероятно, сбой при запуске во время создания storage. | Не нормализован/не покрыт тестами. | Добавить тест запуска с невалидным `REDIS__URL`. | P2 |
| Runtime missing | 503 + metrics. | Хорошо. | Сохранить. | OK |
| Исключение limiter | Перехватывается для выбранных исключений. | Не все общие неожиданные исключения перехватываются. | Рассмотреть перехват более широкого `Exception` вокруг storage backend, но логировать безопасно. | P2 |
| Сбой window stats после блокировки | Откат к policy expiry. | Хорошо. | Добавить тест. | P2 |
| Режим сбоя политики | Хардкодирован per-policy. | Settings `default_fail_open`/`sensitive_fail_open` не используются. | Привязать settings к созданию политик. | P1 |

---

## 6. Security review для abuse scenarios

| Сценарий злоупотребления | Текущая защита | Пробел | Рекомендация | Приоритет |
|---|---|---|---|---|
| Brute force invite токена | invite_accept, 5/5min, keyed по пользователю. | Только bucket аутентифицированного пользователя; нет измерения по IP/org/попыткам токена. | Сохранить user bucket; добавить IP fallback, если endpoint когда-либо станет публичным; рассмотреть счётчики попыток token hash. | P2 |
| Invite spam | invite_create, 20/hour keyed по пользователю. | Нет ограничения на уровне организации; resend разделяет create политику. | Добавить org-level квоту или составную политику: user + organisation. | P1 |
| Email enumeration | Создание invite может раскрывать конфликты в зависимости от ошибок сервиса. | Rate limit помогает только для create endpoint. | Добавить низкообъёмную политику и нормализовать сообщения об invite конфликтах при необходимости. | P1/P2 |
| Перечисление аккаунтов/пользователей | Platform users endpoints не защищены rate limit. | Злоупотребление/нагрузка admin не ограничена. | Добавить platform read лимиты. | P1 |
| Перебор organisation slug | Organisation create/update/list не имеют rate limit. | Возможны повторные попытки slug. | Добавить tenant write/default auth политику. | P1 |
| Злоупотребление дорогостоящими endpoints | Audit events, platform list endpoints не защищены. | Давление на БД. | Добавить expensive read политики. | P1 |
| Redis DoS высокая кардинальность | Proxy header отключён по умолчанию; используются хэши. | При неправильно включённом доверии proxy атакующий контролирует IP bucket. | Сохранять отключённым, если только не за доверенным proxy; добавить config docs/tests. | P2 |
| Обход заголовков | `x-forwarded-for` используется только при включении. | Хорошее умолчание. | Сохранить. | OK |
| Redis outage DoS | Чувствительные политики fail-closed. | Redis outage блокирует invite flows с 503. Это безопаснее, но может повлиять на доступность. | Решить per-policy; привязать settings к политикам. | P1 |
| NAT/общий IP | Текущие покрытые endpoints keyed по пользователю, не по IP. | OK для аутентифицированных. Будущие публичные endpoints требуют NAT-aware лимитов. | Использовать многоуровневые лимиты: IP + user при наличии. | P2 |
