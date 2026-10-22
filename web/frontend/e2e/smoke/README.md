# Browser smoke-сценарии

Минимальные browser smoke сценарии MVP.

Текущее правило:
- мало сценариев;
- только critical flow;
- предпочтительно mocked API для детерминированности;
- pageerror считается smoke-failure.


## Путь с настоящим backend

`auth-and-workspaces.smoke.spec.ts` намеренно использует Playwright
`page.route` mocks и проверяет только детерминированный
boot/auth/workspace-rendering. Он не доказывает работу с настоящим backend.

Отдельный no-mock путь находится в `smoke/real-backend.smoke.spec.ts`:

```bash
npm run test:browser:real-backend
```

В `devbootstrap release-gates` он включается через
`--include-real-backend-browser` и требует безопасной БД через
`TEST_DATABASE_URL` либо осознанный `--allow-dev-db-write`.

Основным обязательным доказательством теперь считается custom UIX
real-backend flow; Playwright-путь остаётся дополнительным.

## Окно карточки и опрос узла

`card-form-polling.smoke.spec.ts` (mocked API) проверяет, что выставленный, но
ещё не сохранённый приоритет переживает опрос списка карточек, когда на доске
меняется другая карточка, а правка названия с другого устройства попадает в
нетронутое поле. Запуск: `npx playwright test e2e/smoke/card-form-polling.smoke.spec.ts`.

## Очистка колонки

`clear-column.smoke.spec.ts` (mocked API): кнопка «Удалить все карточки колонки»
спрашивает подтверждение, после «Отмены» ничего не удаляет, после согласия удаляет
карточки только этой колонки (архивные тоже) обычным `DELETE /cards/{id}?scope=all_devices`
и не трогает соседнюю колонку. Запуск: `npx playwright test e2e/smoke/clear-column.smoke.spec.ts`.
