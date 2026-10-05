# Программа стабилизации релиза v1

## Решение

Release/dev lifecycle рассматривается как измеряемая система. Каждый красный
gate становится:

1. продуктовой регрессией;
2. проблемой окружения;
3. явной неизвестностью со следующим probe.

## Поддерживаемая реальность

| Область | Baseline |
|---|---|
| ОС | Windows и Linux |
| Backend | Rust/Axum и Cargo gates |
| Frontend | React/Vite build и tests |
| БД | PostgreSQL; запись только в safe target |
| UI | Custom UIX, Playwright optional |
| Patch | Внешний devctl и manifest ZIP |
| Evidence | Отдельный release-gates bundle |

## Цикл

1. Запустить безопасную диагностику.
2. Прочитать readiness, problem ledger и logs.
3. Классифицировать blocker.
4. Применить минимальное исправление.
5. Повторить тот же profile.
6. Увеличивать цену профиля только после очистки дешёвых сигналов.

```bash
python -B tools/devbootstrap.py self-check --no-write-report
python -B tools/devbootstrap.py release-gates --dry-run
python -B tools/devbootstrap.py release-gates --profile diagnostic --prepare-deps
python -B tools/devbootstrap.py release-gates --managed-test-db --managed-runtime --prepare-deps
python -B tools/devbootstrap.py release-gates --profile full-local-release
```

## Реестры

| Реестр | Назначение |
|---|---|
| Problem | `REL-*`, owner, severity, evidence, probe |
| Probe | Что проверялось и с какими side effects |
| Decision | Исправить, принять, отложить, разделить |
| Regression memory | Повторяющиеся семейства между runs |

## Метрики

- Release Confidence Score;
- Unknown Ratio;
- Reproducibility Index;
- Classification Coverage;
- Remediation Closure Rate;
- Artifact Quality.

## Фазы

| Фаза | Результат |
|---|---|
| 0 | Governance, scorecard, side effects |
| 1 | Bundle contract, fingerprint, redaction, completeness |
| 2 | Машиночитаемые ledgers |
| 3 | Diagnostic provocation matrix |
| 4 | Controlled mutators |
| 5 | Repeatability loop |
| 6 | Автоматический confidence gate |
| 7 | Regression memory |

Все фазы реализованы в текущем devbootstrap. Следующая работа должна улучшать
конкретный слабый сигнал, а не добавлять фазу 8 без причины.

## Готовность программы

- release gates запускаются из чистого workspace;
- side effects документированы;
- DB/runtime изолированы;
- red signals классифицированы;
- generated files не попадают в source;
- bundle достаточно мал и полон для диагностики;
- обязательный UI path не зависит от Playwright downloads.

