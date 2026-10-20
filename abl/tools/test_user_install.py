#!/usr/bin/env python3
"""tools/user_install.py и abl/launcher.json без pacman, makepkg и сети: всё внешнее подменено."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import user_install as ui  # noqa: E402

ABL = Path(__file__).resolve().parents[1]
REVISION = "9db706cb0abf" + "0" * 28


def fake_run(answers: dict):
    def run(argv, **_kwargs):
        key = " ".join(argv[:2])
        code, out = answers.get(key, (1, ""))
        return subprocess.CompletedProcess(argv, code, out, "")
    return run


class UserInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.home, "XDG_CACHE_HOME": self.home})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def arch(self, answers: dict):
        return [mock.patch.object(ui, "is_arch", return_value=True), mock.patch.object(ui, "run", side_effect=fake_run(answers)),
                mock.patch.object(ui.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}")]

    def test_status_off_arch_is_honest(self) -> None:
        with mock.patch.object(ui, "is_arch", return_value=False):
            value = ui.status_payload()
        self.assertEqual((value["installed"], value["running"]), (False, None))

    def test_status_not_installed_names_missing_build_packages(self) -> None:
        patches = self.arch({"pacman -Q": (1, ""), "pacman -T": (127, "cargo\nnpm\n")})
        with patches[0], patches[1], patches[2]:
            value = ui.status_payload()
        self.assertFalse(value["installed"])
        self.assertIn("cargo npm", value["problems"][0])

    def test_status_reports_revision_only_for_its_own_install(self) -> None:
        patches = self.arch({"pacman -Q": (0, "p2pkanban 0.1.0-1\n"), "pgrep -x": (0, "123\n")})
        with patches[0], patches[1], patches[2]:
            foreign = ui.status_payload()
            ui.write_state({"version": "0.1.0-1", "revision": REVISION})
            own = ui.status_payload()
        self.assertEqual((foreign["installed"], foreign["revision"]), (True, None))
        self.assertEqual((own["revision"], own["running"], own["version"]), (REVISION, True, "0.1.0-1"))

    def test_dry_run_plans_without_building(self) -> None:
        patches = self.arch({"pacman -Q": (1, ""), "pacman -T": (0, ""), "git rev-parse": (0, REVISION + "\n"),
                             "git status": (0, "")})
        out = io.StringIO()
        with patches[0], patches[1], patches[2], mock.patch.object(ui.os, "geteuid", return_value=1000), \
                mock.patch.object(ui.subprocess, "call") as call, redirect_stdout(out):
            code = ui.main(["install", "--dry-run"])
        self.assertEqual(code, 0)
        call.assert_not_called()
        self.assertIn("makepkg --nocheck", out.getvalue())
        self.assertIn(REVISION[:12], out.getvalue())

    def test_update_skips_when_installed_from_same_checkout(self) -> None:
        ui.write_state({"version": "0.1.0-1", "revision": REVISION})
        patches = self.arch({"pacman -Q": (0, "p2pkanban 0.1.0-1\n"), "git rev-parse": (0, REVISION + "\n"),
                             "git status": (0, "")})
        out = io.StringIO()
        with patches[0], patches[1], patches[2], mock.patch.object(ui.os, "geteuid", return_value=1000), redirect_stdout(out):
            code = ui.main(["update"])
        self.assertEqual(code, 0)
        self.assertIn("обновлять нечего", out.getvalue())


class LauncherEntryTests(unittest.TestCase):
    def test_entry_points_to_this_tool_and_status_is_json(self) -> None:
        entry = json.loads((ABL / "launcher.json").read_text(encoding="utf-8"))
        self.assertEqual((entry["schema"], entry["component"]), ("p2p-kanban-launcher-entry/1", "abl"))
        for action in entry["actions"]:
            self.assertEqual(action["argv"][:2], ["{python}", "tools/user_install.py"], action["id"])
        done = subprocess.run([sys.executable, "-B", "tools/user_install.py", "status", "--json"], cwd=ABL,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["schema"], "p2p-kanban-launcher-status/1")


if __name__ == "__main__":
    unittest.main()
