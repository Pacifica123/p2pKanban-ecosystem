#!/usr/bin/env python3
"""Executable loopback/security smoke tests for the source-update control plane."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import container_bootstrap as bootstrap
import update_control_plane as control
from update_control_plane import (
    ControlApplication,
    ControlHandler,
    ThreadingHTTPServer,
    installed_revision,
)

ECOSYSTEM = "https://github.com/Pacifica123/p2pKanban-ecosystem"
LEGACY = "https://github.com/Pacifica123/p2p_planner"


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class UpdateControlPlaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="p2pkanban-control-test-")
        self.project_root = Path(self.temporary.name)
        write_json(
            self.project_root / ".dev-bootstrap/container-stack.json",
            {
                "webPort": 18080,
                "activeRevision": "a" * 40,
                "updateRepository": ECOSYSTEM,
                "updateBranch": "main",
            },
        )
        write_json(
            self.project_root / ".dev-bootstrap/latest-source-commit.json",
            {
                "sha": "b" * 40,
                "shortSha": "b" * 12,
                "message": "test commit",
                "committedAt": "2032-01-01T10:00:00Z",
                "url": ECOSYSTEM + "/commit/" + "b" * 40,
                "checkedAt": "2032-01-01T10:00:00Z",
            },
        )
        self.application = ControlApplication(self.project_root, 0)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ControlHandler)
        setattr(self.server, "application", self.application)
        self.application.server = self.server
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = "http://127.0.0.1:18080"
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        origin: str | None = None,
        token: str | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        headers: dict[str, str] = {}
        if origin:
            headers["Origin"] = origin
        if token:
            headers["X-P2PKanban-Control"] = token
        request = urllib.request.Request(
            self.base_url + path,
            data=b"{}" if method == "POST" else None,
            method=method,
            headers=headers,
        )
        try:
            response = urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, dict(response.headers.items())

    def test_status_requires_exact_loopback_origin_and_exposes_no_wildcard(self) -> None:
        status, _payload, _headers = self.request("/v1/status")
        self.assertEqual(status, 403)
        status, _payload, _headers = self.request(
            "/v1/status",
            origin="http://127.0.0.1.evil.example:18080",
        )
        self.assertEqual(status, 403)

        status, payload, headers = self.request("/v1/status", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(payload["installedRevision"], "a" * 40)
        self.assertEqual(payload["latest"]["sha"], "b" * 40)
        self.assertGreaterEqual(len(str(payload["sessionToken"])), 32)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), self.origin)

    def test_mutation_requires_origin_and_random_token(self) -> None:
        _status, payload, _headers = self.request("/v1/status", origin=self.origin)
        token = str(payload["sessionToken"])
        status, _payload, _headers = self.request(
            "/v1/unknown",
            method="POST",
            origin=self.origin,
        )
        self.assertEqual(status, 403)
        status, _payload, _headers = self.request(
            "/v1/unknown",
            method="POST",
            origin=self.origin,
            token=token,
        )
        self.assertEqual(status, 404)

    def test_running_image_identity_does_not_follow_checkout_head(self) -> None:
        state_path = self.project_root / ".dev-bootstrap/container-stack.json"
        write_json(
            state_path,
            {
                "webPort": 18080,
                "imageTag": "1.0.0-beta.10-0123456789ab",
            },
        )
        self.assertEqual(installed_revision(self.project_root), "0123456789ab")

        write_json(state_path, {"webPort": 18080})
        self.assertIsNone(installed_revision(self.project_root))

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
    def test_control_state_is_private(self) -> None:
        mode = (self.project_root / ".dev-bootstrap/update-control.json").stat().st_mode
        self.assertEqual(mode & 0o077, 0)


    def test_host_verdict_hides_web_commit_already_in_running_build(self) -> None:
        cache = self.project_root / ".dev-bootstrap/latest-source-commit.json"
        cached = json.loads(cache.read_text(encoding="utf-8"))
        write_json(cache, {**cached, "evaluatedFor": "a" * 40, "webUpdateAvailable": False})
        status, payload, _headers = self.request("/v1/status", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertIs(payload["updateAvailable"], False)

        write_json(cache, {**cached, "evaluatedFor": "c" * 40, "webUpdateAvailable": False})
        _status, payload, _headers = self.request("/v1/status", origin=self.origin)
        self.assertIs(payload["updateAvailable"], True)


def commit_payload(sha: str, repository: str = ECOSYSTEM) -> dict[str, object]:
    return {
        "sha": sha,
        "html_url": f"{repository}/commit/{sha}",
        "commit": {"message": "web: test", "committer": {"date": "2032-01-01T10:00:00Z"}},
    }


class UpdateChannelTest(unittest.TestCase):
    """The node follows web/ of the monorepo, not every ecosystem commit."""

    def test_legacy_repository_follows_monorepo(self) -> None:
        self.assertEqual(control.normalize_repository(LEGACY), ECOSYSTEM)
        self.assertEqual(control.normalize_repository(LEGACY + ".git"), ECOSYSTEM)
        self.assertEqual(control.normalize_repository(None), ECOSYSTEM)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                bootstrap.discover_update_repository(root, {"updateRepository": LEGACY}, None),
                ECOSYSTEM,
            )
            self.assertEqual(bootstrap.discover_update_repository(root, {}, None), ECOSYSTEM)

    def test_latest_commit_is_the_last_one_touching_web(self) -> None:
        calls: list[str] = []

        def github(url: str) -> object:
            calls.append(url)
            return [commit_payload("d" * 40)]

        with mock.patch.object(control, "github_json", side_effect=github):
            latest = control.fetch_latest_commit(ECOSYSTEM, "main")
        self.assertEqual(latest["sha"], "d" * 40)
        self.assertEqual(latest["sourcePath"], "web")
        self.assertEqual(
            calls,
            ["https://api.github.com/repos/Pacifica123/p2pKanban-ecosystem/commits?sha=main&path=web&per_page=1"],
        )

        with mock.patch.object(bootstrap, "github_api_json", side_effect=github):
            self.assertEqual(bootstrap.github_latest_commit(ECOSYSTEM, "main")["sha"], "d" * 40)

    def test_repository_without_web_directory_uses_branch_head(self) -> None:
        def github(url: str) -> object:
            return [] if "path=web" in url else commit_payload("e" * 40)

        with mock.patch.object(control, "github_json", side_effect=github):
            latest = control.fetch_latest_commit("https://github.com/owner/single", "main")
        self.assertEqual(latest["sha"], "e" * 40)
        self.assertIsNone(latest["sourcePath"])
        with mock.patch.object(bootstrap, "github_api_json", side_effect=github):
            self.assertEqual(
                bootstrap.github_latest_commit("https://github.com/owner/single", "main")["sha"],
                "e" * 40,
            )

    def test_running_build_after_non_web_commit_contains_latest_web(self) -> None:
        verdicts = {"ahead": True, "identical": True, "behind": False, "diverged": False}
        for status, contains in verdicts.items():
            with mock.patch.object(control, "github_json", return_value={"status": status}):
                self.assertIs(control.installed_contains(ECOSYSTEM, "d" * 40, "a" * 40), contains)
        with mock.patch.object(control, "github_json", side_effect=RuntimeError("404")):
            self.assertFalse(control.installed_contains(ECOSYSTEM, "d" * 40, "301495c0a3f4"))
        self.assertTrue(control.installed_contains(ECOSYSTEM, "d" * 40, "d" * 12))
        self.assertFalse(control.installed_contains(ECOSYSTEM, "d" * 40, None))

    def test_cache_from_legacy_repository_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / ".dev-bootstrap/container-stack.json", {"activeRevision": "a" * 40})
            write_json(
                root / ".dev-bootstrap/latest-source-commit.json",
                {"sha": "f" * 40, "url": LEGACY + "/commit/" + "f" * 40},
            )
            application = ControlApplication(root, 0)
            self.assertEqual(application.repository, ECOSYSTEM)

            def github(url: str) -> object:
                if "/compare/" in url:
                    return {"status": "diverged"}
                return [commit_payload("d" * 40)]

            with mock.patch.object(control, "github_json", side_effect=github):
                state = application.state()
            self.assertEqual(state["latest"]["sha"], "d" * 40)
            self.assertIs(state["updateAvailable"], True)
            self.assertEqual(state["sourcePath"], "web")

    def test_failed_update_reports_the_updater_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "update-job.log"
            log.write_text(
                "Получаю исходники x (main).\n"
                "Проверяю полученный source перед сборкой.\n"
                "\n"
                "Запуск остановлен: Встроенная проверка нового bootstrap завершилась ошибкой.\n"
                "AssertionError: README became dense again\n",
                encoding="utf-8",
            )
            self.assertEqual(
                control.failure_reason(log),
                "Встроенная проверка нового bootstrap завершилась ошибкой.\n"
                "AssertionError: README became dense again",
            )
            log.write_text("a\n" * 20 + "last line\n", encoding="utf-8")
            self.assertTrue(str(control.failure_reason(log)).endswith("last line"))
            self.assertIsNone(control.failure_reason(Path(directory) / "missing.log"))

    def test_bootstrap_self_check_does_not_gate_on_readme_length(self) -> None:
        checker = (Path(__file__).resolve().parent / "check_zero_config_bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("README became dense again", checker)

    def test_monorepo_archive_builds_from_web_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            monorepo = Path(directory) / "p2pKanban-ecosystem-abc"
            (monorepo / "web").mkdir(parents=True)
            (monorepo / "web/bootstrap.py").write_text("", encoding="utf-8")
            (monorepo / "mobile").mkdir()
            self.assertEqual(bootstrap.update_source_subdirectory(monorepo), monorepo / "web")

            single = Path(directory) / "p2p_planner-abc"
            (single / "web").mkdir(parents=True)
            (single / "bootstrap.py").write_text("", encoding="utf-8")
            self.assertEqual(bootstrap.update_source_subdirectory(single), single)

    def test_watch_updates_serves_the_root_the_running_node_came_from(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / "node"
            write_json(node / ".dev-bootstrap/container-stack.json", {"webPort": 8082})
            # A root with stack state is served as is.
            self.assertEqual(bootstrap.watch_updates_root(node), node)
            copy = Path(directory) / "copy"  # a UserTestSpace copy: no .dev-bootstrap state
            copy.mkdir()
            with mock.patch.object(bootstrap, "running_stack_root", return_value=node):
                self.assertEqual(bootstrap.watch_updates_root(copy), node)
            with mock.patch.object(bootstrap, "running_stack_root", return_value=None):
                with self.assertRaises(bootstrap.BootstrapError) as raised:
                    bootstrap.watch_updates_root(copy)
                self.assertIn("UserTestSpace", str(raised.exception))

    def test_root_without_stack_state_would_not_allow_the_node_origin(self) -> None:
        # Why the copy cannot serve: its updater falls back to port 8080.
        with tempfile.TemporaryDirectory() as directory:
            stray = ControlApplication(Path(directory), 0)
            self.assertNotIn("http://127.0.0.1:8082", stray.allowed_origins())


if __name__ == "__main__":
    unittest.main()
