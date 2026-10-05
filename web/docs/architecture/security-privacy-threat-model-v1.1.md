# Security / privacy / threat model v1.1

- Статус: Draft v1.1
- Дата: 2026-04-14
- Назначение: зафиксировать минимальный, но уже инженерно проверяемый security/privacy слой для account-based, local-first, sync-ready p2pKanban.

> Этот документ не обещает «zero-knowledge безопасность», которой у проекта пока нет. Его задача — определить точные границы доверия, обязательные инварианты, приоритеты риска, жизненный цикл данных и release-gates, по которым можно принимать инженерные решения без самообмана.

---

## 1. Что меняет версия 1.1

По сравнению с v1 эта версия специально усиливает места, которые были слишком общими:
- вводит **проверяемые security invariants**;
- уточняет различие между **public product data**, **service-visible metadata** и **private data**;
- делает **maximal logger / redaction policy** конкретной;
- вводит требования к **локальной маркировке данных по user/workspace scope**;
- фиксирует более точную **auth/session/device state machine**;
- добавляет **data lifecycle / retention / deletion**;
- выносит в отдельный слой **operational security сервера**;
- усиливает тему **availability / abuse / quota exhaustion**;
- разделяет требования на **blocker / high / medium**, чтобы checklist перестал быть плоским.

---

## 2. Цель этого этапа

Нам нужна такая модель безопасности, которая:
- совместима с web-first и local-first архитектурой;
- не ослабляет будущий sync и optional p2p;
- не выдает dev-flow за production security;
- честно описывает privacy posture без обещаний сильнее реальной системы;
- содержит требования, которые можно проверить кодом, тестами и операционными процедурами.

Этот этап **включает**:
- trust boundaries;
- threat model v1.1;
- security invariants;
- auth/session/device semantics;
- privacy assumptions и lifecycle данных;
- review рисков для auth/session/token/storage;
- local data protection assumptions;
- sync / coordinator / relay / future p2p risk review;
- operational security baseline;
- release checklist и risk priority.

Этот этап **не включает**:
- полноценную криптографическую спецификацию;
- formal verification;
- окончательный E2EE дизайн;
- SOC2/ISO-style compliance пакет;
- детальный hardening playbook под конкретную облачную платформу.

---

## 3. Главный вывод

Для p2pKanban нельзя принимать модель «сначала быстро сделаем auth, а privacy потом как-нибудь докрутим».

Минимально здравая позиция для v1.1 такая:

1. **MVP остается account-based server-coordinated системой**.
2. **Server-side access control — канонический барьер доступа** для synced-state.
3. **Replica не является auth principal** и не подменяет собой user/device/session.
4. **Guest mode = только local-only режим**.
5. **Relay и future p2p не считаются доверенной domain-authority**.
6. **Browser local store — offline/availability слой, а не надежный сейф**.
7. **Без отдельного E2EE-проекта сервер и оператор инстанса потенциально видят synced payload в plaintext**.
8. **Перед интернет-facing использованием обязательны не только auth-фичи, но и abuse-controls, logging discipline и операционная управляемость инцидентов**.

Иначе говоря: baseline v1.1 — это **разумная прикладная безопасность и честная privacy-модель**, а не имитация zero-trust.

---

## 4. Data classes: что считаем public, service-visible и private

### 4.1. Public product data

`Public` — это только то, что владелец или продукт **намеренно** делает анонимно доступным через отдельную публичную поверхность.

Для MVP такая поверхность **не является baseline**. Значит, по умолчанию у проекта **нет** product-level public data, кроме технически публичных служебных endpoint'ов уровня `health`, которые не должны раскрывать пользовательский контент.

### 4.2. Service-visible operational metadata

Это данные, которые может видеть серверная инфраструктура или оператор инстанса в силу работы системы, но которые **не являются публичными для других пользователей**.

Сюда относятся:
- сам факт, что пользователь зарегистрирован или использует сервис;
- email, timestamps входа, IP, user agent, device label;
- факт существования workspace/board;
- граф membership;
- факты синхронизации, refresh, relay/bootstrap активности;
- технические идентификаторы `sessionId`, `deviceId`, `replicaId`, `eventId`.

Важно: это **не public data**. Это приватные или ограниченно-операционные метаданные, доступные только тем компонентам и ролям, которым они нужны для работы системы.

### 4.3. Private domain data

Private data — это пользовательское содержимое и derived state, которое не должно быть раскрыто вне авторизованного scope.

Сюда относятся:
- названия и описания workspace/board/card;
- комментарии, чек-листы, labels;
- imports/exports/backups;
- локальная offline queue и unsynced changes;
- activity/audit детали, если они раскрывают private context;
- любые payload fields, из которых можно восстановить содержимое карточек или поведения пользователя.

### 4.4. Sensitive secrets

Отдельный класс — секреты, которые нельзя логировать, отдавать в activity/audit или хранить в открытом виде, где это не требуется:
- пароли;
- refresh tokens;
- access tokens;
- password reset tokens;
- email verification tokens;
- CSRF secrets;
- relay/bootstrap tickets;
- signing secrets, webhook secrets и иные server-side ключи.

