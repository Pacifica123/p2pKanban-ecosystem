# Local-first data layer v1

- Статус: Draft v1
- Дата: 2026-04-12
- Назначение: зафиксировать **локальный слой данных клиента** так, чтобы web UI не был привязан только к online-first запросам, а следующий этап sync можно было строить поверх уже правильных read/write границ.

> Этот документ уточняет прикладной смысл ранее принятого local-first направления из `ADR-001` и не заменяет будущие документы про sync protocol, conflict resolution или transport/p2p. Здесь мы определяем именно **клиентский data layer**: локальное хранение, hydration, optimistic updates, offline UX и связь локальных сущностей с server DTO и domain model.

## 1. Что считаем целью этого этапа

В рамках этого этапа принимаем следующие цели:
- UI читает данные не напрямую из HTTP-ответов, а из локального клиентского store;
- пользовательский сценарий `workspace -> board -> column -> card` остается usable при кратковременной потере сети;
- локальные изменения можно накапливать и позже синхронизировать;
- клиентская модель остается sync-ready, но не требует уже сейчас полного sync protocol;
- offline UX и optimistic updates описаны как явные правила, а не как случайное поведение отдельных экранов.

Этот этап **не** включает:
- полный sync protocol;
- conflict resolution matrix;
- p2p / relay / bootstrap детали;
- deep mobile platform constraints.

---

## 2. Главный вывод

Для проекта нужен не просто query-cache поверх online-first API, а **persistent local store**, который становится основным read/write слоем для UI.

Итоговая формула v1:
- **persistent local store** — source of truth для экранов клиента;
- **in-memory selectors / view state** — быстрый производный слой поверх локального store;
- **server** — upstream для hydration, подтверждения изменений и синхронизации, но не прямой источник каждого рендера.

Следствие:
- UI не должен быть смыслово привязан к "сначала fetch, потом render";
- сетевые ответы сначала нормализуются и записываются локально;
- экраны подписываются на локальные сущности, а не на сырые transport DTO.

---

## 3. Границы local-first слоя

В local-first слой клиента входят:
- persistent storage для доменных сущностей;
- локальные read-models для списков и detail screens;
- локальная запись прикладных изменений;
- pending operations queue;
- optimistic updates;
- hydration / refresh lifecycle;
- sync status metadata;
- offline и degraded UX rules.

В local-first слой клиента не входят:
- server-side change event log как canonical sync source;
- user-facing history как источник истины по domain state;
- полный cross-device merge policy;
- transport-level retry protocol;
- peer discovery и p2p transport.

---

## 4. Local cache vs local source of truth

### 4.1. Чего недостаточно

Для этого проекта недостаточно модели "TanStack Query cache + occasional optimistic mutation".

Такой подход:
- удобен как ускоритель запросов;
- подходит для обычного CRUD-first web UI;
- но плохо покрывает offline create/update/delete;
- плохо переживает restart вкладки/браузера;
- слишком сильно привязывает экран к сетевому lifecycle.

### 4.2. Что принимаем вместо этого

В проекте принимаем следующую терминологию:

- **local cache** — вспомогательный memory/query слой;
- **persistent local store** — основной слой клиентских данных;
- **local source of truth** — именно persistent local store, а не HTTP cache.

То есть в этом проекте слово "cache" можно использовать только как вторичный технический слой. Основной прикладной слой должен быть modeled как **локальная БД клиента**.

---

## 5. Storage model на клиенте

## 5.1. Два уровня хранения

Клиентский data layer состоит из двух уровней.

### A. Persistent local store

Содержит:
- нормализованные локальные сущности;
- индексы и lookup-таблицы для выборок;
- pending operations;
- sync metadata;
- hydration markers;
- локальные tombstones / deleted flags там, где это нужно.

Для web MVP рекомендуемый backend этого слоя:
- **IndexedDB** как базовое persistent storage;
- thin storage adapter поверх него;
- допустимо использовать библиотеку уровня Dexie, но сам проект должен зависеть от своей storage abstraction, а не от конкретной библиотеки напрямую.

`localStorage` не подходит как основной persistent store для domain entities:
- слишком примитивен по структуре;
- неудобен для индексов и выборок;
- хуже масштабируется под normalized records и pending queue.

### B. In-memory runtime layer

