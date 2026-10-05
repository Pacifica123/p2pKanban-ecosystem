# Auth и identity v1

Документ фиксирует **минимальную auth-модель MVP** для p2pKanban.
Он должен быть совместим с уже принятыми решениями:
- backend обязателен в MVP как HTTP/API, auth/session слой и координатор синхронизации;
- модель уже sync-ready и device/replica-aware;
- full p2p, mobile, advanced permissions и полноценный public surface не являются обязательной частью первой версии.

## 1. Что фиксируем этим документом

На этапе MVP принимаем следующие решения:

1. **Серверная аутентификация только для зарегистрированного пользователя.**
2. **Базовый login-метод — email + password.**
3. **Session model = short-lived access token + rotating refresh token.**
4. **Device identity и replica identity — разные сущности.**
5. **Guest mode существует только как local-only режим клиента и не создает server-side user/session/device.**
6. **Public read surface не является обязательной частью baseline MVP** и по умолчанию выключен, хотя модель данных под него уже готова.

## 2. Минимальная auth-модель

### 2.1. Кто вообще может быть actor в MVP

В MVP различаем 4 типа actor/state:

- **guest** — анонимный пользователь без серверного аккаунта;
- **user** — зарегистрированный пользователь с `users.id`;
- **device** — пользовательское устройство/инсталляция, привязанная к пользователю;
- **replica** — sync-идентичность конкретного клиентского экземпляра.

Ключевое различие:
- **user** отвечает на вопрос “кто это?”;
- **device** отвечает на вопрос “с какого устройства он работает?”;
- **session** отвечает на вопрос “какая сейчас активная аутентифицированная сессия?”;
- **replica** отвечает на вопрос “какой клиентский экземпляр отправил sync-изменения?”.

### 2.2. Что входит в MVP

В первой версии включаем:
- sign-up, если он разрешен конфигом инстанса;
- sign-in по email/password;
- refresh session;
- sign-out текущей сессии;
- sign-out all sessions;
- просмотр своих устройств;
- revoke device;
- получение current session с привязкой к `user / device / replica`.

### 2.3. Что не входит в MVP

Сознательно **не включаем** в baseline v1:
- SSO/OAuth;
- magic link;
- passkeys/WebAuthn;
- MFA/2FA;
- полноценный password reset flow;
- email verification как обязательный барьер входа;
- invite-by-email как обязательную auth-функцию;
- service accounts;
- anonymous write access;
- cryptographic device attestation.

## 3. Модель идентичности

## 3.1. User identity

Пользователь имеет глобально пригодный UUID, но запись identity принадлежит
конкретному deployment. Общего реестра email между self-hosted узлами нет.

Канонические поля для MVP:
- `id` — глобальный UUIDv7;
- `email` — уникальный логин-идентификатор;
- `display_name` — отображаемое имя;
- `username` — необязательный публичный алиас;
- `password_hash` — хэш пароля;
- `deleted_at` — soft delete для совместимости с audit/sync-ready foundation.

Принятые правила:
- email уникален среди активных пользователей;
- email в MVP используется как login identifier, но **не считается подтвержденным каналом связи**;
- user profile и auth credentials логически разделены: профиль живет в `users`, lifecycle сессий — в `user_sessions`.

## 3.2. Device identity

Device — это серверная запись о пользовательском устройстве или клиентской установке,
которая помогает:
- показывать пользователю список его устройств;
- отзывать доступ по устройству;
- связывать session lifecycle с конкретным device;
- в будущем аккуратно состыковать auth и sync.

### Что считаем device в MVP

Для web-first MVP device — это **не железо в криптографическом смысле**.
Это доверенная сервером запись, созданная после аутентификации и обновляемая клиентом.

Иначе говоря:
- device — это **account-bound client installation record**;
- устройство не доказывает свою идентичность криптографически;
- поля `public_key`/подобные считаются future-ready и не обязательны для v1-потока.

### Поля device

Минимально фиксируем такие поля:
- `id` — UUIDv7 device;
- `user_id` — владелец устройства;
- `platform` — `web | desktop | android | ios | server`;
- `display_name` / `label` — человекочитаемое имя;
- `client_device_id` — опциональный клиентский локальный идентификатор;
- `app_version`;
- `user_agent` как метаданные запроса;
- `last_seen_at`;
- `revoked_at`.

### Правила жизненного цикла device

1. Device создается или переиспользуется при успешном `sign-up`, `sign-in` или `refresh`, если клиент передал device metadata.
2. Один пользователь может иметь много устройств.
3. Revoke device:
   - помечает устройство как отозванное;
   - отзывает все активные `user_sessions`, привязанные к нему;
   - блокирует дальнейшее использование этого device в auth/sync flow без повторной явной регистрации.
4. Удаление device физически не требуется для MVP; достаточно `revoked_at` / soft lifecycle.

## 3.3. Replica identity

Replica — это **не auth-сущность**, а sync-сущность.

Она нужна, чтобы:
- различать несколько клиентских экземпляров одного пользователя;
- обеспечивать idempotency по `(replica_id, replica_seq)`;
- вести cursors и историю примененных изменений.

