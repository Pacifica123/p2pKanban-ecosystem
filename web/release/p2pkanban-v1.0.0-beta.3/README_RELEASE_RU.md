# p2pKanban v1.0.0-beta.3

## Что нужно заранее

- Python 3.10+;
- запущенный Docker Desktop или Docker Engine;
- Docker Compose v2;
- свободное место для сборки контейнеров и базы.

Rust, Node.js, PostgreSQL и `.env` на компьютере не нужны.

## Запуск

Откройте терминал в распакованном каталоге и выполните:

```bash
python bootstrap.py
```

На Windows можно использовать:

```powershell
py bootstrap.py
```

После готовности приложение откроется в браузере. Первый запуск может занять
несколько минут, потому что Docker собирает backend и frontend.

## Управление

```bash
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py logs --follow
python bootstrap.py stop
```

`stop` сохраняет данные. Полный сброс удаляет БД и секреты:

```bash
python bootstrap.py reset --yes
```

Используйте сброс только тогда, когда данные точно больше не нужны.
