#!/usr/bin/env python3
"""Exercise real SQLx migration recovery using only disposable Docker resources."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    docker = shutil.which('docker')
    if not docker:
        raise SystemExit('Docker is required for the real PostgreSQL migration gate.')
    identifier = 'p2pkanban-migration-test-' + secrets.token_hex(6)
    image = identifier + ':local'
    postgres = identifier + '-postgres'
    runner = identifier + '-runner'
    env = os.environ.copy()
    env['BUILDKIT_PROGRESS'] = 'plain'

    def run(*args, **kwargs):
        return subprocess.run([docker, *args], cwd=ROOT, env=env, check=True, **kwargs)

    try:
        run('build', '-f', 'deploy/bootstrap/migration-tests.Dockerfile', '-t', image, '.', timeout=1800)
        run('network', 'create', identifier, timeout=30)
        # No host ports, no application volumes, no real database credentials.
        run('run', '--detach', '--name', postgres, '--network', identifier,
            '-e', 'POSTGRES_PASSWORD=disposable-migration-test', '-e', 'POSTGRES_DB=portable_test',
            'postgres:16-alpine', timeout=180)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            probe = subprocess.run([docker, 'exec', postgres, 'pg_isready', '-U', 'postgres', '-d', 'portable_test'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready.')
        run('run', '--rm', '--name', runner, '--network', identifier,
            '-e', f'P2PKANBAN_MIGRATION_TEST_DATABASE_URL=postgres://postgres:disposable-migration-test@{postgres}:5432/portable_test',
            image, timeout=180)
        print('OK: CRLF history, pending migrations, concurrent/repeated starts, retained data and mismatch rejection.')
        return 0
    finally:
        # These random names belong only to this gate, including partial failures.
        for args in [('rm', '--force', '--volumes', runner, postgres), ('network', 'rm', identifier), ('image', 'rm', image)]:
            subprocess.run([docker, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__':
    raise SystemExit(main())