---

## 5. Assets: что защищаем

### 5.1. Identity и access
- user accounts;
- password hashes;
- sessions;
- refresh token family;
- device records;
- replica registrations;
- workspace memberships и роли.

### 5.2. Domain data
- workspaces;
- boards;
- columns;
- cards;
- comments/checklists/labels по мере включения;
- appearance settings, если они синхронизируются.

### 5.3. Derived и technical data
- change events;
- sync cursors;
- activity entries;
- audit log;
- bootstrap / relay tickets;
- import/export bundles;
- local pending operations queue.

### 5.4. Availability assets
- auth endpoints;
- refresh path;
- sync apply/pull endpoints;
- relay/bootstrap endpoints;
- storage quotas;
- dedupe cache / replay protection state;
- background cleanup jobs для session revocation, backup expiry и local wipe directives.

---

## 6. Trust boundaries

### 6.1. Граница A — пользователь и его устройство

Внутри:
- браузер/клиентское приложение;
- память процесса;
- local persistent store;
- draft state;
- pending ops.

Не предполагаем:
- что устройство не скомпрометировано;
- что на shared device никто не получит доступ к профилю браузера;
- что browser extension / malware отсутствуют.

Вывод: локальное хранение повышает доступность и UX, но не гарантирует secrecy при полном компромете устройства.

### 6.2. Граница B — web app origin

Что важно:
- XSS внутри origin = практически полный компромет локального store и access token в памяти;
- CSRF важен там, где участвуют cookie-bound endpoints;
- CORS и Origin/Referer policy — часть security, а не только удобство разработки.

### 6.3. Граница C — backend / coordinator

Backend доверяется как:
- auth/session authority;
- access-control authority;
- canonical server-side API;
- canonical coordinator для MVP sync.

Backend **не должен** автоматически считаться:
- доверенным relay для будущих peer-path без отдельного ограничения scope;
- оправданием для чрезмерного логирования пользовательских данных.

### 6.4. Граница D — relay / bootstrap services

Relay и bootstrap layer:
- могут помогать установить маршрут;
- могут переносить sync envelopes;
- могут видеть metadata маршрута и времени жизни сессии;
- не должны сами решать, кто на что имеет доступ.

В baseline v1.1 relay — это **semi-trusted transport component**, а не semantic authority.

### 6.5. Граница E — operator / support / admin plane

Это отдельная trust boundary, которую нельзя скрывать за словом “server”.

Нужно различать:
- **app runtime** — процесс приложения;
- **infra operator** — тот, кто может видеть окружение, БД, бэкапы, логи;
- **support/admin user** — тот, кто помогает пользователям через продуктовый или внутренний admin surface.

Support/admin операции не должны требовать прямого доступа в БД или лог-агрегатор. Любой такой обход — incident-level исключение, а не обычный способ работы.

### 6.6. Граница F — external integrations / import-export

Внешние интеграции и экспорт:
- расширяют attack surface;
- увеличивают риск exfiltration и over-scoped credentials;
- не должны получать больше данных, чем нужно для конкретной операции.

---

## 7. Security invariants v1.1

Ниже перечислены инварианты, которые должны держаться **всегда**, а не “обычно”. Если какой-то из них не соблюдается, security posture считается сломанным.

1. **Actor identity server-stamped.** Канонический actor для protected операции определяется сервером из текущей session context; клиент не может самостоятельно объявить другой `userId`, роль или scope.
2. **Client-supplied role never authoritative.** Любые client-side claims о ролях, membership или правах используются только как hint для UX, но не как source of truth.
3. **Replica cannot widen scope.** `replicaId` помогает с idempotency и sync lineage, но не дает право выйти за пределы текущего `user/session/device/workspace` scope.
4. **Sync apply not weaker than CRUD.** Любой sync apply проходит ту же или более строгую authz-проверку, чем эквивалентный обычный CRUD mutation.
5. **Membership revoke cuts future server acceptance.** После server-side revoke membership любые последующие sync apply от этого пользователя в данном workspace отклоняются независимо от клиентского времени создания события.
6. **Offline replay has no grandfather privilege.** Офлайн-событие, созданное до revoke, не обязано быть принято после revoke. Решение принимается по server-side canonical state на момент apply.
7. **Deleted/tombstoned entity cannot be silently resurrected.** Stale update не может неявно вернуть удаленную сущность к жизни без явного restore-правила и отдельной авторизованной операции.
8. **Derived endpoints inherit primary access boundary.** `activity`, `audit`, `export`, `snapshot`, `sync pull/apply` и другие derived endpoints обязаны наследовать те же boundaries, что и базовые сущности.
9. **Logout/revoke has explicit local wipe semantics.** После logout/revoke существует определенное правило, какие локальные данные удаляются немедленно, какие помечаются stale и какие запрещено использовать дальше.
10. **Secrets never enter logs, activity or audit payloads.** Секреты и чувствительные payload-поля не должны попадать в логи, activity feed или audit entries.
11. **Observability does not become shadow export.** Метрики, трассировки и логи не должны превращаться в скрытый канал утечки пользовательского контента.
12. **Auth/relay internet-facing surfaces are abuse-controlled.** Для auth, refresh, bootstrap, relay и sync apply обязаны существовать rate limits, quotas и limits по размеру/частоте запросов.
13. **Backup visibility is explicit.** Бэкапы считаются копиями пользовательских данных и попадают под те же privacy и operator-control требования, что и основная БД.
14. **Forced logout-all is real.** Должен существовать механизм, который делает все refresh token family пользователя недействительными и завершает дальнейшее обновление сессий без ручной чистки по одной записи.
15. **Security-sensitive changes are auditable.** Revoke membership, revoke device, reset password, rotate secrets, admin export и аналогичные операции оставляют security/audit trail без хранения лишнего payload.

