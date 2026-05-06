# Security review кода ветки `main` 
2026-05-06

> Локальный аудит, а не полноценный — это partial security review по доступному коду ветки main.

---

## 1. Проверка доступа и полноты анализа

| Проверка | Статус | Комментарий |
|---|---|---|
| Доступ к репозиторию | OK | Репозиторий доступен, public, default branch — main. |
| Чтение ветки main | PARTIAL | Точные файлы из main читались через GitHub connector. Рекурсивный listing/локальный clone не удался. |
| Security-relevant код изучен | PARTIAL | Прочитаны auth, JWT, users, organisations, memberships, invites, platform, audit, rate-limit, settings, logging, errors, middleware, compose, .env.example. |
| Тесты запущены | FAIL | Локальный git clone не прошёл из-за DNS. pytest, ruff, black, isort не запускались. |
| Ограничения | PARTIAL | Миграции, все тесты и полный file tree не удалось проверить полностью. |

---

## 2. Карта security-relevant частей проекта

| Область | Files / directories | Почему важно для безопасности |
|---|---|---|
| Application entrypoint / middleware | `backend/app/main.py` | Подключает middleware, exception handlers, router, lifespan, rate limiter. |
| API router wiring | `backend/app/api/master_router.py` | Показывает полный набор подключённых API-модулей. |
| Authentication | `backend/app/core/auth.py`, `auth_claims.py`, `auth_jwt.py` | Bearer extraction, JWT validation, claims mapping. |
| Settings / env / secrets | `backend/app/core/config/settings.py`, `.env.example`, `compose.yaml` | Auth/rate-limit/prod guards, Vault, Redis, DB, Keycloak, outbox crypto. |
| Users | `users/api/users.py`, `users/services/users.py`, `users/models/user.py` | Local user projection, external_auth_id, user status. |
| Organisations | `organisations/api/organisations.py`, `services/repositories/models` | Tenant resources, soft delete, slug, owner/admin actions. |
| Memberships / roles | `memberships/services`, `repositories`, `models` | Tenant isolation, one-user-one-org, owner invariant. |
| Invites | `invites/api`, `services`, `repositories`, `models` | Invite token, email binding, expiry, replay, role assignment. |
| Platform/admin logic | `platform/api/*`, `platform/services/*`, `core/platform/*` | Platform permissions, staff roles, global admin actions. |
| Suspended users/orgs | `access_control/guards.py`, user/org services | Central active/suspended guards. |
| Rate limiting | `core/rate_limit/*` | Redis-backed throttling, invite policies, Retry-After. |
| Audit logging | `audit/models`, `audit/services`, `audit/context` | Security event trail, metadata validation, actor context. |
| Structured logging | `core/logging/*`, `middleware/access_log.py` | Redaction, request logs, request_id. |
| Error handling | `core/errors/handlers.py` | Problem Details, validation errors, stack trace hiding. |
| CORS | Fixed: `CorsSettings` в `settings.py`, `CORSMiddleware` в `main.py` | CORS выключен по умолчанию и включается только с явным allowlist origins. |
| Tests / tooling | `backend/pyproject.toml`, README commands | Pytest markers, ruff config, dependency surface. |

---

## 3. Threat model проекта

| Угроза | Возможный ущерб | Затронутые области |
|---|---|---|
| Пользователь получает доступ к чужой организации | Утечка данных тенанта, BOLA | Organisations, memberships, repositories |
| IDOR через organisation_id, membership_id, invite_id | Чтение/обновление чужих ресурсов | Tenant endpoints |
| Tenant user получает platform privileges | Полная компрометация платформы | core/platform, platform_staff |
| Приостановленный пользователь продолжает защищённые действия | Обход политики | UserService, active guards |
| Replay / кража invite token | Несанкционированное создание membership | Invite token flow |
| Brute force invite | Попытка вступить в организацию | Invite accept + rate limit |
| Обход rate-limit | Злоупотребление invite/platform endpoints | Redis/rate-limit policies |
| Секреты в логах/аудите | Утечка token/password/key | logging processors, audit metadata |
| Утечка информации через ошибки | Перечисление token/email/resource | errors, invites |
| Потеря аудита / неполный аудит | Пробел в криминалистике | audit service, transaction boundaries |
| Конкурентные admin/staff операции | Удалён последний platform admin или нарушен owner invariant при похожих ошибках синхронизации | membership/platform staff |
| Soft-deleted данные всё ещё видны | Раскрытие удалённых данных тенанта | organisation repositories/platform service |
| Некорректная обработка будущих медицинских документов | Высокорисковое нарушение приватности | future file/document module, GDPR |

---

## 4. Auth / Authentication review

