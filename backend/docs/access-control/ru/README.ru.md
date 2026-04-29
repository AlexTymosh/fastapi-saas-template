# Документация по контролю доступа

Эта папка описывает целевую модель контроля доступа для FastAPI SaaS template.

## Область применения

Документация покрывает:

- onboarding пользователя и создание организации;
- роли и права доступа на уровне tenant/организации;
- роли и права сотрудников платформы;
- правила invite и membership;
- план изменений кода для удаления `superadmin`;
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

```text
Tenant endpoints:   /api/v1/organisations/*
Platform endpoints: /api/v1/platform/*
```

## Документы

| Файл | Назначение |
|---|---|
| `business-rules.md` | Продуктовые и доменные правила для пользователей, организаций, memberships, invites и platform staff |
| `role-matrix.md` | Матрицы прав для tenant и platform ролей |
| `platform-access.md` | Модель platform staff, permissions, bootstrap и audit rules |
| `implementation-plan.md` | Пошаговый план изменений кода |
