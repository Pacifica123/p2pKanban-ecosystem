# Оценка уверенности в релизе v1

Политика считается автоматически фазой 6 и дополняется памятью регрессий
фазы 7. Текущие значения находятся в `release-confidence-gate.json/md`, а этот
документ фиксирует правила.

## Категории

| Балл | Категория | Решение |
|---:|---|---|
| `< 50` | `diagnostic_chaos` | Релиз запрещён |
| `50–69` | `partial_signal` | Сначала blockers |
| `70–84` | `internal_candidate` | Внутреннее тестирование |
| `85–94` | `beta_candidate` | Ограниченная внешняя beta с limitations |
| `95+` | `stable_release_loop` | Возможен стабильный ритм |

## Блоки

| Блок | Вес |
|---|---:|
| Полнота evidence | 15 |
| Реально выполненные gates | 20 |
| Повторяемость | 15 |
| Безопасная изоляция | 15 |
| Windows/Linux уверенность | 10 |
| Реальный продуктовый путь | 15 |
| Зрелость remediation | 5 |
| Качество bundle | 5 |

```text
score = evidence + gates + repeatability + isolation
      + cross_platform + product_path + remediation + artifact_quality
```

## Жёсткие ограничения

| Условие | Максимальная категория |
|---|---|
| Неизвестный релизный blocker | `partial_signal` |
| Обязательный gate пропущен из-за prerequisites | `partial_signal` |
| Нет двух сравнимых прогонов | `internal_candidate` |
| Нет real-backend UIX/product path | `internal_candidate` |
| Bundle неполон или не прошёл redaction | `partial_signal` |
| Код изменён без релевантной проверки | `partial_signal` |
| Dry-run | `partial_signal` |

Высокий балл не отменяет активный hard cap.

## Метрики

```text
unknown_ratio =
  unknown_or_skipped_required_gates / all_required_gates

reproducibility_index =
  passed_repeatability_scenarios / total_repeatability_scenarios
```

Real-backend cap снимает успешный
`frontend_uiux_real_backend_core_flow` на managed DB/runtime либо равносильное
документированное доказательство. Mocked UIX сам по себе недостаточен.

## Историческая точка 2026-06-04

```text
Target: v1.0.0-beta.2
Profile: full-local-release
Overall: ok
Score: 89/100
Raw class: beta_candidate
Effective class: internal_candidate
Active cap: repeatability-not-proven
Unknown ratio: 0.0
```

Этот прогон подтвердил основной продуктовый путь, но относится к состоянию до
transport foundation и zero-config bootstrap. Для beta.3 нужен новый score и
artifact smoke.

## Вопросы reviewer

1. Каким файлом доказан каждый ненулевой балл?
2. Какие skips считаются unknown?
3. Какой real-backend путь реально прошёл?
4. Какие экспериментальные части исключены из оценки?
5. Какие `REL-*` изменили статус?
6. Почему категория изменилась?
7. Есть ли повторяющееся семейство проблем, требующее изменения процесса?