---

## 8. Access boundaries

### 8.1. Канонический субъект доступа

Каноническая цепочка проверки доступа в synced-режиме:

`user -> session -> optional device -> optional replica -> workspace membership -> конкретная операция`

Правила:
- `user` — основной actor;
- `session` подтверждает текущую аутентификацию;
- `device` нужен для revoke/visibility и lifecycle;
- `replica` нужна для sync/idempotency, но не заменяет auth;
- workspace membership и роль остаются каноническим прикладным access boundary.

### 8.2. Что нельзя делать

Нельзя:
- давать доступ только потому, что клиент прислал `replicaId`;
- давать доступ только потому, что устройство когда-то было известно;
- считать, что board-level object сам по себе доказывает право на workspace;
- принимать sync event без проверки, что actor действительно имеет право на изменение нужного scope.

### 8.3. Guest boundary

Guest mode:
- существует только локально;
- не получает server-side session;
- не выполняет server-side write;
- не участвует в shared membership;
- не должен “магически” апгрейдиться в authenticated access без явного user action.

### 8.4. Public boundary

Public readonly не является baseline MVP.

Если он появится позже, его границы должны быть отдельными:
- anonymous read only;
- no anonymous write;
- no membership management;
- no leakage приватных полей через derived endpoints и metadata.

---

## 9. Auth, session, device lifecycle

### 9.1. Базовая auth-модель

Целевая модель для web MVP:
- sign-up / sign-in по `email + password`;
- `Argon2id` для password hashing;
- short-lived access token;
- opaque rotating refresh token;
- access token живет только в памяти web-клиента;
- refresh token хранится в cookie или эквивалентном secure http transport-bound механизме в зависимости от deployment-модели.

### 9.2. Обязательные flows

До non-dev deployment должны существовать:
- sign-up;
- email verification;
- sign-in;
- refresh;
- sign-out current session;
- sign-out all sessions;
- revoke device;
- password reset;
- forced password change after reset.

### 9.3. Session state machine

#### Session states
- `active` — session валидна и может refresh/access;
- `rotating` — refresh в процессе ротации;
- `suspicious` — обнаружен reuse/stolen-token pattern, session ограничивается и требует reauth;
- `revoked` — session больше не должна обновляться;
- `expired` — истекла по TTL или inactivity policy.

#### Device states
- `registered` — устройство известно пользователю;
- `active` — на устройстве есть как минимум одна действующая session;
- `revoked` — все session на устройстве отозваны;
- `stale` — устройство давно не использовалось и скрыто из обычного UI, но может оставаться в истории до retention cutoff.

### 9.4. Refresh token family semantics

1. Каждый login создает новую refresh token family.
2. Каждый refresh выдает новый refresh token и делает предыдущий single-use.
3. На сервере хранится хэш/фингерпринт refresh token, но не raw value.
4. Reuse уже использованного refresh token считается **suspicious reuse**.
5. При suspicious reuse:
   - текущая token family немедленно ревокается;
   - все access tokens продолжают жить только до short TTL, без дальнейшего refresh;
   - пользователю показывается forced reauth;
   - событие пишется в security log;
   - при высоком риске можно дополнительно revoke all sessions этого пользователя.

### 9.5. Password reset и email verification

- email verification token: single-use, short-lived, не логируется, после успешной верификации повторно не применяется;
- password reset token: single-use, short-lived, invalidates previous unused reset tokens;
- успешный password reset:
  - инвалидирует все refresh token families пользователя;
  - сбрасывает remembered device trust, если оно когда-либо появится;
  - требует sign-in заново на всех устройствах.

### 9.6. Lockout / rate limit policy

Для internet-facing auth-surface rate limiting — **blocker**, а не nice-to-have.

Минимум:
- rate limit per IP для sign-in, refresh, password reset, email verification, bootstrap;
- rate limit per account/email для sign-in и password reset;
- progressive backoff после серии неуспешных входов;
- отсутствие явной account enumeration в ответах;
- отдельные лимиты для relay/bootstrap ticket issuance.

### 9.7. Forced reauth для sensitive actions

Для операций повышенной чувствительности желателен свежий auth context:
- смена email;
- смена пароля;
- sign-out all;
- device revoke;
- экспорт полного workspace;
- будущие admin/support операции повышенного риска.

---

## 10. Cookie / CSRF / deployment model

Cookie-политика не должна описываться как одна вечная истина. Набор атрибутов зависит от deployment-модели.