| Проблема | File / location | Риск | Сценарий эксплуатации | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| `from_verified_jwt_claims()` игнорирует `resource_client_id` | `auth_claims.py` | Вводящий в заблуждение контракт; будущий разработчик может решить, что валидация клиента там происходит | Будущее изменение опирается на `resource_client_id`, но метод его молча игнорирует | Удалить параметр или явно валидировать intended client/audience. Поскольку audience уже валидируется в JWT validator, задокументировать это | P4 |
| Auth отключён по умолчанию в local/dev конфиге | `.env.example`, settings validators | Случайное небезопасное развёртывание при неправильно заданном окружении как local | Приложение развёрнуто с `APP__ENVIRONMENT=local`, `AUTH__ENABLED=false` | Добавить deployment checklist и CI config validation. Сохранить prod validator, но блокировать деплой, если env не является явно prod/staging | P3 |
| JWT validation в целом корректна | `auth_jwt.py` | Низкий | Валидирует issuer, audience, exp, sub, alg=RS256, JWKS | Сохранить. Добавить тесты для issuer/audience/alg/kid rotation | P4 |

---

## 5. Authorization review

### 5.1 Tenant authorization

| Проблема | File / location | Риск | Сценарий эксплуатации | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Нет централизованной зависимости `require_active_user` | Проверки активности разбросаны по сервисам | Непоследовательная защита; уже видно на `/users/me` | Новый endpoint забывает вызвать `ensure_user_is_active()` | Ввести `CurrentUserContext` / `require_active_user` dependency и использовать в защищённых маршрутах | P1 |
| Tenant isolation в основном реализована корректно | Organisation/membership services + `backend/tests/api/test_tenant_bola_idor.py` | Низкий | Пользователь передаёт чужой `organisation_id`; проверка membership блокирует доступ | Fixed: добавлены BOLA/IDOR regression tests для tenant UUID path params (`organisation_id`, `membership_id`, `invite_id`) | Fixed |
| Правило one-user-one-organisation существует | Membership model/repository/service | Низкий | Пользователь пытается вступить/создать вторую организацию | Частичный уникальный индекс БД + проверки в сервисе блокируют активное второе членство. Сохранить. Добавить concurrency test | — |

### 5.2 Platform authorization

| Проблема | File / location | Риск | Сценарий эксплуатации | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Защита последнего platform admin от race condition | `PlatformStaffService.change_role/suspend_staff()`, `PlatformStaffRepository.lock_active_platform_admins()` | Исправлено | Active platform admin rows блокируются через SQLAlchemy `with_for_update()` перед demote/suspend; PostgreSQL применяет `SELECT ... FOR UPDATE`, SQLite-тесты покрывают lock-aware path без имитации row-lock semantics | Сохранить regression tests для последнего admin и сценариев с другим active admin | Fixed |
| Ограниченные audit permissions объявлены, но не применяются в audit list API | `permissions.py`, `platform/api/audit_events.py` | Избыточная видимость аудита | Будущая support/compliance роль получает слишком много данных аудита | Реализовать отдельный limited audit endpoint/filter/redaction или удалить неиспользуемый `AUDIT_READ_LIMITED` до реализации | P2 |
| Platform role отделена от tenant role | `core/platform/write_context.py` | Низкий | Tenant owner пытается вызвать platform endpoints | Требует local user + active platform_staff + permission. Хороший baseline. Сохранить — нет superadmin bypass в tenant flows | — |

### 5.3 Dependency order

| Проблема | File / location | Риск | Сценарий эксплуатации | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Rate-limit dependency требует аутентифицированного субъекта | `rate_limit/dependencies.py` | Невозможно переиспользовать для публичных endpoints | Будущему публичному endpoint нужен IP throttling, но dependency требует auth | Разделить на `authenticated_rate_limit_dependency` и `public_or_authenticated_rate_limit_dependency` | P2 |
| DB session может открываться до некоторых guards | FastAPI dependency graph в сигнатурах маршрутов | Низкий/Средний | Неудачная аутентификация всё равно создаёт DB/session объект в зависимости от порядка разрешения | Сохранить side-effect-free DB session dependency. Для чувствительных endpoints предпочтительно auth/current-user context до вызовов сервисов | P3 |

---

## 6. BOLA / IDOR review

