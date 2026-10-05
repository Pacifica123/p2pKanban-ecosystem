# p2pKanban v1.0.0-beta.6

## Requirements

- Python 3.10+;
- a running Docker Desktop or Docker Engine;
- Docker Compose v2;
- internet access and enough free space for the first build.

Host Rust, Node.js, PostgreSQL, and a handwritten `.env` are not required.

## Start

```bash
python bootstrap.py
```

On Windows, you can use:

```powershell
py bootstrap.py
```

For a trusted local network:

```bash
python bootstrap.py start --listen lan
```

LAN mode uses plain HTTP. Do not expose this port directly to the internet.

## Lifecycle

```bash
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py stop
python bootstrap.py update
python bootstrap.py rollback
```

`stop` preserves data. `update` and `rollback` create a PostgreSQL backup
before switching application code.

A full reset removes the database and secrets:

```bash
python bootstrap.py reset --yes
```

Only use reset for data you no longer need.