| Deployment model | Пример | Cookie posture | CSRF posture |
|---|---|---|---|
| Same-origin | один origin для web и API | `HttpOnly`, `Secure`, `SameSite=Lax` или `Strict` по UX-ограничениям | Origin/Referer checks обычно достаточны для sensitive cookie-bound routes |
| Subdomain split | `app.example.com` + `api.example.com` | cookie scope и SameSite зависят от точной схемы доменов | нужны Origin/Referer checks; при сложной схеме возможен дополнительный CSRF token |
| Cross-site deployment | разные site-контексты | `SameSite=None; Secure` | требуется отдельная CSRF-стратегия: token + Origin/Referer validation + строгий CORS allowlist |

Инварианты:
- wildcard CORS недопустим для production cookie/session flows;
- cookie-bound sensitive endpoints обязаны иметь Origin/Referer validation;
- выбранная cookie/CSRF политика должна быть явно зафиксирована в deployment docs перед beta.

---

## 11. Local data protection and wipe semantics

### 11.1. Что считаем реалистичным

Для web MVP локальная защита ограничена возможностями браузера и ОС.

Мы можем рассчитывать на:
- sandbox браузера;
- изоляцию origin;
- обычные механизмы защиты пользовательского профиля ОС.

Мы **не можем** рассчитывать на:
- secrecy при наличии локального malware;
- secrecy на shared/public компьютере;
- надежное client-side key safekeeping без отдельного криптографического дизайна.

### 11.2. Локальная маркировка данных

Каждая запись в persistent local store, которая относится к конкретному пользователю или рабочему пространству, должна быть **явно размечена** минимум следующими полями:
- `owner_user_id`;
- `workspace_id` или явный marker `workspace_id = null`, если запись user-scoped;
- `data_class` (`session_cache`, `workspace_snapshot`, `offline_queue`, `user_pref`, `blob_cache`, `sync_meta` и т.п.);
- `created_at` / `updated_at`;
- `last_auth_context_id` или эквивалентный session-bound marker, если запись зависит от текущей авторизации.

Требование к ключам и индексам local store: данные разных пользователей **не должны** смешиваться так, будто они принадлежат одному аккаунту.

### 11.3. Минимальные классы локальных данных

| Local class | Пример | Переживает logout? | Переживает revoke? | Требование |
|---|---|---:|---:|---|
| `session_cache` | access-related ephemeral state | Нет | Нет | удалить немедленно |
| `offline_queue` | pending ops | Нет | Нет | удалить или пометить unusable немедленно |
| `workspace_snapshot` | локальный снимок shared data | Обычно нет для shared device; допускается policy-based wipe | Нет | нужен user/workspace scope marker |
| `user_pref` | локальные UI-предпочтения | Можно policy-based | Можно policy-based | не должны давать доступ к чужим данным |
| `blob_cache` | attachment/cache | Нет для private scopes | Нет | TTL + size limits |
| `sync_meta` | cursors, replica seq | Нет при logout/revoke | Нет | нельзя использовать после смены auth context |

### 11.4. Logout / revoke semantics

- **Logout current session**: access token очищается немедленно, session-bound store и offline queue текущего пользователя очищаются или помечаются unusable, background sync останавливается.
- **Sign-out all / revoke device**: при следующем контакте с сервером клиент получает directive на local cleanup; до этого момента локальные данные не должны использоваться для server write.
- **Switch account**: новый аккаунт не должен видеть локальные записи старого аккаунта без явной ре-гидрации под своим scope.
- **Shared device posture**: baseline должен считать shared device небезопасным; следовательно default policy для session-bound локальных данных — wipe, а не “оставим на всякий случай”.

### 11.5. Что сознательно откладываем

Future enhancement:
- application-level encryption локальной БД;
- per-workspace encryption keys;
- secure enclave / OS keychain dependent design;
- zero-knowledge backup model.

---

## 12. Sync, canonical ordering and revoke races

### 12.1. Кто штампует actor identity

Для sync actor identity определяется **только сервером** по текущему session context и его binding к `userId`, `deviceId` и разрешенному `replicaId`.

Клиент может прислать:
- `replicaId`;
- `replicaSeq`;
- `eventId`;
- client-side timestamps.

Но клиент **не может** канонически определить:
- какой `userId` считается actor;
- имеет ли он текущую роль в workspace;
- должен ли event быть принят после revoke.

### 12.2. Что считаем каноническим порядком событий

Нужно различать два порядка:

1. **Client causal order** — порядок, в котором реплика локально породила изменения.
2. **Server acceptance order** — порядок, в котором сервер принял и включил изменения в канонический журнал.

Для authz и canonical shared state решающим является **server acceptance order**, а не клиентский timestamp.

Минимальный серверный порядок должен быть выражен через:
- `(workspace_id, server_seq)` или эквивалентный monotonic server-assigned ordering;
- idempotency markers `eventId` и/или `(replicaId, replicaSeq)`;
- stored `accepted_at` timestamp.

### 12.3. Где проверяется scope ownership