Содержит:
- derived selectors;
- текущие подписки экранов;
- draft form state;
- preview state;
- ephemeral UI flags;
- временные loading/error/pending markers, не требующие долговременного хранения.

Этот слой может очищаться при reload, но должен легко восстанавливаться из persistent local store.

---

## 5.2. Базовые локальные коллекции v1

Первая обязательная волна локального хранения:
- `workspaces`
- `boards`
- `columns`
- `cards`

Следующая волна:
- `user_appearance`
- `board_appearance`

Дополнительная read-model волна:
- `activity_entries`

Технические коллекции клиента:
- `entity_meta`
- `pending_ops`
- `sync_state`
- `hydration_state`

### Почему именно такой порядок

`workspace / board / column / card` уже являются подтвержденным рабочим core flow и поэтому должны стать первым local-first slice.

Appearance локализуется следующей волной, потому что это уже отдельный стабильный surface. История `activity_entries` хранится локально как user-facing read model, но не считается основой sync pipeline.

---

## 6. Что локализуется, а что нет

### 6.1. Локализуем в первую очередь

В первую очередь локализуются те сущности, без которых невозможен устойчивый board UX:
- workspace list;
- boards list;
- board details;
- columns;
- cards;
- reorder metadata.

### 6.2. Локализуем как обычное прикладное состояние

- `me/appearance`
- `board appearance`

Они не требуют отдельного transport-режима, но должны жить в той же local-first модели: persisted locally, editable locally, synchronizable later.

### 6.3. Локализуем как read model, а не как canonical log

- `board activity`
- `card activity`

Здесь важно не смешивать:
- `activity_entries` — user-facing проекция для UI;
- `change_events` — будущий sync/change log.

### 6.4. Пока не делаем first-class частью local-first слоя

На этом этапе не обязаны входить в первую волну:
- comments/checklists/labels как fully wired local-first domain slice;
- сложные auth/session flow как часть domain store;
- public/guest/shared сценарии.

Это не запрещено позже, но не должно блокировать старт local-first ядра.

---

## 7. Model layering: server DTO vs domain model vs local record

Клиент не должен хранить и рендерить сырые DTO напрямую.

Принимаем четыре уровня модели:

### 1. Server DTO
Transport-level контракты API.

### 2. Domain model
Нормальная прикладная сущность клиента:
- `Workspace`
- `Board`
- `Column`
- `Card`
- `BoardAppearance`
- `UserAppearance`

### 3. Local record
Форма хранения в локальном persistent store:
- normalized fields;
- relation ids;
- storage-friendly indexes;
- sidecar metadata через `entity_meta`.

### 4. View model
Производная модель конкретного экрана.

Итоговый mapping:

`Server DTO <-> mapper <-> Domain model <-> Local record <-> View model`

Главное правило:

**UI не должен зависеть от server DTO напрямую.**

---

## 8. Правила идентификаторов

Для local-first слоя принимаем client-generated identifiers.

Это означает:
- id создается на клиенте в момент локального create;
- тот же id используется позже при отправке на сервер;
- не требуется отдельная remap-фаза "temporary id -> server id".

Плюсы:
- проще offline create;
- проще локальные ссылки между еще не синхронизированными объектами;
- лучше согласуется с уже принятой UUIDv7/global-id стратегией.

---

## 9. Metadata и локальные технические поля

Доменные поля и техническое состояние клиента не нужно без необходимости смешивать в одну структуру.

Для этого вводится sidecar metadata.

Пример `entity_meta`:
- `entityType`
- `entityId`
- `localStatus`: `synced | pending_create | pending_update | pending_delete | failed`
- `dirtyFields`
- `lastLocalWriteAt`
- `lastServerSyncAt`
- `baseVersion` или `baseUpdatedAt`
- `deletedLocally`
- `hasConflictStub`

Это позволяет:
- держать domain model чистой;
- не засорять основные таблицы transport- или sync-шумом;
- показывать UI статус отдельно от предметных данных.

---

## 10. Read flow

## 10.1. Boot flow

При запуске клиента:
1. открывается persistent local store;
2. восстанавливаются базовые session/config markers;
3. UI сначала читает локальные сущности;
4. параллельно запускается hydration/refresh worker.

Следствие:
- warm start не должен требовать обязательного initial fetch перед первым meaningful render.

## 10.2. Screen read flow

