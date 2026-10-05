#!/usr/bin/env python3
"""Windows/ReviOS regressions that do not depend on the host Docker daemon."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import container_bootstrap as bootstrap


class WindowsBootstrapTests(unittest.TestCase):
    def test_stopped_gateway_keeps_its_node_port(self) -> None:
        inspected = {
            "NetworkSettings": {"Ports": {}},
            "HostConfig": {
                "PortBindings": {
                    "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8082"}],
                },
            },
        }
        calls: list[list[str]] = []

        def run(command, **_kwargs):
            calls.append(list(command))
            if command[1:3] == ["ps", "--all"]:
                return subprocess.CompletedProcess(command, 0, "gateway-id\n", "")
            if command[1:2] == ["inspect"]:
                return subprocess.CompletedProcess(command, 0, json.dumps([inspected]), "")
            return subprocess.CompletedProcess(command, 1, "unexpected command", "")

        docker = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
        with (
            mock.patch.object(bootstrap.shutil, "which", return_value=docker),
            mock.patch.object(bootstrap, "run_capture", side_effect=run),
            # This test isolates port retention; ownership is covered separately.
            mock.patch.object(bootstrap.resilient, "verified_owner", return_value=True),
            mock.patch.object(bootstrap, "is_port_available", return_value=True),
        ):
            port = bootstrap.discover_owned_web_port(Path("C:/p2pKanban"))

        self.assertEqual(port, 8082)
        self.assertTrue(calls)
        self.assertTrue(all(call[0] == docker for call in calls))
        self.assertIn("--all", calls[0])

    def test_crlf_checkout_cannot_reintroduce_host_mounted_init_script(self) -> None:
        root = Path(__file__).resolve().parent.parent
        compose = (root / bootstrap.COMPOSE_RELATIVE_PATH).read_text(encoding="utf-8")
        simulated_windows_checkout = compose.replace("\n", "\r\n")

        self.assertIn('entrypoint: ["/bin/sh", "-ec"]', simulated_windows_checkout)
        self.assertIn("ensure_secret", simulated_windows_checkout)
        self.assertNotIn("./init-secrets.sh", simulated_windows_checkout)
        self.assertFalse((root / "deploy/bootstrap/init-secrets.sh").exists())

    def test_repository_pins_posix_entrypoint_line_endings(self) -> None:
        root = Path(__file__).resolve().parent.parent
        attributes = (root / ".gitattributes").read_text(encoding="utf-8")
        dockerfile = (root / "deploy/bootstrap/backend.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("*.sh text eol=lf", attributes)
        self.assertIn("*.yaml text eol=lf", attributes)
        self.assertIn("sed -i 's/\\r$//'", dockerfile)

    def test_port_parser_rejects_ambiguous_bindings(self) -> None:
        container = {
            "NetworkSettings": {
                "Ports": {
                    "8080/tcp": [
                        {"HostPort": "8081"},
                        {"HostPort": "8082"},
                    ],
                },
            },
        }
        self.assertIsNone(bootstrap.published_web_port(container))


if __name__ == "__main__":
    unittest.main()
