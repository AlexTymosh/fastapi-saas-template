# Бизнес-правила

## 1. Регистрация пользователя и onboarding

### Правила

1. Пользователь может зарегистрироваться без организации.
2. Зарегистрированный пользователь без active membership является standalone user.
3. Standalone active user может создать организацию.
4. Когда пользователь создаёт организацию, backend должен:
   - создать или обновить local user projection;
   - создать организацию;
   - создать active membership для создателя;
   - назначить создателю роль `owner`;
   - отметить onboarding как completed.
5. Пользователь может иметь максимум один active organisation membership.
6. Создание организации должно требовать `email_verified=true`.
7. Suspended user не должен иметь возможность:
   - создавать организацию;
   - принимать invite;
   - создавать invite;
   - изменять данные организации;
   - управлять memberships;
   - выполнять platform actions.

### Не роль

`standalone user` — это не роль. Это состояние пользователя:

```text
User exists
AND user.status = active
AND no active membership exists
```

---

## 2. Правила организации

### Жизненный цикл организации

1. Организация создаётся standalone user или через administrative action на уровне platform.
2. Создатель становится `owner`.
3. Ownership организации нельзя передать через tenant/business API.
4. `owner` нельзя удалить через tenant/business API.
5. `owner` нельзя понизить до `admin` или `member`.
6. Только `owner` может удалить организацию.
7. `owner` и `admin` могут изменять `name` организации.
8. `owner` и `admin` могут изменять `slug` организации.
9. Suspended organisation должна блокировать обычные tenant actions.
10. Deleted organisation должна быть недоступна через обычные tenant endpoints.

### Модель статусов

Рекомендуемые статусы:

```text
active
suspended
```

Не добавляй статус `deleted`, пока уже существует `deleted_at`.

```text
status = active / suspended
deleted_at = marker soft deletion
```

---

## 3. Правила membership

### Роли

```text
owner
admin
member
```

### Общие правила

1. Пользователь может иметь только один active membership.
2. Membership принадлежит ровно одной организации.
3. Membership role ограничена областью конкретной организации.
4. Organisation roles не являются platform roles.
5. Platform staff roles не должны давать tenant membership rights.

### Правила Owner

`owner` может:

- смотреть организацию;
- изменять organisation name;
- изменять organisation slug;
- приглашать members;
- приглашать admins;
- повышать member до admin;
- понижать admin до member;
- удалять admin;
- удалять member;
- удалять организацию.

`owner` не может:

- передавать ownership;
- понижать себя или другого owner;
- удалять себя или другого owner через tenant API;
- приглашать другого owner.

### Правила Admin

`admin` может:

- смотреть организацию;
- изменять organisation name;
- изменять organisation slug;
- приглашать members;
- удалять members.

`admin` не может:

- приглашать admins;
- повышать members до admins;
- понижать admins;
- удалять admins;
- удалять owner;
- удалять организацию;
- передавать ownership.

### Правила Member

`member` может:

- смотреть организацию.

`member` не может:

- изменять организацию;
- приглашать пользователей;
- управлять memberships;
- удалять организацию;
- выполнять platform actions.

---

## 4. Правила Invite

1. Invite tokens должны храниться только в виде hashes.
2. Invite acceptance должен использовать request body, а не token path parameter.
3. Invite должен иметь expiry.
4. Expired invites нельзя принимать.
5. Revoked invites нельзя принимать.
6. Accepted invites нельзя использовать повторно.
7. Invite acceptance должен требовать:
   - valid token;
   - matching email;
   - `email_verified=true`;
   - active user;
   - active organisation.
8. `owner` может приглашать `member` и `admin`.
9. `admin` может приглашать только `member`.
10. `member` не может приглашать пользователей.
11. Никто не может приглашать `owner` через обычный invite flow.
12. Не должно быть duplicate pending invites для одного email в одной organisation.
13. Invite creation и invite acceptance должны быть rate-limited.
14. Invite revocation и resend должны аудироваться.

---

## 5. Правила Platform Staff

Platform roles отделены от organisation roles.

Рекомендуемые роли:

```text
platform_admin
support_agent
compliance_officer
```

Platform access должен храниться в backend, а не рассматриваться как обычный organisation membership.

Platform actions должны проходить через:

```text
/api/v1/platform/*
```

Platform actions не должны обходить:

```text
/api/v1/organisations/*
```

### Platform Admin

Может:

- suspend/restore users;
- suspend/restore organisations;
- manage platform staff;
- read audit events;
- выполнять audited emergency corrections.

### Support Agent

Может:

- читать limited user information;
- читать limited organisation information;
- помогать решать support cases.

Не должен:

- suspend users;
- suspend organisations;
- manage platform staff;
- получать доступ к unrestricted audit events.

### Compliance Officer

Может:

- читать audit events;
- выполнять или запрашивать GDPR-related workflows;
- читать limited user/organisation information, когда это необходимо.

Не должен:

- управлять organisation memberships;
- выполнять обычные tenant actions;
- manage platform staff, если это явно не разрешено.

---

## 6. Правила Audit

Audit events должны записываться для:

- organisation name changed;
- organisation slug changed;
- organisation deleted;
- member removed;
- membership role changed;
- invite created;
- invite revoked;
- invite resent;
- user suspended/restored;
- organisation suspended/restored;
- platform staff created/removed/suspended;
- GDPR export/anonymisation actions;
- emergency data correction.
