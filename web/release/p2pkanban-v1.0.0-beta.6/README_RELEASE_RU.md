# p2pKanban v1.0.0-beta.6

## Требования

- Python 3.10+;
- запущенный Docker Desktop или Docker Engine;
- Docker Compose v2;
- интернет и свободное место для первой сборки.

Rust, Node.js, PostgreSQL и ручной `.env` на компьютере не нужны.

## Запуск

```bash
python bootstrap.py
```

На Windows можно использовать:

```powershell
py bootstrap.py
```

Для доступа из доверенной локальной сети:

```bash
python bootstrap.py start --listen lan
```

LAN-режим использует HTTP. Не публикуйте этот порт напрямую в интернет.

## Управление

```bash
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py stop
python bootstrap.py update
python bootstrap.py rollback
```

`stop` сохраняет данные. `update` и `rollback` создают PostgreSQL backup перед
переключением кода.

Полный сброс удаляет БД и секреты:

```bash
python bootstrap.py reset --yes
```

Используйте reset только для данных, которые точно больше не нужны.
