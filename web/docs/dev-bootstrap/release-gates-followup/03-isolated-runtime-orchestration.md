# Proposal: isolated runtime orchestration for release-gates

## Источник анализа

Документ построен по результатам архива `20260524_200616_release-gates.zip` для запуска `20260524_200616_release-gates`.

Фактический итог прогона:

- overall: `infra_failed`;
- classification: `release_gates_infra_failed`;
- `self_check` и `diagnose` прошли;
- `cargo test` завершился кодом `0`, но release-gates классифицировал его как `partial_pass / critical_tests_ignored`, потому что DB-зависимые Rust-тесты были `ignored`;
- `cargo test -- --include-ignored` был пропущен из-за отсутствия `TEST_DATABASE_URL` и безопасного DB-target;
- два Python smoke-прогона были пропущены защитой от записи в live/dev DB;
- `npm run build`, `npm run test:run`, `npm run test:browser` не стартовали из-за отсутствующего `frontend/node_modules`;
- `npm run test:browser:real-backend` был пропущен, потому что write-capable real-backend gate требует явного opt-in и безопасной DB;
- docs gates прошли, clean-machine quickstart был optional и не запускался.

Ключевой вывод: этот прогон не доказал regression в продуктовой логике backend/frontend. Он доказал, что release-gates пока слишком часто останавливается на подготовке окружения и ручных prerequisite-действиях.

## Смелая идея

`release-gates` должен уметь запускать собственный временный backend/frontend runtime для проверки write-capable сценариев, а не полагаться на то, что на портах `18080` и `5173` уже случайно висит правильная версия проекта.

Текущий `diagnose` показал важный симптом: backend health отвечал `200`, frontend port был открыт, но `frontend_root` вернул HTTP `404`. Это не доказывает поломку фронта. Это доказывает, что наличие открытого порта не равно «там запущен наш правильный runtime».

## Цель

Сделать release-gates воспроизводимым:

```text
release-gates
→ создает/выбирает isolated DB
→ стартует backend из текущего workspace against that DB
→ стартует frontend из текущего workspace with API base URL to managed backend
→ ждет health/readiness
→ гоняет smoke/browser gates
→ останавливает только свои процессы
→ складывает логи процессов в bundle
```

## Почему это нужно

Без собственного runtime release-gates может ошибиться в обе стороны:

- false pass: тесты попали в старый backend-процесс, который случайно жив;
- false fail: порт занят чужим процессом или старой версией;
- false skip: write gates пропущены, потому что непонятно, какая DB у live backend;
- миграционный drift: backend binary был собран до добавления migration files;
- frontend root `404`: порт открыт, но это не Vite текущего проекта.

## Целевой UX

```bash
python tools/devbootstrap.py release-gates --managed-runtime
```

Комбинированный полноценный сценарий:

```bash
python tools/devbootstrap.py release-gates   --prepare-deps   --managed-test-db   --managed-runtime   --include-real-backend-browser
```

Сокращенный профиль в будущем:

```bash
python tools/devbootstrap.py release-gates --profile full-local-release
```

## Runtime ownership contract

Bootstrapper имеет право останавливать только процессы, которые сам запустил и записал в `.dev-bootstrap/state.json` текущего run.

Нельзя:

- убивать процесс только потому, что он слушает порт;
- перезапускать чужой backend/frontend без согласия;
- считать открытый порт достаточным readiness-сигналом.

Можно:

- выбрать свободные временные порты;
- если стандартный порт занят, уйти на динамический порт и передать URLs в env тестов;
- сохранить PID, command, cwd, env diff без секретов, stdout/stderr logs;
- остановить эти PID в teardown.

## Порты

Рекомендуемая стратегия:

