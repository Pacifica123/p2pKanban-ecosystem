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

from update_control_plane import (
    ControlApplication,
    ControlHandler,
    ThreadingHTTPServer,
    installed_revision,
)


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
                "updateRepository": "https://github.com/Pacifica123/p2p_planner",
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
                "url": "https://github.com/Pacifica123/p2p_planner/commit/" + "b" * 40,
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


if __name__ == "__main__":
    unittest.main()
