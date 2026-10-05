# Import / export / backup v1

- Статус: частично реализовано в beta; board export и create-copy import работают
- Дата: 2026-04-12
- Назначение: зафиксировать **переносимость данных, резервное копирование и восстановление** так, чтобы local-first модель, sync-ready архитектура и integration layer не противоречили друг другу.

> Этот документ опирается на `ADR-001`, `ADR-004`, `docs/architecture/local-first-data-layer-v1.md`, `docs/architecture/sync-model-implementation-plan-v1.md`, `docs/architecture/conflict-resolution-v1.md` и `docs/architecture/integrations-architecture-v1.md`.

---

## 1. Что считаем целью этапа

На этом этапе нужно определить:
- канонический **portable export format**;
- различие между **export**, **backup**, **import** и **restore**;
- границы между **server-coordinated export** и **offline/local backup**;
- пользовательские ожидания от restore/import flow;
- contracts/stubs, которые можно потом наращивать без переписывания integration layer.

Этот этап **не** включает:
- raw database dump как пользовательскую фичу;
- production-ready file upload/download pipeline;
- attachments/blob storage;
- full replica-log export;
- автоматическое фоновой backup-оркестрации;
- финальный security hardening.

---

## 2. Главный вывод

Проекту нужен **единый переносимый bundle contract**, но с разными режимами использования.

Каноническая формула v1:
- **portable export** — пользовательский переносимый bundle для переноса между устройствами и инстансами;
- **backup snapshot** — более "страховочный" snapshot для сохранения и последующего восстановления;
- **local backup snapshot** — клиентский offline backup из local store, который может существовать даже без backend;
- **import / restore** всегда проходят через preview/apply flow и не превращаются в silent overwrite.

Главное правило:
**экспортируем не raw DB dump и не sync log, а versioned application-level snapshot bundle.**

Это важно потому, что:
- raw SQL dump слишком хрупок между версиями;
- replica log и pending ops не являются user-facing portable format;
- local-first слой содержит device-specific состояние, которое не всегда допустимо переносить между устройствами напрямую.

---

## 3. Термины и различия

### 3.1. Export
**Export** — намеренное формирование переносимого bundle для передачи, архивирования или handoff в другой инстанс.

Ожидания:
- bundle понятен как продуктовый артефакт;
- по умолчанию не включает device/session secrets;
- может быть импортирован в другой инстанс после preview.

### 3.2. Backup
**Backup** — snapshot ради сохранности данных.

Ожидания:
- допускает более полный состав данных, чем portable export;
- может использоваться для restore same-user/same-instance сценариев;
- не равен непрерывной авто-синхронизации.

### 3.3. Local backup
**Local backup** — backup, сформированный на клиенте из persistent local store.

Ожидания:
- доступен offline;
- не требует контакта с backend;
- может отражать локальное состояние, которое еще не было синхронизировано;
- должен явно маркироваться как "local snapshot".

### 3.4. Import
**Import** — привнесение внешнего bundle в текущую систему.

Ожидания:
- часто означает "чужие или внешние данные";
- почти всегда требует preview и import strategy.

### 3.5. Restore
**Restore** — восстановление из backup/export bundle в новый или существующий scope.

Ожидания:
- не делает silent destructive overwrite;
- в v1 по умолчанию идет через new copy или merge-review path;
- не восстанавливает auth/session secrets.

---

## 4. Канонический export format

## 4.1. Logical format
В v1 канонический логический формат называется:

- `p2p_planner_bundle`
- `formatVersion = 1`

Его нужно трактовать как **application-level bundle envelope**, а не как конкретный transport/container.

То есть:
- сегодня это может быть JSON bundle;
- позже он может быть упакован в zip/container, если появятся blobs/attachments;
- семантика bundle не должна зависеть от конкретной упаковки.

## 4.2. Почему не raw DB dump
Мы специально **не** фиксируем SQL dump как пользовательский export format, потому что:
- schema-level changes ломают совместимость;
- такой dump протекает через внутреннюю storage topology;
- он не отделяет portable data от instance-specific служебных таблиц.

