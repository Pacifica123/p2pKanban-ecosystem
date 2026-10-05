# Стратегия тестирования v1

## Цель

Доказать, что основной пользовательский путь работает на реальном backend, а
ошибки окружения не маскируются под ошибки продукта.

## Принципы

- сначала самая дешёвая проверка, способная поймать дефект;
- тестовая БД отделена от пользовательской;
- повторный smoke обязан быть идемпотентным;
- generated evidence не хранится как исходный код;
- пропущенная обязательная зависимость — отдельный результат, а не успех;
- релизный артефакт проверяется после сборки, а не только по исходникам.

## Слои

| Слой | Что проверяет | Основной запуск |
|---|---|---|
| Статика | Форматы, версии, контракты и структура | `tools/check_release_prep.py` |
| Rust unit/integration | Доменные правила, auth, DB и sync | `cargo test --workspace --all-features --all-targets` |
| Frontend unit/integration | React-состояния и API-контракты | `npm run test:run` |
| Backend smoke | Живой HTTP API и PostgreSQL | `backend/tests/smoke_core_api.py` |
| UIX mocked | Критический UI-путь без backend | custom UI/UX Evidence Runner |
| UIX real backend | Настоящий продуктовый путь | managed runtime gate |
| Bootstrap | Compose, секреты, порты и lifecycle | `tools/check_zero_config_bootstrap.py` |
| Артефакт | Поведение распакованного release ZIP | ручной/автоматизированный clean-machine smoke |

## Обязательные доказательства beta.3

Перед публикацией:

```bash
python -B tools/check_release_prep.py
python -B tools/check_zero_config_bootstrap.py --frontend-build
python -B tools/devbootstrap.py release-gates --profile full-local-release
```

После сборки:

- распаковать ZIP в чистый каталог;
- запустить `python bootstrap.py`;
- пройти registration → workspace → board → column → card;
- остановить и запустить снова;
- проверить сохранение данных;
- выполнить это минимум на Windows и Linux.

## UI/UX направление

Playwright остаётся необязательным переходным покрытием. Основной путь —
лёгкий UI/UX Evidence Runner через CDP, который умеет:

- находить доступный Chromium;
- запускать mock и real-backend сценарии;
- собирать screenshot, DOM markers, console и network evidence;
- классифицировать отказ по понятной категории.

Это не отменяет unit-тесты и backend smoke.

## Fixtures и безопасность

- маленькие устойчивые fixtures хранятся в Git;
- реальные токены, пароли и пользовательские данные запрещены;
- DB-writing тесты требуют managed test DB или явный `TEST_DATABASE_URL`;
- тест не должен удалять неизвестную БД или чужие Docker volumes;
- полный reset проверяется только на специально созданных тестовых данных.

## Частота

| Когда | Минимум |
|---|---|
| Малый патч | Затронутые unit/static checks |
| Изменение API/DB | Cargo tests + backend smoke |
| Изменение UI | Frontend tests + соответствующий UIX-сценарий |
| Изменение bootstrap | Bootstrap self-check + Compose config + чистый запуск |
| Release candidate | Полный профиль + smoke собранного артефакта |

## Запрещённые упрощения

- считать успешную компиляцию доказательством работы продукта;
- отмечать skipped обязательный gate как pass;
- запускать destructive тест против обычной dev-БД;
- считать mock UIX заменой real-backend пути;
- публиковать ZIP, который никто не запускал после распаковки.

