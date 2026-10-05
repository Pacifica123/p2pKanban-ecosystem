# Архитектура интеграций v1

- Статус: архитектурная основа; пользовательские адаптеры ещё не готовы
- Дата: 2026-04-12
- Актуализация: 2026-07-29
- Назначение: зафиксировать архитектуру внешних интеграций так, чтобы Obsidian,
  GitHub, import/export и webhook-сценарии добавлялись как изолированные
  адаптеры, а не расползались по модулям предметной области.

Этот документ описывает техническую границу provider registry и adapters.
Продуктовая модель «что считать проектом», локальный каталог `.p2pkanban` и
receipt-контракт devctl описаны отдельно:
[`github-devctl-project-integration-concept-v1.md`](../product/github-devctl-project-integration-concept-v1.md).

Документ опирается на `ADR-004`, `backend-modules.md`,
`local-first-data-layer-v1.md`, `sync-model-implementation-plan-v1.md` и
`p2p-relay-bootstrap-abstraction-v1.md`.

---

## 1. Что считаем целью этапа

В рамках этого этапа нужно зафиксировать:
- единый provider interface для внешних и системных интеграций;
- место модуля `integrations` в backend и его границы относительно core domain modules;
- import/export touchpoints как часть integration orchestration, а не как ad-hoc utility code;
- inbound/outbound webhook boundary;
- правило, что core domain emits neutral domain events, а adapters уже решают внешний формат и транспорт;
- кодовые stubs/contracts, которые можно потом наращивать без переписывания маршрутов и структуры проекта.

Этот этап **не** включает:
- production-ready GitHub/Obsidian реализацию;
- OAuth/PAT secret storage;
- webhook retries/delivery store;
- полноценный backup/restore формат;
- full security hardening и threat model интеграций.

---

## 2. Главный вывод

Для проекта нужен отдельный **integration orchestration layer**.

Итоговая формула v1:
- `workspaces / boards / cards / comments / sync` остаются нейтральными по отношению к внешним платформам;
- `integrations` получает provider registry, adapter contracts и HTTP touchpoints;
- import/export и webhooks живут в этом же integration layer, даже если часть из них относится не к third-party SaaS, а к system adapters;
- core domain services никогда не импортируют GitHub/Obsidian DTO напрямую.

Следствие:
- нельзя встраивать markdown parsing внутрь `cards`;
- нельзя встраивать GitHub issue payload shape внутрь `boards/cards` API;
- нельзя делать webhook delivery concern частью CRUD handler'ов.

---

## 3. Какие интеграции считаем first-wave adapters

### 3.1. Obsidian
Нужен как **third-party content adapter**.

Первый смысловой контракт:
- import vault snapshot -> normalized planner commands;
- export board/workspace snapshot -> markdown bundle.

### 3.2. GitHub
Нужен как **third-party work-tracking adapter**.

Первый смысловой контракт:
- import issues / labels / project fields;
- export selected cards/boards back into GitHub surface;
- future inbound webhooks from GitHub.

### 3.3. Import / export
Это **system adapter**, а не обязательно внешний SaaS.

Он отвечает за:
- portable bundle format;
- restore/import orchestration;
- backup/export touchpoints;
- подготовку мостика к будущему этапу import/export/backup.

Детальная продуктовая и API policy для этого adapter'а фиксируется отдельным документом `docs/architecture/import-export-backup-v1.md`.

### 3.4. Webhooks
Это тоже **system adapter layer**.

Он отвечает за:
- inbound webhook receiver contracts;
- outbound event delivery contracts;
- signature / secret / retry concerns как adapter-owned responsibility.

---

## 4. Где проходит граница между core domain и integrations

## 4.1. Что остается в core domain
В core domain остаются:
- workspace/board/column/card lifecycle;
- labels/checklists/comments behavior;
- permissions;
- activity history projection;
- sync event ingestion and reconciliation.

## 4.2. Что уходит в integrations
В integrations layer уходят:
- provider catalog и capabilities;
- mapping between external payloads and domain commands;
- import/export job contracts;
- webhook verification and translation;
- external rate limits, auth modes and provider-specific DTOs.

## 4.3. Главное правило
Core domain **не знает** о формате GitHub issue, структуре Obsidian vault и webhook-delivery mechanics.

Core видит только:
- validated application commands;
- neutral domain events;
- integration-safe snapshots/read models.

---

## 5. Provider interface

Ниже — минимальная абстракция, которую фиксируем уже сейчас.

```rust
pub trait IntegrationProvider {
    fn manifest(&self) -> IntegrationProviderManifest;
}

pub struct IntegrationProviderManifest {
    pub key: String,
    pub provider_type: IntegrationProviderType,
    pub supports_import: bool,
    pub supports_export: bool,
    pub supports_inbound_webhooks: bool,
    pub supports_outbound_webhooks: bool,
    pub auth_mode: IntegrationAuthMode,
    pub import_touchpoints: Vec<IntegrationTouchpoint>,
    pub export_touchpoints: Vec<IntegrationTouchpoint>,
    pub inbound_webhook: Option<WebhookContract>,
    pub outbound_webhook: Option<WebhookContract>,
    pub domain_event_subscriptions: Vec<DomainEventSubscription>,
}
```

Это deliberately минимальный интерфейс:
- он не заставляет core знать про конкретный transport;
- он не требует уже сейчас job scheduler;
- он позволяет держать provider registry как data-driven contract layer.

---