Принятые правила:
- replica может быть привязана к `device_id`, но не тождественна ему;
- у одного device может быть несколько replica при необходимости;
- auth flow не обязан создавать replica немедленно, но current session и sync flow должны уметь ее учитывать;
- guest replica на сервере в MVP не поддерживается.

## 4. Session model

## 4.1. Общая схема

Принимаем минимальную схему:

- **access token** — короткоживущий signed bearer token;
- **refresh token** — длинноживущий opaque random token;
- **server session** — запись в `user_sessions`, которая является source of truth для refresh lifecycle.

### Почему именно так

Это минимально покрывает сразу несколько требований:
- web-клиенту не нужно хранить long-lived bearer token в `localStorage`;
- можно отзывать отдельные сессии и устройства;
- модель совместима с уже принятой таблицей `user_sessions`;
- sync и device flow можно аккуратно привязывать к текущей сессии.

## 4.2. Access token

Для MVP фиксируем:
- формат — signed bearer token, **по умолчанию JWT**;
- хранение на web-клиенте — **в памяти**, а не в `localStorage`;
- TTL — **15 минут**;
- token содержит минимально необходимые claims:
  - `sub` = `user_id`;
  - `sid` = `session_id`;
  - `did` = `device_id`, если есть;
  - `rid` = `replica_id`, если уже известна;
  - `exp`, `iat`.

В access token **не кладем workspace roles** как источник истины.
Роли и membership проверяются сервером по данным workspace/access слоя.

## 4.3. Refresh token

Для MVP фиксируем:
- refresh token — случайный opaque token длиной не меньше 256 бит;
- на сервере хранится только `refresh_token_hash`;
- refresh token передается через `HttpOnly`, `Secure`, `SameSite=Lax` cookie;
- TTL refresh session — **30 дней sliding**;
- каждый refresh делает **rotation** refresh token;
- reuse старого refresh token после rotation трактуется как подозрительный сценарий и ведет к revoke текущей session family минимум на уровне текущей session.

## 4.4. Session record

Запись `user_sessions` фиксирует:
- `id`;
- `user_id`;
- `device_id` nullable;
- `refresh_token_hash`;
- `user_agent`;
- `ip_address`;
- `created_at`;
- `last_seen_at`;
- `expires_at`;
- `revoked_at`.

Правила:
- одна session = один активный refresh token;
- sign-out отзывает только текущую session;
- sign-out-all отзывает все session пользователя;
- revoke device отзывает все session этого device;
- password change в будущем должен отзывать все session, но сам password change flow не обязателен для baseline MVP.

## 5. Auth flow

## 5.1. Sign-up

Sign-up — **deployment-level choice**.

Email уникален только внутри конкретного deployment. Два независимых узла не
имеют общего реестра пользователей, поэтому повторная регистрация одинакового
email создаёт две разные identity с разными UUID. Для переноса существующей
identity между web-узлами используется явный web-node link, описанный в
[`web-node-link-v1.md`](web-node-link-v1.md); обычный sign-in не выполняет
сетевой поиск аккаунта.

Это значит:
- self-hosted инстанс может включить публичную регистрацию;
- может полностью выключить `sign-up` и создавать пользователей административно/внутренне;
- остальные auth flows от этого не ломаются.

Flow:
1. Клиент отправляет `email`, `password`, `displayName` и optional `device` metadata.
2. Сервер создает `users` запись.
3. Сервер хэширует пароль через `Argon2id`.
4. Сервер создает или upsert-ит `device`.
5. Сервер создает `user_session`.
6. Сервер выдает:
   - access token в response body;
   - refresh token в secure cookie;
   - session/device snapshot в response.

## 5.2. Sign-in

Flow:
1. Пользователь передает `email + password`.
2. Сервер ищет активного пользователя по email.
3. Сервер проверяет пароль через `Argon2id` verify.
4. При успехе создает новую `user_session`.
5. Если клиент прислал device metadata, сервер создает/обновляет device record.
6. Сервер возвращает user/session/device и новый access token, а refresh token кладет в cookie.

## 5.3. Refresh

Flow:
1. Клиент вызывает `/auth/refresh` с refresh cookie.
2. Сервер находит текущую session по hash токена.
3. Проверяет, что session не истекла и не revoked.
4. Делает refresh token rotation.
5. Обновляет `last_seen_at` у session и device.
6. Выдает новый access token и новый refresh cookie.

## 5.4. Sign-out

Flow:
1. Клиент вызывает `/auth/sign-out` с access token.
2. Сервер находит `sid`.
3. Помечает session как revoked.
4. Очищает refresh cookie.

## 5.5. Sign-out all

Flow:
1. Клиент вызывает `/auth/sign-out-all`.
2. Сервер отзывает все активные session данного `user_id`.
3. Текущий access token перестает считаться валидным после ближайшей server-side проверки session status.
4. Refresh cookie очищается.

## 5.6. Revoke device