Проверка обязана происходить **до apply**, на сервере, по текущему canonical state:
- существует ли workspace membership;
- позволяет ли текущая роль операцию;
- принадлежит ли target entity нужному workspace;
- не tombstoned ли entity;
- не нарушает ли mutation текущие domain invariants.

### 12.4. Revoke membership vs offline replay

Это отдельный жесткий кейс.

Правило baseline v1.1:
- если membership отозвана на сервере, то **все последующие apply от этого пользователя в этом workspace отклоняются**, даже если событие было создано офлайн до revoke;
- клиентский timestamp не дает права “доиграть старые записи задним числом”;
- повторный доступ возможен только после нового grant membership и новой аутентифицированной session;
- при этом сервер может сохранить факт отклоненной попытки как security/abuse signal, но не применяет payload.

### 12.5. Tombstone and restore semantics

- delete/tombstone побеждает stale update;
- restore — отдельная авторизованная операция с явной политикой;
- snapshot/bootstrap path не может неявно resurrect tombstoned entity;
- derived feeds не должны показывать resurrected state без реально принятого restore.

---

## 13. Relay / bootstrap / availability / abuse

### 13.1. Базовая роль relay

Relay и bootstrap помогают установить маршрут и транспортировать envelopes, но не являются источником domain authorization.

### 13.2. Реалистичные abuse-сценарии

Нужно учитывать не только confidentiality/integrity, но и availability:
- brute-force issuance bootstrap tickets;
- reuse или перепродажа чужих relay tickets;
- relay как открытый прокси/open relay;
- quota exhaustion по соединениям, bandwidth, envelopes;
- oversized payloads;
- sync flood и replay storm;
- expensive bootstrap loops и route thrashing;
- DoS на auth/refresh, после которого страдает весь sync.

### 13.3. Минимальные controls

Для internet-facing relay/bootstrap обязательны:
- short-lived scoped tickets;
- binding ticket к `user/session/scope`;
- max concurrent circuits per user/session/workspace;
- max envelope size;
- max batch size и rate limit на sync apply;
- dedupe / replay window;
- quotas по bandwidth и частоте выдачи билетов;
- возможность быстро отключить relay/bootstrap feature flag'ом;
- явное разделение telemetry для availability и security anomalies.

### 13.4. Privacy note

Даже если relay не читает payload, он все равно может видеть traffic metadata. Это часть threat model, а не “мелкая оговорка”.

---

## 14. Audit, activity, logs and maximal logger policy

### 14.1. Принцип “maximal logger” в правильном смысле

Система должна логировать **максимум security-relevant facts**, но **минимум пользовательского содержимого**.

То есть “maximal logger” для v1.1 означает:
- максимум полезных фактов об аутентификации, доступе, отказах, аномалиях и безопасности;
- минимум payload и контента;
- structured logging вместо dump всего request/response.

### 14.2. Что логировать можно

Разрешенный baseline для app/security logs:
- `request_id`, `route`, `method`, `status_code`, `latency_ms`;
- server-stamped `actor_user_id`;
- `session_id`, `device_id`, `replica_id`, `event_id`;
- `workspace_id`, `board_id`, `card_id`, если это нужно для расследования и не раскрывает payload;
- security outcome codes (`auth_failed`, `refresh_reuse_detected`, `membership_revoked`, `rate_limit_hit`, `relay_ticket_rejected`);
- source IP и user agent только там, где это нужно для security logs и troubleshooting, а не для обычного business logging.

### 14.3. Что логировать нельзя

Никогда не должны попадать в логи:
- raw `Authorization` header;
- raw `Cookie` / `Set-Cookie`;
- пароли и password reset payload;
- email verification tokens;
- access tokens;
- refresh tokens;
- CSRF tokens/secrets;
- relay/bootstrap tickets;
- полный payload карточек, комментариев, описаний, импортируемых файлов и export bundle;
- полные request/response body для sensitive routes.

### 14.4. Redaction rules

Минимальные redaction rules:
- все токены и секреты заменяются на `[REDACTED]`;
- для correlation допускается хранить только server-generated fingerprint, например HMAC/SHA-256 fingerprint от токена, но не raw value;
- IP может храниться целиком только в security logs; в обычных app logs допускается усечение/хэширование по policy;
- user-provided rich text/HTML/markdown не логируется;
- validation errors не должны эхо-выводить чувствительные поля обратно в logs.

### 14.5. Activity vs audit vs security logs

Это разные слои:
- **activity** — user-facing история действий, без секретов и без скрытых админских деталей;
- **audit** — управленческий след важной операции, с минимально нужным контекстом;
- **security logs** — события аутентификации, злоупотреблений, блокировок, reuse, rate limits и системных подозрений.

Они не должны дублировать друг друга полным payload.

---

## 15. Operational security baseline

### 15.1. Кто имеет доступ к чему

Минимально допустимая модель:
- **app runtime** имеет доступ только к тем secret/materialized stores, которые нужны для работы;
- **infra operator** может управлять инфраструктурой, но такой доступ ограничивается по принципу need-to-know;
- **support/admin** не получает прямой доступ к БД, резервным копиям и лог-сырым данным по умолчанию.

