"""L5: get.py, самообновление checkout и doctor. Без сети: origin — локальный bare-репозиторий.

    cd launcher && python -B -m unittest discover -s tests
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAUNCHER))

import get  # noqa: E402
from launcher_app import doctor, entry as entries, paths, remote, selfupdate  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "нужен git")
class SelfUpdateGitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.work = self.tmp / "work"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.work))
        (self.work / "ecosystem.json").write_text("{}", encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", "первый")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.user = self.tmp / "user"
        git(self.tmp, "clone", "-q", str(self.origin), str(self.user))
        (self.work / "ecosystem.json").write_text('{"v": 2}', encoding="utf-8")
        git(self.work, "commit", "-qam", "launcher: второй")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self.lines: list[str] = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_then_fast_forward(self):
        self.assertEqual(selfupdate.update(self.user, "main", True, self.lines.append), 0)
        self.assertTrue(any("launcher: второй" in line for line in self.lines))
        self.assertEqual(json.loads((self.user / "ecosystem.json").read_text(encoding="utf-8")), {})
        self.assertEqual(selfupdate.update(self.user, "main", False, self.lines.append), 0)
        self.assertEqual(selfupdate.revision(self.user), git(self.work, "rev-parse", "HEAD"))

    def test_dirty_checkout_is_left_alone(self):
        (self.user / "ecosystem.json").write_text('{"mine": 1}', encoding="utf-8")
        self.assertEqual(selfupdate.update(self.user, "main", False, self.lines.append), 2)
        self.assertEqual(json.loads((self.user / "ecosystem.json").read_text(encoding="utf-8")), {"mine": 1})

    def test_local_commits_are_not_merged(self):
        (self.user / "note.txt").write_text("x", encoding="utf-8")
        git(self.user, "add", "-A")
        git(self.user, "commit", "-qm", "моё")
        self.assertEqual(selfupdate.update(self.user, "main", False, self.lines.append), 2)
        self.assertTrue(any("не сливает" in line for line in self.lines))

    def test_status_payload_names_revision(self):
        payload = selfupdate.status_payload(self.user, "0.4.0")
        self.assertEqual((payload["component"], payload["installed"], payload["running"]), ("launcher", True, True))
        self.assertEqual(payload["revision"], git(self.user, "rev-parse", "HEAD"))


class ArchiveTest(unittest.TestCase):
    def zip_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, body in {"r-main/ecosystem.json": "{}", "r-main/launcher/launcher.py": "print()",
                               "r-main/web/bootstrap.py": "web", "r-main/abl/README.md": "abl",
                               "r-main/../evil.txt": "x"}.items():
                archive.writestr(name, body)
        return buffer.getvalue()

    def test_extract_only_selected_and_keeps_local_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "web" / ".dev-bootstrap").mkdir(parents=True)
            (target / "web" / ".dev-bootstrap" / "container-stack.json").write_text("state", encoding="utf-8")
            count = get.extract_archive(self.zip_bytes(), target, ["web"])
            self.assertEqual(count, 3)
            self.assertTrue((target / "launcher" / "launcher.py").is_file())
            self.assertFalse((target / "abl").exists())
            self.assertEqual((target / "web" / ".dev-bootstrap" / "container-stack.json").read_text(encoding="utf-8"), "state")
            self.assertFalse((target.parent / "evil.txt").exists())

    def test_get_refuses_foreign_non_empty_dir_and_unknown_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.txt").write_text("чужое", encoding="utf-8")
            self.assertEqual(get.main(["--dir", tmp, "--no-gui"]), 2)
            self.assertEqual(get.main(["--dir", tmp, "--only", "ios"]), 2)


class LauncherEntryTest(unittest.TestCase):
    def test_launcher_declares_itself(self):
        root = LAUNCHER.parent
        if not (root / "ecosystem.json").is_file():
            self.skipTest("лаунчер взят без корня экосистемы")
        info = entries.load(root, "launcher")
        self.assertTrue(info["available"], info["error"])
        done = subprocess.run([sys.executable, "-B", "launcher.py", "self-status", "--json"], cwd=LAUNCHER,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        parsed = entries.parse_status(info["entry"], done.returncode, done.stdout)
        self.assertEqual(parsed["state"], "running")


class DoctorTest(unittest.TestCase):
    def test_collect_offline_without_status_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["P2PKANBAN_LAUNCHER_HOME"] = tmp
            try:
                def fetch(url):
                    raise remote.RemoteError(f"GitHub ответил 404 на {url}")
                report = doctor.collect(fetch=fetch, offline=True, status_run=None)
                path = doctor.save(report)
                self.assertTrue(path.is_file())
                self.assertTrue(str(path).startswith(tmp))
            finally:
                del os.environ["P2PKANBAN_LAUNCHER_HOME"]
        self.assertEqual(report["schema"], doctor.SCHEMA)
        self.assertEqual(report["network"], [])
        self.assertIn("python3.11", [item["id"] for item in report["requires"]])
        self.assertTrue(all(isinstance(value, bool) for value in report["tokens"].values()))
        self.assertTrue(doctor.summary(report)[0].startswith("Лаунчер"))


if __name__ == "__main__":
    unittest.main()
