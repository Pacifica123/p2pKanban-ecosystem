#!/usr/bin/env python3
"""Regression tests for adopting a legacy Compose deployment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import container_bootstrap as bootstrap


def compose_container(
    service: str,
    *,
    image: str,
    project_root: Path,
    ports: dict[str, object] | None = None,
    volumes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "Config": {
            "Image": image,
            "Labels": {
                "com.docker.compose.project": bootstrap.COMPOSE_PROJECT,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files": str(
                    project_root / bootstrap.COMPOSE_RELATIVE_PATH
                ),
                "com.docker.compose.project.working_dir": str(
                    project_root / "deploy/bootstrap"
                ),
            },
        },
        "NetworkSettings": {"Ports": ports or {}},
        "Mounts": [
            {"Type": "volume", "Name": name}
            for name in volumes
        ],
    }


class RuntimeAdoptionTests(unittest.TestCase):
    def test_parses_beta_image_identity(self) -> None:
        version, revision = bootstrap.image_version_and_revision(
            "1.0.0-beta.10-68c7d79968c3"
        )
        self.assertEqual(version, "1.0.0-beta.10")
        self.assertEqual(revision, "68c7d79968c3")

    def test_discovers_legacy_stack_without_touching_volumes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p2pkanban-adoption-") as raw:
            legacy = Path(raw) / "legacy-project"
            (legacy / "deploy/bootstrap").mkdir(parents=True)
            (legacy / "backend").mkdir()
            (legacy / "frontend").mkdir()
            (legacy / bootstrap.COMPOSE_RELATIVE_PATH).write_text("services: {}\n")
            (legacy / "backend/Cargo.toml").write_text("[package]\nname='legacy'\n")
            (legacy / "frontend/package.json").write_text("{}\n")
            full_revision = "68c7d79968c3f0a168c7d79968c3f0a168c7d799"
            bootstrap.write_state(
                legacy,
                {
                    "appVersion": "1.0.0-beta.10",
                    "activeRevision": full_revision,
                    "webPort": 8082,
                    "bindAddress": "127.0.0.1",
                },
            )

            gateway = compose_container(
                "gateway",
                image="p2pkanban/gateway:local",
                project_root=legacy,
                ports={
                    "8080/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": "8082"}
                    ]
                },
            )
            backend = compose_container(
                "backend",
                image="p2pkanban/backend:1.0.0-beta.10-68c7d79968c3",
                project_root=legacy,
                volumes=(f"{bootstrap.COMPOSE_PROJECT}_bootstrap_secrets",),
            )
            web = compose_container(
                "web",
                image="p2pkanban/web:1.0.0-beta.10-68c7d79968c3",
                project_root=legacy,
            )
            postgres = compose_container(
                "postgres",
                image="postgres:16-alpine",
                project_root=legacy,
                volumes=(f"{bootstrap.COMPOSE_PROJECT}_postgres_data",),
            )
            containers = {
                "gateway": gateway,
                "backend": backend,
                "web": web,
                "postgres": postgres,
            }
            with (
                mock.patch.object(
                    bootstrap,
                    "compose_service_container",
                    side_effect=lambda _root, service: containers[service],
                ),
                mock.patch.object(bootstrap, "http_ready", return_value=True),
            ):
                discovered = bootstrap.discover_running_deployment(Path(raw))

            self.assertEqual(discovered["legacyRoot"], legacy)
            self.assertEqual(discovered["webPort"], 8082)
            self.assertEqual(discovered["appVersion"], "1.0.0-beta.10")
            self.assertEqual(discovered["activeRevision"], full_revision)
            self.assertEqual(
                set(discovered["volumes"]),
                {
                    "p2pkanban-bootstrap_postgres_data",
                    "p2pkanban-bootstrap_bootstrap_secrets",
                },
            )

    def test_registry_redirects_source_checkout_to_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p2pkanban-registry-") as raw:
            workspace = Path(raw)
            source = workspace / "kanban"
            runtime = workspace / "runtime/p2pkanban-node"
            for root in (source, runtime):
                (root / "deploy/bootstrap").mkdir(parents=True)
                (root / "backend").mkdir()
                (root / "frontend").mkdir()
                (root / bootstrap.COMPOSE_RELATIVE_PATH).write_text("services: {}\n")
                (root / "backend/Cargo.toml").write_text("[package]\nname='test'\n")
                (root / "frontend/package.json").write_text("{}\n")
            bootstrap.write_state(runtime, {"webPort": 8082})
            bootstrap.write_json_object(
                bootstrap.deployment_registry_path(source),
                {
                    "sourceProjectRoot": str(source.resolve()),
                    "deploymentRoot": str(runtime.resolve()),
                },
            )

            self.assertEqual(
                bootstrap.registered_deployment_root(source),
                runtime.resolve(),
            )

    def test_adopted_state_drops_legacy_release_paths(self) -> None:
        state = bootstrap.adopted_stack_state(
            {
                "legacyRoot": Path("/tmp/legacy"),
                "legacyState": {
                    "createdAt": "2026-08-16T12:00:00+00:00",
                    "activeSourceRoot": ".dev-bootstrap/releases/old/source",
                    "releaseHistory": [{"previousSourceRoot": "old"}],
                },
                "webPort": 8082,
                "bindAddress": "127.0.0.1",
                "appVersion": "1.0.0-beta.10",
                "activeRevision": "68c7d79968c3",
                "imageTag": "1.0.0-beta.10-68c7d79968c3",
                "volumes": [
                    "p2pkanban-bootstrap_postgres_data",
                    "p2pkanban-bootstrap_bootstrap_secrets",
                ],
            }
        )
        self.assertEqual(state["webPort"], 8082)
        self.assertEqual(state["releaseHistory"], [])
        self.assertNotIn("activeSourceRoot", state)
        self.assertNotIn("lastUpdateReport", state)

    def test_adopt_command_moves_only_control_ownership(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p2pkanban-command-") as raw:
            workspace = Path(raw)
            source = workspace / "kanban"
            runtime = workspace / "runtime/p2pkanban-node"
            required = (
                bootstrap.COMPOSE_RELATIVE_PATH,
                Path("backend/Cargo.toml"),
                Path("frontend/package.json"),
                Path("bootstrap.py"),
                Path("tools/container_bootstrap.py"),
                bootstrap.UPDATE_CONTROL_RELATIVE_PATH,
                Path("deploy/bootstrap/gateway.Dockerfile"),
                Path("deploy/bootstrap/gateway.conf"),
                Path("deploy/bootstrap/maintenance.html"),
            )
            for relative in required:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n")
            (source / "VERSION").write_text("1.0.0\n")
            (source / ".git").mkdir()
            (source / ".git/should-not-copy").write_text("ignored\n")
            (source / "frontend/.env.local").write_text("SECRET=ignored\n")

            discovered = {
                "legacyRoot": workspace / "legacy",
                "legacyState": {
                    "createdAt": "2026-08-16T12:00:00+00:00",
                    "updateRepository": bootstrap.DEFAULT_UPDATE_REPOSITORY,
                    "updateBranch": "main",
                },
                "webPort": 8082,
                "bindAddress": "127.0.0.1",
                "appVersion": "1.0.0-beta.10",
                "activeRevision": "68c7d79968c3",
                "imageTag": "1.0.0-beta.10-68c7d79968c3",
                "volumes": [
                    "p2pkanban-bootstrap_postgres_data",
                    "p2pkanban-bootstrap_bootstrap_secrets",
                ],
            }
            args = SimpleNamespace(runtime_root=str(runtime), dry_run=False)
            with (
                mock.patch.object(bootstrap, "ensure_docker_ready"),
                mock.patch.object(
                    bootstrap,
                    "discover_running_deployment",
                    return_value=discovered,
                ),
                mock.patch.object(bootstrap, "stop_any_p2p_update_control"),
                mock.patch.object(bootstrap, "ensure_update_control_plane") as ensure_control,
            ):
                result = bootstrap.command_adopt_running(args, source)

            self.assertEqual(result, 0)
            self.assertEqual(bootstrap.load_state(runtime)["webPort"], 8082)
            self.assertFalse((runtime / ".git").exists())
            self.assertFalse((runtime / "frontend/.env.local").exists())
            self.assertEqual(
                bootstrap.registered_deployment_root(source),
                runtime.resolve(),
            )
            ensure_control.assert_called_once_with(runtime)


if __name__ == "__main__":
    unittest.main()
