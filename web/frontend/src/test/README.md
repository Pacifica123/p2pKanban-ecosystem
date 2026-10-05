# Frontend tests

Здесь находится реальный frontend test harness.

Структура:
- `unit/` — быстрые pure tests helpers/components/selectors;
- `integration/` — feature/screen tests поверх Query + Router + mocked fetch;
- `contracts/` — совместимость payload shape с backend/sync contracts;
- `fixtures/` — mocked responses и будущие local-first snapshots;
- `factories/` — builders для test data;
- `setup.ts` — общий test runtime setup;
- `renderWithProviders.tsx` — reusable render helper для feature tests.

Основные команды:

```bash
npm test
npm run test:run
```

Browser smoke остается отдельно в `frontend/e2e/`.