1. По умолчанию использовать динамические порты для managed runtime.
2. Стандартные порты `18080/5173` использовать только в legacy/live mode.
3. Перед запуском backend выбрать свободный port и передать `SERVER__PORT` или соответствующий env/config override.
4. Перед запуском frontend выбрать свободный Vite port и передать `VITE_API_BASE_URL` на managed backend.
5. В summary явно печатать:

```text
managed backend: http://127.0.0.1:<port>/api/v1
managed frontend: http://127.0.0.1:<port>/
```

Если проект пока не поддерживает port override через env, это отдельная code/tooling task.

## Readiness

Backend readiness:

- process started;
- `/health` returns `200`;
- `/api/v1/health` returns `200`;
- optional DB check endpoint или migration log подтверждает подключение к test DB.

Frontend readiness:

- process started;
- Vite stdout содержит local URL;
- HTTP root returns `200`, not just port-open;
- HTML содержит ожидаемый app root marker;
- optional smoke selector виден browser test.

## Режимы

| Mode | Runtime | DB | Для чего |
|---|---|---|---|
| `live` | Использует уже запущенные процессы | Требует explicit DB safety | Быстрая локальная проверка |
| `managed-runtime` | Запускает backend/frontend сам | Может использовать external test DB | Release-gates воспроизводимость |
| `managed-all` | Запускает DB/backend/frontend | Ephemeral DB | Самый близкий к одной кнопке локальный release |

## Windows/Linux риски

| Риск | Linux | Windows | Смягчение |
|---|---|---|---|
| Process tree teardown | SIGTERM/SIGKILL | CTRL_BREAK/TerminateProcess nuances | Process group/session per child, tracked PID, graceful timeout |
| Port allocation | race после free-port check | race аналогично | bind-test + retry, readiness validates actual service |
| Shell quoting | ниже риск | выше риск | subprocess args list, no shell |
| Env inheritance | обычный риск | path/case-insensitive env keys | explicit sanitized env map |
| Long-running cargo/npm | stdout buffering | stdout buffering | line-buffered log reader или communicate with timeout |

## Логи и bundle

Нужно сохранить:

```text
logs/runtime-backend.log
logs/runtime-frontend.log
logs/runtime-state.json
logs/runtime-env-diff.md
logs/managed-urls.env
```

`runtime-state.json` должен отвечать на вопросы:

- какой command был запущен;
- какой port выбран;
- какой PID/process group;
- какой DB target использовался;
- был ли процесс остановлен успешно;
- сколько занял readiness.

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Managed backend не стартует | DB/smoke/browser gates blocked | Лог backend stdout/stderr, classification `managed_backend_start_failed` |
| Managed frontend не стартует | Browser gates blocked | Лог Vite, classification `managed_frontend_start_failed` |
| Порт занят | Flaky fail | Dynamic ports by default |
| Тесты попали в старый backend | Неверный результат | BASE_URL всегда from managed runtime state |
| Teardown не сработал | Zombie processes | State registry + `devbootstrap stop --run-id` future cleanup |
| Secrets in logs | Утечка | Mask URL credentials and secret env keys |

## Этапы реализации

### Phase A: runtime identity diagnostics

- Улучшить diagnose: отличать `port open` от `our service ready`.
- Для frontend root `404` давать classification: `frontend_port_open_but_root_not_ready`.

### Phase B: managed backend only

- Запустить backend на managed DB и dynamic port.
- Прогнать Python smoke against managed backend.

### Phase C: managed frontend

- Запустить Vite на dynamic port.
- Прогнать browser smoke against managed frontend.

### Phase D: managed-all profile

- Объединить managed DB + managed backend + managed frontend.
- Сделать это основой future `--profile full-local-release`.

## Definition of done

- Release-gates не принимает «открытый порт» как достаточный факт готовности.
- Real-backend browser smoke всегда знает, в какой backend и DB он пишет.
- После прогона не остается backend/frontend процессов, запущенных bootstrapper-ом.
- При падении runtime startup в bundle достаточно логов, чтобы понять причину без ручного копирования терминала.