## 4.3. Bundle envelope
Минимальная смысловая структура bundle:

```json
{
  "format": "p2p_planner_bundle",
  "formatVersion": 1,
  "bundleKind": "portable_export",
  "scope": {
    "scopeKind": "workspace",
    "workspaceId": "uuid"
  },
  "origin": {
    "instanceId": "optional-string",
    "exportedByUserId": "uuid-or-null"
  },
  "includes": {
    "appearance": true,
    "activityHistory": false,
    "archived": false,
    "attachments": false,
    "localMetadata": false
  },
  "summary": {
    "workspaces": 1,
    "boards": 3,
    "columns": 12,
    "cards": 58,
    "comments": 0,
    "checklists": 0,
    "attachments": 0
  },
  "payload": {
    "workspaces": [],
    "boards": [],
    "columns": [],
    "cards": [],
    "activityEntries": []
  },
  "restoreHints": {
    "recommendedStrategy": "create_copy",
    "requiresManualReview": false
  }
}
```

## 4.4. Что входит в portable export по умолчанию
По умолчанию portable export может включать:
- workspace/board/column/card state;
- appearance settings, если пользователь этого хочет;
- comments/checklists/labels, когда они станут production-ready;
- минимальный origin/compatibility metadata.

По умолчанию portable export **не должен** включать:
- access tokens / refresh secrets;
- session cookies;
- internal DB-only bookkeeping;
- device-private local queue internals;
- transient sync cursors, не нужные для переносимости.

## 4.5. Что может включать backup snapshot
Backup snapshot может включать больше контекста, чем portable export, но все равно остается application-level артефактом.

Допустимые категории:
- archived state;
- activity history;
- appearance/customization;
- future local metadata, если backup делается клиентом и явно помечен как local-only.

---

## 5. Backup semantics

## 5.1. Есть три режима
### A. Portable export
Используется для:
- переноса между инстансами;
- ручного обмена;
- продуктового export/import сценария.

### B. Coordinated backup snapshot
Используется для:
- ручного backup через backend/API;
- snapshot с более полным охватом данных;
- будущего admin/self-host restore path.

### C. Local backup snapshot
Используется для:
- offline safety copy на клиенте;
- ручного user-owned snapshot без backend;
- аварийного сохранения local-first состояния перед risky changes.

## 5.2. Local backup boundary
Важно разделять:
- **coordinated snapshot** — строится из backend-visible domain state;
- **local snapshot** — строится из persistent local store и может отражать pending ops.

Следствие:
- local backup не гарантирует, что snapshot уже отражен на сервере;
- coordinated backup не гарантирует наличие purely-local unsynced UI state;
- UI должен явно показывать, какой тип backup пользователь создает.

## 5.3. Snapshot semantics
Каждый backup/export должен быть:
- **immutable** после формирования;
- self-describing через manifest/bundle envelope;
- versioned;
- безопасным для repeated preview/import.

## 5.4. Что не обещаем в v1
В v1 мы **не обещаем**:
- continuous automatic backup schedule;
- deduplicated blob backup;
- point-in-time restore для произвольной секунды;
- raw replica-log replay как user-facing restore mode.

---

## 6. Restore expectations

## 6.1. Restore не должен быть destructive by default
Базовое правило доверия:
**restore/import не делает silent overwrite существующего workspace/board state.**

Безопасный default для v1:
- `create_copy` — восстановить как новый workspace/board copy;
- `merge_review` — дать preview и warnings перед merge-like сценарием.

## 6.2. Что пользователь должен увидеть до apply
Перед restore/import пользователь должен понимать:
- какой format/version обнаружен;
- что именно будет создано/обновлено;
- сколько сущностей внутри bundle;
- будет ли это create-copy или merge-review;
- есть ли warnings / incompatible sections / unsupported fields.

## 6.3. Что не восстанавливается
Даже backup bundle **не восстанавливает**:
- active sessions;
- refresh tokens;
- provider secrets;
- transport/session identity конкретного браузера/девайса.

