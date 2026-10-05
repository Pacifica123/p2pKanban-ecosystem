# Backend smoke scenarios v1

## Обязательный smoke-набор

### 1. Boot and health
- `GET /health`
- `GET /api/v1/health` при необходимости
- backend отвечает без 500 и без миграционных сюрпризов

### 2. Auth/session happy-path
- sign-up нового smoke пользователя;
- fallback sign-in для повторного прогона;
- `GET /auth/session` подтверждает authenticated session;
- `GET /me` и `GET /me/devices` отдают валидный профиль.

### 3. Core CRUD vertical slice
- создать workspace;
- создать board;
- создать column;
- создать card;
- изменить card;
- переместить card;
- archive/unarchive card;
- прочитать списки workspaces/columns/cards.

### 4. Derived read models
- `GET /boards/{boardId}/activity`;
- `GET /cards/{cardId}/activity`;
- `GET /workspaces/{workspaceId}/audit-log`.

### 5. Appearance surface
- получить defaults для `me/appearance` и `boards/{boardId}/appearance`;
- сохранить appearance;
- повторно прочитать и подтвердить обновление;
- partial update не ломает остальные поля.

### 6. Auth boundary regression
- `POST /auth/sign-out-all`;
- anonymous request к закрытому endpoint получает `401`, а не `500`.

## Что smoke не обязан делать
- exhaustive permissions matrix;
- every validation branch;
- sync/conflict edge cases;
- load/performance behavior.
