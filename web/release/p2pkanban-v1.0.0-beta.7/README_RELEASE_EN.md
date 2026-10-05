# p2pKanban v1.0.0-beta.7

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

## Link a second web node

The same email on two independent installations does not link accounts. Update
both nodes to beta.7. On a clean second node, choose “Link from another node”
and enter the primary node's LAN URL, email, and password.

If a disposable duplicate was already registered on the second node, verify
that it has no unique data, then reset only that local stack:

```bash
python bootstrap.py reset --yes
```

## Lifecycle

```bash
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py stop
python bootstrap.py update
python bootstrap.py rollback
```

`stop` preserves data. `update` and `rollback` create a PostgreSQL backup
before switching application code. A full reset removes the selected stack's
database and generated secrets.
