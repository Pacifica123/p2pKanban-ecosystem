"""Детерминированные проверки лаунчера: без сети и Docker; окно — только если есть PySide6.

    cd launcher && python -B -m unittest discover -s tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launcher_app import apk, entry as entries, install, local, paths, probes, remote, runner, settings, state, themes, view  # noqa: E402

DIRS = ["web", "mobile", "abl", "devctl", "launcher"]
ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "contracts" / "launcher-entry" / "1" / "vectors"
REVISION = "9db706cb0abf" + "0" * 28


def web_status(state_id: str = "running") -> Callable:
    """Подменный запуск status: отвечает как web, не трогая Docker."""
    def run(argv, cwd, env, timeout):
        body = {"schema": entries.STATUS_SCHEMA, "component": Path(cwd).name, "installed": state_id != "absent",
                "running": {"running": True, "stopped": False}.get(state_id), "version": "2.1.0",
                "revision": REVISION, "url": "http://127.0.0.1:8080", "values": {"port": 8080}, "detail": "x", "problems": []}
        return 0, json.dumps(body)
    return run


def fake_commit(sha: str, subject: str) -> bytes:
    return json.dumps([{"sha": sha, "commit": {"committer": {"date": "2026-10-20T08:00:00Z"}, "message": subject + "\n\nтело"}}]).encode()


class PlatformTest(unittest.TestCase):
    def test_arch_family_is_arch_linux(self):
        host = probes.detect_platform("Linux", {"ID": "manjaro", "ID_LIKE": "arch", "PRETTY_NAME": "Manjaro Linux"})
        self.assertEqual(host["tags"], ["linux", "arch-linux"])
        self.assertEqual(probes.platform_fit(["arch-linux"], host)["fit"], "yes")

    def test_abl_is_grey_on_windows_and_web_is_not(self):
        host = probes.detect_platform("Windows")
        abl = probes.platform_fit(["arch-linux"], host)
        self.assertEqual(abl["fit"], "no")
        self.assertIn("Arch-based Linux", abl["reason"])
        self.assertEqual(probes.platform_fit(["linux", "windows", "macos"], host)["fit"], "yes")

    def test_android_is_phone(self):
        self.assertEqual(probes.platform_fit(["android"], probes.detect_platform("Windows"))["fit"], "phone")

    def test_docker_missing_on_windows_says_docker_desktop(self):
        host = probes.detect_platform("Windows")
        original = shutil.which
        try:
            probes.shutil.which = lambda name: None
            result = probes.check_requires(["docker"], host, runner=lambda argv, timeout: (0, ""))[0]
        finally:
            probes.shutil.which = original
        self.assertFalse(result["ok"])
        self.assertIn("Docker Desktop", result["hint"])

    def test_docker_windows_containers_are_rejected(self):
        host = probes.detect_platform("Windows")
        original = shutil.which
        try:
            probes.shutil.which = lambda name: "docker"
            result = probes.check_requires(["docker"], host, runner=lambda argv, timeout: (0, "windows\n"))[0]
        finally:
            probes.shutil.which = original
        self.assertFalse(result["ok"])
        self.assertIn("Linux containers", result["hint"])


class GlobalStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls: list[str] = []
        self.now = 1000.0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        if "raw.githubusercontent.com" in url:
            return json.dumps({"origin": {"boardRevision": 57, "lastPatchId": "p57"}}).encode()
        return fake_commit("b" * 40, "web: новое")

    def test_network_then_cache_then_stale_cache_on_error(self):
        cache = remote.GlobalState(self.tmp / "g.json", self.fetch, clock=lambda: self.now)
        first = cache.get("o/r", "main", ["web"])
        self.assertEqual(first["source"], "network")
        self.assertEqual(first["directories"]["web"]["subject"], "web: новое")
        self.assertEqual(first["board"]["boardRevision"], 57)
        self.assertIn("path=web", self.calls[0])

        self.calls.clear()
        self.assertEqual(cache.get("o/r", "main", ["web"])["source"], "cache")
        self.assertEqual(self.calls, [])

        def broken(url: str) -> bytes:
            raise remote.RemoteError("нет связи с GitHub")
        self.now += remote.TTL_SECONDS + 1
        stale = remote.GlobalState(self.tmp / "g.json", broken, clock=lambda: self.now).get("o/r", "main", ["web"])
        self.assertEqual(stale["source"], "cache")
        self.assertIn("нет связи", stale["error"])

    def test_offline_without_cache(self):
        result = remote.GlobalState(self.tmp / "none.json", self.fetch).get("o/r", "main", ["web"], offline=True)
        self.assertEqual(result["source"], "none")
        self.assertEqual(self.calls, [])


@unittest.skipUnless(shutil.which("git"), "нужен git")
class CheckoutTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.root / "ecosystem.json").write_text("{}", encoding="utf-8")
        for directory in ("web", "abl"):
            (self.root / directory).mkdir()
            (self.root / directory / "README.md").write_text(directory, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "first")
        self.first = self.git("rev-parse", "HEAD").strip()
        (self.root / "web" / "README.md").write_text("web 2", encoding="utf-8")
        self.git("commit", "-qam", "web: second")
        self.second = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *arguments: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *arguments], cwd=self.root, check=True, capture_output=True, text=True, env=env).stdout

    def verdict(self, directory: str, remote_sha: str | None) -> dict:
        checkout = local.checkout_state(self.root, [directory])
        commit = {"sha": remote_sha, "subject": "x"} if remote_sha else None
        return state.checkout_verdict(self.root, directory, checkout["directories"][directory], commit)

    def test_current_outdated_ahead_modified_absent(self):
        self.assertEqual(self.verdict("web", self.second)["id"], "current")
        self.assertEqual(self.verdict("abl", self.first)["id"], "current")
        self.assertEqual(self.verdict("web", "c" * 40)["id"], "outdated")
        self.assertEqual(self.verdict("web", self.first)["id"], "ahead")
        self.assertEqual(self.verdict("mobile", self.first)["id"], "absent")
        (self.root / "abl" / "README.md").write_text("правка", encoding="utf-8")
        self.assertEqual(self.verdict("abl", self.first)["id"], "modified")

    def test_outdated_counts_commits_when_main_is_known(self):
        self.git("checkout", "-q", self.first)
        checkout = local.checkout_state(self.root, ["web"])
        result = state.checkout_verdict(self.root, "web", checkout["directories"]["web"], {"sha": self.second, "subject": "web: second"})
        self.assertEqual(result["id"], "outdated")
        self.assertIn("1 коммит", result["detail"])


class SettingsTest(unittest.TestCase):
    def test_normalize_rejects_unknown_theme_and_clamps_window(self):
        value = settings.normalize({"theme": "navy", "window": {"width": 10, "height": 99999}})
        self.assertEqual(value["theme"], "graphite")
        self.assertEqual(value["window"], {"width": settings.MIN_SIZE[0], "height": settings.MAX_SIZE[1]})

    def test_save_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            settings.save(path, settings.merge(settings.load(path), {"theme": "lemon"}))
            self.assertEqual(settings.load(path)["theme"], "lemon")

    def test_themes_match_dictionary(self):
        root = Path(__file__).resolve().parents[2]
        dictionary = root / "docs/ecosystem/ui-themes.json"
        if not dictionary.is_file():
            self.skipTest("лаунчер взят без корня экосистемы")
        ids = [theme["id"] for theme in json.loads(dictionary.read_text(encoding="utf-8"))["themes"]]
        self.assertEqual(list(settings.THEMES), ids)


class ThemesTest(unittest.TestCase):
    def test_qss_for_every_theme_uses_its_colors(self):
        for theme_id, spec in themes.THEMES.items():
            sheet = themes.qss(theme_id)
            self.assertIn(spec["colors"]["background"], sheet)
            self.assertIn(spec["colors"]["accentStrong"], sheet)
            self.assertEqual(sheet.count("{"), sheet.count("}"), theme_id)

    def test_unknown_theme_falls_back_to_default(self):
        self.assertEqual(themes.qss("navy"), themes.qss(themes.DEFAULT))

    def test_mix(self):
        self.assertEqual(themes.mix("#000000", "#ffffff", 0.5), "#808080")


class InstallTest(unittest.TestCase):
    def test_requirement_is_pinned_pyside6(self):
        requirement = install.pinned()
        self.assertTrue(requirement.startswith("PySide6-Essentials=="), requirement)

    def test_venv_lives_outside_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["P2PKANBAN_LAUNCHER_HOME"] = tmp
            try:
                venv = paths.venv_dir()
            finally:
                del os.environ["P2PKANBAN_LAUNCHER_HOME"]
        self.assertNotIn(paths.LAUNCHER_DIR, venv.parents)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 не установлен: проверка окна пропущена")
class WindowSmokeTest(unittest.TestCase):
    def test_window_renders_state_offscreen(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QPushButton
        except ImportError as error:
            self.skipTest(f"PySide6 не загружается: {error}")
        from launcher_app import qt_app
        app = QApplication.instance() or QApplication([])
        root = Path(__file__).resolve().parents[2]
        if not (root / "ecosystem.json").is_file():
            self.skipTest("лаунчер взят без корня экосистемы")
        with tempfile.TemporaryDirectory() as tmp:
            fetch = lambda url: (json.dumps({"origin": {"boardRevision": 1, "lastPatchId": "p"}}).encode()
                                 if "raw.githubusercontent.com" in url else fake_commit("d" * 40, "x"))
            value = state.build_state(root, remote.GlobalState(Path(tmp) / "g.json", fetch),
                                      runner=lambda argv, timeout: (0, "linux\n"), host=probes.detect_platform("Windows"),
                                      status_run=web_status("running"), apk_feed=apk.Feed(Path(tmp) / "a.json", fetch))
            window = qt_app.Window(lambda force: value, Path(tmp) / "s.json")
            window.render(value)
            offs = [card for card in window.apps.cards if card.property("off") == "true"]
            self.assertEqual(len(offs), 1)  # abl на Windows
            texts = [button.text() for card in window.apps.cards for button in card.findChildren(QPushButton)]
            self.assertIn("Открыть", texts)  # web «работает» — кнопка открыть узел
            self.assertIn("Обновить", texts)  # main новее установленного коммита
            window.apply_theme("lemon")
            self.assertEqual(settings.load(Path(tmp) / "s.json")["theme"], "lemon")
            window.close()
        app.processEvents()


class BuildStateTest(unittest.TestCase):
    def test_build_state_against_real_ecosystem_map(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "ecosystem.json").is_file():
            self.skipTest("лаунчер взят без корня экосистемы")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["P2PKANBAN_LAUNCHER_HOME"] = tmp
            try:
                fetch = lambda url: (json.dumps({"origin": {"boardRevision": 1, "lastPatchId": "p"}}).encode()
                                     if "raw.githubusercontent.com" in url else fake_commit("d" * 40, "x"))
                cache = remote.GlobalState(Path(tmp) / "g.json", fetch)
                value = state.build_state(root, cache, runner=lambda argv, timeout: (1, ""),
                                          host=probes.detect_platform("Windows"), status_run=web_status("stopped"),
                                          apk_feed=apk.Feed(Path(tmp) / "a.json", fetch))
            finally:
                del os.environ["P2PKANBAN_LAUNCHER_HOME"]
        rows = {row["id"]: row for row in value["components"]}
        self.assertEqual(value["schema"], state.STATE_SCHEMA)
        self.assertEqual(set(rows), set(DIRS))
        self.assertEqual(rows["abl"]["fit"]["fit"], "no")
        self.assertEqual(rows["abl"]["requires"], [])
        self.assertEqual(rows["mobile"]["installed"]["id"], "phone")
        self.assertTrue(rows["web"]["install"])
        self.assertEqual(value["global"]["source"], "network")
        self.assertEqual(rows["web"]["status"]["state"], "stopped")
        self.assertEqual(rows["web"]["installed"]["label"], "остановлено")
        self.assertIsNone(rows["abl"]["status"])  # abl на Windows не спрашивают
        self.assertIsNotNone(rows["launcher"]["entry"])  # лаунчер объявляет и себя (L5)
        self.assertEqual(rows["mobile"]["apk"]["id"], "unknown")  # подменный GitHub отдал не ленту
        self.assertTrue(rows["mobile"]["apk"]["page"].startswith("https://expo.dev/accounts/"))


@unittest.skipUnless(VECTORS.is_dir(), "лаунчер взят без корня экосистемы: векторы контракта недоступны")
class EntryVectorsTest(unittest.TestCase):
    """Своя реализация launcher-entry/1 даёт то же, что эталон корня."""

    def load(self, name: str) -> dict:
        return json.loads((VECTORS / name).read_text(encoding="utf-8"))

    def test_commands(self):
        data = self.load("commands.json")
        entry = entries.check(data["entry"])
        for case in data["cases"]:
            with self.subTest(case["name"]):
                if "rejected" in case:
                    with self.assertRaises(entries.Rejected) as caught:
                        entries.command(entry, case["action"], case["values"], case["dryRun"])
                    self.assertEqual(caught.exception.reason, case["rejected"])
                else:
                    self.assertEqual(entries.command(entry, case["action"], case["values"], case["dryRun"]), case["expected"])

    def test_rejections(self):
        for case in self.load("rejections.json")["cases"]:
            with self.subTest(case["name"]):
                with self.assertRaises(entries.Rejected) as caught:
                    entries.check(case["entry"])
                self.assertEqual(caught.exception.reason, case["rejected"])

    def test_status(self):
        data = self.load("status.json")
        for case in data["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(entries.parse_status(data["entry"], case["exitCode"], case["stdout"]), case["expected"])

    def test_real_entries_of_the_tree_load(self):
        for directory in ("web", "abl"):
            info = entries.load(ROOT, directory)
            self.assertTrue(info["available"], info["error"])


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "demo").mkdir()
        (self.root / "demo" / "tool.py").write_text(
            "import json, sys\n"
            "if sys.argv[1] == 'status':\n"
            "    print(json.dumps({'schema': 'p2p-kanban-launcher-status/1', 'component': 'demo', 'installed': True,"
            " 'running': None, 'values': {'port': 9000}}))\n"
            "else:\n"
            "    print('аргументы:', ' '.join(sys.argv[1:]))\n"
            "    sys.exit(3 if '--fail' in sys.argv else 0)\n", encoding="utf-8")
        self.entry = entries.check({
            "schema": entries.ENTRY_SCHEMA, "component": "demo",
            "settings": [{"id": "port", "label": "Порт", "type": "port"},
                         {"id": "fail", "label": "Упасть", "type": "bool"}],
            "actions": [
                {"id": "install", "label": "Поставить", "argv": ["{python}", "tool.py", "install"],
                 "options": [{"setting": "port", "argv": ["--port", "{value}"]}, {"setting": "fail", "argv": ["--fail"]}],
                 "dryRun": ["--dry-run"]},
                {"id": "status", "label": "Состояние", "argv": ["{python}", "tool.py", "status"], "output": "status"},
            ]})
        self.registry = self.root / "installs.json"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_command_runs_in_direction_with_our_python_and_records(self):
        command = runner.resolve(self.root, entries.command(self.entry, "install", {"port": 9001}), sys.executable)
        self.assertEqual(command["argv"][0], sys.executable)
        self.assertEqual(Path(command["cwd"]), (self.root / "demo").resolve())
        lines: list[str] = []
        self.assertEqual(runner.stream(command, lines.append), 0)
        self.assertEqual(lines, ["аргументы: install --port 9001"])
        runner.record(self.registry, command, 0, False, {"port": 9001})
        saved = local.read_registry(self.registry)["installs"]["demo"]
        self.assertEqual((saved["lastAction"]["action"], saved["values"]), ("install", {"port": 9001}))

    def test_failure_and_dry_run(self):
        command = runner.resolve(self.root, entries.command(self.entry, "install", {"fail": True}, dry_run=True))
        self.assertEqual(runner.stream(command, lambda line: None), 3)
        runner.record(self.registry, command, 3, True, {})
        self.assertEqual(local.read_registry(self.registry)["installs"], {})  # пробный прогон — не установка

    def test_status_through_real_process(self):
        value = runner.status(self.root, self.entry)
        self.assertEqual((value["state"], value["values"]), ("installed", {"port": 9000}))

    def test_status_timeout_is_broken_not_crash(self):
        value = runner.status(self.root, self.entry, run=lambda argv, cwd, env, timeout: (124, ""))
        self.assertEqual((value["state"], value["detail"]), ("broken", "status не ответил вовремя"))

    def test_saved_values_survive_changed_entry(self):
        local.save_values(self.registry, "demo", {"port": 9002, "gone": 1, "fail": "да"})
        self.assertEqual(entries.clean_values(self.entry, local.saved_values(self.registry, "demo")), {"port": 9002})


class CardActionsTest(unittest.TestCase):
    def row(self, state_id: str | None, freshness: str = "current", ready: bool = True) -> dict:
        entry = json.loads((ROOT / "web" / "launcher.json").read_text(encoding="utf-8")) \
            if (ROOT / "web" / "launcher.json").is_file() else None
        if entry is None:
            self.skipTest("нет web/launcher.json")
        status = None if state_id is None else {"state": state_id, "url": "http://127.0.0.1:8080"}
        return {"entry": entry, "fit": {"fit": "yes"}, "status": status, "freshness": {"id": freshness},
                "ready": ready, "requires": [{"label": "Docker", "ok": ready}]}

    def ids(self, row: dict) -> list[str]:
        return [item["id"] for item in view.card_actions(row)["buttons"]]

    def test_buttons_follow_state(self):
        self.assertEqual(self.ids(self.row("absent")), ["install"])
        self.assertEqual(self.ids(self.row("running")), ["open", "stop"])
        self.assertEqual(self.ids(self.row("stopped")), ["start"])
        self.assertEqual(self.ids(self.row("running", "outdated")), ["update", "open", "stop"])
        self.assertEqual(self.ids(self.row("broken")), ["doctor", "install"])

    def test_menu_has_the_rest_but_not_status(self):
        plan = view.card_actions(self.row("running"))
        menu = [item["id"] for item in plan["menu"]]
        self.assertIn("remove", menu)
        self.assertNotIn("status", menu)
        self.assertNotIn("stop", menu)

    def test_missing_docker_blocks_but_names_it(self):
        self.assertEqual(view.card_actions(self.row("absent", ready=False))["blocked"], "Сначала нужно: Docker")


if __name__ == "__main__":
    unittest.main()
