# Testing pyramid v1

## 1. Назначение

Этот документ фиксирует **практическую пирамиду тестов проекта** и ожидаемую долю разных типов проверок.

## 2. Пирамида

```text
                 smoke / browser smoke
                       very small

                contract / schema checks
                     small but required

          integration tests (backend + frontend)
                 substantial working layer

              unit tests / pure logic tests
                  largest and fastest base
```

## 3. Как читать эту пирамиду

### Unit — самый широкий слой

Здесь должны жить самые частые и быстрые проверки:
- pure helpers;
- selectors;
- validators;
- mappers;
- derived column placement and workflow selectors;
- conflict/apply helpers.

### Integration — основной слой доверия

В этом проекте именно integration tests должны нести основную нагрузку доверия, потому что бизнес-ценность рождается на стыках:
- router + service + repo + DB;
- feature + query/local store + mocked transport.

### Contract — узкий, но обязательный слой

Контрактных тестов должно быть мало, но их нельзя пропускать на API/sync-sensitive поверхностях.

### Smoke — самый тонкий слой

Smoke нужен как короткая живая проверка vertical slice. Он не заменяет собой integration suite.

## 4. Практическая пропорция

Для MVP принимается такая практическая цель:

- **55–65%** test cases — unit;
- **25–35%** — integration;
- **5–10%** — contract;
- **1–5%** — smoke/browser smoke.

Это не математический KPI, а ориентир против двух перекосов:
- слишком много хрупких e2e;
- слишком много изолированных unit при пустых межслойных проверках.

## 5. Обязательный минимум на текущем этапе

С учетом текущего состояния проекта:

- backend integration + smoke уже являются обязательной опорой;
- frontend уже имеет базовый unit/integration harness и короткий browser smoke;
- contract слой должен расти вокруг `openapi.yaml` и `docs/sync/schemas/`;
- browser smoke должен оставаться коротким и проверять только основной UI path.

## 6. Когда пирамида считается соблюденной

Пирамида считается соблюденной, если:
- большинство проверок быстрые и локальные;
- все критические пользовательские пути закрыты integration/smoke;
- API/sync surface защищены contract tests;
- local-first/sync кейсы воспроизводимы и не зависят от случайности среды.