### 15.2. БД и резервные копии

- доступ к production БД и бэкапам ограничен узким набором операторов;
- доступ оформляется через управляемые роли/аккаунты, а не shared credentials;
- любые ручные чтения production data считаются exceptional access и должны быть логируемыми по возможности;
- backup storage шифруется инфраструктурно и имеет отдельную retention policy.

### 15.3. Support/admin boundary

- support/admin операции должны проходить через явные app/admin flows;
- ad-hoc SQL, ручное редактирование строк и доступ к сырым backup-файлам — не стандартная операционная модель;
- все high-risk admin действия должны оставлять audit trail.

### 15.4. Observability boundary

Нужно четко разделять:
- business/app logs;
- security logs;
- metrics;
- traces.

Ни один из этих слоев не должен становиться теневым export-каналом пользовательского контента.

### 15.5. Минимальная retention policy

Базовые ориентиры для MVP/self-hosted baseline:
- application logs: **7–14 дней**;
- security logs: **минимум 30 дней**, целевой ориентир **90 дней**;
- audit trail по security-sensitive операциям: **минимум 90 дней** или дольше по policy инстанса;
- backups: rolling retention, по умолчанию **до 30 дней**, если инстанс не задает иное.

Это baseline, а не универсальная истина для всех будущих редакций продукта.

### 15.6. Forced logout-all

Система обязана поддерживать операцию forced logout-all:
- инвалидировать все refresh token families пользователя;
- пометить device sessions revoked;
- прекратить успешный refresh со всех устройств;
- оставить только короткий остаточный TTL у уже выданных access tokens;
- при наличии local cleanup directive — инициировать очистку при следующем онлайне клиента.

### 15.7. Secret rotation

Для секретов должна существовать rotation-ready модель:
- auth signing keys и другие критичные secrets имеют `key id` / versioning или эквивалент;
- rotation возможна без полного простоя;
- есть процедура аварийной rotation при компрометации;
- refresh token validation и webhook signing не должны быть намертво прибиты к одному вечному секрету.

### 15.8. Incident response baseline

Минимум, который должен быть зафиксирован до beta:
- кто принимает решение об incident severity;
- как быстро можно revoke sessions и rotate secrets;
- где искать security logs;
- как временно отключить relay/bootstrap или import/export;
- как уведомить пользователя о forced reauth / session compromise.

---

## 16. Privacy lifecycle: хранение, удаление, backups

### 16.1. Общий принцип

Privacy без lifecycle — неполная. Поэтому для каждого класса данных должны быть ответы на вопросы:
- как долго данные живут;
- кто их видит;
- что удаляется сразу;
- что остается как минимальный audit/security след;
- когда исчезает из бэкапов.

### 16.2. Account deletion

При удалении аккаунта baseline policy должна делать следующее:
- немедленно revoke all sessions и device access;
- удалить или анонимизировать профильные поля пользователя, которые больше не нужны;
- удалить membership, где это допускается моделью продукта;
- сохранить только минимально необходимый security/audit след на ограниченный срок;
- не оставлять активных refresh token families.

### 16.3. Workspace deletion

При удалении workspace:
- доступ к workspace прекращается сразу;
- содержимое уходит в soft-delete/tombstone state на retention window, если такая стадия нужна для safety/restore;
- после hard delete удаляются domain snapshots, activity entries и derived state этого workspace;
- security/audit след может остаться в минимальном виде без payload, на ограниченный срок.

### 16.4. Activity / audit retention

- activity feed должен хранить факты действий, но не полные снимки private payload;
- audit trail для security-sensitive действий хранит кто/когда/что сделал и над каким scope, но не обязан сохранять чувствительный контент;
- при account deletion actor может быть pseudonymized как `deleted-user:<id>` после завершения operational retention периода, если полная привязка больше не нужна.

### 16.5. Backups

Бэкапы:
- считаются копиями пользовательских данных;
- не редактируются “точечно” задним числом;
- стареют по rolling retention policy;
- после пользовательского удаления данные могут оставаться в существующих backup sets до истечения backup retention, что должно быть явно сказано в privacy posture.

---

## 17. Threat model v1.1 by surface

### 17.1. Auth и session layer

**Угрозы**
- credential stuffing / brute force;
- theft of access token;
- theft or reuse of refresh token;
- session fixation;
- stale long-lived access on forgotten device;
- dev-auth accidentally shipped to production.

**Обязательные controls**
- `Argon2id`;
- short-lived access token;
- opaque rotating refresh token;
- refresh family invalidation;
- suspicious reuse detection;
- password reset;
- email verification;
- rate limiting + backoff;
- revoke current / revoke all / revoke device;
- явное отключение dev-bootstrap и `X-User-Id`-flow вне dev.

### 17.2. Web/browser surface

**Угрозы**
- XSS и захват in-memory access token;
- чтение IndexedDB/local store вредоносным JS внутри origin;
- CSRF на cookie-bound endpoint'ах;
- слишком широкая CORS-конфигурация;
- утечка через сторонние скрипты или небезопасный HTML rendering.

