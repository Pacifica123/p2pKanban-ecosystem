# Release stabilization phase 4 controlled mutators rollout

- Статус: Implemented in `tools/devbootstrap.py`
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-DB-001`, `REL-DB-002`, `REL-FE-001`, `REL-BROWSER-001`, `REL-CLEAN-001`, `REL-PROC-001`, `REL-PORT-001`, `REL-ART-001`, `REL-SEC-001`
- Назначение: разрешить release-gates делать подготовительные действия только когда они явно запрошены профилем/флагом, заранее описаны consent plan и оставляют cleanup/rollback evidence в bundle.

---

## 1. Что закрывает фаза 4

Фаза 4 превращает уже существующие подготовительные действия `release-gates` в явно контролируемый слой autopsy-контракта.

Новый обязательный артефакт bundle:

| Artifact | Purpose |
|---|---|
| `remediation/controlled-mutators.json` / `.md` | Единый ledger всех разрешённых mutators: managed DB, managed runtime, dependency preparation, Playwright browser install и clean-machine sandbox. |

Контракт bundle поднят до `phase-4`. Артефакт включён в:

- `bundle-manifest.json`;
- `artifact-completeness.json/md`;
- release-gates archive;
- `self-check` case `release_gates_phase4_bundle_contract`.

Фаза 4 не делает controlled mutators включёнными по умолчанию. Базовый `diagnostic` profile остаётся безопасным: без DB creation, dependency install, Playwright download, runtime start и clean-machine copy.

---

## 2. Controlled mutators

| Mutator | Trigger | Allowed side effects | Cleanup / rollback evidence |
|---|---|---|---|
| `managed-test-database` | `--managed-test-db`, `isolated-db`, `managed-runtime`, `full-local-release` | Создать одну per-run PostgreSQL DB, направить DB-writing gates в неё, затем drop/retain по policy. | `managed-test-db.json`, `managed_test_db_prepare` / `managed_test_db_retention` logs, `cleanup_command`. |
| `managed-runtime-dynamic-ports` | `--managed-runtime` или profile с managed runtime | Выбрать dynamic loopback ports, запустить только owned backend/frontend process, записать runtime-state/env-diff/managed-urls. | `logs/runtime-state.json`, stop gate logs, managed process logs. |
| `dependency-preparation` | `--prepare-deps`, `--prepare-frontend`, `prepared-local`, `full-local-release` | Подготовить frontend npm deps/marker и backend Cargo warmup без изменения source/lock/env files. | prepare/warmup logs; manual cache cleanup notes. |
| `playwright-browser-install` | `--install-playwright-browsers`, `prepared-local`, `full-local-release` | Запустить `npx playwright install chromium`, если browser binary отсутствует. | `playwright_install` log; browser cache roots in controlled-mutators ledger. |
| `clean-machine-sandbox` | `--include-clean-machine`, `full-local-release` | Скопировать проект во временный sandbox с исключением generated/local state и выполнить выбранный profile. | `logs/clean-machine/*`, retained sandbox cleanup command or auto-deleted marker. |

---

## 3. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Managed DB create/drop with retention policy | Existing managed DB flow remains opt-in and now appears in `controlled-mutators.*` with cleanup command and retention status. |
| Managed runtime dynamic ports | Existing managed runtime flow records dynamic URLs, PIDs, process logs and stop evidence in `controlled-mutators.*`. |
| Dependency preparation with marker and consent | `release-gates-consent.json/md` are now required bundle artifacts; dependency preparation is represented as a controlled mutator. |
| Optional Playwright browser install with consent | `playwright_install` remains gated by explicit flag/profile and now includes cache cleanup hints. |
| Cleanup and rollback artifacts | `controlled-mutators.*` gives cleanup/rollback/evidence sections for every enabled mutator. |

Exit criteria after this patch:

- `unsafeMutationCount == 0` in `controlled-mutators.json`;
- `cleanupCoverage == "ok"` for enabled mutators;
- every created/started/copied resource has cleanup or explicit rollback notes;
- diagnostic profile still performs no DB/dependency/network/process/sandbox mutation.

---

## 4. Reviewer workflow после фазы 4

1. Открыть `bundle-manifest.json` и проверить `contractVersion == "phase-4"`.
2. Открыть `artifact-completeness.json` и проверить наличие `release-gates-consent.*` и `remediation/controlled-mutators.*`.
3. Открыть `remediation/controlled-mutators.md` и проверить:
   - enabled mutators;
   - allowed/denied side effects;
   - cleanup commands;
   - rollback notes;
   - evidence paths.
4. Если run выполнялся с `--managed-test-db`, сверить `managed-test-db.json` и `managed_test_db_retention` log.
5. Если run выполнялся с `--managed-runtime`, сверить `logs/runtime-state.json` и stop-gate logs.
6. Если run выполнялся с `--include-clean-machine`, сверить `logs/clean-machine/report.md` и cleanup command.

---

## 5. Extraordinary findings during phase 4

### 5.1. Phase 4 implementation was partially present but not visible as a contract

Перед этим патчем в `tools/devbootstrap.py` уже были важные building blocks: managed DB, managed runtime, dependency preparation, Playwright install flag, clean-machine sandbox и profile consent. Слабое место было не в отсутствии действий, а в том, что reviewer не получал одного machine-readable ledger, где все mutators, side effects и cleanup собраны в одном месте.

Решение фазы 4: не переписывать runtime-flow, а добавить `controlled-mutators.*` как обязательный autopsy artifact.

### 5.2. Report rendering had duplicate rows/lines

Во время фазы 4 найден косметический, но мешающий аудиту дефект: summary/report renderer дублировал строку managed runtime и строки gate table, а `ManagedTestDatabaseState` содержал повторное dataclass field definition для `drop_command`.

Решение фазы 4: убрать дублирование в затронутом report/contract коде. Это не меняет gate semantics, но снижает шум в bundle review.
