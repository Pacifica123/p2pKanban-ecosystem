# Release stabilization phase 3 diagnostic provocation matrix

- Статус: Implemented in `tools/devbootstrap.py`
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-PORT-001`, `REL-WIN-001`, `REL-DB-002`, `REL-SMOKE-001`, `REL-CLEAN-001`, `REL-ART-001`
- Назначение: заранее и безопасно провоцировать ожидаемые release/dev failure modes, чтобы они попадали в bundle как классифицированные сигналы до того, как пользователь случайно наткнётся на них в живом запуске.

---

## 1. Что закрывает фаза 3

Фаза 3 добавляет к `release-gates` remediation bundle новый артефакт:

| Artifact | Purpose |
|---|---|
| `remediation/provocation-matrix.json` / `.md` | Controlled diagnostic provocation matrix: безопасные probe-сигналы для портов, launcher resolution, DB capability, dirty-state smoke и clean-machine dry profile. |

Контракт bundle поднят до `phase-3`. Артефакт включён в:

- `bundle-manifest.json`;
- `artifact-completeness.json/md`;
- release-gates archive;
- `self-check` case `release_gates_phase3_bundle_contract`.

Фаза 3 не добавляет destructive mutators: она не создаёт БД, не ставит зависимости, не запускает долгоживущие backend/frontend процессы и не меняет project files.

---

## 2. Probe matrix

| Probe | Failure family | Side effect class | Notes |
|---|---|---|---|
| `provocation:low-risk-port-binder` | `REL-PORT-001` | temporary loopback bind | Биндит `127.0.0.1:0` внутри текущего Python-процесса, чтобы проверить возможность динамического managed-runtime порта без занятия фиксированных портов проекта. |
| `provocation:launcher:*` | `REL-WIN-001` / prerequisites | dry-run only | Проверяет command resolution для `python`, `git`, `cargo`, `npm`, `node`, `docker compose`, `psql`; команды не выполняются. |
| `provocation:db:*` | `REL-DB-002` | read-only | Проверяет наличие и parseability DB URL, а также launcher resolution для `psql`/`pg_isready`; подключение к PostgreSQL не выполняется. |
| `provocation:dirty-state-smoke` | `REL-SMOKE-001` | static source inspection | Проверяет, что backend smoke использует run-scoped user через `SMOKE_RUN_ID` и не содержит известных brittle default-state assertions. |
| `provocation:clean-machine-dry-profile` | `REL-CLEAN-001` | planning only | Проверяет required files и фиксирует planned commands для clean-machine dry profile без создания sandbox copy. |

---

## 3. Статусы и классификации

`provocation-matrix.json` пишет по каждому probe:

- `probeId`;
- `status`;
- `classification`;
- `problemId`, если classification не `ok`;
- `nextAction`, если для classification есть remediation hint;
- `sideEffects`.

`overallStatus` матрицы трактуется так:

| Status | Meaning |
|---|---|
| `ok` | Все controlled probes дали чистый сигнал. |
| `incomplete` | Есть ожидаемые missing-prerequisite/skip сигналы, но destructive failure не воспроизведён. |
| `failed` | Низкорисковый probe действительно не смог выполниться, например нельзя забиндить loopback port. |

Важно: `incomplete` у provocation matrix не равен product regression. Это классифицированный diagnostic signal, который должен уменьшать unknown ratio, а не автоматически блокировать runtime-code changes.

---

## 4. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Add low-risk port binder probe | `release_gates_low_risk_port_binder_probe()` bind на `127.0.0.1:0`. |
| Add launcher dry-run matrix | `release_gates_launcher_dry_run_matrix()` через `command_resolution_details()`. |
| Add DB capability probes | `release_gates_db_capability_probes()` для DB URL parseability и PostgreSQL launcher resolution без подключения. |
| Add dirty-state smoke probe | `release_gates_dirty_state_smoke_probe()` статически проверяет `backend/tests/smoke_core_api.py`. |
| Add clean-machine dry profile | `release_gates_clean_machine_dry_profile_probe()` фиксирует required files и planned dry commands без sandbox copy. |

---

## 5. Reviewer workflow после фазы 3

1. Открыть `bundle-manifest.json` и проверить `contractVersion == "phase-3"`.
2. Открыть `artifact-completeness.json` и проверить наличие `remediation/provocation-matrix.*`.
3. Открыть `remediation/provocation-matrix.md` для быстрого чтения probe-status table.
4. Если есть non-ok classification, сверить `problemId` с `release-stabilization-problem-ledger.md`.
5. Только после этого переходить к `problem-ledger.md`, `probe-ledger.md`, logs и targeted rerun commands.

---

## 6. Extraordinary findings during phase 3

### 6.1. Controlled provocation should not mutate the environment

Изначальная формулировка “provocation” может быть ошибочно прочитана как “сломать окружение, чтобы проверить классификатор”. Для текущего стабилизационного контура это опасно: фаза 4 как раз отведена под controlled mutators.

Решение фазы 3:

- все probes read-only/dry-run;
- единственное активное действие — кратковременный bind loopback port `0`, который освобождается сразу после проверки;
- clean-machine dry profile в matrix только планируется, а настоящий sandbox остаётся отдельным opt-in gate через `--include-clean-machine`.

### 6.2. Matrix signals are separate from gate failures

`provocation-matrix.*` пока не превращает каждый non-ok probe в отдельный release gate. Это сделано намеренно: matrix должна уменьшать неизвестность и направлять анализ, но не подменять реальные gates. Если один из matrix-сигналов станет повторяющимся блокером, следующая ремедиация должна либо добавить полноценный gate, либо расширить Problem Ledger.
