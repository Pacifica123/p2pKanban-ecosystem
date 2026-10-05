#!/usr/bin/env python3
"""Offline regressions for field failure diagnosis and retained build output."""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import container_bootstrap as bootstrap


class PortableStartupTests(unittest.TestCase):
    def test_migration_report_distinguishes_exact_line_endings_from_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / 'backend/migrations'
            migrations.mkdir(parents=True)
            lf = b'SELECT 1;\nSELECT 2;'
            (migrations / '0001_example.sql').write_bytes(lf.replace(b'\n', b'\r\n'))
            for sql, status in [(lf, 'LF'), (lf.replace(b'\n', b'\r\n'), 'CRLF-compatible'), (b'SELECT 3;', 'unknown')]:
                digest = hashlib.sha384(sql).hexdigest()
                result = bootstrap.migration_checksum_report(root, f'1|t|{digest}\n')
                self.assertEqual(result[0]['status'], status)
            self.assertEqual(bootstrap.migration_checksum_report(root, '1|f|00')[0]['status'], 'dirty')
            self.assertEqual(bootstrap.migration_checksum_report(root, '999|t|00')[0]['status'], 'missing-source')

    def test_build_failure_survives_without_any_docker_containers(self):
        with tempfile.TemporaryDirectory(prefix='p2pkanban Тест & ') as directory:
            root = Path(directory)
            log = root / 'logs/build.log'
            command = [sys.executable, '-c', "import sys; print('npm error Exit handler never called!', file=sys.stderr); sys.exit(7)"]
            with redirect_stdout(io.StringIO()):
                result = bootstrap.run_logged(command, cwd=root, env=os.environ.copy(), log_path=log)
            self.assertEqual(result.returncode, 7)
            self.assertIn('Exit handler never called!', log.read_text())
            self.assertIn('exit: 7', log.read_text())

    def test_diagnostic_masks_password_and_authorization(self):
        text = 'postgres://user:secret@postgres/db https://u:p@proxy Authorization: Bearer abc _authToken=xyz'
        output = bootstrap.redact_diagnostic(text)
        for secret in ['user:secret', 'u:p', 'abc', 'xyz']:
            self.assertNotIn(secret, output)

    def test_windows_console_codepage_does_not_drop_the_build_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream = io.BytesIO()
            console = io.TextIOWrapper(stream, encoding='cp1251')
            command = [sys.executable, '-c', "import sys; sys.stdout.buffer.write('Docker ✔ готов\\n'.encode('utf-8'))"]
            with redirect_stdout(console):
                result = bootstrap.run_logged(command, cwd=root, env=os.environ.copy(), log_path=root / 'build.log')
            self.assertEqual(result.returncode, 0)
            self.assertIn('✔', (root / 'build.log').read_text(encoding='utf-8'))
            console.flush()
            self.assertIn('готов', stream.getvalue().decode('cp1251'))

    def test_loopback_health_ignores_machine_proxy(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(bootstrap.urllib.request, 'build_opener', return_value=opener), \
             mock.patch.object(bootstrap.urllib.request, 'ProxyHandler') as handler:
            self.assertTrue(bootstrap.http_ready('http://127.0.0.1:8080/healthz'))
            handler.assert_called_once_with({})

    def test_utf8_docker_output_does_not_depend_on_windows_locale(self):
        with mock.patch.object(bootstrap.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok')) as run:
            bootstrap.run_capture(['docker', 'version'], cwd=Path.cwd(), env={})
        self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
        self.assertEqual(run.call_args.kwargs['errors'], 'replace')


if __name__ == '__main__':
    unittest.main()
