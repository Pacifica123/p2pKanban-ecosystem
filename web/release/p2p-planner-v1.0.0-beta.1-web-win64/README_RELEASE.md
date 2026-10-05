# p2pKanban v1.0.0-beta.1 — исторический Windows web bundle

Это памятка к первому beta-артефакту. Она не описывает текущий способ
развёртывания. Для beta.3 используйте корневой `README.md` и
`python bootstrap.py`.

## Что требовалось beta.1

- Windows x64;
- Docker Desktop для PostgreSQL;
- Node.js для раздачи собранного frontend;
- ручной `backend/.env`;
- отдельный запуск backend и frontend.

## Исторический запуск

PostgreSQL:

```powershell
docker compose -f docker-compose.dev.yml up -d
```

Затем требовалось скопировать `backend/.env.example` в `backend/.env`,
запустить:

```powershell
cd backend
.\p2p-planner-backend.exe
```

и в другом терминале:

```powershell
cd frontend
npx serve -s dist -l 5173
```

Этот путь устарел: beta.3 автоматически создаёт БД, секреты и контейнеры и не
требует ручного `.env`.

## Возможности того релиза

Работали базовые учётные записи, workspace, доски, колонки, карточки,
drag-and-drop, внешний вид и activity/audit.

Local-first, sync, backup/export, метки, чек-листы и комментарии в beta.1 ещё
не входили. Сейчас эти сведения сохраняются только как история развития.

