# Conflict resolution v1

- Статус: Draft v1
- Дата: 2026-04-12
- Назначение: детально зафиксировать conflict taxonomy, resolution rules, user-facing UX principles и edge-case policy для local-first sync-ready модели.

> Этот документ не заменяет `ADR-003`, `docs/sync/protocol.md` и `docs/sync/conflict-resolution.md`, а разворачивает их в **практическую матрицу решений для реализации**. Он исходит из уже принятой модели `persistent local store + pending ops + backend-coordinated sync` и из инженерного уточнения, что для реальной реализации нужны **оба** поля: `logicalClock` и `replicaSeq`.

---

## 1. Что считаем целью этапа

Нужно отдельно определить:
- какие типы конфликтов реально бывают в этом проекте;
- где допустим auto-merge;
- где нужен `LWW per field`;
- где нужна structural merge policy;
- где автоматический исход допустим только вместе с user-visible loss marker;
- где нужна manual resolution;
- как эти исходы показываются пользователю так, чтобы не разрушать trust.

Этот этап **не** включает:
- transport mechanics;
- bootstrap/relay/p2p wiring;
- полный security model;
- full CRDT-programming для всех сущностей;
- полноценный отдельный conflict center как обязательную экранную фичу MVP.

---

## 2. Главные принципы

1. **Никакой магии.** Для каждой категории конфликта есть документированное правило.
2. **Deterministic first.** Повторное применение одних и тех же событий дает тот же исход.
3. **Silent overwrite допустим только там, где риск понятен и приемлем.**
4. **Tombstone/lifecycle guards сильнее stale update.**
5. **Disjoint field edits не должны теряться.**
6. **Server order нужен для воспроизведения потока, но не всегда для semantic winner.**
7. **Manual resolution — редкий путь, а не дефолт.**
8. **Пользователь должен понимать, что произошло с его локальным изменением.**

---

## 3. Что именно сравниваем при конфликте

Нужно различать три разных порядка:

### 3.1. `replicaSeq`
Строгий монотонный порядок событий **внутри одной реплики**.

Нужен для:
- идемпотентности push;
- detect gap/out-of-order по одной реплике;
- tie-break внутри одной реплики;
- объяснимости порядка локальных изменений.

### 3.2. `logicalClock`
Логический счетчик/lamport-подобная метка для causal/merge semantics.

Нужен для:
- сравнения конкурирующих изменений разных реплик;
- LWW-политики без привязки к wall-clock;
- field-level winner selection.

### 3.3. `serverOrder`
Глобальный возрастающий порядок, назначаемый coordinator/backend при принятии события.

Нужен для:
- pull cursor;
- детерминированного inbound replay;
- pagination и progress tracking.

### Важная граница

Для same-field конфликта семантический winner определяется **не просто по `serverOrder`**.

Нормативное правило v1:
1. сначала проверяются lifecycle/invariant guards;
2. затем сравниваются `logicalClock`;
3. если часы равны и это одна реплика — выигрывает больший `replicaSeq`;
4. если часы равны и реплики разные — используется стабильный tie-break по `replicaId`;
5. крайний детерминирующий fallback — `eventId`.

`serverOrder` задает порядок применения в event stream, но не должен подменять отдельную conflict policy для одного и того же смыслового поля.

---

## 4. Taxonomy конфликтов

### 4.1. Scalar same-field conflict
Две реплики меняют одно и то же scalar/text поле одной сущности.

Примеры:
- `card.title` vs `card.title`;
- `board.name` vs `board.name`;
- `comment.body` vs `comment.body`.

### 4.2. Disjoint field conflict
Изменения приходятся на разные поля одной сущности и логически совместимы.

Примеры:
- `card.title` vs `card.dueAt`;
- `board.name` vs `board.description`;
- `checklistItem.title` vs `checklistItem.isDone`.

### 4.3. Structural move/reorder conflict
Конфликтует положение сущности в ordered/container структуре.

Примеры:
- перестановка колонок;
- move карточки между колонками;
- reorder карточек внутри одной колонки;
- reorder checklist items.

### 4.4. Membership/set conflict
Конфликтует принадлежность элемента множеству, а не scalar-поле.

