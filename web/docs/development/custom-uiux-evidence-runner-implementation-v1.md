# Реализация UI/UX Evidence Runner v1

## Реализовано

- поиск системного Chromium/Chrome/Edge;
- запуск отдельного browser profile;
- CDP WebSocket client на стандартной библиотеке Python;
- boot scenario;
- mocked core flow;
- real-backend core flow;
- screenshots, DOM, console и network evidence;
- интеграция с devbootstrap release gates;
- redaction чувствительных заголовков и значений;
- очистка owned process/profile.

## Сценарии

Файлы:

```text
tools/uiux/scenarios/boot.json
tools/uiux/scenarios/mocked-core-flow.json
tools/uiux/scenarios/real-backend-core-flow.json
```

Frontend предоставляет устойчивые markers, чтобы runner не зависел от текста,
случайных CSS-классов и координат.

## Поведение окружения

- отсутствие браузера → infrastructure result;
- frontend недоступен → runtime result;
- fatal console → UI runtime failure;
- неправильный network contract → contract failure;
- backend недоступен в real flow → backend/runtime result.

Runner не скачивает браузер автоматически.

## Не входит

- полная замена всех frontend unit tests;
- visual regression по пикселям;
- mobile WebView;
- удалённая browser farm;
- произвольный general-purpose automation DSL.

## Следующее усиление

- стабилизировать CDP input на разных Chromium;
- расширять console classification только по реальным сбоям;
- сохранять regression memory по scenario ID;
- удалить обязательные ссылки на Playwright после ещё одного повторяемого
  full release run.

## Релизное значение

Принятый прогон 2026-06-04 доказал mocked и real-backend core flow. Для
beta.3 runner должен быть выполнен снова, потому что transport/bootstrap и
релизная упаковка изменились после этой точки.

