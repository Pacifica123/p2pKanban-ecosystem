# Release stabilization phase 1 autopsy bundle contract

- Статус: Implemented in `tools/devbootstrap.py`; superseded in active bundles by Phase 2 contract version
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-ART-001`, `REL-SEC-001`, `REL-WIN-001`, `REL-DOCS-001`
- Назначение: сделать каждый `release-gates` запуск самодостаточным для анализа без terminal scrollback.

---

## 1. Что закрывает фаза 1

Фаза 1 реализует autopsy bundle contract для `python tools/devbootstrap.py release-gates`.

Каждый bundle теперь обязан содержать:

| Artifact | Purpose |
|---|---|
| `bundle-manifest.json` | Главный machine-readable manifest: версия контракта, run ID, профиль, итоговая классификация, список обязательных артефактов и gates. |
| `environment-fingerprint.json` | Быстрый root-level снимок окружения: OS/Python/tools/ports/health/dependency/hash/state. |
| `command-resolution.json` / `command-resolution.md` | Явное объяснение display command, resolved executable и execution command для tools и gates. Особенно важно для Windows `.cmd/.bat` wrappers. |
| `redaction-report.json` / `redaction-report.md` | Какие источники secret-like ключей обнаружены, какие правила маскирования применяются, есть ли raw secret hits в созданных артефактах. |
| `artifact-completeness.json` / `artifact-completeness.md` | Проверка, что обязательные артефакты присутствуют до сборки `release-gates_*.zip`. |
| `remediation/*` | Уже существующий diagnostic remediation bundle: ledger, prerequisites, skipped gates, next actions, rerun commands, environment fingerprint. |
| `logs/*.log` | Per-gate evidence. |

---

## 2. Поведение по безопасности

Фаза 1 не добавляет destructive mutators.

Разрешенные side effects остаются прежними и зависят от выбранного release-gates profile. Новый bundle contract только пишет дополнительные диагностические файлы в текущий `.dev-bootstrap/runs/<run-id>/`.

Redaction report:

- не записывает сами secret values;
- перечисляет secret-like key names;
- сканирует raw values только из env-файлов проекта и из release-gates-relevant process env keys (`DATABASE__URL`, `DATABASE_URL`, `TEST_DATABASE_URL`, `P2P_TEST_DB_ADMIN_PASSWORD`, `PGPASSWORD`);
- игнорирует unrelated ambient secrets процесса, чтобы sandbox/CI переменные не создавали ложные positive hits в обычном тексте.

Если raw secret hit найден в bundle artifact, `artifact-completeness.json` помечает contract как failed.

---

## 3. Что теперь должен смотреть ревьюер

Минимальный порядок ручного анализа bundle:

1. Открыть `bundle-manifest.json`. Для архивов после Phase 2 активное значение — `contractVersion == "phase-2"`; для старых Phase 1 архивов допустимо `phase-1`.
2. Открыть `artifact-completeness.json` и проверить `overallStatus == "ok"`.
3. Открыть `redaction-report.json` и проверить `status == "ok"`.
4. Открыть `command-resolution.md`, если есть Windows/npm/Vite/cargo странности.
5. Открыть `environment-fingerprint.json`, если gate оказался infra/prerequisite failure.
6. Затем читать `release-gates.md`, `remediation/gate-ledger.md` и нужные `logs/*.log`.

---

## 4. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Add required bundle manifest | `bundle-manifest.json`, included in archive and self-check. |
| Add environment fingerprint | Root `environment-fingerprint.json` plus existing `remediation/environment-fingerprint.json`. |
| Add command-resolution artifacts | `command-resolution.json` and `command-resolution.md`. |
| Add redaction report | `redaction-report.json` and `redaction-report.md`. |
| Add artifact completeness check | `artifact-completeness.json` and `artifact-completeness.md`, generated before archive creation. |

---

## 5. Checks added

`self-check` now includes `release_gates_phase1_bundle_contract`.

This fixture creates a temporary release-gates run directory, writes reports, opens the resulting archive and verifies that the Phase 1 contract artifacts are present.

Manual verification command:

```bash
python tools/devbootstrap.py self-check --no-write-report
python tools/devbootstrap.py release-gates --dry-run
```

---

## 6. Extraordinary findings during phase 1

### 6.1. Ambient secret false positives

Initial raw-secret scanning against every process environment variable was too noisy: unrelated sandbox/CI secret values can accidentally appear inside ordinary diagnostic text.

Resolution:

- keep inventory of all secret-like process env keys;
- scan raw process env values only for release-gates-relevant keys;
- continue scanning project env-file values because those are direct project inputs.

No product runtime code was changed.

### 6.2. devctl v0.2 archive filename edge case in `release/`

During patch acceptance on a temporary workspace, the existing devctl v0.2 pre-archive step failed before applying the patch when it tried to ZIP a legacy/generated `release/` filename containing surrogate characters from the source archive.

Resolution for this patch:

- no project runtime file is changed for this edge case;
- patch manifest `archive.exclude` includes `release/*` and `release/`, so devctl pre/post/failed service archives do not try to re-encode problematic generated release payload names;
- the actual patch `files/` payload remains limited to source/docs files.

This finding reinforces `REL-ART-001`: acceptance archives must avoid generated/heavy/legacy release payloads unless an explicit release-packaging patch is targeting them.

---

## 7. Phase 2 compatibility note

Phase 1 artifacts remain mandatory, but the active bundle contract has moved to `phase-2` because the same bundle now also contains machine-readable Problem/Probe/Decision ledgers.
