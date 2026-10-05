# Фаза 6: автоматическое решение о готовности

- Статус: реализовано в `tools/devbootstrap.py`

## Результат

Каждый release-gates bundle содержит:

| Файл | Назначение |
|---|---|
| `release-confidence-gate.json/md` | Балл, блоки, hard caps и решение |
| `v1-release-readiness.md` | Короткий verdict для reviewer |

Глобальный bundle contract после фазы 7 называется `phase-7`, но артефакты
фазы 6 остаются обязательными.

## Источники балла

| Блок | Максимум | Evidence |
|---|---:|---|
| Полнота | 15 | gate ledger и наличие файлов |
| Gates | 20 | статусы required gates |
| Повторяемость | 15 | repeatability loop |
| Изоляция | 15 | controlled mutators |
| Платформы | 10 | command resolution и provocation |
| Product path | 15 | backend/frontend/real-backend |
| Remediation | 5 | ledgers |
| Bundle | 5 | redaction, completeness, manifest |

Dry-run оценивает форму контракта, а не runtime.

## Hard caps

```text
unknown-release-blockers       → partial_signal
required-gate-failed           → partial_signal
repeatability-not-proven       → internal_candidate
real-backend-product-path-missing → internal_candidate
artifact-not-shareable         → partial_signal
dry-run                        → partial_signal
```

Для `beta_candidate` нужны score не ниже 85, `overallStatus == ok`, отсутствие
hard caps и документированное принятие необязательных skips.

## Работа reviewer

1. Открыть `v1-release-readiness.md`.
2. Посмотреть active hard caps.
3. Проверить блоки в `release-confidence-gate.md`.
4. Найти действия в `remediation/problem-ledger.md`.
5. После исправления повторить тот же profile.

## Двухпроходная запись

Confidence files должны входить в completeness, а итоговый score должен знать
результат completeness. Поэтому реализация:

1. пишет предварительный confidence;
2. формирует completeness/manifest;
3. переписывает confidence с окончательным artifact-quality signal.

Это решение разрывает циклическую зависимость. Фаза 6 не запускает новые
product tests, а только принимает решение на основе существующих.

