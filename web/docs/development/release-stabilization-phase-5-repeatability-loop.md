# Release stabilization phase 5 repeatability loop

- Статус: Implemented in `tools/devbootstrap.py`
- Дата: 2026-05-27
- Родительский документ: `docs/development/release-stabilization-program-v1.md`
- Связанные failure-mode IDs: `REL-SMOKE-001`, `REL-PROC-001`, `REL-PORT-001`, `REL-CFG-001`, `REL-ART-001`
- Назначение: перестать считать одиночный успешный прогон доказательством стабильности и добавить в release-gates bundle явный repeatability report.

---

## 1. Что закрывает фаза 5

Фаза 5 добавляет обязательный artifact:

| Artifact | Purpose |
|---|---|
| `remediation/repeatability-loop.json` / `.md` | Показывает, какие repeatability-сценарии уже имеют evidence, какие требуют повторного прогона, и какой `Reproducibility Index` получается по текущему bundle. |

Phase 5 introduced the `repeatability-loop.*` artifact and originally raised the bundle contract to `phase-5`. After Phase 7 the global bundle contract is `phase-7`, while this artifact remains required. Артефакт включён в:

- `bundle-manifest.json`;
- `artifact-completeness.json/md`;
- release-gates archive;
- `release-gates.md`;
- `self-check` case `release_gates_phase5_bundle_contract`.

Фаза 5 не запускает бесконечную рекурсию `release-gates` внутри самого себя. Вместо этого она делает безопасный первый шаг: текущий прогон сравнивается с предыдущими совместимыми `release-gates.json` в `.dev-bootstrap/runs/`, а reviewer получает точные команды для второго прогона / managed-runtime проверки.

---

## 2. Repeatability components

| Component | Что проверяет | Статусы |
|---|---|---|
| `same-profile-repeat` | Есть ли предыдущий прогон с тем же profile и совпадает ли общая классификация / gate signature. | `verified`, `unstable`, `insufficient-history`, `planned-only` |
| `start-stop-start` | Есть ли evidence owned managed-runtime start/stop lifecycle. | `single-cycle-evidence`, `failed-cycle-evidence`, `not-observed`, `planned-only` |
| `failed-start-retry` | Был ли предыдущий managed start failure, после которого текущий прогон смог стартовать managed runtime. | `verified`, `not-observed` |
| `fresh-and-dirty-smoke` | Присутствует ли двойной backend smoke path как proxy fresh/dirty smoke. | `verified`, `known-classified`, `not-observed` |
| `ledger-compare` | Сравнение текущего gate ledger signature с последним same-profile run. | `verified`, `unstable`, `insufficient-history` |
| `cleanup-verification` | Совместимость с Phase 4: cleanup coverage и `unsafeMutationCount == 0`. | `verified`, `incomplete` |

`Reproducibility Index` считается как средний score по этим компонентам. Exit criterion программы остаётся `>= 0.8`, но dry-run помечается как contract-shape verification, а не как доказательство repeatability.

---

## 3. Acceptance criteria mapping

| Program action | Implementation |
|---|---|
| Run same profile twice | `repeatability-loop.*` ищет предыдущий same-profile `release-gates.json` и сравнивает overall/gate signature. |
| Run start-stop-start | Managed runtime start/stop evidence попадает в компонент `start-stop-start`; для полного доказательства reviewer запускает тот же profile повторно. |
| Run failed-start-retry scenario | Компонент ищет предыдущий managed start failure и текущий успешный managed start. |
| Run fresh and dirty smoke | Двойной `backend_python_smoke_first/second` учитывается как in-run proxy для fresh/dirty smoke, когда доступна write-safe DB. |
| Compare ledgers between runs | Gate signature comparison включён в `comparisons[]` и `ledger-compare`. |

Exit criteria after this patch:

- `bundle-manifest.json` contains the current global contract version, now `phase-7` after Phase 7;
- `artifact-completeness.json` требует `remediation/repeatability-loop.*`;
- archive содержит `repeatability-loop.json/md`;
- reviewer видит `Reproducibility Index`, `exitCriteriaMet` и точные repeatability commands;
- одиночный run больше не выглядит как полное доказательство стабильности, если нет historical comparison.

---

## 4. Reviewer workflow после фазы 5

1. Открыть `bundle-manifest.json` и проверить текущий `contractVersion` (`phase-7` после Phase 7).
2. Открыть `remediation/repeatability-loop.md`.
3. Проверить `Reproducibility Index` и `exitCriteriaMet`.
4. Если `same-profile-repeat == insufficient-history`, запустить рекомендованную команду того же profile второй раз.
5. Если `start-stop-start == not-observed`, повторить профиль с `--managed-test-db --managed-runtime`.
6. Если `fresh-and-dirty-smoke == not-observed`, подготовить write-safe DB (`TEST_DATABASE_URL` или `--managed-test-db`).
7. После второго прогона сравнить новый `repeatability-loop.*` с предыдущим bundle.

---

## 5. Extraordinary findings during phase 5

### 5.1. Нельзя честно доказать repeatability одним запуском

Самый важный вывод фазы 5: repeatability нельзя “сгенерировать” постфактум внутри одиночного bundle. Поэтому патч не притворяется, что один dry-run или один успешный запуск закрывает всю фазу. Вместо этого `repeatability-loop.*` явно разделяет:

- уже имеющееся evidence;
- insufficient history;
- planned-only dry-run evidence;
- конкретные команды для следующего повторного запуска.

### 5.2. Repeatability artifact не должен менять общий результат release-gates

`repeatability-loop.*` является evidence/report layer. Он не превращает `release-gates` в failed только потому, что нет истории предыдущих прогонов. Иначе первый честный прогон в новом workspace всегда был бы искусственно красным. Вместо этого decision остаётся за release confidence gate следующей фазы.

### 5.3. Archive extraction encoding can affect devctl verification

During local verification of this phase, extracting the input project archive with the system `unzip` command produced surrogate-escaped filenames for Cyrillic release placeholders under `release/`. That made `tools/devctl.py start` fail while creating its pre-apply archive, because Python `zipfile` cannot write paths containing surrogate code points.

This was not caused by the Phase 5 patch contents. Re-extracting the same archive with Python `zipfile.extractall()` preserved the UTF-8 filenames correctly and `devctl status/start` passed. If this appears again, treat it as an archive extraction/encoding issue first, not as a repeatability-loop regression.