**Обязательные controls**
- запрет unsafe HTML без sanitization;
- CSP baseline;
- production CORS только по allowlist origin;
- deployment-aware cookie/CSRF policy;
- минимизация third-party runtime dependencies.

### 17.3. Backend API и access control

**Угрозы**
- IDOR/BOLA: доступ к чужому workspace/board/card по ID;
- доверие клиентским полям роли/принадлежности;
- пропуск membership checks на derived endpoint'ах;
- слишком подробные error messages.

**Обязательные controls**
- server-side membership/role check на каждом protected endpoint;
- derived endpoints наследуют тот же access boundary, что и primary domain state;
- `404`/`403` стратегия не должна раскрывать лишнюю информацию о существовании чужих сущностей.

### 17.4. Local persistent storage

**Угрозы**
- чтение данных из браузерного профиля после logout/shared-device use;
- извлечение IndexedDB/кэша с локального диска;
- stale sensitive data после revoke session;
- backup/export без шифрования;
- offline queue хранит данные дольше, чем ожидает пользователь.

**Обязательные controls**
- явная разметка local records по user/workspace scope;
- logout/revoke cleanup semantics;
- selective wipe local store для текущего аккаунта/устройства;
- честная формулировка про отсутствие secrecy при полном компромете устройства.

### 17.5. Sync и coordinator

**Угрозы**
- подмена source replica;
- replay/dedup abuse;
- запись событий вне своего workspace scope;
- попытка resurrect deleted entity через stale event;
- race между revoke membership и offline replay.

**Обязательные controls**
- строгая binding-проверка `replicaId -> session/user/device`;
- idempotency по `eventId` и `(replicaId, replicaSeq)`;
- server-side validation scope ownership и domain permissions перед apply;
- canonical server ordering;
- tombstone / delete invariants не обходятся stale update.

### 17.6. Relay / bootstrap

**Угрозы**
- reuse чужого relay ticket;
- route confusion;
- metadata leakage;
- downgrade в менее безопасный transport;
- abuse как open relay;
- quota exhaustion, replay storm, oversized envelope flood.

**Обязательные controls**
- short-lived scoped tickets;
- route binding к `user/session/scope`;
- relay не принимает решение о domain authorization;
- quotas, rate limits, feature flag kill switch;
- max size / max frequency / replay window.

### 17.7. Audit, activity, logs

**Угрозы**
- logs содержат токены, cookies, пароли, полный payload карточек;
- activity feed раскрывает private fields viewer'ам;
- audit log хранит больше персональных данных, чем реально нужно;
- observability становится shadow export.

**Обязательные controls**
- redaction policy;
- четкая схема что идет в activity, audit и security logs;
- retention policy;
- role-based visibility для admin/support surface.

### 17.8. Import / export / integrations

**Угрозы**
- экспорт уводит больше данных, чем пользователь ожидал;
- импортер принимает вредоносный/поврежденный bundle;
- внешняя интеграция получает слишком широкие credentials;
- webhook утекает в неправильный endpoint.

**Обязательные controls**
- explicit preview/apply для import;
- валидация структуры, размера и версии import bundle;
- least-privilege scopes для integrations;
- webhook signing / shared secret;
- password-based encryption option для backup/export, если bundle чувствительный.

---

## 18. Risk priorities and release gates

### 18.1. Blockers before any non-dev deployment

| Priority | Area | Почему blocker |
|---|---|---|
| Blocker | Production-hardened sign-in / refresh / sign-out / revoke flow | Без hardening проект остается dev/test auth системой, даже если базовые endpoints уже wired |
| Blocker | Rate limit + backoff для auth/refresh/reset/bootstrap | Internet-facing auth без abuse controls слишком хрупок |
| Blocker | Refresh family rotation + reuse detection | Иначе украденный refresh token становится тихим долговременным доступом |
| Blocker | Production CORS + deployment-aware CSRF policy | Ошибка здесь делает cookie/session surface либо дырявым, либо неработающим |
| Blocker | Server-side authz на CRUD + derived + sync endpoints | Иначе BOLA/IDOR и обход access boundary неизбежны |
| Blocker | Logout/revoke local wipe semantics | Иначе local-first слой продолжает жить после утраты доступа |
| Blocker | Redaction policy + запрет секретов в логах | Иначе observability становится каналом утечки |
| Blocker | Forced logout-all + secret rotation readiness | Нельзя нормально реагировать на компрометацию |
| Blocker | Relay/bootstrap quotas и limits, если они internet-facing | Иначе transport layer легко становится точкой DoS/abuse |

### 18.2. High priority soon after baseline

- suspicious login visibility в UI;
- admin/support role separation;
- backup encryption option;
- security test matrix automation;
- retention cleanup jobs;
- export confirmation / sensitive action reauth.

### 18.3. Medium / later

- MFA/2FA;
- passkeys/WebAuthn;
- application-level local DB encryption;
- full E2EE sync payload secrecy;
- cryptographic device attestation;
- advanced anomaly detection.

---

## 19. Test evidence: чем доказывается соблюдение модели

