#!/usr/bin/env python3
"""web/launcher.json и `bootstrap.py status --json` (p2p-kanban-launcher-entry/1) без Docker."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import container_bootstrap as bootstrap  # noqa: E402

WEB = Path(__file__).resolve().parents[1]
ENTRY = json.loads((WEB / "launcher.json").read_text(encoding="utf-8"))
REVISION = "9db706cb0abf" + "0" * 28


class LauncherEntryTests(unittest.TestCase):
    def test_entry_declares_only_bootstrap_commands_that_exist(self) -> None:
        self.assertEqual(ENTRY["schema"], "p2p-kanban-launcher-entry/1")
        self.assertEqual(ENTRY["component"], "web")
        parser = bootstrap.build_parser()
        for action in ENTRY["actions"]:
            self.assertEqual(action["argv"][:2], ["{python}", "bootstrap.py"], action["id"])
            argv = action["argv"][2:]
            for option in action.get("options", []):
                argv += [part.replace("{value}", "8091" if option["setting"] == "port" else "lan") for part in option["argv"]]
            for extra in ([], action.get("dryRun", [])):
                parsed = parser.parse_args(argv + list(extra))
                self.assertTrue(hasattr(parsed, "func"), action["id"])

    def test_status_is_declared_as_status_output(self) -> None:
        status = next(a for a in ENTRY["actions"] if a["id"] == "status")
        self.assertEqual(status["output"], "status")
        self.assertIn("--json", status["argv"])

    def test_second_node_is_honestly_unsupported(self) -> None:
        profiles = {p["id"]: p for p in ENTRY["profiles"]}
        self.assertFalse(profiles["second-node"]["supported"])
        self.assertIn(bootstrap.COMPOSE_PROJECT, profiles["second-node"]["reason"])
        self.assertTrue(profiles["same-node-port"]["supported"])


class StatusJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())

    def write_state(self, **fields) -> None:
        state = {"webPort": 8082, "bindAddress": "0.0.0.0", "status": "running", "appVersion": "2.1.0",
                 "activeRevision": REVISION}
        state.update(fields)
        bootstrap.write_state(self.root, state)

    def test_not_installed(self) -> None:
        value = bootstrap.launcher_status_payload(self.root)
        self.assertEqual((value["installed"], value["running"], value["url"]), (False, False, None))

    def test_running_node(self) -> None:
        self.write_state()
        with mock.patch.object(bootstrap, "http_ready", return_value=True):
            value = bootstrap.launcher_status_payload(self.root)
        self.assertEqual(value["running"], True)
        self.assertEqual(value["url"], "http://127.0.0.1:8082")
        self.assertEqual(value["values"], {"port": 8082, "listen": "lan"})
        self.assertEqual(value["revision"], REVISION)

    def test_docker_down_is_unknown_not_an_error(self) -> None:
        self.write_state(activeRevision="local-fingerprint")
        with (
            mock.patch.object(bootstrap, "http_ready", return_value=False),
            mock.patch.object(bootstrap.shutil, "which", return_value=None),
        ):
            value = bootstrap.launcher_status_payload(self.root)
        self.assertIsNone(value["running"])
        self.assertIsNone(value["revision"])
        self.assertIn("Docker не найден", value["problems"][0])

    def test_stopped_node(self) -> None:
        self.write_state(status="stopped")
        with (
            mock.patch.object(bootstrap, "http_ready", return_value=False),
            mock.patch.object(bootstrap, "ensure_docker_ready", return_value=None),
        ):
            value = bootstrap.launcher_status_payload(self.root)
        self.assertEqual((value["running"], value["detail"]), (False, "узел остановлен"))

    def test_cli_prints_one_json_object(self) -> None:
        # Как его вызывает лаунчер: из каталога web/, stdout — ровно один JSON-объект.
        done = subprocess.run(
            [sys.executable, "-B", "bootstrap.py", "status", "--json"],
            cwd=WEB, capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        value = json.loads(done.stdout)
        self.assertEqual((value["schema"], value["component"]), ("p2p-kanban-launcher-status/1", "web"))
        self.assertIn(value["running"], (True, False, None))

if __name__ == "__main__":
    unittest.main()