Например, для board screen:
1. экран читает board/columns/cards из local store;
2. если данные уже есть, они показываются сразу;
3. параллельно запускается refresh из сети;
4. сетевой ответ не рендерится напрямую, а записывается в local store;
5. экран автоматически обновляется от локального store.

## 10.3. Distinct empty states

Клиент обязан различать минимум три состояния:
- **truly empty** — данных реально нет;
- **not hydrated yet** — локальный store пуст или частичен, но refresh еще идет;
- **offline and nothing cached** — локально ничего нет, а сеть недоступна.

Это разные UX-сценарии и они не должны сливаться в одну "пустую страницу".

---

## 11. Hydration model

### 11.1. Cold hydration

Сценарий первого запуска или пустого store:
- показывается loading/skeleton;
- после получения server snapshot он записывается локально;
- дальнейшие рендеры уже идут из local store.

### 11.2. Warm hydration

Если локальные данные уже есть:
- показываем cached snapshot immediately;
- запускаем background refresh;
- не блокируем рабочий экран full-screen loading'ом.

### 11.3. Partial hydration

Если часть графа уже локально есть, а часть нет:
- уже известные сущности рендерятся сразу;
- недостающие догружаются адресно;
- не перезапускается весь экран как cold state.

Для этого полезны `hydration_state` markers по scope, например:
- workspace list hydrated;
- board summary hydrated;
- board detail hydrated;
- activity page hydrated.

---

## 12. Write flow

Главное правило:

**Любая пользовательская мутация сначала фиксируется локально, затем попадает в pending queue.**

Базовый порядок:
1. пользователь инициирует действие;
2. клиент валидирует команду на прикладном уровне;
3. в одной локальной транзакции:
   - изменяется сущность;
   - обновляется `entity_meta`;
   - создается или обновляется запись в `pending_ops`;
4. UI сразу видит новое состояние;
5. sync worker позже пытается отправить pending operation на сервер;
6. при успехе локальный статус снимается или нормализуется;
7. при ошибке операция помечается как failed/retryable.

Следствие:
- UI не должен ждать network round-trip как обязательного условия для локального commit.

---

## 13. Pending operations model

На этом этапе не требуется финальная sync event-модель. Нужна прикладная очередь локальных намерений.

Минимальная структура `pending_ops`:
- `opId`
- `entityType`
- `entityId`
- `opType`
- `payloadPatch`
- `createdAt`
- `attemptCount`
- `status`
- `lastErrorCode`
- `baseVersion` или `baseUpdatedAt`

Минимальный каталог операций v1:
- `create`
- `update`
- `delete`
- `reorder`
- `upsert_appearance`

Допустима коалесценция нескольких последовательных update-операций для одной сущности, если это не ломает user-facing semantics.

---

## 14. Optimistic updates rules

## 14.1. Что делаем fully optimistic

На этом этапе допустимо fully optimistic поведение для:
- create workspace;
- create board;
- create column;
- create card;
- rename/update базовых полей;
- reorder columns/cards;
- archive/unarchive;
- `me/appearance`;
- `board appearance`.

## 14.2. Что делаем осторожнее

Осторожнее нужно относиться к:
- destructive delete с необратимым UX;
- массовым операциям;
- действиям, которые могут быть часто отклонены серверными permission/business rules.

## 14.3. Что делаем при сетевой или серверной ошибке

По умолчанию в local-first слое **не принимаем обязательный немедленный hard rollback всей локальной сущности**.

Базовая политика такая:
- локальный state остается видимым;
- операция переходит в `failed` или `retryable`;
- UI показывает понятный sync status;
- пользователь позже может retry/discard/reopen действие.

Жесткий rollback допустим только там, где сохранение локального состояния само по себе вредно или вводит пользователя в заблуждение.

---

## 15. Offline behavior rules

## 15.1. Что пользователь должен мочь offline

Если данные уже были гидрированы или созданы локально, offline должны продолжать работать:
- просмотр workspace list;
- просмотр boards list;
- открытие board screen;
- чтение card details;
- создание и редактирование card/column;
- reorder внутри board;
- изменение appearance;
- повторное открытие приложения с сохранением локального состояния.

## 15.2. Что offline может быть ограничено

Offline может быть ограничено для:
- еще не гидрированных сущностей;
- server-derived activity pages, если они никогда не загружались локально;
- auth/session refresh;
- операций, требующих server-side authority checks beyond current local knowledge.

