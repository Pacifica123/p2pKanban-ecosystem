# devctl: привязка проекта и подтверждения

Продолжение project-binding/resource/receipt: UUID проекта и компонента, provider `devctl`, область — доска. Locator — метка локального workspace, не исполняемая команда. Привязку создаёт владелец; просматривать могут участники, импортировать — пользователи с правом записи.

1. На доске создать привязку devctl. Экспортировать project.json и сохранить как `.p2pkanban/project.json` в workspace, рядом с `.devctl`.
2. Применить патч обычным локальным devctl. Необязательно добавить в manifest:

```json
{"integrations":{"p2pKanban":{"schemaVersion":1,"projectId":"UUID-ПРОЕКТА","workItems":[{"ref":"card:UUID-КАРТОЧКИ","requestedTransition":"complete"}]}}}
```

3. Преобразовать уже записанные результаты:

```sh
python path/to/kanban/tools/devctl_receipt.py --workspace . --project .p2pkanban/project.json --output receipt.json
```

Необязательный `--patch-id` выбирает run; иначе берётся последний. Поддержаны applied и push_failed после локального commit. Проверяются checksum, commit, архивный manifest и заголовки check-логов. Конвертер не запускает процессы, не обращается в сеть, не перезаписывает выходной файл.

4. Выбрать receipt на доске, проверить preview, явно импортировать. Автоматического завершения/перемещения карточек нет даже при requestedTransition. Это предоставленное пользователем evidence, не подписанное доказательство исполнения доверенным runner.

API `/api/v1/integrations/projects` (GET boardId / POST boardId,name,locator), `/integrations/projects/{projectId}/receipts` (GET/POST), `/receipts/preview` (POST). Обычная аутентификация и проверка доступа. Receipt: schemaVersion=1, UUID receiptId/projectId, patchId, patchSha256 с `sha256:`, result, commit, checks, workItems, appliedAt с часовым поясом. Ссылки card:UUID/checklistItem:UUID проверяются внутри доски; неизвестные поля отклоняются. UI ограничивает файл 256 KiB.

Идентичный повтор возвращает duplicate=true; тот же ID с другим содержимым — 409. Панель показывает последние 100 подтверждений. Привязки и receipts хранятся только на этом узле, не входят в roaming/pairing/portable bundle. Изменять projectId для обхода проверки связи нельзя. Существующий devctl сохраняет управление проверками, commit и push; отдельного сервера исполнения нет.
