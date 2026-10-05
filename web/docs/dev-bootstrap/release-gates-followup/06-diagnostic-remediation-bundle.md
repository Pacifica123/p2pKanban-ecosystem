# Proposal: diagnostic remediation bundle for release-gates

> Статус: исторический план. Managed DB, managed runtime и remediation bundle
> уже реализованы; актуальные команды находятся в
> `docs/dev-bootstrap/release-gates-test-database.md`.

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

Release-gates bundle должен быть не просто «папкой логов», а диагностическим пакетом, который отвечает на три вопроса:

1. Что реально проверялось?
2. Что не проверялось и почему?
3. Какой следующий минимальный шаг нужен, чтобы превратить skipped/prerequisite в реальный test signal?

Текущий отчет уже движется в эту сторону через classifications и next actions. Нужно сделать это first-class форматом.

## Проблема текущего прогона

С точки зрения качества продукта получился неоднозначный сигнал:

- backend compile/test path частично жив;
- DB tests не выполнены;
- Python smoke не выполнен;
- frontend build/unit/browser не выполнены;
- docs gates выполнены.

Человеку нужно вручную интерпретировать, что это не «фронт сломан», а «frontend dependencies missing». Аналогично, `cargo test` code 0 не равен полному backend успеху, потому что важные тесты ignored.

## Целевой формат bundle

Помимо текущих `release-gates.md/json/summary.txt` добавить структурированные файлы:

```text
remediation/
  gate-ledger.md
  gate-ledger.json
  prerequisites.md
  skipped-gates.md
  next-actions.md
  rerun-commands.md
  environment-fingerprint.json
```

## Gate ledger

`gate-ledger` должен разделять статусы:

| Status | Meaning |
|---|---|
| `passed` | Gate реально выполнился и прошел |
| `failed` | Gate реально выполнился и нашел defect/test failure |
| `infra_failed` | Gate не смог проверить продукт из-за окружения/tooling |
| `skipped_prerequisite` | Gate безопасно пропущен из-за отсутствующего prerequisite |
| `skipped_optional` | Gate intentionally optional |
| `partial_pass` | Команда ok, но release confidence неполный |

Важно: итоговый overall может быть `infra_failed`, но ledger должен показывать, какой release confidence уже получен и чего не хватает.

## Пример выводимого анализа

```text
Release confidence: incomplete
Product regressions proven: none
Infrastructure blockers:
- frontend dependencies missing
- write-safe DB target missing
Unverified release-critical areas:
- DB integration tests
- backend Python smoke idempotency
- frontend build
- frontend unit/integration tests
- browser smoke
- real backend browser path
```

Это намного полезнее, чем просто `failed`.

## Environment fingerprint

Нужно сохранять:

- OS/platform;
- Python version;
- git version;
- cargo/rustc version;
- node/npm version;
- docker/compose availability;
- psql/pg_isready availability;
- port readiness classification;
- dependency marker hashes;
- package lock hash;
- migrations hash;
- backend build.rs presence;
- active devbootstrap state.

Часть этого уже есть в diagnose/release-gates details. Нужно собрать это в отдельный компактный fingerprint, чтобы легко сравнивать два прогона.

## Remediation commands

`rerun-commands.md` должен содержать не generic advice, а commands, привязанные к найденным blockers.

Для текущего прогона это было бы:

```bash
python tools/devbootstrap.py release-gates --prepare-frontend --install-playwright-browsers
```

и для DB-writing gates:

```bash
# create/export TEST_DATABASE_URL или future --managed-test-db
python tools/devbootstrap.py release-gates --managed-test-db --include-real-backend-browser
```

На момент исходного плана managed DB ещё не была реализована. Сейчас команда
использует действующий `--managed-test-db`; ссылка выше остаётся runbook.

## Failure taxonomy

Нужно расширить classifications так, чтобы разные причины не слипались:

| Current/general | More precise future classification |
|---|---|
| `frontend_dependencies_missing` | `frontend_node_modules_missing`, `frontend_install_marker_stale`, `frontend_lockfile_mismatch` |
| `db_test_prerequisite_missing` | `test_database_url_missing`, `postgres_missing`, `postgres_createdb_permission_denied` |
| `smoke_db_write_guard` | `smoke_requires_write_safe_db`, `live_backend_db_unknown` |
| `real_backend_browser_opt_in_required` | `real_backend_browser_requires_managed_runtime_or_explicit_db` |
| `infra_failed` | aggregated, never the only detailed reason |

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Слишком много файлов | Bundle становится шумным | `remediation/` с короткими индексными файлами |
| Дублирование release-gates.json | Расхождение | Remediation генерируется из единого gate model |
| Next actions становятся устаревшими | Вводят в заблуждение | Self-check fixtures для classifications/next actions |
| Secrets in fingerprint | Утечка | Masking policy как в env parser |
| AI/human misreads status | Неверный план фиксов | Отдельно выводить `Product regressions proven: yes/no/unknown` |

## Связь с текущими результатами

Для конкретного прогона remediation bundle должен был бы сказать:

```text
Что стало лучше:
- self-check passed;
- diagnose passed;
- docs gates passed;
- cargo test compiled and ran non-DB health test.

Что осталось неизвестным:
- DB integration behavior;
- Python smoke idempotency on real backend;
- frontend build/unit/browser tests;
- real backend browser path;
- clean-machine quickstart.

Главная причина неизвестности:
- prerequisites не подготовлены, а не доказанные failures кода.
```

## Этапы реализации

### Phase A: gate ledger

- Добавить normalized ledger JSON.
- Выводить release confidence summary.

### Phase B: remediation files

- Генерировать `next-actions.md`, `rerun-commands.md`, `skipped-gates.md`.

### Phase C: compare mode

- Future: `devbootstrap compare-runs <old.zip> <new.zip>`.
- Показывать, улучшился ли signal: fewer skipped, more real gates passed, new product failures.

## Definition of done

- По одному bundle можно понять, какие зоны проекта реально проверены.
- Для каждого skipped/infra_failed gate есть precise next action.
- Итог явно различает `product failure`, `infrastructure failure` и `unknown due to skipped prerequisites`.
- Два release-gates архива можно сравнить по normalized ledger.
