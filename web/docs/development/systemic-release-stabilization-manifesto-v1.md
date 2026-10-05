# Манифест радикального вскрытия release/dev lifecycle v2

## Формула

Мы больше не лечим каждый новый stacktrace как отдельную болезнь. Мы строим систему, которая вскрывает весь release/dev контур, классифицирует сбой, собирает evidence и предлагает следующий безопасный probe.

## Почему это нужно

До этой вехи проект страдал от трёх проблем:

1. симптомы путались с причинами;
2. окружение, PostgreSQL, frontend deps, browser runners и devctl transport смешивались в один красный шум;
3. каждый патч рисковал быть реакцией на последний лог, а не шагом к воспроизводимой стабилизации.

## Центральный принцип

**Первое действие после красного лога — классификация, а не фикс.**

Нужно ответить:

- это продуктовый баг или prerequisite?
- это повторяемо?
- какой слой владеет проблемой?
- какой минимальный probe уменьшит unknown?
- какие side effects безопасны?

## Release Autopsy Harness

`release-gates` должен выдавать не только pass/fail, а bundle:

- `release-gates.md/json`;
- raw logs;
- environment fingerprint;
- command resolution;
- redaction report;
- artifact completeness;
- problem/probe/decision ledgers;
- repeatability and regression memory;
- next actions and rerun commands.

## Матрица провокаций

Безопасные probes:

| Probe | Goal |
|---|---|
| filesystem/workspace | Найти мусор, длинные пути, missing files, archive bloat. |
| process/port | Отличить занятый порт от сломанного backend/frontend. |
| launcher matrix | Проверить Windows/Linux command resolution. |
| PostgreSQL authority | Разделить “сервер жив”, “пароль неверный”, “нет CREATEDB”, “миграции не сходятся”. |
| runtime config | Проверить, что smoke/browser смотрят в тот backend/API. |
| repeatability | Отличить случайный сбой от устойчивой регрессии. |

## Controlled mutators

Mutating actions допускаются только с явным consent profile:

- dependency install/cache write;
- Playwright legacy browser install during transition;
- managed PostgreSQL DB create/drop;
- managed backend/frontend runtime;
- clean-machine sandbox copy.

Каждый mutator должен писать evidence, cleanup/rollback hint и входить в bundle.

## PostgreSQL authority ladder

1. Use explicit existing `TEST_DATABASE_URL`.
2. Create managed per-run DB with known admin credentials.
3. Use dedicated local dev role.
4. Provide manual remediation pack when authority is unavailable.

Запрещено молча писать в shared dev DB.

## Problem Ledger over panic

Сбой без `REL-*` ID — временное состояние. Если failure повторился или влияет на решение, ему нужен stable family, owner layer, severity and probe.

## Acceptance criteria

- red gates are classified;
- unknown ratio trends down;
- generated artifacts are complete and redacted;
- rerun commands are actionable;
- remediation patches are small;
- old failures become regression memory;
- optional heavy checks are separated from mandatory signal.

## Post-Phase-7 lesson

Playwright itself became a recurring infra blocker. The manifesto therefore extends beyond “make Playwright install reliably”: the mandatory browser evidence layer must become lighter, inspectable and project-owned.
