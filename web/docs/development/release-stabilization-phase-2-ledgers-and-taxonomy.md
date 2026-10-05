# Release stabilization phase 2 ledgers and taxonomy

- Статус: Implemented in `tools/devbootstrap.py`
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-ART-001`, `REL-DOCS-001`, `REL-FE-001`, `REL-DB-001`, `REL-DB-002`, `REL-BROWSER-001`, `REL-PROC-001`, `REL-PORT-001`, `REL-CLEAN-001`
- Назначение: превратить результаты `release-gates` из набора логов в устойчивые ledger-артефакты, которые можно сравнивать между прогонами и использовать как вход для следующих ремедиаций.

---

## 1. Что закрывает фаза 2

Фаза 2 добавляет к remediation bundle слой машинно-читаемых ledgers:

| Artifact | Purpose |
|---|---|
| `remediation/problem-ledger.json` / `.md` | Durable список проблем текущего прогона, сгруппированный по стабильным `REL-*` IDs. |
| `remediation/probe-ledger.json` / `.md` | Скелет Probe Ledger: каждый gate становится probe-записью с областью, статусом, classification и ссылкой на problem ID, если сигнал не чисто успешный. |
| `remediation/decision-ledger-template.json` / `.md` | Шаблон Decision Ledger для следующего behavior-changing patch: какие проблемы затрагиваются, какие варианты рассматривались, acceptance checks и rollback. |
| `remediation/gate-ledger.json` | Расширен `problemId` и `nextAction`, чтобы gate-level и problem-level слой были связаны. |
| `bundle-manifest.json` | Контракт поднят до `contractVersion == "phase-2"` и теперь явно перечисляет новые ledger paths. |

Фаза 2 не добавляет destructive mutators. Она только пишет дополнительные диагностические файлы в `.dev-bootstrap/runs/<run-id>/remediation/`.

---

## 2. Правило стабильных IDs

`problem-ledger.json` мапит gate classification в известные ledger IDs из `docs/development/release-stabilization-problem-ledger.md`.

Примеры стабильных маппингов:

| Classification family | Stable ID |
|---|---|
| `frontend_dependencies_*`, `frontend_prepare_*`, `frontend_lockfile_*` | `REL-FE-001` |
| `db_test_prerequisite_missing`, `critical_tests_ignored` | `REL-DB-001` |
| `managed_test_db_*`, `postgres_*` | `REL-DB-002` |
| `browser_smoke_prerequisite`, `real_backend_browser_*` | `REL-BROWSER-001` |
| `managed_backend_port_*`, `managed_frontend_port_*`, `frontend_port_conflict` | `REL-PORT-001` |
| `managed_runtime_*`, `runtime_unreachable` | `REL-PROC-001` |
| `clean_machine_*` | `REL-CLEAN-001` |
| `docs_*` | `REL-DOCS-001` |

Если в будущем появится новая classification, которой еще нет в taxonomy, devbootstrap не теряет сигнал: он назначает стабильный fallback `REL-UNMAPPED-<sha1-prefix>`. Такой ID считается временным и должен быть заменен нормальной `REL-*` записью в следующем docs/governance patch.

---

## 3. Reviewer workflow после фазы 2

Минимальный порядок анализа нового `release-gates` bundle:

1. Открыть `bundle-manifest.json` и проверить `contractVersion == "phase-2"`.
2. Открыть `artifact-completeness.json` и проверить, что новые ledger artifacts присутствуют.
3. Открыть `remediation/problem-ledger.md` — это главный список unresolved blockers текущего прогона.
4. Открыть `remediation/probe-ledger.md`, если нужно понять, какие probes покрывают или не покрывают проблему.
5. Открыть `remediation/decision-ledger-template.md`, если следующий patch меняет поведение, а не только документацию.
6. После этого читать `logs/*.log`, `command-resolution.md`, `redaction-report.md` и старый `gate-ledger.md`.

---

## 4. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Generate Problem Ledger JSON/Markdown | `remediation/problem-ledger.json` / `.md`. |
| Generate Probe Ledger skeleton | `remediation/probe-ledger.json` / `.md`. |
| Add Decision Ledger templates | `remediation/decision-ledger-template.json` / `.md`. |
| Map gate statuses into families | `classificationFamily`, `problemId`, `family`, `severity`, `status` fields in gate/problem ledgers. |
| Generate rerun/next-action commands | Existing `next-actions.md` and `rerun-commands.md` are now linked from each problem entry. |

---

## 5. Checks added

`self-check` now includes `release_gates_phase2_bundle_contract`.

The fixture creates a temporary release-gates run directory, writes the full report bundle, opens the resulting archive and verifies that the Phase 2 ledger artifacts are included.

Manual verification command:

```bash
python tools/devbootstrap.py self-check --no-write-report
python tools/devbootstrap.py release-gates --dry-run
```

---

## 6. Extraordinary findings during phase 2

### 6.1. Taxonomy drift needs a safe fallback

Phase 2 exposed a predictable future problem: gate classifications will keep evolving faster than the human Problem Ledger.

Resolution:

- known release/dev failure classes map to stable `REL-*` IDs;
- unknown classifications become deterministic `REL-UNMAPPED-<sha1-prefix>` records instead of disappearing;
- any `REL-UNMAPPED-*` record in a real run should trigger a small taxonomy/doc patch before deeper remediation.

This keeps the bundle analyzable without pretending that unknown classifications are already part of the canonical taxonomy.