Минимальный security test matrix должен покрывать:
- auth happy path и negative auth cases;
- rate limit / lockout behavior;
- refresh rotation и reuse detection;
- forced logout-all;
- BOLA/IDOR против CRUD и derived endpoints;
- logout/revoke local cleanup semantics;
- sync apply authz, tombstone protection и revoke-vs-offline-replay cases;
- relay/bootstrap ticket misuse;
- logging redaction assertions.

Документ считается реально живым только тогда, когда эти требования можно показать не только prose'ом, но и тестами/операционными процедурами.

---

## 20. Current posture: v1alpha vs target model

### 20.1. Что уже концептуально определено правильно

Уже зафиксировано в docs:
- account-based auth model;
- access token + rotating refresh token как целевая session scheme;
- device и replica как разные сущности;
- guest только local-only;
- server-side membership как canonical access boundary;
- relay как transport helper, а не semantic authority.

### 20.2. Что сейчас явно еще не production-ready

По текущему состоянию архива:
- backend auth endpoints и frontend auth/session wiring уже являются основным flow;
- access token передается через `Authorization: Bearer ...`, refresh-сессия живет в cookie;
- есть dev-only bootstrap и legacy `X-User-Id` fallback, но `AUTH__ENABLE_DEV_HEADER_AUTH=false` по умолчанию и web-клиент не должен считать его обычным путем;
- backend CORS сейчас нельзя считать production-ready policy сам по себе;
- фактическая security posture текущей сборки должна считаться **dev/test-only**, пока не закрыты rotation/reuse/rate-limit/cleanup gates.

### 20.3. Что обязательно нельзя забыть перед beta

Перед beta нельзя выпускать систему, если одновременно остаются:
- production-доступ через `X-User-Id`;
- wildcard CORS или незафиксированная CSRF policy;
- отсутствующая real session rotation/revocation logic;
- отсутствие explicit cleanup strategy для local user data;
- отсутствие redaction/logging policy;
- sync access checks, не доведенные до same rigor, что и CRUD;
- отсутствие rate limiting на auth/refresh/bootstrap.

---

## 21. What we deliberately defer

Сознательно не делаем обязательным для v1.1 baseline:
- MFA/2FA;
- passkeys/WebAuthn;
- full E2EE sync payload secrecy;
- cryptographic device attestation;
- anonymous public collaboration;
- peer-to-peer without coordinator fallback;
- advanced anomaly detection platform.

Это не потому, что это неважно, а потому что для текущего проекта опаснее другое: недоделать базовый security слой, одновременно делая вид, что у нас уже “почти decentralized secure system”.

---

## 22. Итог в одной формуле

Security v1.1 для p2pKanban =

**server-authoritative access control + disciplined session model + explicit local-data lifecycle + operator-aware privacy posture + sync/relay boundaries that do not weaken auth**.

То есть:
- local-first не отменяет server security;
- replica не заменяет auth;
- relay не заменяет authorization;
- observability не должна становиться скрытым экспортом данных;
- отсутствие E2EE не должно маскироваться расплывчатыми обещаниями “полной приватности”; 
- auth/refresh/relay интернет-facing поверхности требуют abuse-controls как blocker, а не “когда-нибудь потом”.

Именно такой слой дает шанс не пожалеть потом о “быстром security-решении”, потому что он сначала расставляет границы доверия, инварианты и жизненный цикл данных, а уже потом позволяет наращивать hardening.

---

## 23. Auth/security hardening baseline for v1

Патч `auth security hardening` закрывает минимальный beta-safety baseline без смены выбранной auth-модели:

- `AUTH__ENABLE_DEV_HEADER_AUTH` остается выключенным по умолчанию и теперь дополнительно валидируется по deployment profile: включать dev-header auth можно только в `local/dev/test` окружениях.
- `POST /auth/dev-bootstrap` больше не доступен для beta/self-host/staging/production-like профилей даже как скрытый helper.
- CORS по-прежнему строится из allowlist, но `X-User-Id` попадает в разрешенные request headers только когда реально включен local/dev header-auth режим.
- Для beta/self-host/production-like профилей startup config guard требует явный CORS allowlist, запрещает wildcard `*`, требует `AUTH__COOKIE_SECURE=true` и не принимает placeholder/слишком короткий `AUTH__JWT_SECRET`.
- `SameSite=None` разрешен только вместе с `Secure`, чтобы refresh-cookie deployment profile не оказался несовместимым с браузерной моделью cookies.
- Sync push baseline теперь требует `workspaceId` для workspace-scoped events и не считает чужой `eventId` duplicate-событием для другой replica.
- Sync payload/metadata перед сохранением в `change_events` проходит redaction/truncation для чувствительных JSON ключей (`password`, `token`, `secret`, `authorization`, `cookie`, `jwt`, `apiKey`).
- Backend smoke расширен negative auth/security cases: anonymous request, wrong bearer token, forbidden workspace, and derived endpoint access for activity/audit/export/sync.

Ограничения baseline:

- это не MFA/passkey/E2EE слой;
- local-first snapshots остаются клиентской ответственностью и не шифруются в этом патче;
- full refresh-token family analytics и suspicious login UI остаются future hardening;
- browser smoke по реальному backend-path остается задачей release gates.
