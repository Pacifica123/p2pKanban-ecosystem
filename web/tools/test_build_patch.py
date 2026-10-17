#!/usr/bin/env python3
"""The node names the devctl patch it was built from (board/README.md «Номер патча в версии клиентов»)."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import container_bootstrap as bootstrap

WEB = Path(__file__).resolve().parents[1]
SHA = "a" * 40
REQUIRED = (
    "VERSION",
    "bootstrap.py",
    "deploy/bootstrap/compose.yaml",
    "deploy/bootstrap/gateway.Dockerfile",
    "deploy/bootstrap/gateway.conf",
    "deploy/bootstrap/maintenance.html",
    "backend/Cargo.toml",
    "frontend/package.json",
    "tools/container_bootstrap.py",
    "tools/resilient_bootstrap.py",
    "tools/update_control_plane.py",
)


def board(revision: object, patch_id: object) -> str:
    return json.dumps({"origin": {"boardRevision": revision, "lastPatchId": patch_id}})


def monorepo(root: Path, revision: object = 41, patch_id: object = "2026-10-17-web-build-patch") -> Path:
    (root / "board").mkdir(parents=True)
    (root / "board" / "board.json").write_text(board(revision, patch_id), encoding="utf-8")
    (root / "ecosystem.json").write_text("{}", encoding="utf-8")
    web = root / "web"
    web.mkdir()
    return web


class SourcePatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("P2PKANBAN_PATCH_ID", None)
        os.environ.pop("P2PKANBAN_PATCH_REVISION", None)

    def tearDown(self) -> None:
        self.env.stop()

    def test_checkout_reads_board_right_above_web(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            web = monorepo(Path(raw))
            self.assertEqual(bootstrap.source_patch(web), {"patchId": "2026-10-17-web-build-patch", "boardRevision": 41})

    def test_release_copy_inside_checkout_does_not_borrow_its_board(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            release = monorepo(Path(raw)) / ".dev-bootstrap" / "releases" / "x" / "source"
            release.mkdir(parents=True)
            self.assertIsNone(bootstrap.source_patch(release))
            bootstrap.write_build_patch(release, {"patchId": "2026-10-16-web-static-checks", "boardRevision": 31})
            self.assertEqual(bootstrap.source_patch(release), {"patchId": "2026-10-16-web-static-checks", "boardRevision": 31})

    def test_explicit_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            web = monorepo(Path(raw))
            os.environ["P2PKANBAN_PATCH_ID"] = "2026-10-18-other"
            os.environ["P2PKANBAN_PATCH_REVISION"] = "50"
            self.assertEqual(bootstrap.source_patch(web), {"patchId": "2026-10-18-other", "boardRevision": 50})

    def test_malformed_board_is_unknown(self) -> None:
        for revision, patch_id in ((41, "../etc"), (41, ""), (41, None), (True, "ok-id"), (0, "ok-id")):
            with tempfile.TemporaryDirectory() as raw:
                web = monorepo(Path(raw), revision, patch_id)
                patch = bootstrap.source_patch(web)
                if patch_id == "ok-id":
                    self.assertEqual(patch, {"patchId": "ok-id", "boardRevision": None})
                else:
                    self.assertIsNone(patch)

    def test_compose_environment_carries_patch_or_unknown(self) -> None:
        env = bootstrap.compose_environment(8080, "127.0.0.1", patch={"patchId": "p-1", "boardRevision": 7})
        self.assertEqual((env["P2PKANBAN_PATCH_ID"], env["P2PKANBAN_PATCH_REVISION"]), ("p-1", "7"))
        env = bootstrap.compose_environment(8080, "127.0.0.1")
        self.assertEqual((env["P2PKANBAN_PATCH_ID"], env["P2PKANBAN_PATCH_REVISION"]), ("unknown", "unknown"))

    def test_label(self) -> None:
        self.assertEqual(bootstrap.patch_label({"patchId": "p-1", "boardRevision": 7}), "патч 7 · p-1")
        self.assertEqual(bootstrap.patch_label(None), "патч неизвестен")

    def test_github_update_keeps_board_patch_of_the_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            archive = work / "commit.zip"
            prefix = f"p2pKanban-ecosystem-{SHA}"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(f"{prefix}/ecosystem.json", "{}")
                bundle.writestr(f"{prefix}/board/board.json", board(42, "2026-10-17-web-build-patch"))
                for relative in REQUIRED:
                    bundle.write(WEB / relative, f"{prefix}/web/{relative}")

            def download(_url: str, destination: Path) -> str:
                destination.write_bytes(archive.read_bytes())
                return "0" * 64

            staging_parent = work / "incoming"
            staging_parent.mkdir()
            args = argparse.Namespace(source_dir=None, branch="main", repository=bootstrap.DEFAULT_UPDATE_REPOSITORY, target_commit=SHA)
            latest = {"sha": SHA, "message": "web: x", "url": "https://example.invalid"}
            with mock.patch.object(bootstrap, "github_latest_commit", return_value=latest), \
                    mock.patch.object(bootstrap, "download_update_archive", side_effect=download):
                staging, metadata = bootstrap.prepare_update_source(args, work, {}, staging_parent)
            expected = {"patchId": "2026-10-17-web-build-patch", "boardRevision": 42}
            self.assertEqual(metadata["patch"], expected)
            self.assertEqual(bootstrap.source_patch(staging), expected)
            # BUILD_PATCH.json is not a runtime input: the web source fingerprint stays the tree's.
            (staging / bootstrap.BUILD_PATCH_FILENAME).unlink()
            self.assertEqual(bootstrap.source_fingerprint(staging), metadata["sourceFingerprint"])


if __name__ == "__main__":
    unittest.main()
