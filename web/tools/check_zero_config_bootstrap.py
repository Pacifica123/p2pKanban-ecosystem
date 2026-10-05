#!/usr/bin/env python3
"""Static and executable checks for the zero-config bootstrap patch."""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def service_block(compose_text: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    start = compose_text.find(marker)
    require(start >= 0, f"compose service is missing: {service_name}")
    remainder = compose_text[start + len(marker) :]
    boundaries = [
        index
    for name in ("bootstrap-init", "postgres", "backend", "web", "gateway")
        if name != service_name
        for index in [remainder.find(f"\n  {name}:\n")]
        if index >= 0
    ]
    end = min(boundaries) if boundaries else len(remainder)
    return remainder[:end]


def check_python() -> None:
    for relative in (
        "bootstrap.py",
        "tools/check_production_images.py",
        "tools/container_bootstrap.py",
        "tools/update_control_plane.py",
    ):
        path = ROOT / relative
        ast.parse(path.read_text(encoding="utf-8"), filename=relative)

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "bootstrap.py",
            "start",
            "--dry-run",
            "--no-open",
            "--port",
            "18088",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(result.returncode == 0, result.stdout)
    require("http://127.0.0.1:18088" in result.stdout, result.stdout)
    require("POSTGRES" not in result.stdout or "внутри Docker" in result.stdout, result.stdout)

    update_watch = subprocess.run(
        [sys.executable, "-B", "bootstrap.py", "watch-updates", "--dry-run"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(update_watch.returncode == 0, update_watch.stdout)
    require("8765" in update_watch.stdout, update_watch.stdout)

    update_plan = subprocess.run(
        [
            sys.executable,
            "-B",
            "bootstrap.py",
            "update",
            "--dry-run",
            "--source-dir",
            ".",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(update_plan.returncode == 0, update_plan.stdout)
    require("PostgreSQL backup" in update_plan.stdout, update_plan.stdout)
    require("Docker volumes" in update_plan.stdout, update_plan.stdout)

    control_tests = subprocess.run(
        [sys.executable, "-B", "tools/test_update_control_plane.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(control_tests.returncode == 0, control_tests.stdout)

    adoption_tests = subprocess.run(
        [sys.executable, "-B", "tools/test_runtime_adoption.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(adoption_tests.returncode == 0, adoption_tests.stdout)

    windows_tests = subprocess.run(
        [sys.executable, "-B", "tools/test_windows_bootstrap.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(windows_tests.returncode == 0, windows_tests.stdout)


def check_compose_contract() -> None:
    compose_path = ROOT / "deploy/bootstrap/compose.yaml"
    text = compose_path.read_text(encoding="utf-8")
    postgres = service_block(text, "postgres")
    backend = service_block(text, "backend")
    web = service_block(text, "web")
    gateway = service_block(text, "gateway")
    init = service_block(text, "bootstrap-init")

    require("POSTGRES_PASSWORD_FILE:" in postgres, "PostgreSQL must use a secret file")
    require("POSTGRES_USER: p2pkanban" in postgres, "managed PostgreSQL role is missing")
    require("POSTGRES_DB: p2pkanban" in postgres, "managed PostgreSQL DB is missing")
    require("\n    ports:" not in postgres, "PostgreSQL must not publish a host port")
    require("\n    ports:" not in backend, "backend must not publish a host port")
    require("\n    ports:" not in web, "versioned web must stay on the Docker network")
    require("\n    ports:" in gateway, "stable gateway must publish the only host port")
    require("service_completed_successfully" in init + postgres + backend, "init ordering is missing")
    require('entrypoint: ["/bin/sh", "-ec"]' in init, "init must use an inline POSIX script")
    require("ensure_secret" in init, "inline secret initialization is missing")
    require("./init-secrets.sh" not in init, "Windows-sensitive init bind mount is forbidden")
    require("bootstrap_secrets:" in text, "persistent secret volume is missing")
    require("postgres_data:" in text, "persistent PostgreSQL volume is missing")
    require(
        "image: p2pkanban/backend:${P2PKANBAN_IMAGE_TAG:-local}" in backend,
        "backend does not use a rollback-safe versioned image tag",
    )
    require(
        "image: p2pkanban/web:${P2PKANBAN_IMAGE_TAG:-local}" in web,
        "web does not use a rollback-safe versioned image tag",
    )
    require(
        "image: p2pkanban/gateway:local" in gateway,
        "gateway must keep a stable image identity across app switches",
    )
    require("VITE_API_BASE_URL: /api/v1" in web, "frontend API must be same-origin")
    require(
        "VITE_SOURCE_REVISION: ${P2PKANBAN_SOURCE_REVISION:-unknown}" in web,
        "frontend image must embed the running source revision",
    )
    require("change-me" not in text.lower(), "compose contains a placeholder secret")
    require("POSTGRES_PASSWORD:" not in text, "compose must not embed a DB password")
    require("AUTH__JWT_SECRET:" not in text, "compose must not embed a JWT secret")


def check_images_and_proxy() -> None:
    required = (
        "deploy/bootstrap/backend-entrypoint.sh",
        "deploy/bootstrap/backend.Dockerfile",
        "deploy/bootstrap/frontend.Dockerfile",
        "deploy/bootstrap/nginx.conf",
        "deploy/bootstrap/gateway.Dockerfile",
        "deploy/bootstrap/gateway.conf",
        "deploy/bootstrap/maintenance.html",
    )
    for relative in required:
        require((ROOT / relative).is_file(), f"missing {relative}")

    entrypoint = (ROOT / "deploy/bootstrap/backend-entrypoint.sh").read_text(encoding="utf-8")
    require("DATABASE__URL=" in entrypoint, "backend entrypoint does not construct DATABASE__URL")
    require("AUTH__JWT_SECRET=" in entrypoint, "backend entrypoint does not load JWT secret")
    require("echo \"$" not in entrypoint, "entrypoint may print a secret")

    nginx = (ROOT / "deploy/bootstrap/nginx.conf").read_text(encoding="utf-8")
    require("location /api/" in nginx, "Nginx API proxy is missing")
    require("proxy_pass http://backend:18080" in nginx, "Nginx backend target is wrong")
    require("try_files $uri $uri/ /index.html" in nginx, "SPA fallback is missing")

    gateway = (ROOT / "deploy/bootstrap/gateway.conf").read_text(encoding="utf-8")
    require("resolver 127.0.0.11" in gateway, "gateway needs dynamic Docker DNS")
    require("proxy_pass http://$web_upstream:8080" in gateway, "gateway web proxy is missing")
    require("proxy_pass http://$backend_upstream:18080" in gateway, "gateway API proxy is missing")
    require("location = /healthz" in gateway, "gateway needs an exact readiness route")
    health_start = gateway.index("location = /healthz")
    health_end = gateway.index("\n    }", health_start)
    require(
        "error_page" not in gateway[health_start:health_end],
        "readiness must not turn an upstream failure into maintenance HTTP 200",
    )
    require("error_page 502 503 504 =200 /maintenance.html" in gateway, "maintenance fallback is missing")

    maintenance = (ROOT / "deploy/bootstrap/maintenance.html").read_text(encoding="utf-8")
    require("127.0.0.1:8765/v1/status" in maintenance, "maintenance progress polling is missing")


def check_update_control_contract() -> None:
    bootstrap = (ROOT / "tools/container_bootstrap.py").read_text(encoding="utf-8")
    control = (ROOT / "tools/update_control_plane.py").read_text(encoding="utf-8")
    reminders = (
        ROOT / "frontend/src/features/reminders/lib/localReminders.ts"
    ).read_text(encoding="utf-8")

    require(
        bootstrap.count('get("scriptSha256") == desired_script_sha') >= 2,
        "bootstrap must verify the exact loaded control-plane script",
    )
    switch_start = bootstrap.index('print("Переключаю backend и web')
    switch_end = bootstrap.index("ready =", switch_start)
    switch_block = bootstrap[switch_start:switch_end]
    require('"backend"' in switch_block and '"web"' in switch_block, "update switch scope is incomplete")
    require('"--remove-orphans"' not in switch_block, "gateway must remain up during app switch")
    for table in (
        "users",
        "workspaces",
        "boards",
        "board_columns",
        "cards",
        "board_labels",
        "card_labels",
        "checklists",
        "checklist_items",
        "comments",
        "user_appearance_preferences",
        "board_appearance_settings",
        "tombstones",
        "roaming_board_events",
    ):
        require(f'"{table}"' in bootstrap, f"update data count is missing: {table}")

    require('"-u"' in control, "UI updater child process must stream progress")
    require("loaded_script_sha256" in control, "control-plane health lacks loaded script identity")
    require("ThreadingHTTPServer((\"127.0.0.1\", port)" in control, "control plane must bind loopback only")
    require("secrets.compare_digest" in control, "mutating update calls must verify a random token")
    require("origin in self.app.allowed_origins()" in control, "control plane must enforce exact web origins")
    require("Git HEAD is therefore not evidence" in control, "update identity must describe the running image")
    require('"adopt-running"' in bootstrap, "legacy Compose adoption command is missing")
    require("registered_deployment_root" in bootstrap, "source/runtime delegation is missing")
    require("postgres_data" in bootstrap and "bootstrap_secrets" in bootstrap, "adoption must pin both data volumes")
    update_api = (
        ROOT / "frontend/src/features/system/api/updateControl.ts"
    ).read_text(encoding="utf-8")
    require("api.github.com/repos/Pacifica123/p2p_planner/commits/main" in update_api, "web update fallback is missing")
    require("VITE_SOURCE_REVISION" in update_api, "web update fallback lacks running revision identity")
    update_surface = (
        ROOT / "frontend/src/features/system/components/SourceUpdateSurface.tsx"
    ).read_text(encoding="utf-8")
    require("python bootstrap.py watch-updates" in update_surface, "web fallback must not restart containers")
    devctl = (ROOT / "tools/devctl.py").read_text(encoding="utf-8")
    require('"watch-updates"' in devctl, "devctl push must wake the web update surface")
    require("userId: string" in reminders, "web reminders must be scoped by authenticated user")
    require("item.userId === userId" in reminders, "web reminder reads are not user-isolated")


def check_manifest_and_readme() -> None:
    cargo = tomllib.loads((ROOT / "backend/Cargo.toml").read_text(encoding="utf-8"))
    require(
        cargo.get("package", {}).get("default-run") == "p2p-planner-backend",
        "Cargo default-run does not select the backend binary",
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    require("python bootstrap.py" in readme, "README has no primary bootstrap command")
    require("docs/deployment/zero-config-bootstrap-v1.md" in readme, "README has no bootstrap runbook link")
    require(len(readme.splitlines()) <= 220, "README became dense again")

    release_builder = (ROOT / "tools/build_release_bundle.py").read_text(
        encoding="utf-8"
    )
    require(
        '"gitRepository": public_github_repository(' in release_builder,
        "release bundle does not embed its public update repository",
    )
    require(
        '"updateEntrypoint": "python bootstrap.py update"' in release_builder,
        "release bundle does not advertise the update entrypoint",
    )


def optional_compose_validation(
    *,
    require_docker: bool = False,
    bootstrap_init_smoke: bool = False,
) -> None:
    docker = shutil.which("docker")
    if not docker:
        require(not require_docker, "docker CLI is required")
        print("SKIP docker compose config: docker CLI is not installed")
        return
    version = subprocess.run(
        [docker, "compose", "version"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if version.returncode != 0:
        require(not require_docker, "Docker Compose v2 is required")
        print("SKIP docker compose config: Compose v2 is not available")
        return
    env = os.environ.copy()
    env.update(
        {
            "P2PKANBAN_WEB_PORT": "18088",
            "P2PKANBAN_BIND_ADDRESS": "127.0.0.1",
        }
    )
    project_name = f"p2pkanban-bootstrap-check-{os.getpid()}"
    compose = [
        docker,
        "compose",
        "--project-name",
        project_name,
        "--file",
        "deploy/bootstrap/compose.yaml",
    ]
    result = subprocess.run(
        compose + ["config", "--quiet"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(result.returncode == 0, result.stdout)
    print("OK docker compose config")

    if not bootstrap_init_smoke:
        return

    try:
        smoke = subprocess.run(
            compose + ["run", "--rm", "--no-deps", "bootstrap-init"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        require(smoke.returncode == 0, smoke.stdout)
        require("bootstrap secrets are ready" in smoke.stdout, smoke.stdout)
        print("OK isolated bootstrap-init smoke")
    finally:
        subprocess.run(
            compose + ["down", "--volumes", "--remove-orphans"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def check_frontend_production_build() -> None:
    npm = shutil.which("npm")
    require(npm is not None, "npm is required for --frontend-build")
    source = ROOT / "frontend"
    with tempfile.TemporaryDirectory(prefix="p2pkanban-bootstrap-frontend-") as raw:
        temporary = Path(raw)
        checkout = temporary / "frontend"
        checkout.mkdir()
        for name in (
            "package.json",
            "package-lock.json",
            "tsconfig.json",
            "tsconfig.node.json",
            "vite.config.ts",
            "index.html",
        ):
            shutil.copy2(source / name, checkout / name)
        shutil.copytree(source / "src", checkout / "src")

        env = os.environ.copy()
        env.update(
            {
                "NPM_CONFIG_CACHE": str(temporary / "npm-cache"),
                "VITE_API_BASE_URL": "/api/v1",
                "VITE_ENABLE_PROJECT_ROADMAP_SEED": "true",
            }
        )
        for command in ([npm, "ci"], [npm, "run", "test:run"], [npm, "run", "build"]):
            from devbootstrap import command_for_subprocess

            result = subprocess.run(
                command_for_subprocess(command),
                cwd=checkout,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            require(result.returncode == 0, result.stdout)
        require((checkout / "dist/index.html").is_file(), "frontend dist/index.html is missing")
    print("OK frontend tests and production build with /api/v1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--frontend-build",
        action="store_true",
        help="Also run npm ci, frontend tests and the production Vite build in a temporary copy.",
    )
    parser.add_argument(
        "--require-docker",
        action="store_true",
        help="Fail instead of skipping when Docker Compose v2 is unavailable.",
    )
    parser.add_argument(
        "--bootstrap-init-smoke",
        action="store_true",
        help="Run bootstrap-init in an isolated temporary Compose project and volume.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = (
        ("python CLI", check_python),
        ("compose isolation and secrets", check_compose_contract),
        ("container images and gateway", check_images_and_proxy),
        ("UI update and local reminder contract", check_update_control_contract),
        ("Cargo and README contract", check_manifest_and_readme),
        (
            "optional Compose parser",
            lambda: optional_compose_validation(
                require_docker=args.require_docker or args.bootstrap_init_smoke,
                bootstrap_init_smoke=args.bootstrap_init_smoke,
            ),
        ),
    )
    for name, check in checks:
        check()
        if not name.startswith("optional"):
            print(f"OK {name}")
    if args.frontend_build:
        check_frontend_production_build()
    print("zero-config bootstrap checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
