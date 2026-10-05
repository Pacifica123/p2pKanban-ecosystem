# Переход к собственному UI/UX Evidence Runner

## Решение

Playwright больше не является обязательной основой release gates. Основное
UI-доказательство собирает проектный runner через доступный системный Chromium
и Chrome DevTools Protocol.

## Почему

Playwright давал полезный API, но добавлял тяжёлое и хрупкое окружение:

- отдельные browser binaries;
- несовпадение revision/cache;
- большие downloads;
- ошибки инфраструктуры, похожие на продуктовые;
- лишний слой Node tooling для простого smoke.

Отказ от обязательности Playwright не означает отказ от проверки браузера.

## Что нужно сохранить

- настоящий DOM и JavaScript runtime;
- screenshots;
- console и network evidence;
- проверку route markers;
- ввод в формы и клики;
- mocked flow;
- real-backend flow;
- понятную классификацию отказа.

## Чего не строим

- новый универсальный Playwright/Selenium;
- собственный браузер;
- пиксельный visual regression framework;
- сложный язык сценариев;
- облачную browser farm.

## Минимальная архитектура

```text
tools/uiux/
  browser_discovery.py
  chrome_launcher.py
  cdp_client.py
  mock_api.py
  scenario_runner.py
  evidence.py
  scenarios/
```

Runner находит Chrome/Chromium/Edge, запускает отдельный профиль, подключается
к CDP, выполняет JSON-сценарий и сохраняет evidence.

## Миграция

1. Сохранить существующие тестируемые продуктовые пути.
2. Добавить устойчивые `data-*` markers.
3. Проверить boot.
4. Проверить mocked core flow.
5. Проверить real-backend core flow.
6. Подключить результаты к release scorecard.
7. Оставить Playwright optional либо удалить после доказанной parity.

## Риски

- различия CDP между браузерами;
- нестабильные координаты и timing;
- слишком широкий DSL;
- утечка токенов в evidence;
- ложный успех при непроверенном backend.

Снижение риска: DOM markers вместо координат, ограниченный scenario contract,
redaction и отдельные mocked/real-backend результаты.

## Готовность

Переход завершён, когда full release profile получает надёжный UI signal без
обязательной загрузки Playwright browsers, а неуспех отвечает, что именно
сломалось: browser, boot, route, action, console, network или product assertion.