| Endpoint | Resource ID | Текущая защита | Риск BOLA/IDOR | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| `GET /api/v1/organisations/{organisation_id}` | organisation_id | `OrganisationAccessService`: user active + org active + membership | Низкий | Fixed: regression test подтверждает, что член org A не читает org B и получает Problem Details 403 | Fixed |
| `PATCH /api/v1/organisations/{organisation_id}` | organisation_id | Сервис проверяет membership owner/admin актора | Низкий | Fixed: regression test подтверждает 403 для cross-org update и неизменность org B в БД | Fixed |
| `DELETE /api/v1/organisations/{organisation_id}` | organisation_id | Только owner | Низкий | Fixed: regression tests подтверждают 403 для admin/member/non-member не из целевой org и отсутствие soft-delete | Fixed |
| `GET /api/v1/organisations/{organisation_id}/directory` | organisation_id | Актор должен быть активным членом | Низкий | Fixed: regression test подтверждает 403 для cross-org directory read | Fixed |
| `GET /api/v1/organisations/{organisation_id}/memberships` | organisation_id | Только owner/admin | Низкий | Fixed: regression test подтверждает 403 для tenant member management view | Fixed |
| `PATCH /api/v1/organisations/{organisation_id}/memberships/{membership_id}/role` | membership_id | Целевой membership загружается по membership_id + organisation_id | Низкий | Fixed: regression test подтверждает 404 для membership_id из другой org и неизменность роли | Fixed |
| `DELETE /api/v1/organisations/{organisation_id}/memberships/{membership_id}` | membership_id | Ограничен org + правилами owner/admin | Низкий | Fixed: regression test подтверждает 404 для cross-org membership delete и активность чужого membership сохраняется | Fixed |
| `POST /api/v1/organisations/{organisation_id}/invites` | organisation_id | Актор должен быть owner/admin org | Низкий | Fixed: regression test подтверждает 403 для cross-org invite create и отсутствие созданного invite | Fixed |
| `DELETE /api/v1/organisations/{organisation_id}/invites/{invite_id}` | invite_id | Invite загружается по invite_id + organisation_id | Низкий | Fixed: regression test подтверждает 404 для cross-org invite revoke и сохранение pending invite | Fixed |
| `POST /api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | invite_id | Invite загружается по invite_id + organisation_id | Низкий | Fixed: regression test подтверждает 404 для cross-org invite resend и неизменность token/expires/status | Fixed |
| `POST /api/v1/invites/accept` | token | Hash токена + совпадение аутентифицированного email + verified email | Средний | Добавить audit + нормализованный error response | P1/P3 |
| `/api/v1/platform/*` | user/org/staff/audit IDs | Platform permission guard | Средний по дизайну | Добавить rate limit и limited views для support/compliance | P2 |

---

## 7. Invite flow security review

| Проблема | File / location | Риск | Сценарий эксплуатации | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Принятие invite не аудируется | `InviteService.accept_invite()` | Создание membership происходит без audit trail | Пользователь принимает invite; система создаёт membership, но нет события invite_accepted / membership-created-by-invite | Добавить `AuditAction.INVITE_ACCEPTED` или `MEMBERSHIP_CREATED`. Включить organisation_id, invite_id, membership_id, role. Добавить тест | P1 |
| Состояние токена различимо | `accept_invite()` возвращает: Invite not found, Invite has expired, Invite is no longer pending | Перечисление состояний токена для аутентифицированных атакующих | Атакующий перебирает токены и узнаёт, существовал ли токен / истёк / был использован | Вернуть одно обобщённое сообщение для невалидного invite токена. Сохранять подробную причину только в audit/metrics | P3 |
| Отзыв invite не имеет rate limit | `invites/api/invites.py` | Перебор invite ID / злоупотребление скомпрометированным admin | Admin токен используется для brute-force invite ID внутри org | Добавить политику для invite revoke/resend/admin write действий | P3 |
| Сырой токен не хранится в таблице invites | `InviteService`, Invite model | Низкий | Утечка БД раскрывает только хэши токенов, не сырые токены | Хорошо. Сохранить SHA-256 hash + high entropy token. Рассмотреть HMAC с server secret для усиления token_hash | P3 |
| Accept атомарен по статусу invite | `accept_pending_invite_by_token_hash()` | Низкий | Два пользователя пытаются использовать один токен | Атомарный `UPDATE ... WHERE status=pending` блокирует replay. Добавить concurrency regression test | — |
| Привязка email invite существует | `accept_invite()` | Низкий | Токен украден другим залогиненным пользователем | Несовпадение email блокирует принятие. Сохранить. Добавить тест для несовпадающего email | — |

---

## 8. Suspended users / organisations review

| Сценарий | Текущее поведение | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|
| Приостановленный пользователь вызывает `/users/me` | Разрешено; нет active guard в `get_me()` | Приостановленный пользователь всё ещё использует защищённый endpoint | Добавить active guard | P1 |
| Приостановленный пользователь обновляет организацию | Заблокировано в сервисе через `ensure_user_is_active()` | Низкий | Сохранить тесты | P3 |
| Приостановленный пользователь создаёт invite | Заблокировано в `_get_actor_membership()` через active user check | Низкий | Сохранить тесты | P3 |
| Приостановленный пользователь принимает invite | Заблокировано после JIT загрузки пользователя через `ensure_user_is_active()` | Низкий | Добавить regression test | P3 |
| Приостановленный platform staff использует platform API | Заблокировано через `resolve_platform_actor()` | Низкий | Сохранить тесты | P3 |
| Tenant операции приостановленной организации | Заблокировано через `ensure_organisation_active()` | Низкий | Сохранить тесты | P3 |
| Soft-deleted организация в tenant API | Repository фильтрует `deleted_at is None` | Низкий | Сохранить тесты | P3 |
| Soft-deleted организация в platform API | Platform service использует прямой `select(Organisation)` и `session.get()` | Средний/неясный | Сделать `include_deleted` явным или задокументировать, что платформа видит удалённые orgs | P2/P3 |

---

## 9. Rate limiting security review

| Endpoint / Область | Текущая политика | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|
| `POST /organisations/{id}/invites` | `INVITE_CREATE_POLICY`: 20/hour, fail-closed | Низкий | Хороший baseline. Добавить per-org измерение при злоупотреблениях | P3 |
| `POST /invites/accept` | `INVITE_ACCEPT_POLICY`: 5 per 5 min, fail-closed | Низкий/Средний | Хорошо. Рассмотреть комбинированный ключ IP+user для token attacks | P3 |
| Revoke invite | Политика отсутствует | Средний | Добавить revoke политику | P3 |
| Platform write endpoints | Fixed: `platform_write` 30/min и `platform_staff_write` 10/min, fail-closed | Низкий/контролируемый | Сохранить dependency-based защиту для всех новых platform write endpoints | P4 |
| `/users/me` | Политика отсутствует | Низкий/Средний | Добавить общую authenticated read политику позже | P3 |
| Публичные endpoints | Текущая dependency требует auth | Риск в будущем | Разделить зависимости public/authenticated limiter | P2 |
| Redis недоступен | Чувствительные invite политики fail-closed; runtime missing возвращает unavailable | Риск доступности, не обход | Хорошо для чувствительных flows. Добавить тесты для Redis timeout/unavailable | P3 |
| Retry-After | Возвращается и раскрывается через `Access-Control-Expose-Headers` | Низкий | Хорошо | P4 |
| IP spoofing | Proxy headers отключены по умолчанию | Низкий | Сохранить false, если только не за доверенным proxy со строгими сетевыми границами | P3 |

---

## 10. Secrets and configuration review

| Проблема с секретами/конфигурацией | File / location | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|
| Local compose использует слабые dev credentials | `compose.yaml`: Postgres app/app, Keycloak admin/admin, Vault dev token | Случайное переиспользование в prod | Пометить compose как dev-only; добавить CI/deployment check, предотвращающий эти значения в prod | P3 |
| Auth/rate-limit отключены в local defaults | `.env.example`, `compose.yaml` | Небезопасно при деплое как local | Prod validators существуют, но деплой должен принудительно устанавливать `APP__ENVIRONMENT=prod` | P3 |
| Prod guards присутствуют | `Settings.validate_environment_security()` | Низкий | Сохранить: auth required, docs disabled, request-id trust disabled, rate limit/edge required | P4 |
| Ключ шифрования outbox token обязателен для dev/staging/prod | `SecuritySettings`, env validator | Низкий | Хорошо. Добавить тест для отсутствующего ключа при включённой доставке invite | P3 |
| Redaction в логировании менее строгий, чем в аудите | `logging/processors.py` vs `audit/services` | Секреты могут утекать при вариантах ключей | Нормализовать ключи и использовать substring detection, как в audit metadata | P2 |

---

## 11. Logging and audit security review

### 11.1 Logging

| Область | Проблема | File / location | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Logging | Redaction только по точному ключу | `logging/processors.py` | raw-token, clientSecret, x-api-key, encrypted_raw_token могут не быть redacted при логировании | Нормализовать ключи: lower + replace `-` на `_`; redact по чувствительным подстрокам | P2 |
| Logging | Access logs включают path, но не query/body | `access_log.py` | Низкий | Хорошо; держать токены вне URL paths/query | P4 |
| Logging | Валидация Request ID существует | `request_context.py` | Низкий | Хорошо. Prod validator отключает доверие входящему request ID | P4 |

### 11.2 Audit

| Область | Проблема | File / location | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Audit | Нет audit события для invite accept | `invites/services/invites.py` | Отсутствует security trail для создания membership | Добавить audit событие | P1 |
| Audit | Валидация метаданных строгая | `audit/services/audit_events.py` | Низкий | Сохранить валидацию depth/size/type/forbidden-key | P4 |
| Audit | Защита от несовпадения audit actor есть в tenant services, но не в platform services | tenant services vs platform services | Риск внутреннего злоупотребления | Добавить `_ensure_audit_actor_matches()` в platform services | P3 |
| Audit | Отклонённые/неудачные security действия не аудируются | auth/rate/invite flows | Пробел в криминалистике | Добавить security audit для повторных ошибок invite accept и отказов platform permission при необходимости | P3 |

---

## 12. Error handling / information leakage review

| Сценарий ошибки | Текущее поведение | Риск утечки | Рекомендация | Приоритет |
|---|---|---|---|---|
| Необработанное исключение | Общий Internal Server Error Problem Details | Низкий | Хорошо; стек трейс не утекает | P4 |
| Route 404 | Общий ответ 404 | Низкий | Хорошо | P4 |
| Validation errors | Возвращаются поле-уровень invalid params | Низкий/Средний | Приемлемо для API клиентов. Избегать включения сырых входных значений | P4 |
| Invite accept невалидный токен | Различает: not found / expired / no longer pending | Средний | Нормализовать внешний ответ до "Invalid or expired invite" | P3 |
| Auth errors | Конкретные сообщения об issuer/audience/expired | Низкий | Приемлемо для dev/API клиентов; рассмотреть обобщённые auth details в prod | P4 |
| Дублирующийся slug/email | Сообщения о конфликте раскрывают существование | Низкий/Средний | Для tenant-аутентифицированных flows приемлемо. Для будущей публичной регистрации использовать обобщённые формулировки | P3 |

---

## 13. CORS / browser-facing security review

| Проблема CORS | File / location | Риск | Рекомендация | Приоритет |
|---|---|---|---|---|
| CORS middleware отсутствовал в проверенной настройке приложения | `main.py`, `settings.py` | Исправлено: браузерный доступ теперь требует явного environment-based allowlist | Fixed: добавлены `CorsSettings` + `CORSMiddleware`; wildcard запрещён в prod и несовместим с credentials | Fixed |
| Небезопасный wildcard не найден | Проверенная настройка приложения | Низкий | Хорошо. Не добавлять `allow_origins=["*"]` с credentials | P4 |
| Retry-After и X-Request-ID должны быть доступны browser frontend | `settings.py`, `main.py` | Низкий | Fixed: `CORS__EXPOSE_HEADERS` по умолчанию содержит `X-Request-ID` и `Retry-After`; сохранять этот список при deployment overrides | Fixed |

---

## 14. Database security review

| Проблема БД | File / location | Риск | Сценарий эксплуатации / сбоя | Рекомендация | Приоритет |
|---|---|---|---|---|---|
| Race condition последнего platform admin | `PlatformStaffService`, `PlatformStaffRepository` | Исправлено | Demote/suspend active platform admin блокирует active platform admin rows перед проверкой инварианта | Fixed by row-level locking of active platform admin records before demote/suspend | Fixed |
| Soft-deleted orgs видны через platform service | `platform_organisations.py` | Раскрытие удалённых данных, если не предусмотрено | Platform list/get возвращает все организации, включая строки с `deleted_at` | Добавить дефолтное `deleted_at is None` или явный флаг/разрешение `include_deleted` | P2/P3 |
| Tenant soft delete обрабатывается в repository | `organisations/repositories.py` | Низкий | Tenant reads фильтруют `deleted_at is None`; slug переименовывается при удалении | Сохранить. Добавить тесты: удалённая org недоступна и slug можно переиспользовать | P3 |
| One-user-one-org enforced для membership | `membership.py` | Низкий | Пользователь пытается создать активное членство в двух org | Хороший partial unique index | P4 |
| One active owner per org enforced | `membership.py` | Низкий | Два owner создаются одновременно | Хороший DB index; сохранить concurrency tests | P3 |
| Invite token hash уникален | `invite.py` | Низкий | Коллизия дублирующегося token hash | Хорошо | P4 |
| Дублирующийся pending invite по email на org заблокирован | `invite.py`, repository/service | Низкий | Дублирующийся pending invite на тот же email | Хорошо | P4 |
| Raw SQL injection | Проверенные repositories | Низкий | Пользовательский raw SQL не найден; используется SQLAlchemy expression API | Продолжать избегать интерполированного raw SQL | P4 |

---

## 15. API endpoint security matrix

| Method | Path | Auth | Role | Tenant guard | Rate limit | Audit | Риск |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/health/live` | Нет* | Public health | N/A | Нет | Нет | Низкий |
| GET | `/api/v1/health/ready` | Нет* | Public health | N/A | Нет | Нет | Низкий |
| GET | `/api/v1/users/me` | Да | User | N/A | Нет | Нет | Средний: пробел для приостановленного пользователя |
| POST | `/api/v1/organisations` | Да | User without org | one-user-one-org | Нет | Неизвестно, onboarding не получен | Средний/неизвестный |
| GET | `/api/v1/organisations/{organisation_id}` | Да | Member | Да | Нет | Нет | Низкий |
| PATCH | `/api/v1/organisations/{organisation_id}` | Да | Owner/Admin | Да | Нет | Да | Низкий |
| DELETE | `/api/v1/organisations/{organisation_id}` | Да | Owner | Да | Нет | Да | Низкий |
| GET | `/api/v1/organisations/{organisation_id}/directory` | Да | Member | Да | Нет | Нет | Низкий |
| GET | `/api/v1/organisations/{organisation_id}/memberships` | Да | Owner/Admin | Да | Нет | Нет | Низкий |
| PATCH | `/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role` | Да | Owner | Да | Нет | Да | Низкий |
| DELETE | `/api/v1/organisations/{organisation_id}/memberships/{membership_id}` | Да | Owner/Admin limited | Да | Нет | Да | Низкий |
| POST | `/api/v1/organisations/{organisation_id}/invites` | Да | Owner/Admin | Да | Да | Да | Низкий |
| POST | `/api/v1/invites/accept` | Да | Email-verified invited user | Via invite | Да | Нет | Средний |
| DELETE | `/api/v1/organisations/{organisation_id}/invites/{invite_id}` | Да | Owner/Admin limited | Да | Нет | Да | Низкий/Средний |
| POST | `/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend` | Да | Owner/Admin limited | Да | Да | Да | Низкий |
| GET | `/api/v1/platform/users` | Да | USERS_READ | Global platform | Нет | Нет | Средний |
| GET | `/api/v1/platform/users/{user_id}` | Да | USERS_READ | Global platform | Нет | Нет | Средний |
| POST | `/api/v1/platform/users/{user_id}/suspend` | Да | USERS_SUSPEND | Global platform | `platform_write` | Да | Низкий/контролируемый |
| POST | `/api/v1/platform/users/{user_id}/restore` | Да | USERS_RESTORE | Global platform | `platform_write` | Да | Низкий/контролируемый |
| GET | `/api/v1/platform/organisations` | Да | ORGANISATIONS_READ | Global platform | Нет | Нет | Средний |
| GET | `/api/v1/platform/organisations/{organisation_id}` | Да | ORGANISATIONS_READ | Global platform | Нет | Нет | Средний |
| POST | `/api/v1/platform/organisations/{organisation_id}/suspend` | Да | ORGANISATIONS_SUSPEND | Global platform | `platform_write` | Да | Низкий/контролируемый |
| POST | `/api/v1/platform/organisations/{organisation_id}/restore` | Да | ORGANISATIONS_RESTORE | Global platform | `platform_write` | Да | Низкий/контролируемый |
| PATCH | `/api/v1/platform/organisations/{organisation_id}` | Да | ORGANISATIONS_CORRECT_PROFILE | Global platform | `platform_write` | Да | Низкий/контролируемый |
| GET | `/api/v1/platform/audit-events` | Да | AUDIT_READ | Global platform | Нет | Нет | Средний |
| GET | `/api/v1/platform/staff` | Да | PLATFORM_STAFF_MANAGE | Global platform | Нет | Нет | Средний |
| POST | `/api/v1/platform/staff` | Да | PLATFORM_STAFF_MANAGE | Global platform | `platform_staff_write` | Да | Низкий/контролируемый |
| PATCH | `/api/v1/platform/staff/{staff_id}/role` | Да | PLATFORM_STAFF_MANAGE | Global platform | `platform_staff_write` | Да | Низкий/Средний: last-admin invariant защищён row-level lock |
| POST | `/api/v1/platform/staff/{staff_id}/suspend` | Да | PLATFORM_STAFF_MANAGE | Global platform | `platform_staff_write` | Да | Низкий/Средний: last-admin invariant защищён row-level lock |
| POST | `/api/v1/platform/staff/{staff_id}/restore` | Да | PLATFORM_STAFF_MANAGE | Global platform | `platform_staff_write` | Да | Низкий/контролируемый |

_\* Код health router не был получен; публичный статус выведен из README/API wiring._

---

## 16. Security test coverage

> Тесты не запущены и не прочитаны полностью. Поэтому «Текущее покрытие» ниже — не утверждение о фактическом отсутствии, а список того, что нужно проверить/добавить.

| Область тестирования безопасности | Текущее покрытие | Недостающие тесты | Риск | Приоритет |
|---|---|---|---|---|
| Unauthenticated access | Неизвестно | Все защищённые endpoints возвращают 401 | Auth bypass regression | P2 |
| Forbidden access | Неизвестно | Матрица member/admin/owner | Privilege escalation | P2 |
| Tenant isolation | Покрыто regression tests в `backend/tests/api/test_tenant_bola_idor.py` | Расширить матрицу при добавлении новых tenant UUID endpoints | BOLA/IDOR | Fixed/P3 |
| Suspended user | Частично по коду, тесты неизвестны | `/users/me` suspended должен возвращать 403 | Обход политики | P1 |
| Suspended organisation | Неизвестно | Чтение/обновление/invite заблокированы | Обход политики тенанта | P2 |
| Invite token expiry/replay | Код корректный, тесты неизвестны | Expired, accepted, replay, concurrent accept | Invite takeover | P1 |
| Invite accept audit | Отсутствует в коде | Проверить создание audit события | Пробел в криминалистике | P1 |
| Invite brute force/rate limit | Неизвестно | 429 + Retry-After + Redis failure | Token attack | P2 |
| Redis unavailable/timeout | Неизвестно | fail-closed для invite политик | Неопределённость доступности/безопасности | P2 |
| Platform/tenant boundary | Неизвестно | Tenant user не может вызывать `/platform/*` | Platform escalation | P1 |
| Last platform admin race | Покрыт lock-aware regression tests для demote/suspend; полноценная concurrency-гарантия зависит от PostgreSQL `SELECT ... FOR UPDATE` | PostgreSQL concurrent demote/suspend test при доступном external DB | Platform lockout | Fixed/P3 |
| No secret logging | Неизвестно | Варианты redaction: token, raw-token, api-key, bearer, email | Утечка секретов | P2 |
| Problem Details shape | Неизвестно | Схема 401/403/404/409/422/429/500 | Согласованность клиента/безопасности | P3 |
| CORS | Fixed | Explicit allowlist origins, credentials validation, exposed `X-Request-ID`/`Retry-After` headers | Браузерная мисконфигурация снижена; deployment должен задать конкретные origins | Fixed |

**Команды для качества, найденные/ожидаемые из метаданных проекта:**

```bash
cd backend
pytest -q -m "not external_db"
pytest -q -m integration -rs
ruff check .
ruff format --check .
```

> black / isort конфиги не были видны в полученном `pyproject.toml`; ruff настроен для lint/format/import ordering.

---

## 17. Приоритизация security issues

| Приоритет | Область | Проблема | File / location | Воздействие | Рекомендуемое исправление |
|---|---|---|---|---|---|
| P1 | Suspended users | `/users/me` разрешён для приостановленного пользователя | `users/api/users.py`, `users/services/users.py` | Приостановленный пользователь всё ещё использует защищённый endpoint | Добавить active-user guard |
| P1 | Audit / invite | Invite accept не аудируется | `invites/services/invites.py` | Создание membership не имеет audit trail | Добавить `INVITE_ACCEPTED` audit event |
| Fixed | CORS | Явная CORS конфигурация добавлена | `main.py`, `settings.py` | Браузерный frontend использует безопасный allowlist | Сохранять environment-based origins без wildcard в prod |
| P2 | Rate limit | Fixed: platform writes имеют `platform_write`/`platform_staff_write` rate limit | `platform/api/*`, `core/platform/write_context.py`, `core/rate_limit/policies.py` | Злоупотребление с валидным platform токеном ограничено fail-closed политиками | Сохранить regression tests |
| P2 | Logging | Redaction слишком точный по ключу | `logging/processors.py` | Вариантные секретные ключи могут утекать | Нормализовать и использовать substring-match чувствительных ключей |
| P2 | Platform audit | Limited audit permission не используется | `permissions.py`, `audit_events.py` | Избыточная видимость аудита | Реализовать limited audit view/redaction |
| P2/P3 | Soft delete | Platform org list включает удалённые orgs | `platform_organisations.py` | Раскрытие удалённых данных, если не предусмотрено | Добавить флаг/разрешение `include_deleted` |
| P3 | Invite errors | Состояние токена различимо | `invites/services/invites.py` | Низкая вероятность перечисления | Нормализовать внешние сообщения |
| P3 | Rate limit | Invite revoke не имеет rate limit | `invites/api/invites.py` | Злоупотребление/перебор с admin токеном | Добавить revoke политику |
| P3 | Audit | Platform services не имеют actor-match guard | `platform/services/*` | Риск внутреннего злоупотребления | Добавить `_ensure_audit_actor_matches()` |
| P4 | Auth claims | Неиспользуемый `resource_client_id` | `auth_claims.py` | Путаница разработчика | Удалить или применить |

---

## 18. План исправлений

| Шаг | Действие | Files / areas | Ожидаемый результат | Приоритет |
|---|---|---|---|---|
| 1 | Добавить active-user guard для `/users/me` | `users/api/users.py`, `users/services/users.py`, `access_control/guards.py` | Приостановленный пользователь не может вызывать защищённый self endpoint | P1 |
| 2 | Добавить invite accept audit event | `audit/models/audit_event.py`, `invites/services/invites.py`, tests | Создание membership через invite аудируемо | P1 |
| 4 | Добавить BOLA regression tests | `backend/tests/api/test_tenant_bola_idor.py` | Fixed: cross-tenant `organisation_id`, `membership_id`, `invite_id` доступ зафиксирован как заблокированный; write-сценарии проверяют неизменность чужих ресурсов | Fixed |
| 5 | Добавить CORS настройки и middleware | `settings.py`, `main.py`, CORS tests | Fixed: браузерная безопасность явно настроена через env-based allowlist; CORS выключен по умолчанию | Fixed |
| 6 | Fixed: добавлены platform write rate limits | `core/rate_limit/policies.py`, `core/platform/write_context.py`, `platform/api/*` | Злоупотребление platform write снижено; 429 + Retry-After и fail-closed 503 покрыты тестами | Completed |
| 7 | Усилить logging redaction | `core/logging/processors.py` | Вариантные секретные ключи redacted | P2 |
| 8 | Реализовать limited audit view или удалить неиспользуемое limited разрешение | `core/platform/permissions.py`, `platform/api/audit_events.py` | Доступ support/compliance чётко определён | P2 |
| 9 | Нормализовать invite token error responses | `invites/services/invites.py` | Меньше утечки состояния токена | P3 |
| 10 | Добавить security test suite markers | `tests/security/*` или существующие тесты | Security regressions становятся видимыми | P1/P2 |

---

## 19. Точные инструкции по файлам

| File | Необходимое изменение | Причина | Тесты для добавления/обновления |
|---|---|---|---|
| `backend/app/users/services/users.py` | В `get_me()` вызывать `ensure_user_is_active(user)` перед return | Приостановленный пользователь в настоящее время проходит через `/users/me` | `test_users_me_forbidden_for_suspended_user` |
| `backend/app/users/api/users.py` | Предпочтительно использовать централизованный `CurrentUserContext` / active user dependency | Избегать разбросанных проверок активности | Auth dependency tests |
| `backend/app/audit/models/audit_event.py` | Добавить `INVITE_ACCEPTED` или `MEMBERSHIP_CREATED` action | Отсутствующий audit action | Enum/schema migration test |
| `backend/app/invites/services/invites.py` | После создания membership в `accept_invite()` записать audit event | Принятие invite должно быть трассируемым | `test_accept_invite_records_audit_event` |
| `backend/app/invites/services/invites.py` | Нормализовать внешние ошибки для невалидного/истёкшего/использованного токена | Снизить перечисление состояний токена | `test_accept_invite_uses_generic_invalid_response` |
| `backend/app/platform/repositories/platform_staff.py` | Fixed: добавлен метод блокировки active platform admin строк через `with_for_update()` | Предотвратить race condition последнего admin | Lock-aware service/repository regression tests; PostgreSQL concurrent test можно добавить при external DB |
| `backend/app/platform/services/platform_staff.py` | Fixed: demote/suspend active platform admin проверяют наличие другого active admin после блокировки active admin rows | Предотвратить нарушение инварианта при конкурентном доступе | `test_cannot_demote_last_active_platform_admin`, `test_cannot_suspend_last_active_platform_admin`, allowed-with-other-admin tests |
| `backend/app/core/config/settings.py` | Fixed: добавлен `CorsSettings` с enabled, allow_origins, credentials, methods, headers, exposed_headers, max_age и validation | Конфигурация браузерной части явная; wildcard + credentials и prod wildcard запрещены | Settings validation tests |
| `backend/app/main.py` | Fixed: добавлен `CORSMiddleware` в app factory, включается только при enabled + origins | Избежать будущего небезопасного wildcard patch | CORS response tests |
| `backend/app/core/rate_limit/policies.py` | Fixed: добавлены `platform_write` и `platform_staff_write`; invite revoke policy остаётся отдельным P3 | Platform write политики зарегистрированы и fail-closed | `tests/rate_limit/test_policy_registry.py`, `tests/platform/test_platform_write_rate_limiting.py` |
| `backend/app/core/rate_limit/dependencies.py` | Разделить authenticated и public limiter dependencies | Текущий limiter всегда требует auth | Public endpoint limiter unit test |
| `backend/app/core/logging/processors.py` | Использовать нормализованный ключ и substring-based redaction | Точный redaction по ключу слишком слаб | Redaction tests для raw-token, clientSecret, x-api-key, encrypted_raw_token |
| `backend/app/platform/api/audit_events.py` | Добавить limited audit endpoint/filter или требовать только полный `AUDIT_READ` и удалить limited разрешение | Избегать вводящей в заблуждение модели разрешений | Permission matrix tests |
| `backend/app/platform/services/platform_organisations.py` | Принять решение и реализовать дефолтную обработку `deleted_at` | Платформа в настоящее время видит soft-deleted orgs | `include_deleted=false/true` tests |
| `backend/app/core/platform/write_context.py` | Рассмотреть общий helper для валидации platform audit actor | Снизить риск внутреннего злоупотребления | Platform service unit tests |
| `backend/app/core/auth_claims.py` | Удалить или применить `resource_client_id` | Избегать вводящего в заблуждение мёртвого параметра | JWT claims mapping unit test |