Примеры:
- add/remove label on card;
- add/remove workspace member;
- add/remove checklist item.

### 4.5. Lifecycle conflict
Конфликт между edit/update и более сильным жизненным переходом.

Примеры:
- delete vs edit;
- archive vs update;
- revoke membership vs further edits;
- delete parent vs child move/update.

### 4.6. Invariant conflict
Обе операции сами по себе валидны, но вместе нарушают доменное ограничение.

Примеры:
- две колонки с одинаковым нормализованным именем там, где uniqueness сохраняется;
- move в удаленную колонку;
- restore в уже занятый уникальный slug.

### 4.7. Permission / policy conflict
Изменение пришло из реплики, которая уже не имеет прав или больше не проходит lifecycle guard.

### 4.8. Duplicate / replay / out-of-order case
Технический случай доставки, который не должен маскироваться под пользовательский conflict.

### 4.9. Manual-resolution conflict
Ситуация, где автоматический canonical outcome допустим, но потеря проигравшего содержимого слишком значима, чтобы скрыть ее без user-visible surface.

---

## 5. Базовые стратегии разрешения

## 5.1. `LWW per field`
Используется для простых значений, где допустим выбор победителя по одному полю:
- short text;
- enum values;
- optional scalar values;
- boolean flags;
- даты;
- numeric scalar settings.

### Нормативное правило
Для одного поля выигрывает значение события с более сильным conflict-key:
- `logicalClock`;
- затем `replicaSeq` внутри одной реплики;
- затем `replicaId` как стабильный tie-break;
- затем `eventId`.

### Что важно
- LWW применяется **на уровне поля**, а не всей сущности.
- LWW не означает silent discard всего объекта.
- Для high-value text полей допускается сохранение проигравшего текста в `conflict_stub` даже если canonical state уже выбран автоматически.

## 5.2. Field merge
Если изменены разные поля одной сущности, результат собирается по полям.

Пример:
- Реплика A меняет `card.title`.
- Реплика B меняет `card.dueAt`.
- Итог: сохраняются оба изменения.

## 5.3. Structural operation merge
Для ordered/container данных canonical unit — не весь объект, а отдельная structural операция:
- `move_column`;
- `move_card`;
- `reorder_card`;
- `move_checklist_item`.

Политика v1:
- перемещение одной и той же сущности конфликтует как единый structural tuple;
- move одной сущности и scalar update той же сущности обычно совместимы;
- конкурирующие move одной сущности разрешаются по тому же conflict-key, но как единая structural операция.

## 5.4. Delete/tombstone precedence
Если одна сторона удаляет сущность, а другая редактирует stale copy, canonical outcome по умолчанию:
- **delete wins**.

Исключение только одно:
- есть отдельная валидная операция `restore`/`undelete`, явно задокументированная и прошедшая guards.

## 5.5. Reject / quarantine / manual resolution
Используется, если:
- нарушаются права;
- нарушается lifecycle guard;
- нарушается parent/container invariant;
- silent auto-fix подорвет trust;
- проигравшая сторона содержит значимый пользовательский текст/смысл, который нельзя просто потерять без surface.

---

## 6. Conflict matrix summary

| Scenario type | Default rule | User surface | Notes |
|---|---|---|---|
| Same scalar field | `LWW per field` | usually none | for high-value text optionally keep losing value in stub |
| Different fields of same entity | merge by field | none | canonical per-field merge |
| Same entity move/reorder | structural LWW on move tuple | none in happy path | affected siblings re-normalized deterministically |
| Move/reorder + scalar edit | merge structural + scalar | none | move and content edits commute |
| Add/add same set membership | idempotent accept | none | no duplicate rows |
| Add/remove same set membership | membership LWW | usually none | tombstone/parent validity still stronger |
| Delete vs stale update | delete wins | inline conflict/failure marker if local value significant | no implicit resurrection |
| Archive vs ordinary edit | archive/reject policy | retry/edit after reopen | archived container blocks ordinary edits |
| Parent deleted vs child edit | parent lifecycle wins | child op rejected or conflict marker | explicit re-home or restore required |
| Permission loss vs later edit | reject | clear action message | not a merge problem |
| Unique constraint collision | reject one side, require rename/manual action | inline validation/conflict | no silent auto-rename by default |
| Duplicate / replay | treat as duplicate/no-op | none | not shown as user conflict |
| Equal logical clocks | deterministic tie-break | none | audit/debug only |
| High-value text overwritten | canonical LWW + stub preservation | `Needs review` | manual choice or copy-out action |

