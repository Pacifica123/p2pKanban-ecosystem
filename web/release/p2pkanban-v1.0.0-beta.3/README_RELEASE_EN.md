# p2pKanban v1.0.0-beta.3

## Prerequisites

- Python 3.10+;
- a running Docker Desktop or Docker Engine;
- Docker Compose v2;
- enough free space to build the containers and store the database.

Host Rust, Node.js, PostgreSQL, and a handwritten `.env` are not required.

## Start

Open a terminal in the extracted directory and run:

```bash
python bootstrap.py
```

On Windows, this command can be used instead:

```powershell
py bootstrap.py
```

The application opens in a browser when ready. The first run can take a few
minutes while Docker builds the backend and frontend.

## Lifecycle commands

```bash
python bootstrap.py status
python bootstrap.py logs
python bootstrap.py logs --follow
python bootstrap.py stop
```

`stop` preserves the data. A full reset removes the database and secrets:

```bash
python bootstrap.py reset --yes
```

Only use reset when the local data is no longer needed.