## 15.3. Как показывать offline и pending состояние

Клиент должен использовать явные, но ненавязчивые статусы:
- `Offline`
- `Saved locally`
- `Syncing`
- `Changes pending`
- `Sync failed`

Избегаем UX-модели, где при кратковременном отсутствии сети все сводится к модалке "попробуйте позже".

---

## 16. Правила чтения локальных сущностей

Базовые read rules:
- списки читают сущности из local store, а не из live HTTP response;
- сущности с `pending_delete` или `deletedLocally` не показываются в обычных списках;
- detail screen читает domain record вместе с технической metadata;
- сортировка колонок и карточек идет по локальному `position / orderKey`;
- UI должен уметь видеть `pending` и `failed` как часть нормальной read model.

---

## 17. Правила записи локальных сущностей

### 17.1. Create

При create:
- генерируется client id;
- создается локальная запись;
- ставится `pending_create`;
- в queue попадает `create` operation.

### 17.2. Update

При update:
- локальная запись патчится сразу;
- `dirtyFields` обновляются;
- сущность получает `pending_update`, если она не находится в `pending_create`;
- в queue добавляется или коалесцируется `update` operation.

### 17.3. Delete

При delete:
- сначала выполняется локальный soft delete или скрытие из обычного списка;
- создается `pending_delete`;
- физическое удаление или окончательная server reconciliation происходят позже.

### 17.4. Reorder

При reorder:
- новая последовательность фиксируется локально транзакцией;
- UI сразу отражает результат;
- в queue попадает компактная reorder operation, а не набор случайных разрозненных PATCH, если это можно выразить лучше.

---

## 18. Специальные замечания по appearance и activity

## 18.1. Appearance

`me/appearance` и `board appearance` — обычное прикладное состояние local-first клиента.

Это означает:
- persisted appearance читается из local store;
- preview draft может жить отдельно в memory state;
- после Save локально зафиксированное appearance считается текущим локальным состоянием даже до server confirmation;
- при неуспехе операция не обязана немедленно откатывать всю локальную запись, если пользователь явно видит `failed/pending` статус.

Граница при этом сохраняется:
- preview draft — временное состояние формы;
- persisted local appearance — уже локально committed состояние;
- server-confirmed appearance — синхронизированное состояние.

## 18.2. Activity

`activity_entries` допустимо хранить локально, но только как read model.

Это означает:
- UI может показывать ранее гидрированную историю offline;
- activity не становится canonical log для восстановления domain state;
- rejected/failed local attempts не обязаны автоматически попадать в user-facing history.

---

## 19. Offline UX rules по ключевым экранам

### Workspace list
- читается локально;
- при offline не должен превращаться в ошибку, если данные уже были;
- если локально пусто и сеть недоступна, показывается special offline-empty state.

### Boards list
- ведет себя аналогично workspace list;
- warm hydration preferred over blocking loading.

### Board screen
- является главным local-first экраном;
- должен открываться из local store без обязательного network round-trip;
- card/column actions должны локально коммититься сразу.

### Card details
- должен читать persisted local card state;
- локально показывать pending/failed sync markers;
- не терять unsynced edits просто из-за reload страницы.

### Activity screens
- если история уже была гидрирована, ее можно читать offline;
- если история никогда не загружалась и сеть недоступна, UI честно сообщает, что activity currently unavailable offline.

---

## 20. Связь local state с будущим sync слоем

Этот документ не определяет полный sync protocol, но задает обязательные предпосылки для следующего этапа:
- client-generated ids;
- persistent local store;
- pending queue;
- hydration markers;
- sidecar metadata;
- distinction между domain state и user-facing history;
- distinction между local committed state и server-confirmed state.

Следующий этап sync model implementation plan должен опираться именно на эти границы, а не пытаться заново определить клиентское хранение с нуля.

---

## 21. Минимальный implementation shape для frontend

Чтобы не расползаться по компонентам, local-first слой на frontend лучше держать как отдельную зону:

```text
frontend/src/
  shared/
    local-store/
      db.ts
      tables/
      mappers/
      repositories/
      selectors/
      pending-ops/
      hydration/
      sync-meta/
```

