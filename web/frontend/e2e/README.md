# Frontend browser smoke

Здесь живет короткий browser smoke слой на Playwright.

Обычный smoke намеренно остается маленьким, deterministic и mocked. Он проверяет только критичный пользовательский путь:
- boot;
- auth screen;
- sign-in transition;
- workspace list rendering;
- отсутствие white screen / uncaught page errors.

Запуск:

```bash
npm run test:browser
```

Этот npm script запускает только exact-spec:

```bash
playwright test e2e/smoke/auth-and-workspaces.smoke.spec.ts
```

Это важно для `devbootstrap release-gates`: mocked browser smoke не должен случайно запускать сценарии, которые пишут через настоящий backend.

## Real-backend browser path

`auth-and-workspaces.smoke.spec.ts` intentionally uses Playwright `page.route` mocks and only checks deterministic boot/auth/workspace rendering. It does **not** satisfy the release checklist item for a real backend browser path.

The dedicated no-mock path lives in `smoke/real-backend.smoke.spec.ts` and is executed by:

```bash
npm run test:browser:real-backend
```

In `devbootstrap release-gates` this path is opt-in via `--include-real-backend-browser` and also requires write-safe DB permission through `TEST_DATABASE_URL` or `--allow-dev-db-write`.
