# Release stabilization phase 7 regression memory

- Статус: Implemented in `tools/devbootstrap.py`
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-ART-001`, `REL-DOCS-001`, `REL-SMOKE-001`, `REL-PROC-001`, `REL-PORT-001`, `REL-CLEAN-001`, `REL-SEC-001`
- Назначение: закрыть программу стабилизации постоянной памятью: каждый прогон `release-gates` должен оставлять machine-readable след того, какие проблемы появились, какие probes их держат, какие families повторяются и когда нужен process review.

---

## 1. Что закрывает фаза 7

Фазы 1–6 сделали один прогон понятным, безопасным и пригодным для release decision. Фаза 7 добавляет защиту от отката обратно в реактивный цикл: новый сбой больше не должен растворяться в терминальном выводе или превращаться в очередной тактический патч без памяти.

Фаза 7 добавляет обязательные artifacts в каждый `release-gates` bundle:

| Artifact | Purpose |
|---|---|
| `remediation/regression-memory.json` / `.md` | Общий dashboard непрерывной памяти: ledger update, probe linkage, run comparison, docs sync, release confidence summary and next actions. |
| `remediation/recurring-family-counts.json` / `.md` | Счётчик повторяющихся `REL-*` families по текущему и предыдущим `release-gates` runs. |

Контракт bundle поднят до `phase-7`. Эти artifacts включены в:

- `bundle-manifest.json`;
- `artifact-completeness.json/md`;
- release-gates archive;
- `self-check` case `release_gates_phase7_bundle_contract`.

---

## 2. Regression memory checks

`regression-memory.*` фиксирует шесть проверок:

| Check | Что означает |
|---|---|
| `failure-updates-ledger` | Текущий run написал `problem-ledger.*`; новые failed/skipped сигналы имеют durable `REL-*` mapping. |
| `remediation-updates-probes` | `probe-ledger.*` существует, а failing/skipped probes не теряют связь с Problem Ledger IDs. |
| `run-history-comparison` | Есть сравнение с предыдущими runs через Phase 5 repeatability loop; если истории нет, статус честно `insufficient-history`. |
| `docs-synchronized` | Основные stabilization docs и документ Phase 7 присутствуют в проекте. |
| `recurring-family-counts` | Повторяющиеся failure families вынесены отдельно от одиночных сбоев. |
| `artifact-shareability-memory` | Manifest/completeness artifacts дают будущему reviewer автономный контекст без terminal scrollback. |

Phase 7 не объявляет первый run fully stable. Если истории ещё нет, это не failure, а честная память о том, что repeatability всё ещё требует второго совместимого прогона.

---

## 3. Recurring family policy

`recurring-family-counts.*` считает family names из `problem-ledger.*`:

| Rule | Result |
|---|---|
| Family встречается в одном run | `single_run` |
| Family встречается в двух runs | `repeated_signal` |
| Family встречается в трёх и более runs | `recurring_process_risk`, `processReviewRequired = true` |

Если family достигает process-review threshold, следующий патч не должен быть просто ещё одним локальным workaround. Нужно пересмотреть процесс/границу системы: профиль, preflight, ownership процессов, DB authority ladder, smoke idempotency или документационный контракт.

---

## 4. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Every new failure adds/updates ledger | `problem-ledger.*` остаётся required artifact; `regression-memory.*` проверяет его наличие. |
| Every remediation adds/updates probe | `probe-ledger.*` остаётся required artifact; `regression-memory.*` отслеживает missing problem links. |
| Compare runs over time | `repeatability-loop.*` и `recurring-family-counts.*` читают previous `release-gates.json` / `problem-ledger.json`. |
| Keep docs synchronized | `regression-memory.*` проверяет Phase 7 doc, stabilization program, Problem Ledger and docs map presence. |
| Track recurring family counts | `recurring-family-counts.*` фиксирует current/historical/run counts and process-review triggers. |

Exit criteria after this patch:

- `bundle-manifest.json` содержит `contractVersion == "phase-7"`;
- `artifact-completeness.json` требует `regression-memory.*` и `recurring-family-counts.*`;
- archive содержит Phase 7 artifacts;
- self-check validates the Phase 7 bundle contract;
- reviewer получает явный список `unguardedProblemIds` and recurring families.

---

## 5. Reviewer workflow после фазы 7

1. Открыть `v1-release-readiness.md` для release verdict.
2. Открыть `remediation/regression-memory.md` для continuous-memory status.
3. Если есть `unguardedProblemIds`, связать их с probes или явно принять как non-blocking skip.
4. Открыть `remediation/recurring-family-counts.md`.
5. Если есть `processReviewRequired`, остановить tactical patch loop and review the recurring family at process/system level.
6. Запустить тот же `release-gates` profile повторно, если Phase 5 всё ещё показывает `insufficient-history`.

---

## 6. Extraordinary findings during phase 7

### 6.1. Continuous memory cannot be a static document only

Главный вывод финальной фазы: Problem Ledger в `docs/` важен как taxonomy, но его недостаточно как operational memory. Реальный regression protection должен жить в каждом bundle рядом с конкретным run evidence. Поэтому Phase 7 не заменяет docs-ledger, а добавляет per-run `regression-memory.*` and `recurring-family-counts.*`.

### 6.2. Process review threshold must not fail the first honest run

Повторяющаяся family — это сигнал для процесса, а не автоматическое доказательство regression в текущем коде. Поэтому Phase 7 помечает `processReviewRequired`, но не превращает сам `release-gates` result в failed только из-за исторического повторения. Release decision остаётся в `release-confidence-gate.*`.


### 6.3. Post-phase-7 gap: explicit browser install must not trust stale cache scans

The first Linux acceptance pass after Phase 7 showed that operational memory was present, but the remediation action for `REL-BROWSER` was too weak. `release-gates --install-playwright-browsers` allowed network/cache side effects, yet `build_release_gate_specs()` skipped the `playwright_install` gate because a different cached Chromium executable existed. Playwright then failed at runtime because its installed package required a newer pinned browser revision.

This is tracked as `REL-BROWSER-002`. The regression probe is a self-check fixture with stale browser-cache evidence and an explicit install flag; it requires `playwright_install` to appear before `frontend_browser_smoke`.
