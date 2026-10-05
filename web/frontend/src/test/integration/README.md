# Интеграционные тесты frontend

Здесь проверяются связи между React-компонентами, состоянием, API adapter и
локальным хранилищем. Основные цели:

- WorkspacesPage;
- WorkspaceBoardsPage;
- BoardPage;
- CardDetailsDrawer;
- appearance pages;
- auth/session bootstrap;
- loading/empty/error/retry и local-first pending/failed states.

Интеграционный тест не должен заменять browser/UIX smoke, но обязан ловить
ошибки склейки компонентов дешевле полного запуска браузера.