---

## 7. Правила по сущностям

## 7.1. Workspace

### Поля `name`, `description`, `visibility`
- same field -> `LWW per field`;
- different fields -> merge by field.

### `slug`
- не auto-merge'ится, если возникает uniqueness conflict;
- canonical outcome: один апдейт принимается, другой получает reject/conflict с требованием ручного rename.

### Archive/delete workspace
- lifecycle operation сильнее обычных child edits;
- дочерние изменения после archive/delete не применяются как обычный merge.

### Membership / owner-sensitive changes
- transfer ownership, remove owner, role downgrade под owner/admin guard не решаются LWW;
- сервер сериализует их через permission/invariant rules;
- конфликтующая сторона получает reject, а не silent merge.

## 7.2. Board

### Поля `name`, `description`, `boardType`
- `LWW per field` для same field;
- merge by field для disjoint updates.

### Archive board vs card/column edits
- archive board блокирует обычные структурные и контентные изменения внутри board после точки архивации;
- stale child update не resurrect'ит активность доски.

## 7.3. Column

### Поля `name`, `description`, `wipLimit`, `colorToken`
- same field -> `LWW per field`;
- different fields -> merge by field.

### Reorder columns
- reorder оформляется отдельной structural operation;
- конкурирующие reorder одной и той же колонки решаются по move tuple winner;
- reorder разных колонок в одной доске должен быть детерминированно нормализован сервером после применения победивших операций.

### Delete column vs card move into this column
- delete column сильнее stale move;
- move в уже удаленную колонку отклоняется;
- возможен manual re-home flow позже, но не silent teleport в произвольную колонку.

### Duplicate normalized column name
- не решается silent auto-rename по умолчанию;
- одна сторона получает conflict/reject с требованием изменить имя.

## 7.4. Card

### Scalar/content fields
Поля типа:
- `title`
- `description`
- `priority`
- `dueAt`
- `startAt`

разрешаются так:
- same field -> `LWW per field`;
- different fields -> merge by field.

### `columnId + position`
Это единый structural tuple.

Политика:
- move/reorder карточки — отдельная операция;
- concurrent move одной карточки -> winner по conflict-key;
- move карточки и edit `title/description/priority` -> merge;
- reorder карточки, которая уже tombstoned, не применяется.

### Delete card vs card edit
- delete wins canonically;
- если проигравшая сторона меняла `title` или `description`, клиент сохраняет local losing payload в `conflict_stub` с возможностью copy/recreate later;
- implicit undelete запрещен.

### Перемещение между состояниями vs text edit
- состояние карточки — это structural tuple `columnId + position`, а не отдельное поле;
- move и изменения `description/title/priority` могут merge'иться по своим полям;
- фиксированный набор состояний и отдельный complete/close lifecycle отсутствуют.

## 7.5. BoardLabel / CardLabel

### Label entity (`name`, `color`, `description`)
- same field -> `LWW per field`;
- disjoint fields -> merge by field.

### Membership `card <-> label`
- add/add -> idempotent;
- remove/remove -> idempotent;
- add/remove same edge -> membership LWW;
- delete самой label сильнее stale add edge.

## 7.6. Checklist / ChecklistItem

### Checklist fields
- `title` -> `LWW per field`.

### Checklist item fields
- `title` and `isDone` merge by field when changed independently;
- same field -> `LWW per field`.

### Reorder checklist items
- отдельная structural operation, аналогично card reorder.

### Delete checklist item vs edit
- delete wins canonically;
- текст проигравшей стороны можно сохранить в stub, если он был локально изменен и не пустой.

## 7.7. Comment

### Create comments
- concurrent create разных comments не конфликтует;
- обе записи сохраняются.

### Edit same comment body
- `comment.body` -> `LWW per field`.

### Delete comment vs edit body
- delete wins canonically;
- losing body сохраняется в stub/copy buffer, если это был локальный несинхронизированный текст;
- full collaborative rich-text merge не входит в v1.