Flow:
1. Пользователь отзывает устройство через `me/devices/{deviceId}/revoke`.
2. Сервер проверяет ownership device.
3. Ставит `revoked_at` на device.
4. Отзывает все `user_sessions`, связанные с device.
5. Sync для replica этого device дальше не должен принимать push без повторной регистрации через валидную auth session.

## 6. Guest / private / public режимы

Эта тема важна, потому что в проекте уже есть future-ready задел под `public_readonly`,
но baseline MVP должен оставаться простым.

## 6.1. Guest

**Guest = анонимный local-only пользователь.**

В baseline MVP guest:
- может открыть приложение без логина;
- может работать только с локальными данными браузера;
- не получает server-side `users`, `devices`, `user_sessions`, `replicas`;
- не может sync/push/pull;
- не может комментировать, делиться workspace, управлять membership.

Это самый безопасный и минимальный вариант для первой версии.

## 6.2. Private

**Private = основной режим MVP по умолчанию.**

В private режиме:
- ресурс доступен только участникам workspace;
- все write/read операции идут через authenticated user и membership checks;
- backend не раскрывает содержимое неучастникам.

## 6.3. Shared

Технически в текущей модели данных уже есть `shared`.
Для MVP трактуем его так:
- ресурс не становится публичным для интернета;
- доступ все равно требует authentication;
- отличие от `private` только в продуктовой семантике совместной работы и правилах membership/invite.

То есть для auth-слоя и `private`, и `shared` — это **authenticated access only**.

## 6.4. Public

Под “public” в этом проекте понимаем только **`public_readonly`**.

Решение для baseline MVP:
- схема и БД могут сохранять readiness под `public_readonly`;
- но в первой рабочей версии этот режим **выключен по умолчанию**;
- guest/public server-side read surface не является обязательным acceptance criterion MVP.

Если later-phase `public_readonly` включается, то правила такие:
- anonymous read only;
- никаких anonymous writes;
- наружу отдаем только public-safe user snapshot;
- auth/session модель при этом не меняется.

## 7. Security assumptions v1

## 7.1. Базовые предположения

1. **TLS обязателен** на всех средах, кроме локальной разработки.
2. Backend для MVP — доверенная сторона.
3. В MVP **нет end-to-end encryption** и нет zero-knowledge модели.
4. Любая авторизация на доменные write/read операции делается сервером, а не только UI.

## 7.2. Password handling

Фиксируем:
- `Argon2id` для хранения паролей;
- server-side pepper опционален, но желателен;
- минимальная длина пароля — 8 символов;
- rate limit на `sign-in` и `sign-up` обязателен.

## 7.3. Token handling

Фиксируем:
- access token не кладем в `localStorage`;
- refresh token держим только в `HttpOnly` cookie;
- refresh endpoint защищен через cookie policy и rotation;
- revoke current session/device должен иметь немедленный server-side эффект для refresh flow.

## 7.4. Device trust assumptions

В MVP device identity:
- не является hardware-backed;
- не защищает от компрометации уже угнанной браузерной сессии;
- нужна в первую очередь для UX, revoke и связки auth ↔ sync.

То есть device в v1 — это **удобная управляемая identity, а не сильный криптографический фактор**.

## 7.5. Account recovery assumptions

В baseline MVP:
- password reset может отсутствовать;
- email verification может отсутствовать;
- потеря пароля в self-hosted режиме решается административно или позже отдельным flow.

Это допустимо только потому, что у нас baseline MVP и self-hosted / early-stage сценарий.
Для публичного интернет-сервиса этого уже будет недостаточно.

## 7.6. Abuse / audit assumptions

Фиксируем минимум:
- хранить `last_seen_at`, `user_agent`, `ip_address` для session-level security telemetry;
- логировать sign-in / sign-out / refresh / revoke device в `audit_log`;
- ограничивать brute force rate limit и burst по IP + email;
- не выдавать различимые ошибки вида “email exists / no such user” там, где это создает излишнюю утечку.

## 8. Что это значит для backend и API

Этот документ хорошо ложится на уже зафиксированную основу:
- `auth` модуль владеет login/logout/refresh/session lifecycle;
- `users` модуль владеет user profile и user-visible device surface;
- `workspaces` владеет access rules;
- `sync` использует replica identity, но не заменяет auth.

### Обязательные endpoint groups

Для MVP достаточно следующих групп:
- `/auth/sign-up`;
- `/auth/sign-in`;
- `/auth/refresh`;
- `/auth/sign-out`;
- `/auth/sign-out-all`;
- `/auth/session`;
- `/me`;
- `/me/devices`;
- `/me/devices/{deviceId}/revoke`;
- `/sync/replicas`;
- `/sync/push`;
- `/sync/pull`.

## 9. Решение в одном абзаце

В MVP мы берем **простую account-based auth-модель**: зарегистрированный user
входит по `email + password`, получает короткий bearer access token и rotating
refresh cookie, сессии хранятся в `user_sessions`, устройства — в `devices`, а
replica остается отдельной sync-сущностью. Guest существует только как
local-only режим без серверной identity. `private` и `shared` требуют
аутентификации, а `public_readonly` остается future-ready режимом и не является
обязательной частью baseline MVP.
