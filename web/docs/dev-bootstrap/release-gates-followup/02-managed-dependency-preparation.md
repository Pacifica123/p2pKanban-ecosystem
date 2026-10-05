# Proposal: managed dependency preparation for frontend/backend gates

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

`release-gates` должен уметь сам подготовить зависимости, когда это безопасно и воспроизводимо: frontend `npm ci`, Playwright browsers, backend dependency fetch/build warmup. Пользователь запускает одну команду, а bootstrapper сам доводит окружение до состояния, где тесты действительно могут стартовать.

Это уже частично просматривается в подсказке текущего отчета: `release-gates --prepare-frontend --install-playwright-browsers`. Нужно довести идею до строгой политики, чтобы она была безопасной, не превращалась в package manager и не ломала lockfiles.

## Почему это нужно

Текущий прогон не дошел до frontend-кода вообще:

- `npm run build` не запустился;
- `npm run test:run` не запустился;
- `npm run test:browser` не запустился;
- причина одинаковая: `frontend/node_modules is missing`.

Это значит, что release-gates как «одна кнопка» пока дает пользователю не ответ «фронт сломан/не сломан», а ответ «зависимости не подготовлены». Для локального проекта это полезная диагностика, но для release-review ее нужно уметь автоматически закрывать.

## Целевой UX

Минимально:

```bash
python tools/devbootstrap.py release-gates --prepare-deps
```

Развернуто, но все еще компактно:

```bash
python tools/devbootstrap.py release-gates --prepare-deps=missing|stale|always|never
```

Отдельный opt-in для тяжелых browser binaries:

```bash
python tools/devbootstrap.py release-gates --prepare-deps --install-playwright-browsers
```

Рекомендуемое значение по умолчанию для release profile:

```text
prepare-deps=missing-or-stale
install-playwright-browsers=false unless explicitly requested
```

## Что именно можно готовить автоматически

### Frontend

1. Проверить `frontend/package.json` и `frontend/package-lock.json`.
2. Посчитать SHA-256 lockfile/package manifest.
3. Сравнить с `.dev-bootstrap/frontend-install.json`.
4. Если `node_modules` отсутствует или marker stale:
   - запустить `npm ci`, если есть lockfile;
   - fallback на `npm install` только если lockfile отсутствует и это явно разрешено.
5. После успешной установки записать marker:
   - package manifest hash;
   - lockfile hash;
   - node/npm версии;
   - install command;
   - timestamp;
   - platform.

### Playwright

1. Проверить, установлен ли `@playwright/test`.
2. Проверить наличие browser executable в известных cache roots.
3. Если нет browser cache и включен `--install-playwright-browsers`, выполнить:

```bash
npx playwright install chromium
```

4. Если flag не включен, gate должен быть `skipped_prerequisite`, но с точной командой исправления.

### Backend

Backend dependency install как таковой делать не нужно: Cargo сам скачивает crates при `cargo test/check`. Но можно добавить управляемый warmup:

```bash
cargo fetch
cargo metadata
cargo test --no-run
```

Это полезно, чтобы отличать:

- проблемы сети/crates.io;
- проблемы lockfile;
- compile errors;
- реальные test failures.

Автоматически устанавливать Rust toolchain не надо. Максимум — обнаружить `rustup` и дать next action.

## Что нельзя делать автоматически

- Не менять `package-lock.json` в release-gates, если выбран reproducible mode.
- Не запускать глобальные installs (`npm install -g`, system package managers).
- Не устанавливать Node/Rust/PostgreSQL/Docker за пользователя.
- Не менять `.env` без явного `prepare-env`/consent.
- Не делать `cargo update`.
- Не лечить dependency conflicts путем редактирования manifest.

## Режимы подготовки

| Режим | Поведение | Для кого |
|---|---|---|
| `never` | Только диагностика prerequisites | CI/manual strict |
| `missing` | Установить только если папки/кэша нет | Fresh archive |
| `stale` | Установить если hash lockfile изменился | Обычная локальная разработка |
| `always` | Переустановить каждый раз | Редкий debug flaky deps |

Рекомендуемый default для локального release-gates: `stale`.

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Нет интернета | install падает | Classification `dependency_network_unavailable`, не маскировать как frontend test fail |
| `npm ci` меняет состояние | Dirty workspace / неожиданные файлы | Перед установкой проверить clean git; после установки проверить, что не изменились tracked manifest/lock |
| Lockfile не соответствует package.json | `npm ci` fail | Classification `frontend_lockfile_mismatch`, next action: обновить lockfile отдельным patch |
| Большой Playwright download | Долго и тяжело | Отдельный explicit flag, timeout, progress log |
| Windows path/caches | Browser not found false negative | Список cache roots по OS, browser diagnostic в JSON |
| npm lifecycle scripts | Нежелательное выполнение scripts | По умолчанию стандартный `npm ci`; future hardening может иметь `--ignore-scripts`, но только если проект совместим |
| Backend crates download медленный | Timeouts | Separate backend dependency gate with own timeout and log |

## User-friendly summary

Вместо текущего:

```text
frontend_dependencies_missing
run prepare-frontend first
```

Нужно стремиться к:

```text
frontend dependencies: prepared by release-gates
- command: npm ci
- package-lock hash: ...
- duration: ...
- marker: .dev-bootstrap/frontend-install.json
frontend build: passed/failed
```

Если подготовка невозможна:

```text
frontend dependencies: not prepared
reason: npm ci failed because lockfile is out of sync
safe action: inspect logs/07_prepare_frontend.log and fix package-lock.json in a separate patch
```

## Этапы реализации

### Phase A: unify dependency preflight

- Описать единый JSON contract для frontend/backend/playwright dependency state.
- Сейчас часть этой информации уже есть в details; нужно сделать ее first-class gate.

### Phase B: prepare-deps flag

- Добавить `--prepare-deps` как umbrella над существующим `--prepare-frontend`.
- Сохранить обратную совместимость старого флага.

### Phase C: marker hardening

- Marker должен включать OS, node/npm versions, hashes, install command.
- При mismatch gate должен говорить `stale`, а не просто `missing`.

### Phase D: Playwright browser prepare

- Унести browser install в отдельный controlled gate.
- Не смешивать missing browser и failed browser test.

## Definition of done

- Fresh archive без `node_modules` может дойти до реального `npm run build` одной командой.
- Если `npm ci` падает, summary показывает dependency failure, а не frontend build failure.
- Lockfile не меняется молча.
- Browser binaries устанавливаются только при explicit opt-in.
- Backend dependency/network failures отделены от compile/test failures.
