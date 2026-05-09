# Документация по контролю доступа

Эта папка описывает целевую модель контроля доступа для FastAPI SaaS template.

## Область применения

Документация покрывает:

- onboarding пользователя и создание организации;
- роли и права доступа на уровне tenant/организации;
- роли и права сотрудников платформы;
- правила invite и membership;
- выполненное удаление legacy bypass-логики глобального администратора;
- требования к аудиту чувствительных действий.

## Главный принцип

Проект использует две отдельные плоскости авторизации:

```text
1. Доступ на уровне tenant / организации
   Пользователи действуют как owner/admin/member внутри одной организации.

2. Доступ на уровне platform / back-office
   Внутренние сотрудники действуют только через platform-only endpoints.
```

Platform roles не должны обходить обычные tenant endpoints.
Авторизация является DB-driven: tenant-права берутся из локальных memberships, а platform-права — из `platform_staff`. Внешние IdP/JWT roles не являются источником request-time authorization.

```text
Tenant endpoints:   /api/v1/organisations/*
Platform endpoints: /api/v1/platform/*
```

Keycloak является identity/authentication provider. Backend валидирует JWT access tokens и использует JWT claims только как identity input. Роли из `roles`, `realm_access`, `resource_access`, direct assignments или похожих IdP claims не должны напрямую давать tenant/platform permissions во время обработки запроса. Если позже будет добавлен JIT provisioning, внешние IdP roles можно использовать только как контролируемый, идемпотентный и аудируемый input для записи локальных `memberships` или `platform_staff`; права появляются только после записи в локальную БД.

## Документы

| Файл | Назначение |
|---|---|
| `business-rules.md` | Продуктовые и доменные правила для пользователей, организаций, memberships, invites и platform staff |
| `role-matrix.md` | Матрицы прав для tenant и platform ролей |
| `platform-access.md` | Модель platform staff, permissions, bootstrap и audit rules |
| `implementation-plan.md` | Пошаговый план изменений кода |