## 7.8. Appearance

### `me/appearance`
- same setting field -> `LWW per field`;
- different setting fields -> merge by field.

### `board appearance`
- same field -> `LWW per field`;
- different fields -> merge by field.

### Почему здесь не нужен manual flow
Appearance изменения обратимы, риск low-stakes, а silent winner не разрушает пользовательские данные так, как это делает потеря текстового содержимого карточки или комментария.

## 7.9. Activity / audit read models

`activity_entries` и `audit_log` не считаются user-editable canonical entities для conflict resolution.

Правило:
- они пересчитываются/пишутся из canonical operations;
- они не выигрывают конфликт у доменного state;
- rejected/conflict записи могут в них попадать как наблюдаемый след, но не как источник истины.

---

## 8. Где manual resolution обязательна

Manual resolution нужна не для каждой гонки, а только в ограниченных классах кейсов.

### 8.1. High-value text loss
Если canonical LWW затер:
- `card.description`;
- `comment.body`;
- `checklistItem.title` при значимом локальном изменении;
- `workspace.description` или `board.description` при явной локальной правке,

то UI должен сохранить проигравший локальный вариант и показать `Needs review`, даже если canonical server state уже выбран автоматически.

### 8.2. Delete vs meaningful local edit
Если сущность удалена на другой реплике, а текущий клиент имел несинхронизированный содержательный edit, пользователь должен получить возможность:
- скопировать свой текст;
- recreate as new entity later;
- discard local change.

Но **не** неявное undelete.

### 8.3. Unique/invariant collision
Если auto-merge нарушает инвариант, нужен явный пользовательский следующий шаг:
- rename;
- choose another parent/container;
- reopen board/workspace if policy later allows.

### 8.4. Permission/lifecycle denial after local edit
Если операция отвергнута из-за потери прав, archive, revoke membership или delete parent, нужно честное объяснение причины и безопасное действие `discard/copy`, а не бесконечный retry.

---

## 9. User-facing UX principles

## 9.1. Не показывать транспортный жаргон
Пользовательский текст не должен оперировать словами:
- `replicaSeq`
- `lamport`
- `serverOrder`
- `cursor`

Вместо этого:
- `Saved locally`
- `Syncing`
- `Changes pending`
- `Sync failed`
- `Needs review`
- `Item was deleted elsewhere`

## 9.2. Не делать full-screen catastrophe там, где достаточно inline resolution
Большинство конфликтов — локальные и entity-scoped. Значит предпочитаются:
- badge на сущности;
- inline banner в drawer/detail screen;
- toast + link to review;
- статус в sync panel.

## 9.3. Показывать смысл, а не только факт ошибки
Не `Conflict 409`, а:
- `This card was changed on another device. Your title was kept, but the description needs review.`
- `This item was deleted elsewhere. Your unsynced text is preserved so you can copy it.`
- `This column name is already taken. Rename your column to continue.`

## 9.4. Сохранять проигравшее пользовательское содержимое, если оно ценно
Для текста и содержательных полей система должна предпочитать:
- сохранить losing payload локально;
- дать copy/recreate action;
- только потом discard.

## 9.5. Manual resolution не должна быть обязательной для low-stakes settings
Appearance, простые booleans, enum flags и мелкие scalar-поля не должны превращать UI в conflict desk.

## 9.6. Один и тот же конфликт должен выглядеть одинаково на всех клиентах
Текст может различаться, но классы исходов должны совпадать:
- auto-merged silently;
- auto-merged with review stub;
- rejected/retryable;
- manual resolution required.

---

## 10. Recommended frontend surface model

Минимальный v1 surface поверх `entity_meta`:

```ts
export type EntitySyncStatus =
  | 'synced'
  | 'pending_create'
  | 'pending_update'
  | 'pending_delete'
  | 'failed'
  | 'conflict_stub';

export type ConflictKind =
  | 'same_field_lww_loss'
  | 'delete_vs_update'
  | 'parent_deleted'
  | 'permission_denied'
  | 'unique_constraint'
  | 'structural_conflict';
```

`conflict_stub` означает не обязательно “canonical state неизвестен”.
Чаще это означает:
- canonical state уже выбран;
- но пользовательскому клиенту еще надо показать loss/review surface.

