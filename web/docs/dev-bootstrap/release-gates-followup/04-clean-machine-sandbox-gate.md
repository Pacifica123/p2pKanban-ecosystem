# Proposal: clean-machine sandbox gate as a stronger release signal

## Источник анализа

Документ построен по результатам архива `20260524_200616_release-gates.zip` для запуска `20260524_200616_release-gates`.

Фактический итог прогона:

- overall: `infra_failed`;
- classification: `release_gates_infra_failed`;
- `self_check` и `diagnose` прошли;
- `cargo test` завершился кодом `0`, но release-gates классифицировал его как `partial_pass / critical_tests_ignored`, потому что DB-зависимые Rust-тесты были `ignored`;
- `cargo test -- --include-ignored` был пропущен из-за отсутствия `TEST_DATABASE_URL` и безопасного DB-target;
- два Python smoke-прогона были пропущены защитой от записи в live/dev DB;
- `npm run build`, `npm run test:run`, `npm run test:browser` не стартовали из-за отсутствующего `frontend/node_modules`;
- `npm run test:browser:real-backend` был пропущен, потому что write-capable real-backend gate требует явного opt-in и безопасной DB;
- docs gates прошли, clean-machine quickstart был optional и не запускался.

Ключевой вывод: этот прогон не доказал regression в продуктовой логике backend/frontend. Он доказал, что release-gates пока слишком часто останавливается на подготовке окружения и ручных prerequisite-действиях.

## Смелая идея

`clean-machine quickstart` не должен оставаться только optional smoke-флажком «когда-нибудь потом». Для release review нужен sandbox gate, который берет текущий проект в чистую временную папку, применяет минимальный quickstart path и доказывает, что архив проекта действительно разворачивается на машине без накопленного локального состояния.

## Почему это нужно

Текущий прогон показал типичную ловушку локальной разработки: часть состояния уже есть в машине (`backend` и `postgres` порты открыты), часть отсутствует (`frontend/node_modules`), часть не доказана (`TEST_DATABASE_URL`). Такой mixed state плохо отвечает на вопрос: «сможет ли другой человек развернуть это из архива?»

Clean-machine sandbox должен ловить именно такие проблемы:

- забытые generated files;
- скрытую зависимость от уже запущенного backend;
- отсутствие `node_modules` при неверно описанном prepare flow;
- неполные env examples;
- migration/build drift;
- документация обещает команду, которая на чистом workspace не работает.

## Целевой UX

Быстрый optional режим остается:

```bash
python tools/devbootstrap.py release-gates --include-clean-machine
```

Но должен появиться более сильный профиль:

```bash
python tools/devbootstrap.py release-gates --profile clean-machine
```

И в полном local release:

```bash
python tools/devbootstrap.py release-gates --profile full-local-release
```

`full-local-release` может включать clean-machine sandbox как last gate, но не обязан делать тяжелые browser downloads без explicit флага.

## Что такое clean-machine sandbox

Это не полноценная VM и не контейнер с установкой OS. Это воспроизводимая временная копия проекта:

```text
/tmp/devbootstrap-clean-machine-<run-id>/project
```

Внутри нее:

1. Нет `.dev-bootstrap/state.json` из основной рабочей папки.
2. Нет `node_modules`, `target`, `dist`, `build`.
3. Есть только project files, которые попадут в release/post archive.
4. Команды запускаются из sandbox, а не из исходного workspace.
5. Все generated state остается в sandbox и удаляется/сохраняется по policy.

## Алгоритм

1. Создать временный workspace.
2. Скопировать проект с теми же archive exclusions, что использует devctl/devbootstrap.
3. Проверить required files:
   - `backend/Cargo.toml`;
   - `backend/build.rs`;
   - `backend/migrations`;
   - `frontend/package.json`;
   - `frontend/package-lock.json`;
   - `docker-compose.dev.yml`;
   - docs startup commands.
4. Запустить:
   - `python tools/devbootstrap.py self-check`;
   - `python tools/devbootstrap.py diagnose`;
   - `python tools/devbootstrap.py prepare-env --dry-run` или safe prepare;
   - `python tools/devbootstrap.py up --dry-run`;
   - optional `prepare-deps`;
   - optional `managed-test-db` checks.
5. Сохранить sandbox report в основной release-gates bundle.
6. По retention policy удалить или сохранить sandbox.

## Варианты строгости

| Profile | Что проверяет | Стоимость |
|---|---|---|
| `clean-machine-dry` | Файлы, self-check, diagnose, план запуска | Низкая |
| `clean-machine-deps` | Дополнительно `npm ci`, cargo metadata/fetch | Средняя |
| `clean-machine-runtime` | Дополнительно managed runtime smoke | Высокая |

Рекомендуемый default для `--include-clean-machine`: `clean-machine-dry`.

## Почему не VM

VM/контейнер был бы чище, но дороже и сложнее:

- нужен Docker/Podman/WSL;
- сильнее различия Windows/Linux;
- больше download/build времени;
- выше риск, что bootstrapper сам станет deployment-системой.

Sandbox-копия — хороший промежуточный слой: она ловит большинство ошибок архива и hidden local state, не требуя полноценной новой машины.

## Риски и смягчения

| Риск | Последствие | Смягчение |
|---|---|---|
| Копия слишком большая | Медленный gate | Использовать единый exclusion policy, не копировать target/node_modules/release payloads |
| Sandbox использует те же порты | Конфликт с текущим workspace | Dynamic ports в managed runtime |
| Sandbox случайно пишет в основную DB | Опасность данных | Managed test DB или explicit TEST_DATABASE_URL only |
| Разные OS behave differently | Ложная уверенность | В report писать platform; Windows/Linux оба нужны как отдельные human/CI runs |
| Gate тяжелый | Пользователь избегает его | Profiles: dry/deps/runtime |

## Что хранить в bundle

```text
logs/clean-machine/report.md
logs/clean-machine/clean-machine.json
logs/clean-machine/file-list.txt
logs/clean-machine/exclusions.txt
logs/clean-machine/commands.log
```

Если sandbox сохранен:

```text
Sandbox kept: /tmp/devbootstrap-clean-machine-...
Reason: clean-machine failed at prepare-deps
Cleanup: rm -rf /tmp/devbootstrap-clean-machine-...
```

## Связь с devctl

Это особенно важно для patch conveyor:

- devctl создает post archive;
- clean-machine sandbox может проверять, что post archive применим и разворачиваем;
- future gate может брать именно archive output, а не рабочую папку, чтобы исключить hidden files.

Такой gate отвечает на вопрос: «если пользователь получит архив после патча, сможет ли он стартовать по README?»

## Этапы реализации

### Phase A: dry sandbox

- Создать временную копию с exclusion policy.
- Запустить self-check/diagnose/up dry-run.

### Phase B: dependency sandbox

- Добавить optional prepare-deps.
- Проверить frontend build/test prerequisites without using original node_modules.

### Phase C: runtime sandbox

- Добавить managed DB/runtime и smoke.
- Сохранять sandbox only on failure.

## Definition of done

- Clean-machine gate не зависит от `.dev-bootstrap/state.json` основной папки.
- Bundle содержит отдельный clean-machine report.
- Sandbox не пишет в dev DB без explicit consent.
- Gate может работать в cheap dry mode и в heavy runtime mode.