## 6. Канонический module structure

```text
backend/src/modules/integrations/
  mod.rs
  dto.rs
  handler.rs
  service.rs
  provider.rs
```

### 6.1. `dto.rs`
Содержит:
- provider manifest DTO;
- import/export stub requests;
- webhook receipt DTO.

### 6.2. `provider.rs`
Содержит:
- trait `IntegrationProvider`;
- builtin provider registry;
- manifests для `obsidian`, `github`, `import_export`, `webhooks`.

### 6.3. `service.rs`
Содержит:
- catalog lookup;
- boundary validation;
- stub orchestration responses;
- future coordination point для outbox/jobs.

### 6.4. `handler.rs`
Содержит:
- HTTP routes для provider catalog;
- import/export stub endpoints;
- webhook stub receiver.

---

## 7. HTTP/API boundaries

### 7.1. Provider catalog
Нужен для того, чтобы UI и automation tooling понимали:
- какие providers существуют;
- какие capability flags они объявляют;
- какие touchpoints зарезервированы.

Первый контракт:
- `GET /integrations/providers`
- `GET /integrations/providers/{providerKey}`

### 7.2. Import / export touchpoints
Первый контракт:
- `POST /integrations/import-jobs`
- `POST /integrations/export-jobs`

На этом этапе endpoints могут оставаться **stub_only**, но path, request shape и ответ уже фиксируются.

### 7.3. Webhook boundary
Первый контракт:
- `POST /integrations/webhooks/{providerKey}`

Это не означает, что webhook security уже готова. Это означает только, что:
- path и adapter boundary зарезервированы;
- webhook receiver не будет потом встраиваться прямо в `boards` или `cards`.

---

## 8. Domain events vs external integrations

## 8.1. Что domain events делают
Domain events нужны, чтобы integrations layer видел изменения ядра **без обратного проникновения внешней схемы в домен**.

Примеры neutral events:
- `workspace.changed`
- `board.changed`
- `card.created`
- `card.updated`
- `board.snapshot.requested`
- `workspace.snapshot.requested`

## 8.2. Что adapters делают поверх domain events
Adapters могут:
- подготовить export payload;
- положить delivery intent в future outbox;
- принять inbound webhook и превратить его в validated integration command;
- собрать import preview и затем отдать application layer нормализованный набор команд.

## 8.3. Что запрещено
Запрещено:
- делать `cards` зависимым от GitHub API client;
- добавлять Obsidian-specific поля в canonical card schema;
- кодировать delivery retry state внутри board/card records.

---

## 9. Import / export touchpoints

### 9.1. Почему import/export считаем частью integrations
Import/export — это не просто кнопка "скачать JSON".

Для этого проекта import/export тесно связан с:
- portable format versioning;
- snapshot semantics;
- restore/import validation;
- future external provider adapters.

Поэтому import/export живет рядом с integrations, а не как utility-folder без архитектурной роли.

### 9.2. Базовые touchpoints v1
На будущее фиксируем две прикладные операции:
- `create import job`;
- `create export job`.

Даже если текущая реализация — stub, это уже отделяет:
- orchestration contract;
- provider-specific execution;
- future background execution model.

---

## 10. Webhooks: inbound и outbound

### 10.1. Inbound webhooks
Нужны для сценариев вроде:
- GitHub прислал событие;
- внешний automation service инициировал действие;
- trusted bridge сообщил о внешнем изменении.

Pipeline должен быть таким:

`HTTP webhook -> adapter verification -> integration command -> application service`

А не:

`HTTP webhook -> прямой SQL/update board/card`

### 10.2. Outbound webhooks
Нужны для сценариев вроде:
- отправить уведомление внешней системе о `card.changed`;
- дернуть automation hook на `board.changed`;
- уведомить внешний pipeline о snapshot/export событии.

Pipeline должен быть таким:

`domain event -> integration outbox intent -> adapter delivery`

---

## 11. Integration isolation rules

Принимаем следующие правила:
- provider-specific DTO живут только внутри integrations layer;
- provider auth/credential handling не протекает в core domain modules;
- import/export adapters работают через normalized commands и snapshots;
- webhook signature, retries и rate-limit concerns принадлежат adapters;
- failure внешнего провайдера не должен ломать local-first core flow и обычный CRUD.

---

## 12. Что именно реализуем как кодовые stubs сейчас

В этом этапе достаточно реального, но stubbed слоя:
- backend-модуль `integrations`;
- registry из четырех provider manifests: `obsidian`, `github`, `import_export`, `webhooks`;
- HTTP catalog endpoints;
- `create import job` stub endpoint;
- `create export job` stub endpoint;
- webhook receiver stub endpoint.

Это intentionally не production integration layer, но уже:
- фиксирует contracts;
- фиксирует module boundaries;
- не дает будущей реализации расползтись по случайным местам проекта.

---

## 13. Что остается следующим этапам

Следующие этапы должны уже детализировать:
- portable export bundle format;
- backup/restore semantics;
- provider credential model;
- webhook secret rotation и retry policy;
- integration outbox / delivery history;
- import preview / dry-run / conflict UX.

---

## 14. Итог

В проекте принимается отдельный `integrations` layer с provider registry и adapter boundaries.

Это означает:
- Obsidian и GitHub не вшиваются в core domain;
- import/export не становится случайным utility-кодом;
- webhooks получают собственный boundary;
- domain events остаются нейтральным внутренним языком, а внешний формат остается задачей adapters.