---

## 11. Примеры

## 11.1. Card title vs due date
- A меняет `title` карточки.
- B меняет `dueAt` той же карточки.
- Outcome: merge by field, конфликт как пользовательская проблема не показывается.

## 11.2. Card title vs card title
- A: `title = "Fix sync engine"`
- B: `title = "Implement sync engine"`
- Outcome: `LWW per field` по conflict-key.
- Если это обычное short-text поле, отдельный review UI не обязателен.

## 11.3. Card description vs card description
- обе стороны независимо редактируют длинное описание;
- canonical outcome определяется `LWW per field`;
- проигравшая локальная версия сохраняется в stub;
- UI показывает `Needs review` и дает `Copy my version`.

## 11.4. Delete vs local description edit
- Реплика A удаляет карточку.
- Реплика B офлайн меняет `description`.
- Outcome: карточка считается удаленной;
- локальный edit B не resurrect'ит ее;
- B получает marker `Item was deleted elsewhere` + `Copy text` + `Create new card from my text`.

## 11.5. Card move vs title edit
- A переносит карточку в другую колонку.
- B меняет `title`.
- Outcome: move и title merge'ятся.

## 11.6. Same card moved to two different columns
- A переносит карточку в `Doing`;
- B переносит ту же карточку в `Done`;
- Outcome: выигрывает один structural tuple по conflict-key;
- проигравшее движение не обязательно показывать как manual conflict, если содержимое карточки не потеряно.

## 11.7. Comment body edit vs delete
- A удаляет comment;
- B офлайн продолжает печатать текст;
- Outcome: delete wins;
- B получает review/copy surface, но не hidden undelete.

## 11.8. Column rename collision
- A переименовывает колонку в `Done`;
- B другую колонку тоже переименовывает в `Done`;
- если инвариант уникальности имени колонки в доске сохраняется, одна операция принимается, другая отвергается с требованием rename.

---

## 12. Edge-case policy

### 12.1. Duplicate event with same payload
- статус: `duplicate`;
- не считается пользовательским conflict.

### 12.2. Same `eventId` but different payload
- статус: reject / suspicious event;
- это целостностная ошибка, а не обычный merge case.

### 12.3. Gap in `replicaSeq`
- событие не должно quietly применяться;
- coordinator может запросить rebase/pull or reject batch;
- это защищает от out-of-order within one replica.

### 12.4. Equal `logicalClock` from different replicas
- используется стабильный tie-break;
- исход детерминирован;
- желательно оставить audit/debug след.

### 12.5. Event older than known tombstone
- stale update не resurrect'ит сущность;
- outcome: ignore/reject according to pipeline stage.

### 12.6. Parent deleted after child local move
- child move не телепортируется в произвольный fallback-parent silently;
- canonical outcome: reject/conflict;
- later UX может предложить explicit re-home.

### 12.7. Archived container
- ordinary edits в archived board/workspace не auto-merge'ятся как будто контейнер активен;
- требуется explicit reopen policy, если она появится.

### 12.8. Local losing value too small to preserve
- для мелких scalar полей stub не обязателен;
- manual review резервируется для действительно значимого пользовательского содержимого.

### 12.9. Derived read models lag behind
- `activity_entries`/audit могут временно отставать;
- это не должно влиять на winner selection.

---

## 13. Что обязательно протестировать отдельно

1. same-field `LWW per field` по двум репликам;
2. merge disjoint fields одной card;
3. move card + edit card;
4. delete vs stale edit card;
5. delete vs stale comment edit;
6. add/remove label edge;
7. reorder conflict одной card/column;
8. unique constraint collision;
9. permission loss after local edit;
10. equal `logicalClock` tie-break;
11. duplicate `(replicaId, replicaSeq)`;
12. stale update after tombstone.

---

## 14. Итоговое решение v1 в одной схеме

```text
simple same-field scalar/text
  -> LWW per field

different fields of same entity
  -> merge by field

ordered/container operations
  -> structural operation merge

set membership
  -> idempotent add/remove + membership LWW

delete/archive/revoke/parent invalidation
  -> lifecycle guard wins

high-value text loss or invariant collision
  -> canonical outcome + user-visible review/manual resolution
```