Базовые обязанности:
- `db.ts` — storage adapter / schema bootstrap;
- `mappers/` — DTO <-> domain <-> local record mapping;
- `repositories/` — read/write API поверх persistent store;
- `selectors/` — screen-friendly projections;
- `pending-ops/` — queue and coalescing;
- `hydration/` — boot/read freshness markers;
- `sync-meta/` — entity status helpers.

Эта зона не должна растворяться целиком ни в `shared/api`, ни в React components.

---

## 22. Что считаем результатом этапа

Этап local-first data layer считается концептуально закрытым, если:
- принята модель `persistent local store as UI source of truth`;
- определены первые локализуемые сущности;
- определены read/write/hydration rules;
- определены pending ops и optimistic rules;
- определены offline UX rules;
- связь с sync-ready архитектурой обозначена, но не подменяет собой отдельный sync этап.

---

## 23. Итог

Для этого проекта local-first означает не "чуть более удобный query-cache", а **локальную БД предметных сущностей плюс очередь локальных намерений**, где UI живет от local store, а сеть отвечает за hydration, подтверждение и дальнейшую синхронизацию.

---

## 24. Runtime baseline implementation note — 2026-05-18

Статус практического runtime baseline: **implemented for the main board/card path**.

Что уже сделано в frontend runtime:

- добавлен отдельный слой `frontend/src/features/localFirst/`;
- board snapshot persistится в browser storage как schema-versioned local snapshot;
- локальная схема runtime содержит workspace marker, board, columns, cards и sidecar `syncMetadata`;
- HTTP snapshot из `board / columns / cards` сначала записывается в local-first snapshot, а board UI читает уже runtime projection;
- добавлена pending operations queue для card create/update/move/reorder;
- card create/edit/move/reorder сначала коммитятся локально, затем flush worker пытается подтвердить их через существующий HTTP API;
- при offline или network failure операция остается в queue и получает `pending` или `failed` marker;
- warm start показывает последнюю сохраненную board surface без обязательного network round-trip;
- UI показывает `offline`, `saved locally`, `syncing`, `sync failed`, а также дает `Retry failed`.

Текущая намеренная граница baseline:

- это **не** финальный sync protocol и не replacement для будущего `push/pull by cursor`;
- local-first пока покрывает основной card runtime path, а labels/checklists/comments остаются server-backed и становятся доступны для новой карточки после sync;
- storage adapter сделан как простой browser persistent adapter для beta runtime baseline, чтобы не блокировать v1; его можно заменить на IndexedDB/Dexie без изменения screen-level контрактов;
- client-generated temporary card ids remapятся после подтверждения сервером, потому что текущий backend create API сам выдает UUID.

Минимальный v1-критерий теперь выполняется так:

1. пользователь открывает board;
2. board/columns/cards сохраняются в local snapshot;
3. сеть пропадает;
4. пользователь создает, редактирует или перемещает карточку;
5. UI сразу показывает изменение как `saved locally`;
6. сеть возвращается;
7. pending queue flush-ится через существующие API routes;
8. после server confirmation локальный marker снимается.
## 25. Sync baseline implementation slice

Патч `sync baseline` переводит sync routes из зарезервированных `501` в минимально рабочий event-log контракт поверх уже существующих таблиц `replicas`, `change_events`, `sync_cursors` и `tombstones`.

Что входит в baseline:

- регистрация browser/client replica через `POST /sync/replicas`;
- стабильный client `replicaKey` в browser storage;
- `GET /sync/status` с server time, max server order и optional replica context;
- `POST /sync/push` с обязательными `replicaId`, `replicaSeq`, `logicalClock` и per-event ack;
- идемпотентность по `eventId` и `(replicaId, replicaSeq)`;
- `GET /sync/pull` по `lastServerOrder` для `global` и `workspace` scope;
- tombstone запись для core `delete/archive` событий;
- видимый frontend sync baseline banner на board screen.

Что намеренно не входит:

- полноценный domain replay входящих events в frontend local store;
- автоматический перевод всех local-first CRUD pending ops на `/sync/push`;
- conflict resolution beyond duplicate/out-of-order baseline;
- snapshot recovery для cursor gap.

Эта граница выбрана специально: текущий local-first runtime уже безопасно flush-ит реальные card mutations через domain HTTP API, а sync baseline теперь дает отдельный воспроизводимый event-log контур, который можно harden-ить без регрессии основного board UX.

