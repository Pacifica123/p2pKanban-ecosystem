"""Сверка копии без git (L5): sha файлов против деревьев main. GitHub подменён ответами из настоящего git.

    cd launcher && python -B -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import get  # noqa: E402
from launcher_app import paths, remote, selfupdate, source, state, view  # noqa: E402

REPO = "o/r"
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
ECOSYSTEM = {"name": "t", "repository": REPO, "branch": "main",
             "components": [{"id": "web", "dir": "web", "platforms": ["linux", "windows", "macos"]},
                            {"id": "abl", "dir": "abl", "platforms": ["linux", "windows", "macos"]}]}
HOST = {"os": "linux", "tags": ["linux"], "label": "Linux"}


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True, text=True,
                          env={**os.environ, **ENV}).stdout


class FakeGitHub:
    """Ответы api.github.com и raw.githubusercontent.com из локального репозитория."""

    def __init__(self, root: Path):
        self.root, self.calls = root, []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == "raw.githubusercontent.com":
            ref, path = parsed.path.split("/", 4)[3:5]
            try:
                return git(self.root, "show", f"{ref}:{path}").encode()
            except subprocess.CalledProcessError as error:
                raise remote.RemoteError(f"GitHub ответил 404 на {url}") from error
        parts = parsed.path.split("/")[4:]
        query = urllib.parse.parse_qs(parsed.query)
        if parts[0] == "commits":
            out = git(self.root, "log", f"-{query['per_page'][0]}", "--format=%H%x00%cI%x00%s", query["sha"][0], "--", query["path"][0])
            return json.dumps([{"sha": sha, "commit": {"committer": {"date": date}, "message": subject}}
                               for sha, date, subject in (line.split("\x00") for line in out.splitlines())]).encode()
        if parts[:2] == ["git", "trees"]:
            recursive = query.get("recursive") == ["1"]
            out = git(self.root, "-c", "core.quotePath=false", "ls-tree", *(["-r"] if recursive else []), parts[2])
            tree = []
            for line in out.splitlines():
                meta, path = line.split("\t", 1)
                mode, kind, sha = meta.split()
                tree.append({"path": path, "mode": mode, "type": kind, "sha": sha})
            return json.dumps({"sha": parts[2], "tree": tree, "truncated": False}).encode()
        if parts[0] == "compare":
            base, head = parts[1].split("...")
            ahead = subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=self.root).returncode == 0
            return json.dumps({"status": "identical" if base == head else "ahead" if ahead else "behind"}).encode()
        raise remote.RemoteError(f"GitHub ответил 404 на {url}")


@unittest.skipUnless(shutil.which("git"), "нужен git")
class ContentVerdictTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "ecosystem.json").write_text(json.dumps(ECOSYSTEM), encoding="utf-8")
        for name in ("web", "abl"):
            (self.repo / name).mkdir()
            (self.repo / name / "app.py").write_text(f"print('{name} 1')\n", encoding="utf-8")
            (self.repo / name / "docs").mkdir()
            (self.repo / name / "docs" / "README.md").write_text("one\ntwo\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "первый")
        self.first = git(self.repo, "rev-parse", "HEAD").strip()
        (self.repo / "web" / "app.py").write_text("print('web 2')\n", encoding="utf-8")
        git(self.repo, "commit", "-qam", "web: второй")
        (self.repo / "web" / "app.py").write_text("print('web 3')\n", encoding="utf-8")
        git(self.repo, "commit", "-qam", "web: третий")
        self.github = FakeGitHub(self.repo)
        os.environ["P2PKANBAN_LAUNCHER_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        os.environ.pop("P2PKANBAN_LAUNCHER_HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def copy(self, ref: str = "main") -> Path:
        """Копия без .git, как «Download ZIP» или копия UTS."""
        target = self.tmp / f"copy-{len(list(self.tmp.iterdir()))}"
        target.mkdir()
        data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=self.repo, check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(target)], input=data, check=True)
        return target

    def rows(self, root: Path) -> dict:
        value = state.build_state(root, remote.GlobalState(self.tmp / "g.json", self.github), host=HOST, status_run=None,
                                  trees=source.Trees(paths.cache_dir() / "trees", self.github))
        self.assertEqual(value["checkout"]["method"], "content")
        return {row["id"]: row for row in value["components"]}

    def test_blob_sha_is_git(self):
        path = self.repo / "web" / "app.py"
        self.assertIn(git(self.repo, "hash-object", str(path)).strip(), source.file_shas(path))

    def test_copy_of_main_is_current(self):
        rows = self.rows(self.copy())
        self.assertEqual(rows["web"]["checkout"]["id"], "current")
        self.assertEqual(rows["abl"]["checkout"]["id"], "current")
        self.assertEqual(rows["web"]["local"]["commit"]["subject"], "web: третий")

    def test_old_copy_says_how_far_behind(self):
        rows = self.rows(self.copy(self.first))
        self.assertEqual(rows["web"]["checkout"]["id"], "outdated")
        self.assertIn("2 коммит", rows["web"]["checkout"]["detail"])
        self.assertEqual(rows["web"]["local"]["commit"]["sha"], self.first)
        self.assertEqual(rows["abl"]["checkout"]["id"], "current")  # abl с тех пор не менялся

    def test_local_edit_lists_files(self):
        root = self.copy()
        (root / "web" / "app.py").write_text("print('мой')\n", encoding="utf-8")
        (root / "web" / "docs" / "README.md").unlink()
        verdict = self.rows(root)["web"]["checkout"]
        self.assertEqual(verdict["id"], "modified")
        self.assertIn("app.py", verdict["detail"])
        self.assertIn("docs/README.md", verdict["detail"])

    def test_crlf_and_extra_files_do_not_count(self):
        root = self.copy()
        readme = root / "abl" / "docs" / "README.md"
        readme.write_bytes(readme.read_bytes().replace(b"\n", b"\r\n"))
        (root / "abl" / "__pycache__").mkdir()
        (root / "abl" / "__pycache__" / "x.pyc").write_bytes(b"\0")
        (root / "web" / ".dev-bootstrap").mkdir()
        self.assertEqual(self.rows(root)["abl"]["checkout"]["id"], "current")

    def test_missing_directory_offers_download(self):
        root = self.copy()
        shutil.rmtree(root / "abl")
        row = self.rows(root)["abl"]
        self.assertEqual(row["checkout"]["id"], "absent")
        self.assertTrue(row["canGet"])
        self.assertEqual(view.card_actions(row)["buttons"][0]["id"], "@get")

    def test_trees_are_cached_by_sha(self):
        root = self.copy(self.first)
        self.rows(root)
        first = len([url for url in self.github.calls if "/git/trees/" in url])
        self.github.calls.clear()
        state.build_state(root, remote.GlobalState(self.tmp / "g.json", self.github), force=True, host=HOST,
                          status_run=None, trees=source.Trees(paths.cache_dir() / "trees", self.github))
        again = [url for url in self.github.calls if "/git/trees/" in url]
        self.assertGreater(first, 1)
        self.assertEqual(len(again), 1)  # только корень main: деревья каталогов и старых коммитов — из кеша

    def test_offline_uses_cache_only(self):
        root = self.copy()
        self.rows(root)
        self.github.calls.clear()
        value = state.build_state(root, remote.GlobalState(self.tmp / "g.json", self.github), offline=True, host=HOST,
                                  status_run=None)
        self.assertEqual(self.github.calls, [])
        self.assertEqual({row["id"]: row["checkout"]["id"] for row in value["components"]}, {"web": "current", "abl": "current"})

    def test_install_without_revision_uses_recorded_source(self):
        history = [{"sha": "c" * 40, "subject": "web: третий"}, {"sha": "b" * 40}, {"sha": "a" * 40}]
        running = {"state": "running", "revision": None}
        old = state.freshness(None, running, history[0], history, None, {"sha": "a" * 40})
        self.assertEqual(old["id"], "outdated")
        self.assertIn("2 коммит", old["detail"])
        self.assertEqual(state.freshness(None, running, history[0], history, None, {"sha": "c" * 40})["id"], "current")
        self.assertEqual(state.freshness(None, running, history[0], history, None, None)["id"], "unknown")

    def test_install_revision_checked_by_github_compare_without_git(self):
        trees = source.Trees(paths.cache_dir() / "trees", self.github)
        head = git(self.repo, "rev-parse", "HEAD").strip()
        contains = lambda older, newer: trees.contains(REPO, older, newer)  # noqa: E731
        main_web = {"sha": head, "subject": "web: третий"}
        self.assertEqual(state.freshness(None, {"state": "running", "revision": head}, main_web, [main_web], contains)["id"], "current")
        verdict = state.freshness(None, {"state": "running", "revision": self.first}, main_web, [main_web], contains)
        self.assertEqual(verdict["id"], "outdated")

    def test_self_update_mode_for_copy(self):
        self.assertEqual(selfupdate.mode(self.copy()), "copy")
        self.assertEqual(selfupdate.status_payload(self.copy(), "0.5.0")["detail"], "копия без git: сверка с main по содержимому файлов")


class StandaloneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["P2PKANBAN_LAUNCHER_HOME"] = str(self.tmp / "home")
        self.original = paths.ecosystem_root

    def tearDown(self):
        paths.ecosystem_root = self.original
        os.environ.pop("P2PKANBAN_LAUNCHER_HOME", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_without_ecosystem_lists_main_and_offers_download(self):
        paths.ecosystem_root = lambda start=paths.LAUNCHER_DIR: None
        eco = {**ECOSYSTEM, "components": ECOSYSTEM["components"] + [
            {"id": "mobile", "dir": "mobile", "platforms": ["android"], "distribution": "apk"},
            {"id": "launcher", "dir": "launcher", "platforms": ["linux"]}]}

        def fetch(url: str) -> bytes:
            if url.endswith("/ecosystem.json"):
                return json.dumps(eco).encode()
            raise remote.RemoteError("GitHub ответил 404 на " + url)
        value = state.build_state(None, remote.GlobalState(self.tmp / "g.json", fetch), host=HOST, status_run=None,
                                  apk_feed=None)
        rows = {row["id"]: row for row in value["components"]}
        self.assertEqual(value["ecosystem"]["standalone"]["source"], "network")
        self.assertEqual(rows["web"]["checkout"]["label"], "не скачано")
        self.assertEqual(view.card_actions(rows["web"])["buttons"], [{"id": "@get", "label": "Скачать с GitHub", "main": True}])
        self.assertFalse(rows["mobile"]["canGet"])
        self.assertFalse(rows["launcher"]["canGet"])
        offline = state.build_state(None, remote.GlobalState(self.tmp / "g.json", fetch), offline=True, host=HOST,
                                    status_run=None)
        self.assertEqual(offline["ecosystem"]["standalone"]["source"], "cache")

    def test_saved_root_is_used_only_by_own_launcher(self):
        root = self.tmp / "eco"
        root.mkdir()
        (root / "ecosystem.json").write_text("{}", encoding="utf-8")
        paths.save_root(root)
        self.assertEqual(paths.saved_root(), root)
        self.assertIsNone(paths.ecosystem_root(self.tmp / "elsewhere" / "launcher"))

    def test_get_command_is_launchers_own_script(self):
        from launcher_app import runner
        command = runner.get_command(self.tmp / "eco", "abl", dry_run=True)
        self.assertEqual(command["argv"][1], str(paths.LAUNCHER_DIR / "get.py"))
        self.assertEqual(command["argv"][-3:], ["--only", "abl", "--dry-run"])

    def test_present_only(self):
        root = self.tmp / "eco"
        for name in ("web", "launcher"):
            (root / name).mkdir(parents=True)
        self.assertEqual(get.present_only(root, ["abl"]), ["web", "abl"])
        for name in get.DIRECTIONS:
            (root / name).mkdir(exist_ok=True)
        self.assertEqual(get.present_only(root, []), [])


if __name__ == "__main__":
    unittest.main()
