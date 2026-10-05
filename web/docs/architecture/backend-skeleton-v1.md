# Каркас backend v1

- Статус: исторический документ; каркас давно перерос исходный этап
- Актуальная структура: `docs/architecture/project-structure.md`

## Что создавал этот этап

Первый backend-каркас зафиксировал:

- Rust/Axum приложение;
- конфигурацию из TOML и environment;
- PostgreSQL pool и миграции;
- общие HTTP-ответы и ошибки;
- auth-модуль;
- доменные модули;
- health endpoints;
- telemetry;
- integration и smoke tests.

## Что теперь является настоящей реализацией

В beta.3 работают auth/session, workspace, boards, cards, labels, checklists,
comments, appearance, activity, audit, sync baseline и import/export preview.
Маршруты, которые когда-то были заглушками, нельзя снова описывать как
«следующий этап».

Backend также включает:

- `sync-core`;
- Nostr shadow outbox и recovery;
- optional Iroh adapter;
- container entrypoint для zero-config bootstrap.

## Что всё ещё частично

- integrations/webhooks;
- import execution;
- coordinator-free membership/signatures;
- автоматическое применение всего входящего event log к доменным проекциям.

## Почему структура сохранена

Модульный монолит остаётся подходящим:

- одна транзакционная БД;
- доменные границы видны в коде;
- нет преждевременных микросервисов;
- transport adapters можно менять отдельно;
- один backend binary удобно собирать в контейнер.

Любые новые документы должны ссылаться на этот файл только как на историю
первоначального каркаса, а не как на текущий roadmap.

