# Release stabilization phase 0 baseline

- Статус: Active governance baseline
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные документы:
  - `docs/development/systemic-release-stabilization-manifesto-v1.md`
  - `docs/development/release-stabilization-problem-ledger.md`
  - `docs/development/release-confidence-scorecard-v1.md`
  - `docs/development/release-stabilization-profile-side-effects-v1.md`
- Назначение: включить stabilization lane, зафиксировать начальную карту известных проблем и остановить реактивные фиксы без evidence / failure-mode ID.

---

## 1. Что считается началом фазы 0

Фаза 0 не меняет продуктовый runtime и не пытается чинить очередной локальный симптом. Она фиксирует операционные правила, по которым следующие патчи будут приниматься и проверяться.

С этого baseline считается активным режим:

```text
new release/dev failure
-> evidence
-> Problem Ledger ID
-> remediation/probe decision
-> patch
-> acceptance evidence
```

Документационные и инвентаризационные патчи в фазе 0 могут не закрывать конкретный `REL-*` дефект, но обязаны явно говорить, что они относятся к governance/baseline, а не к runtime remediation.

---

## 2. Freeze rules для stabilization lane

### 2.1. Что теперь запрещено без явного обоснования

- Вносить release/dev/runtime фиксы без ссылки на `REL-*` failure-mode ID.
- Объявлять skipped / not implemented / prerequisite-blocked gate как pass.
- Считать mocked browser smoke доказательством real-backend интеграции.
- Принимать shared-dev smoke как strict default-state proof.
- Смешивать `PUSH_FAILED` / remote outage с качеством содержимого патча.
- Добавлять destructive mutator без профиля согласия, cleanup/rollback и evidence artifact.

### 2.2. Что разрешено на фазе 0

- Документы baseline/governance.
- Инициализация Problem Ledger / scorecard / side-effect matrix.
- Безопасные проверки существования документов и консистентности таксономии.
- Исправление документальных противоречий, найденных при инвентаризации.

### 2.3. Что откладывается на следующие фазы

- Изменения `tools/devbootstrap.py` и runtime-логики release-gates.
- Новые mutators для DB/deps/browser/process lifecycle.
- Массовая перепаковка архивов или cleanup generated файлов.
- Product feature work, не связанный с release/dev confidence.

---

## 3. Current product grounding baseline

На начало stabilization lane ближайший проверяемый happy-path должен строиться только вокруг уже подтвержденных или явно заведенных поверхностей:

| Surface | Phase 0 status | Release-gates meaning |
|---|---|---|
| Workspace / board / columns / cards core CRUD | ready surface | Должен быть в score-affecting smoke. |
| User appearance / board appearance | ready surface | Должен проверяться happy-path + validation. |
| Board activity / card activity / workspace audit log | ready surface | Должен проверяться как read-model после mutations. |
| Auth/session UX | release-proof pending | Можно тестировать, но не маскировать как финально закрытый auth release path без отдельного evidence. |
| Labels / checklists / comments | blocker or explicit deferral | Нельзя включать в green happy-path как готовую область без отдельного решения. |
| Sync / P2P / realtime | future-ready / out of mandatory beta path | Не должен блокировать beta, если явно не выбран как release scope. |
| Import/export destructive restore | deferred / guarded | Preview/backup можно показывать, destructive apply не считать готовым. |
| Mocked browser smoke | UI viability only | Не добавляет real-backend product-path confidence. |
| Real-backend browser smoke | required later | Отдельный score-affecting gate после безопасной DB/runtime подготовки. |

---

## 4. Baseline inventory

### 4.1. Canonical strategy documents

- `docs/development/systemic-release-stabilization-manifesto-v1.md`
- `docs/development/release-stabilization-program-v1.md`
- `docs/development/release-stabilization-plan-merge-notes-2026-05-27.md`

### 4.2. Phase 0 operating documents

- `docs/development/release-stabilization-phase-0-baseline.md`
- `docs/development/release-stabilization-problem-ledger.md`
- `docs/development/release-confidence-scorecard-v1.md`
- `docs/development/release-stabilization-profile-side-effects-v1.md`

### 4.3. Existing release/dev tool surfaces to be governed by later phases

- `tools/devbootstrap.py`
- `tools/devctl.py`
- `docs/dev-bootstrap/devbootstrap-v1-operations.md`
- `docs/dev-bootstrap/devbootstrap-v2-release-gates-plan.md`
- `docs/dev-bootstrap/release-gates-test-database.md`
- `docs/devctl/devctl-patch-conveyor-spec.md`

### 4.4. Known acceptance tool context

Patch acceptance is expected to use the devctl patch format:

```text
patch_YYYYMMDD_HHMMSS_short_slug.zip
  manifest.json
  PATCH_SUMMARY.md
  files/
    relative/path/in/project.ext
```

For stabilization patches, the patch summary must state whether it changes:

```text
product code
release/dev tooling
docs/governance
tests/checks
```

Phase 0 changes only docs/governance.

---

## 5. Phase 0 exit criteria mapping

| Program action | Phase 0 artifact | Status |
|---|---|---|
| Declare stabilization lane active | This document, sections 1-2 | done |
| Create initial Problem Ledger from known failures | `release-stabilization-problem-ledger.md` | done |
| Define score/classes | `release-confidence-scorecard-v1.md` plus canonical program section 10 | done |
| Define profile side effects | `release-stabilization-profile-side-effects-v1.md` | done |
| Update docs map | `docs/README.md` and root README docs list | done |
| Record extraordinary findings | Section 6 of this document | done |

---

## 6. Extraordinary findings during phase 0 inventory

### 6.1. `REL-SEC` seed ID existed without taxonomy family

The canonical program already had seed entry `REL-SEC-001`, but the family table did not define `REL-SEC`. This patch treats that as a documentation consistency issue and adds `REL-SEC` to the taxonomy as diagnostic security / redaction / secret leakage family.

Impact:

- No runtime behavior changes.
- Future Problem Ledger entries can reference `REL-SEC-*` without creating an undefined family.
- Secret/redaction risks stay separate from generic artifact quality (`REL-ART`).

### 6.2. No runtime or product-code anomaly observed

During this phase 0 patch preparation no new runtime failure was investigated, reproduced or fixed. Any future runtime anomaly must be added to the Problem Ledger instead of being silently patched.

---

## 7. Rules for the next patch after phase 0

The next non-doc stabilization patch should target Phase 1: autopsy bundle contract.

Minimum acceptance expectation for that patch:

1. It names the `REL-*` failure modes it improves.
2. It writes or validates machine-readable bundle metadata.
3. It does not mutate DB/deps/process state unless a profile allows that side effect.
4. It adds at least one regression probe or artifact completeness check.
5. It updates the Problem Ledger / Probe Ledger plan if new failure modes appear.

---

## 8. Manual checklist for reviewers

Before accepting a future stabilization patch, ask:

1. Does the patch say whether it is docs/governance, release tooling, tests, or product code?
2. Does it cite a `REL-*` ID, or explicitly state that it is baseline-only?
3. Does it reduce unknowns, or merely move them?
4. Does it produce evidence that can be inspected without terminal scrollback?
5. Does it preserve safe defaults for destructive side effects?
6. Does it update docs when behavior changes?
7. Does it keep devctl patch format minimal and reproducible?
