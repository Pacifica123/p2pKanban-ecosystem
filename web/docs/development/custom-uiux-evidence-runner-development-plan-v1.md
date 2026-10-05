# План UI/UX Evidence Runner v1

- Статус: основные этапы реализованы; документ сжат до контракта

## Обязательный путь v1

Mocked:

1. открыть приложение;
2. пройти auth/workspace/board/card flow;
3. проверить ключевые DOM markers;
4. собрать screenshot, console и network summary.

С настоящим backend:

1. поднять managed test DB и runtime;
2. зарегистрироваться;
3. создать workspace, доску, колонку и карточку;
4. подтвердить результат через UI и API;
5. сохранить evidence.

## Формат результата

Каждый сценарий создаёт:

```text
scenario.json
result.json
summary.md
screenshots/
console.json
network.json
dom.json
```

Результат содержит:

- scenario ID и версию;
- browser/version;
- URLs без секретов;
- список шагов;
- время и статус шага;
- классификацию отказа;
- пути к evidence.

## Архитектура

| Модуль | Ответственность |
|---|---|
| browser discovery | Найти поддерживаемый Chromium |
| launcher | Запустить изолированный профиль и debugging port |
| CDP client | WebSocket/CDP команды и events |
| mock API | Предсказуемые ответы для mocked flow |
| scenario runner | Выполнить ограниченный JSON DSL |
| evidence | Redaction и запись результатов |

## DSL

Достаточные действия:

- `navigate`;
- `waitForMarker`;
- `click`;
- `fill`;
- `press`;
- `assertText`;
- `assertUrl`;
- `screenshot`;
- `apiAssert`.

Сценарии не должны содержать произвольный JavaScript без крайней необходимости.

## Классификация

```text
browser_missing
browser_launch_failed
cdp_failed
frontend_unreachable
app_boot_failed
marker_missing
action_failed
assertion_failed
console_fatal
network_contract_failed
backend_unreachable
cleanup_failed
```

## Release-gates

Основные gates:

- `frontend_uiux_boot`;
- `frontend_uiux_mocked_core_flow`;
- `frontend_uiux_real_backend_core_flow`.

Mocked flow не заменяет real backend. Real-backend flow требует isolated DB,
owned runtime и dynamic ports.

## Безопасность

- отдельный temporary browser profile;
- удаление cookies/storage после run;
- redaction Authorization, cookies, tokens и passwords;
- никаких реальных пользовательских аккаунтов;
- mock server только на loopback;
- screenshot не должен захватывать посторонние окна.

## Кроссплатформенность

Поддерживаются Windows и Linux. Browser discovery проверяет типичные пути,
registry/`PATH` и выдаёт точный список найденного. Отсутствие browser
классифицируется как infra, а не frontend regression.

## Готовность

- mocked и real-backend flow повторяются;
- release bundle содержит полный evidence contract;
- failure имеет одну понятную категорию и команду rerun;
- Playwright не требуется для обязательного профиля;
- runner не оставляет browser processes и временные профили.