## 6.4. Конфликтные случаи
Restore/import flow должен быть согласован с общей conflict policy:
- stale IDs и name collisions не скрываются молча;
- lifecycle conflicts не делают implicit undelete;
- high-value text conflicts требуют review surface;
- unsupported sections импортируются частично только при явном предупреждении.

---

## 7. User-facing flows

## 7.1. Export flow
Минимальный flow:
1. Пользователь выбирает scope (`workspace` или `board`).
2. Выбирает режим: `portable export` или `backup snapshot`.
3. Включает/выключает секции (`appearance`, `activity history`, `archived`).
4. Система строит manifest и формирует файл/артефакт.
5. Пользователь получает понятное имя файла и summary того, что внутри.

## 7.2. Local backup flow
Минимальный offline flow:
1. Пользователь запускает backup с клиента.
2. Клиент сериализует persistent local store в local-backup envelope.
3. UI помечает snapshot как local-only и показывает статус синхронизации на момент backup.
4. Snapshot сохраняется в user-controlled storage/export target.

## 7.3. Import / restore preview flow
Минимальный безопасный flow:
1. Пользователь выбирает bundle.
2. Система читает manifest/summary.
3. Строится preview:
   - detected format;
   - bundle kind;
   - recommended strategy;
   - warnings;
   - предполагаемые create/update operations.
4. Пользователь подтверждает apply.
5. Только после этого запускается import/restore execution.

## 7.4. Restore target rules
В v1 безопаснее поддерживать такие варианты:
- restore into new workspace copy;
- import into existing workspace with merge-review;
- board-level restore как copy.

Нежелательный default:
- destructive replace in place без preview.

---

## 8. API/contracts, которые фиксируем сейчас

На уровне backend/API в этом этапе фиксируются такие touchpoints:
- `GET /integrations/import-export/capabilities`
- `POST /integrations/import-export/exports`
- `POST /integrations/import-export/imports/preview`
- `POST /integrations/import-export/imports`

Эти endpoints не обязаны сразу отдавать real file bytes. Их задача на этапе v1:
- зафиксировать transport-neutral contract;
- описать export modes, restore strategies и bundle summary;
- дать frontend и future adapters стабильную точку интеграции.

---

## 9. Отношение к local-first и sync

## 9.1. Export/backup не заменяет sync
Backup/export — это **не** альтернатива регулярной синхронизации.

Sync отвечает за:
- ongoing reconciliation;
- conflict handling;
- propagation of changes.

Export/backup отвечает за:
- portability;
- manual preservation;
- restore/import flows.

## 9.2. Restore/import не пишет напрямую в таблицы
Даже если источник — trusted bundle, restore/import должен идти через:
- validation;
- preview/plan building;
- application commands / controlled orchestration;
- conflict-aware rules.

## 9.3. Local-only metadata
Device-specific state вроде pending ops, local cursors и transient UI state:
- может попадать в `local backup snapshot`;
- не должен бездумно протекать в portable export;
- не должен становиться обязательной частью cross-instance import.

---

## 10. Что реализовано

Текущий beta-срез даёт:

- versioned application-level JSON bundle;
- реальный board/workspace export через backend;
- скачивание board backup из web-клиента;
- локальную проверку board-level файла до первой записи на сервер;
- preview с составом и предупреждениями;
- board-level `create_copy` import в выбранный workspace через обычные
  board/column/card/label/checklist/comment/appearance API-команды;
- замену всех исходных ID новыми серверными ID;
- попытку удалить только новую недособранную доску, если импорт оборвался.

Текущая реализация сознательно **не обещает**:

- workspace-level import;
- merge с существующей доской;
- destructive replace/restore;
- перенос sessions, secrets, старых actor identity и timestamp;
- replay старой activity history;
- attachments/blob transport;
- транзакцию на весь импорт и background job engine.

Таким образом, рабочая граница beta — перенос одной доски как новой копии.

---

## 13. V1 safety-net implementation baseline

Статус после патча `export backup safety net`: backend больше не возвращает только manifest-oriented stub для dedicated import/export surface.

### 13.1. Что реально экспортируется

`POST /integrations/import-export/exports` формирует versioned JSON bundle со свойством `manifest.json` и application-level payload. Поддержанные scopes:

- `scopeKind=workspace` + `workspaceId`;
- `scopeKind=board` + `boardId`.

В bundle входят backend-visible сущности:

- workspace metadata;
- boards;
- board columns;
- cards;
- board labels и card-label assignments;
- checklists и checklist items;
- comments;
- board appearance settings, если `includeAppearance=true`;
- activity entries, если `includeActivityHistory=true`.

В bundle намеренно не входят:

- access/refresh tokens;
- session cookies;
- `user_sessions`;
- provider secrets;
- sync cursors и transient local-first pending queue;
- raw database dump sections.

### 13.2. Bundle shape

Текущий JSON artifact сохраняется как один файл `*.bundle.json`. Внутри него есть ключ `manifest.json`, чтобы bundle был self-describing даже без отдельного zip-container:

```json
{
  "manifest.json": {
    "format": "p2p_planner_bundle",
    "formatVersion": 1,
    "bundleKind": "backup_snapshot",
    "scopeKind": "board",
    "workspaceId": "uuid",
    "boardId": "uuid",
    "includesLocalMetadata": false,
    "summary": {
      "scopeKind": "board",
      "entityCounts": {
        "workspaces": 1,
        "boards": 1,
        "columns": 3,
        "cards": 12,
        "comments": 2,
        "checklists": 1,
        "attachments": 0
      },
      "includesActivityHistory": true,
      "includesAppearance": true,
      "includesArchived": true,
      "includesAttachments": false
    }
  },
  "payload": {
    "workspaces": [],
    "boards": [],
    "columns": [],
    "cards": [],
    "labels": [],
    "cardLabels": [],
    "checklists": [],
    "checklistItems": [],
    "comments": [],
    "boardAppearanceSettings": [],
    "activityEntries": []
  },
  "restoreHints": {
    "recommendedStrategy": "create_copy",
    "destructiveRestoreAllowed": false
  }
}
```

### 13.3. Import preview baseline

`POST /integrations/import-export/imports/preview` принимает либо `bundle`, либо `bundleManifest`, проверяет `format=formatVersion=1` и возвращает non-destructive preview summary.

V1 baseline **не выполняет destructive restore**. `POST /integrations/import-export/imports` остается reserved execution boundary и возвращает `preview_required`, не мутируя domain state. Board-level create-copy выполняется клиентским orchestrator через уже существующие проверяемые CRUD-команды. Backend execution boundary остаётся зарезервированным для будущей атомарной/background реализации.

### 13.4. Frontend export

На board screen добавлена кнопка `💾`, которая запрашивает board-level `backup_snapshot` и скачивает `*.bundle.json` через браузер. Это user-owned safety copy, а не scheduled backup и не encrypted backup UX.

### 13.5. Frontend board import

На странице boards выбранного workspace есть блок `Импорт доски из JSON`.
Поток состоит из двух отдельных стадий:

1. **До записи на сервер:**
   - проверка ограничения 10 МБ;
   - JSON parse;
   - `format=p2p_planner_bundle`;
   - `formatVersion=1`;
   - `scopeKind=board`;
   - проверка обязательных разделов, уникальности ID и ссылок между сущностями;
   - игнорирование legacy card-status полей: состояние импортированной карточки
     однозначно задаётся ссылкой `columnId`;
   - preview состава, потерь и нового имени.
2. **После явного `Создать копию`:**
   - новая доска в выбранном workspace;
   - новые columns и mapping старых ID на новые;
   - новые labels/cards и восстановление связей;
   - checklists/items/comments;
   - board appearance;
   - переход на новую доску.

Импорт не вызывает silent overwrite. Activity из bundle не воспроизводится:
обычные API-команды сами формируют новую историю создания копии. Комментарии
сохраняют текст, но получают текущего пользователя и новое время.

Client-side orchestration пока не является общей транзакцией. При ошибке после
создания доски клиент вызывает `DELETE /boards/{boardId}` только для этой новой
копии. Если cleanup тоже не сработал, UI показывает ID недособранной доски,
чтобы пользователь мог найти её и принять решение вручную.
