#!/usr/bin/env python3
"""
devbootstrap — local development diagnostics and bootstrap helpers for p2p_planner.

Commands:
    python tools/devbootstrap.py diagnose
    python tools/devbootstrap.py diagnose --no-write-report
    python tools/devbootstrap.py plan
    python tools/devbootstrap.py prepare-env
    python tools/devbootstrap.py start-db
    python tools/devbootstrap.py diagnose --section postgres
    python tools/devbootstrap.py check-backend
    python tools/devbootstrap.py start-backend
    python tools/devbootstrap.py prepare-frontend
    python tools/devbootstrap.py start-frontend
    python tools/devbootstrap.py up
    python tools/devbootstrap.py smoke
    python tools/devbootstrap.py status
    python tools/devbootstrap.py stop
    python tools/devbootstrap.py self-check

The tool intentionally uses only Python standard library modules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_VERSION = "2.0.1-draft"
STATE_VERSION = 1
REPORT_SCHEMA_VERSION = 1
TIMEOUT_POLICY = {
    "probe_command": 5,
    "port_probe": 0.4,
    "http_probe": 1.5,
    "postgres_ready": 60,
    "cargo_metadata": 60,
    "cargo_check": 240,
    "backend_ready": 180,
    "npm_install": 300,
    "frontend_ready": 120,
    "smoke_step": 600,
    "up_step": 120,
    "stop_grace": 10,
    "release_gate": 600,
}
BOOTSTRAP_DIR_NAME = ".dev-bootstrap"
FRONTEND_PREPARE_DEP_MODES = ("never", "missing", "stale", "missing-or-stale", "always")
DEFAULT_FRONTEND_PREPARE_DEP_MODE = "stale"
DEFAULT_PORTS = {
    "postgres": 5432,
    "backend": 18080,
    "frontend": 5173,
}

RELEASE_GATES_MANAGED_BACKEND_GATE_NAMES = {
    "backend_python_smoke_first",
    "backend_python_smoke_second",
    "browser_real_backend_path",
    "frontend_browser_smoke",
    "frontend_uiux_boot",
    "frontend_uiux_real_backend_core_flow",
}
RELEASE_GATES_MANAGED_FRONTEND_GATE_NAMES = {
    "frontend_browser_smoke",
    "browser_real_backend_path",
    "frontend_uiux_boot",
    "frontend_uiux_real_backend_core_flow",
}
REQUIRED_PROJECT_PATHS = [
    "backend",
    "frontend",
    "docs",
    "docker-compose.dev.yml",
    "backend/Cargo.toml",
    "backend/.env.example",
    "backend/build.rs",
    "backend/migrations",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/.env.example",
    "docs/dev-bootstrap/dev-autodeployer-v1-development-plan.md",
]
OPTIONAL_PROJECT_PATHS = [
    "tools/devctl.py",
    "docs/devctl/devctl-patch-conveyor-spec.md",
    "backend/tests/smoke_core_api.py",
    "frontend/playwright.config.ts",
]
TOOL_COMMANDS = {
    "python": [sys.executable, "--version"],
    "git": ["git", "--version"],
    "cargo": ["cargo", "--version"],
    "rustc": ["rustc", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "docker": ["docker", "--version"],
    "docker_compose": ["docker", "compose", "version"],
    "docker_compose_legacy": ["docker-compose", "version"],
    "psql": ["psql", "--version"],
    "pg_isready": ["pg_isready", "--version"],
}
COMPOSE_FILE = "docker-compose.dev.yml"
POSTGRES_SERVICE_NAME = "postgres"
POSTGRES_CONTAINER_NAME = "p2p-planner-postgres-dev"

HEALTH_URLS = {
    "backend_health_root": "http://127.0.0.1:18080/health",
    "backend_health_api": "http://127.0.0.1:18080/api/v1/health",
    "frontend_root": "http://127.0.0.1:5173/",
}
ENV_CONTRACTS = {
    "backend": {
        "example": "backend/.env.example",
        "target": "backend/.env",
        "description": "Backend runtime environment",
    },
    "frontend": {
        "example": "frontend/.env.example",
        "target": "frontend/.env.local",
        "description": "Frontend Vite local environment",
    },
}
SECRET_KEY_MARKERS = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "COOKIE",
    "DATABASE__URL",
    "DATABASE_URL",
)


@dataclass
class CommandProbe:
    name: str
    command: list[str]
    available: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


@dataclass
class PortProbe:
    name: str
    host: str
    port: int
    open: bool
    error: str | None = None


@dataclass
class HttpProbe:
    name: str
    url: str
    reachable: bool
    status: int | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class ProjectPathProbe:
    path: str
    exists: bool
    kind: str
    required: bool


@dataclass
class EnvFileProbe:
    name: str
    description: str
    example_path: str
    target_path: str
    example_exists: bool
    target_exists: bool
    example_keys: list[str]
    target_keys: list[str]
    missing_keys: list[str]
    extra_keys: list[str]
    masked_values: dict[str, str]
    parse_warnings: list[str] = field(default_factory=list)


@dataclass
class EnvConsistencyCheck:
    code: str
    status: str
    message: str
    evidence: str | None = None


@dataclass
class EnvAction:
    code: str
    status: str
    message: str
    path: str | None = None


@dataclass
class EnvPlanResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    mode: str
    files: list[EnvFileProbe] = field(default_factory=list)
    checks: list[EnvConsistencyCheck] = field(default_factory=list)
    actions: list[EnvAction] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    report_dir: str | None = None


@dataclass
class DatabaseUrlProbe:
    raw_present: bool
    masked_url: str | None = None
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    has_password: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProcessProbe:
    name: str
    command: list[str]
    available: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None


@dataclass
class PostgresCheck:
    code: str
    status: str
    message: str
    evidence: str | None = None


@dataclass
class PostgresAction:
    code: str
    status: str
    message: str
    command: str | None = None
    evidence: str | None = None


@dataclass
class PostgresResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    mode: str
    dry_run: bool = False
    database_url: DatabaseUrlProbe | None = None
    port: PortProbe | None = None
    psql: ProcessProbe | None = None
    pg_isready: ProcessProbe | None = None
    docker: ProcessProbe | None = None
    docker_daemon: ProcessProbe | None = None
    compose: ProcessProbe | None = None
    compose_command: list[str] = field(default_factory=list)
    compose_status: ProcessProbe | None = None
    docker_health: ProcessProbe | None = None
    classification: str = "unknown"
    checks: list[PostgresCheck] = field(default_factory=list)
    actions: list[PostgresAction] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    report_dir: str | None = None


@dataclass
class DiagnoseResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    platform: dict[str, str]
    paths: list[ProjectPathProbe] = field(default_factory=list)
    tools: list[CommandProbe] = field(default_factory=list)
    ports: list[PortProbe] = field(default_factory=list)
    http: list[HttpProbe] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    report_dir: str | None = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat(timespec="seconds")


def run_id(command: str) -> str:
    return now_utc().strftime("%Y%m%d_%H%M%S_") + command


def safe_decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    encodings = ["utf-8"]
    preferred = locale.getpreferredencoding(False)
    if preferred and preferred.lower() not in {encoding.lower() for encoding in encodings}:
        encodings.append(preferred)
    if os.name == "nt" and "cp1251" not in {encoding.lower() for encoding in encodings}:
        encodings.append("cp1251")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def resolve_executable_path(executable: str) -> str | None:
    if not executable:
        return None
    if executable == sys.executable:
        return executable
    if os.path.isabs(executable) or os.sep in executable or (os.altsep and os.altsep in executable):
        return executable if Path(executable).exists() else None
    return shutil.which(executable)


def command_for_subprocess(command: list[str], *, resolved_path: str | None = None, platform_name: str | None = None) -> list[str]:
    if not command:
        return command
    effective_platform = platform_name or os.name
    resolved = resolved_path if resolved_path is not None else resolve_executable_path(command[0])
    if not resolved:
        return command
    resolved_command = [resolved, *command[1:]]
    if effective_platform == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        # Run batch launchers through cmd.exe, but keep `call`, the resolved
        # .cmd/.bat path, and the user arguments as separate argv entries.
        # Python will quote only the path-with-spaces in the final Windows
        # command line:
        #   cmd.exe /d /c call "C:\Program Files\nodejs\npm.CMD" --version
        # Passing one pre-quoted `/c` string would force Python to escape the
        # inner quotes as backslash-quote; cmd.exe does not treat backslash as a
        # quote escape there, so the quotes can become part of the executable
        # name and npm.cmd is reported as missing.
        return ["cmd.exe", "/d", "/c", "call", resolved, *command[1:]]
    return resolved_command


def command_resolution_details(command: list[str]) -> dict[str, Any]:
    resolved = resolve_executable_path(command[0]) if command else None
    execution_command = command_for_subprocess(command, resolved_path=resolved)
    return {
        "displayCommand": command_as_text(command),
        "resolvedExecutable": resolved,
        "executionCommand": command_as_text(execution_command),
    }


def print_header(title: str) -> None:
    print(f"\n== {title} ==")


def rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_error": f"invalid json: {exc}"}
    if isinstance(data, dict):
        return data
    return {"_error": "json root is not an object"}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def looks_like_project_root(path: Path) -> bool:
    return (
        (path / "backend").is_dir()
        and (path / "frontend").is_dir()
        and (path / "docs").is_dir()
        and (path / "docker-compose.dev.yml").is_file()
    )


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if looks_like_project_root(candidate):
            return candidate
        nested = candidate / "project"
        if looks_like_project_root(nested):
            return nested.resolve()
    return None


def project_path_probe(project_root: Path, relative_path: str, *, required: bool) -> ProjectPathProbe:
    path = project_root / relative_path
    if path.is_dir():
        kind = "dir"
    elif path.is_file():
        kind = "file"
    else:
        kind = "missing"
    return ProjectPathProbe(path=relative_path, exists=path.exists(), kind=kind, required=required)


def command_display(command: list[str]) -> str:
    return " ".join(command)


def run_probe_command(command: list[str], *, timeout: int = TIMEOUT_POLICY["probe_command"]) -> tuple[bool, str | None]:
    try:
        completed = subprocess.run(
            command_for_subprocess(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "command not found"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except OSError as exc:
        return False, str(exc)
    output = (safe_decode(completed.stdout).strip() or safe_decode(completed.stderr).strip()).splitlines()
    text = output[0] if output else f"exit code {completed.returncode}"
    if completed.returncode != 0:
        return False, text
    return True, text


def probe_tool(name: str, command: list[str]) -> CommandProbe:
    executable = command[0]
    path = sys.executable if executable == sys.executable else shutil.which(executable)
    if not path:
        return CommandProbe(name=name, command=command, available=False, error="not found on PATH")
    ok, text = run_probe_command(command)
    if ok:
        return CommandProbe(name=name, command=command, available=True, path=path, version=text)
    return CommandProbe(name=name, command=command, available=False, path=path, error=text)


def probe_port(name: str, port: int, host: str = "127.0.0.1", timeout: float = TIMEOUT_POLICY["port_probe"]) -> PortProbe:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return PortProbe(name=name, host=host, port=port, open=True)
    except OSError as exc:
        return PortProbe(name=name, host=host, port=port, open=False, error=str(exc))


def probe_http(name: str, url: str, timeout: float = TIMEOUT_POLICY["http_probe"]) -> HttpProbe:
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            duration_ms = int((time.monotonic() - started) * 1000)
            return HttpProbe(name=name, url=url, reachable=True, status=response.status, duration_ms=duration_ms)
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        # HTTP reached the server even if the response is not 2xx.
        return HttpProbe(name=name, url=url, reachable=True, status=exc.code, error=str(exc), duration_ms=duration_ms)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return HttpProbe(name=name, url=url, reachable=False, error=str(exc), duration_ms=duration_ms)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def procfs_process_details(pid: int) -> tuple[str | None, str | None, str | None]:
    proc_dir = Path("/proc") / str(pid)
    try:
        cwd = str((proc_dir / "cwd").resolve())
    except Exception as exc:
        cwd = None
        cwd_error = f"procfs cwd unavailable: {exc}"
    else:
        cwd_error = None
    try:
        raw_cmd = (proc_dir / "cmdline").read_bytes()
        command = raw_cmd.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except Exception as exc:
        command = None
        cmd_error = f"procfs cmdline unavailable: {exc}"
    else:
        cmd_error = None
    errors = "; ".join(part for part in [cwd_error, cmd_error] if part) or None
    return cwd, command, errors


def popen_process_group_kwargs() -> dict[str, Any]:
    """Return cross-platform kwargs that make later owned-process stop safer.

    POSIX starts a new session so `stop` can terminate the process group.
    Windows starts a new process group when the flag is available; `stop` then
    still uses PID-based termination because Python stdlib does not expose a
    complete process-tree API there.
    """
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags} if creationflags else {}
    return {"start_new_session": True}


def summarize_state(project_root: Path) -> dict[str, Any]:
    state_path = project_root / BOOTSTRAP_DIR_NAME / "state.json"
    state = read_json(state_path)
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    process_summary: dict[str, Any] = {}
    for name, value in processes.items():
        if not isinstance(value, dict):
            continue
        pid_raw = value.get("pid")
        try:
            pid = int(pid_raw)
        except (TypeError, ValueError):
            pid = -1
        process_summary[name] = {
            "pid": pid_raw,
            "alive": pid_alive(pid),
            "cwd": value.get("cwd"),
            "command": value.get("command"),
            "runId": value.get("runId"),
        }
    return {
        "statePath": rel(state_path, project_root),
        "exists": state_path.exists(),
        "valid": "_error" not in state,
        "error": state.get("_error"),
        "version": state.get("version"),
        "activeRunId": state.get("activeRunId"),
        "processes": process_summary,
        "lastReports": state.get("lastReports", []),
    }


def process_table_state(project_root: Path) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    state_path = project_root / BOOTSTRAP_DIR_NAME / "state.json"
    state = read_json(state_path)
    if "_error" in state:
        return state_path, state, {}
    processes_raw = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    processes = {
        str(name): dict(entry)
        for name, entry in processes_raw.items()
        if isinstance(entry, dict)
    }
    return state_path, state, processes


def build_diagnose(project_root: Path | None, invoked_from: Path) -> DiagnoseResult:
    result = DiagnoseResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        platform={
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "pythonExecutable": sys.executable,
        },
    )

    if project_root is None:
        result.failures.append(
            {
                "code": "invalid_project_root",
                "message": "Could not find a project root containing backend/, frontend/, docs/ and docker-compose.dev.yml.",
            }
        )
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        result.tools = [probe_tool(name, command) for name, command in TOOL_COMMANDS.items()]
        return result

    result.paths.extend(project_path_probe(project_root, path, required=True) for path in REQUIRED_PROJECT_PATHS)
    result.paths.extend(project_path_probe(project_root, path, required=False) for path in OPTIONAL_PROJECT_PATHS)
    result.tools = [probe_tool(name, command) for name, command in TOOL_COMMANDS.items()]
    result.ports = [probe_port(name, port) for name, port in DEFAULT_PORTS.items()]
    result.http = [probe_http(name, url) for name, url in HEALTH_URLS.items()]
    result.state = summarize_state(project_root)

    missing_required = [path.path for path in result.paths if path.required and not path.exists]
    if missing_required:
        result.failures.append(
            {
                "code": "missing_project_files",
                "message": "Required project files or directories are missing: " + ", ".join(missing_required),
            }
        )
        result.next_actions.append("Verify that the archive was extracted completely and that you are using the latest project state.")

    for tool in result.tools:
        if not tool.available and tool.name in {"cargo", "rustc", "node", "npm"}:
            result.warnings.append(
                {
                    "code": "missing_prerequisite",
                    "message": f"{tool.name} is not available; later phases will not be able to build or run all project layers.",
                }
            )
    if not any(tool.name == "docker" and tool.available for tool in result.tools):
        result.warnings.append(
            {
                "code": "docker_unavailable",
                "message": "Docker is not available; future start-db may need an existing PostgreSQL instead of compose.",
            }
        )

    backend_health = next((probe for probe in result.http if probe.name == "backend_health_api"), None)
    frontend_health = next((probe for probe in result.http if probe.name == "frontend_root"), None)
    if backend_health and not backend_health.reachable:
        result.next_actions.append("Backend is not reachable on http://127.0.0.1:18080 yet; this is expected before start-backend/up phases.")
    if frontend_health and not frontend_health.reachable:
        result.next_actions.append("Frontend is not reachable on http://127.0.0.1:5173 yet; this is expected before start-frontend/up phases.")

    return result


def as_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: as_jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, list):
        return [as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    return value


def result_status_from_payload(payload: dict[str, Any]) -> str:
    failures = payload.get("failures")
    warnings = payload.get("warnings")
    classification = str(payload.get("classification") or "")
    if isinstance(failures, list) and failures:
        return "failed"
    if classification in {"failed", "partial", "invalid_project_root", "state_invalid"}:
        return "failed"
    if isinstance(warnings, list) and warnings:
        return "warning"
    if classification in {"planned", "dry_run"}:
        return classification
    return "ok"


def write_report_json(path: Path, result: Any, *, command: str) -> None:
    payload = as_jsonable(result)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    payload.setdefault("schemaVersion", REPORT_SCHEMA_VERSION)
    payload.setdefault("toolVersion", payload.get("tool_version", TOOL_VERSION))
    payload.setdefault("generatedAt", payload.get("generated_at"))
    payload.setdefault("command", command)
    payload.setdefault("status", result_status_from_payload(payload))
    write_json(path, payload)


def create_report_dir(project_root: Path, command: str) -> Path:
    report_dir = project_root / BOOTSTRAP_DIR_NAME / "runs" / run_id(command)
    report_dir.mkdir(parents=True, exist_ok=False)
    return report_dir


def render_report(result: DiagnoseResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap diagnose report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append("")

    lines.append("## Platform")
    lines.append("")
    for key, value in result.platform.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")

    lines.append("## Project files")
    lines.append("")
    lines.append("| Status | Required | Kind | Path |")
    lines.append("|---|---:|---|---|")
    for item in result.paths:
        status = "OK" if item.exists else "MISSING"
        required = "yes" if item.required else "no"
        lines.append(f"| {status} | {required} | {item.kind} | `{item.path}` |")
    if not result.paths:
        lines.append("Project root was not found, so file checks were skipped.")
    lines.append("")

    lines.append("## Tools")
    lines.append("")
    lines.append("| Tool | Status | Version / error | Path |")
    lines.append("|---|---|---|---|")
    for tool in result.tools:
        status = "OK" if tool.available else "MISSING"
        version = tool.version or tool.error or ""
        path = tool.path or ""
        lines.append(f"| {tool.name} | {status} | `{version}` | `{path}` |")
    lines.append("")

    lines.append("## Ports")
    lines.append("")
    lines.append("| Name | Address | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for port in result.ports:
        status = "open" if port.open else "closed/unreachable"
        evidence = "tcp connect succeeded" if port.open else (port.error or "")
        lines.append(f"| {port.name} | `{port.host}:{port.port}` | {status} | `{evidence}` |")
    if not result.ports:
        lines.append("Port checks were skipped because project root was not found.")
    lines.append("")

    lines.append("## HTTP probes")
    lines.append("")
    lines.append("| Name | URL | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for probe in result.http:
        status = f"HTTP {probe.status}" if probe.reachable and probe.status is not None else "unreachable"
        evidence = probe.error or f"{probe.duration_ms} ms"
        lines.append(f"| {probe.name} | `{probe.url}` | {status} | `{evidence}` |")
    if not result.http:
        lines.append("HTTP probes were skipped because project root was not found.")
    lines.append("")

    lines.append("## State")
    lines.append("")
    if result.state:
        lines.append(f"- State file: `{result.state.get('statePath')}`")
        lines.append(f"- Exists: `{result.state.get('exists')}`")
        lines.append(f"- Valid: `{result.state.get('valid')}`")
        lines.append(f"- Active run: `{result.state.get('activeRunId')}`")
        processes = result.state.get("processes", {})
        if processes:
            lines.append("")
            lines.append("| Process | PID | Alive | Command | CWD |")
            lines.append("|---|---:|---|---|---|")
            for name, process in processes.items():
                lines.append(
                    f"| {name} | {process.get('pid')} | {process.get('alive')} | "
                    f"`{process.get('command')}` | `{process.get('cwd')}` |"
                )
        else:
            lines.append("- No registered devbootstrap-owned processes.")
    else:
        lines.append("State was not checked.")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking findings from phase 1 diagnostics.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")

    lines.append("## Next safe actions")
    lines.append("")
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- Continue with the next devbootstrap phase or run project checks manually.")
    lines.append("")
    return "\n".join(lines)


def write_reports(project_root: Path, result: DiagnoseResult, command: str) -> Path:
    report_dir = create_report_dir(project_root, command)
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / "diagnose.json", result, command="diagnose")
    (report_dir / "report.md").write_text(render_report(result), encoding="utf-8")
    return report_dir




def is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_KEY_MARKERS)


def mask_database_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except Exception:
        return "***"
    if not parsed.scheme or not parsed.netloc:
        return "***"
    username = urllib.parse.unquote(parsed.username or "")
    password = parsed.password
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    if username and password is not None:
        netloc = f"{username}:***@{host}{port}"
    elif username:
        netloc = f"{username}@{host}{port}"
    else:
        netloc = f"{host}{port}"
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def mask_value(key: str, value: str) -> str:
    if key.upper() in {"DATABASE__URL", "DATABASE_URL"}:
        return mask_database_url(value)
    if is_secret_key(key):
        return "***" if value else ""
    return value


def parse_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    warnings: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values, warnings
    except UnicodeDecodeError as exc:
        return values, [f"could not decode as UTF-8: {exc}"]

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            warnings.append(f"line {line_number}: ignored non KEY=VALUE line")
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            warnings.append(f"line {line_number}: ignored empty key")
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values, warnings


def env_effective_values(example_values: dict[str, str], target_values: dict[str, str]) -> dict[str, str]:
    effective = dict(example_values)
    effective.update(target_values)
    return effective


def parse_url_port(url: str) -> int | None:
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    if parsed.port:
        return parsed.port
    if parsed.scheme == "http":
        return 80
    if parsed.scheme == "https":
        return 443
    return None


def parse_url_origin(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_env_file_probe(project_root: Path, name: str, contract: dict[str, str]) -> tuple[EnvFileProbe, dict[str, str], dict[str, str]]:
    example_rel = contract["example"]
    target_rel = contract["target"]
    example_path = project_root / example_rel
    target_path = project_root / target_rel
    example_values, example_warnings = parse_env_file(example_path)
    target_values, target_warnings = parse_env_file(target_path)

    example_keys = sorted(example_values)
    target_keys = sorted(target_values)
    missing_keys = sorted(key for key in example_keys if key not in target_values) if target_path.exists() else example_keys
    extra_keys = sorted(key for key in target_keys if key not in example_values)
    effective = env_effective_values(example_values, target_values)
    masked_values = {key: mask_value(key, value) for key, value in sorted(effective.items())}
    warnings: list[str] = []
    warnings.extend(f"example: {message}" for message in example_warnings)
    warnings.extend(f"target: {message}" for message in target_warnings)

    return (
        EnvFileProbe(
            name=name,
            description=contract["description"],
            example_path=example_rel,
            target_path=target_rel,
            example_exists=example_path.exists(),
            target_exists=target_path.exists(),
            example_keys=example_keys,
            target_keys=target_keys,
            missing_keys=missing_keys,
            extra_keys=extra_keys,
            masked_values=masked_values,
            parse_warnings=warnings,
        ),
        example_values,
        target_values,
    )


def check_env_consistency(
    backend_example: dict[str, str],
    backend_target: dict[str, str],
    frontend_example: dict[str, str],
    frontend_target: dict[str, str],
) -> list[EnvConsistencyCheck]:
    checks: list[EnvConsistencyCheck] = []
    backend = env_effective_values(backend_example, backend_target)
    frontend = env_effective_values(frontend_example, frontend_target)

    app_host = backend.get("APP__HOST", "127.0.0.1")
    app_port = backend.get("APP__PORT", "18080")
    try:
        int(app_port)
        checks.append(
            EnvConsistencyCheck(
                code="backend_port_parse",
                status="ok",
                message="APP__PORT is a valid integer.",
                evidence=f"APP__HOST={app_host}, APP__PORT={app_port}",
            )
        )
    except ValueError:
        checks.append(
            EnvConsistencyCheck(
                code="backend_port_parse",
                status="fail",
                message="APP__PORT is not a valid integer.",
                evidence=f"APP__PORT={app_port}",
            )
        )

    database_url = backend.get("DATABASE__URL", "")
    if database_url:
        try:
            parsed_db = urllib.parse.urlsplit(database_url)
            db_name = parsed_db.path.lstrip("/") or "<missing>"
            if parsed_db.scheme and parsed_db.hostname and db_name != "<missing>":
                checks.append(
                    EnvConsistencyCheck(
                        code="database_url_shape",
                        status="ok",
                        message="DATABASE__URL has scheme, host and database name.",
                        evidence=mask_database_url(database_url),
                    )
                )
            else:
                checks.append(
                    EnvConsistencyCheck(
                        code="database_url_shape",
                        status="warn",
                        message="DATABASE__URL is present but looks incomplete.",
                        evidence=mask_database_url(database_url),
                    )
                )
        except Exception as exc:
            checks.append(
                EnvConsistencyCheck(
                    code="database_url_shape",
                    status="fail",
                    message="DATABASE__URL could not be parsed.",
                    evidence=str(exc),
                )
            )
    else:
        checks.append(
            EnvConsistencyCheck(
                code="database_url_shape",
                status="fail",
                message="DATABASE__URL is missing.",
            )
        )

    api_base = frontend.get("VITE_API_BASE_URL", "")
    if api_base:
        api_port = parse_url_port(api_base)
        if str(api_port) == str(app_port):
            checks.append(
                EnvConsistencyCheck(
                    code="frontend_api_backend_port_match",
                    status="ok",
                    message="VITE_API_BASE_URL points to the configured backend port.",
                    evidence=f"VITE_API_BASE_URL={api_base}, APP__PORT={app_port}",
                )
            )
        else:
            checks.append(
                EnvConsistencyCheck(
                    code="frontend_api_backend_port_match",
                    status="warn",
                    message="VITE_API_BASE_URL does not point to the configured backend port.",
                    evidence=f"VITE_API_BASE_URL={api_base}, APP__PORT={app_port}",
                )
            )
        if api_base.rstrip("/").endswith("/api/v1"):
            checks.append(
                EnvConsistencyCheck(
                    code="frontend_api_base_path",
                    status="ok",
                    message="VITE_API_BASE_URL ends with /api/v1.",
                    evidence=api_base,
                )
            )
        else:
            checks.append(
                EnvConsistencyCheck(
                    code="frontend_api_base_path",
                    status="warn",
                    message="VITE_API_BASE_URL should normally end with /api/v1 for this project.",
                    evidence=api_base,
                )
            )
    else:
        checks.append(
            EnvConsistencyCheck(
                code="frontend_api_base_path",
                status="fail",
                message="VITE_API_BASE_URL is missing.",
            )
        )

    allowed_origins = split_csv(backend.get("HTTP__CORS_ALLOWED_ORIGINS", ""))
    expected_origins = {"http://localhost:5173", "http://127.0.0.1:5173"}
    present_expected = sorted(expected_origins.intersection(allowed_origins))
    if present_expected:
        checks.append(
            EnvConsistencyCheck(
                code="cors_frontend_origin",
                status="ok",
                message="CORS allowed origins include a default Vite dev origin.",
                evidence=", ".join(present_expected),
            )
        )
    else:
        checks.append(
            EnvConsistencyCheck(
                code="cors_frontend_origin",
                status="warn",
                message="CORS allowed origins do not include the default Vite dev origins.",
                evidence=backend.get("HTTP__CORS_ALLOWED_ORIGINS", "<missing>"),
            )
        )

    dev_header_auth = backend.get("AUTH__ENABLE_DEV_HEADER_AUTH", "").strip().lower()
    if dev_header_auth == "false":
        checks.append(
            EnvConsistencyCheck(
                code="dev_header_auth_baseline",
                status="ok",
                message="AUTH__ENABLE_DEV_HEADER_AUTH=false baseline is preserved.",
            )
        )
    elif dev_header_auth == "true":
        checks.append(
            EnvConsistencyCheck(
                code="dev_header_auth_baseline",
                status="warn",
                message="AUTH__ENABLE_DEV_HEADER_AUTH=true; keep this local-only and do not treat it as beta/self-host baseline.",
            )
        )
    else:
        checks.append(
            EnvConsistencyCheck(
                code="dev_header_auth_baseline",
                status="warn",
                message="AUTH__ENABLE_DEV_HEADER_AUTH is missing or not explicitly false.",
                evidence=f"AUTH__ENABLE_DEV_HEADER_AUTH={backend.get('AUTH__ENABLE_DEV_HEADER_AUTH', '<missing>')}",
            )
        )

    return checks


def build_env_plan(project_root: Path | None, invoked_from: Path, *, mode: str) -> EnvPlanResult:
    result = EnvPlanResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        mode=mode,
    )
    if project_root is None:
        result.failures.append(
            {
                "code": "invalid_project_root",
                "message": "Could not find a project root containing backend/, frontend/, docs/ and docker-compose.dev.yml.",
            }
        )
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        return result

    parsed: dict[str, tuple[dict[str, str], dict[str, str]]] = {}
    for name, contract in ENV_CONTRACTS.items():
        probe, example_values, target_values = build_env_file_probe(project_root, name, contract)
        result.files.append(probe)
        parsed[name] = (example_values, target_values)
        if not probe.example_exists:
            result.failures.append(
                {
                    "code": "missing_env_example",
                    "message": f"Required env example is missing: {probe.example_path}",
                }
            )
        if not probe.target_exists:
            result.actions.append(
                EnvAction(
                    code="create_env_file",
                    status="planned" if mode == "plan" else "pending",
                    message=f"Create {probe.target_path} from {probe.example_path}.",
                    path=probe.target_path,
                )
            )
        elif probe.missing_keys:
            result.actions.append(
                EnvAction(
                    code="env_missing_keys",
                    status="manual" if mode == "plan" else "skipped",
                    message=(
                        f"{probe.target_path} exists but misses {len(probe.missing_keys)} key(s): "
                        + ", ".join(probe.missing_keys)
                    ),
                    path=probe.target_path,
                )
            )
        else:
            result.actions.append(
                EnvAction(
                    code="env_file_ok",
                    status="ok",
                    message=f"{probe.target_path} exists and contains all example keys.",
                    path=probe.target_path,
                )
            )
        if probe.extra_keys:
            result.warnings.append(
                {
                    "code": "env_extra_keys",
                    "message": f"{probe.target_path} contains extra key(s): " + ", ".join(probe.extra_keys),
                }
            )
        for warning in probe.parse_warnings:
            result.warnings.append(
                {
                    "code": "env_parse_warning",
                    "message": f"{probe.target_path}: {warning}",
                }
            )

    backend_example, backend_target = parsed.get("backend", ({}, {}))
    frontend_example, frontend_target = parsed.get("frontend", ({}, {}))
    result.checks = check_env_consistency(backend_example, backend_target, frontend_example, frontend_target)
    for check in result.checks:
        if check.status == "fail":
            result.failures.append({"code": check.code, "message": check.message})
        elif check.status == "warn":
            result.warnings.append({"code": check.code, "message": check.message})

    if any(action.code == "create_env_file" for action in result.actions):
        result.next_actions.append("Run `python tools/devbootstrap.py prepare-env` to create missing local env files from examples.")
    if any(action.code == "env_missing_keys" for action in result.actions):
        result.next_actions.append(
            "Review missing env keys. Existing files are not overwritten; use `prepare-env --add-missing-keys` to append example defaults with a backup."
        )
    if not result.next_actions:
        result.next_actions.append("Env baseline looks ready for later start-db/start-backend/start-frontend phases.")
    return result


def backup_file(path: Path) -> Path:
    stamp = now_utc().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(path.name + f".bootstrap-backup.{stamp}")
    shutil.copy2(path, backup)
    return backup


def append_missing_env_keys(target_path: Path, example_values: dict[str, str], target_values: dict[str, str]) -> list[str]:
    missing = [key for key in example_values if key not in target_values]
    if not missing:
        return []
    lines = ["", f"# Added by devbootstrap on {iso_now()} from env example."]
    for key in missing:
        lines.append(f"{key}={example_values[key]}")
    with target_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    return missing


def apply_prepare_env(project_root: Path, *, add_missing_keys: bool) -> list[EnvAction]:
    actions: list[EnvAction] = []
    for name, contract in ENV_CONTRACTS.items():
        example_path = project_root / contract["example"]
        target_path = project_root / contract["target"]
        if not example_path.exists():
            actions.append(
                EnvAction(
                    code="missing_env_example",
                    status="failed",
                    message=f"Cannot prepare {contract['target']} because {contract['example']} is missing.",
                    path=contract["target"],
                )
            )
            continue
        if not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example_path, target_path)
            actions.append(
                EnvAction(
                    code="created_env_file",
                    status="done",
                    message=f"Created {contract['target']} from {contract['example']}.",
                    path=contract["target"],
                )
            )
            continue
        example_values, _ = parse_env_file(example_path)
        target_values, _ = parse_env_file(target_path)
        missing = [key for key in example_values if key not in target_values]
        if missing and add_missing_keys:
            backup = backup_file(target_path)
            appended = append_missing_env_keys(target_path, example_values, target_values)
            actions.append(
                EnvAction(
                    code="appended_missing_env_keys",
                    status="done",
                    message=(
                        f"Appended {len(appended)} missing key(s) to {contract['target']} after backup "
                        f"{rel(backup, project_root)}: " + ", ".join(appended)
                    ),
                    path=contract["target"],
                )
            )
        elif missing:
            actions.append(
                EnvAction(
                    code="missing_env_keys_not_modified",
                    status="skipped",
                    message=(
                        f"{contract['target']} exists and misses {len(missing)} key(s), but existing env files are not changed "
                        "without --add-missing-keys."
                    ),
                    path=contract["target"],
                )
            )
        else:
            actions.append(
                EnvAction(
                    code="env_file_unchanged",
                    status="ok",
                    message=f"{contract['target']} already exists and contains all example keys.",
                    path=contract["target"],
                )
            )
    return actions


def render_env_report(result: EnvPlanResult) -> str:
    title = "devbootstrap prepare-env report" if result.mode == "prepare-env" else "devbootstrap plan report"
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Mode: `{result.mode}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append("")

    lines.append("## Env files")
    lines.append("")
    lines.append("| Name | Example | Target | Target exists | Missing keys | Extra keys |")
    lines.append("|---|---|---|---|---:|---:|")
    for item in result.files:
        lines.append(
            f"| {item.name} | `{item.example_path}` | `{item.target_path}` | {item.target_exists} | "
            f"{len(item.missing_keys)} | {len(item.extra_keys)} |"
        )
    if not result.files:
        lines.append("Env files were not checked because project root was not found.")
    lines.append("")

    for item in result.files:
        lines.append(f"### {item.name}: {item.description}")
        lines.append("")
        lines.append(f"- Example exists: `{item.example_exists}`")
        lines.append(f"- Target exists: `{item.target_exists}`")
        if item.missing_keys:
            lines.append("- Missing keys: `" + "`, `".join(item.missing_keys) + "`")
        else:
            lines.append("- Missing keys: none")
        if item.extra_keys:
            lines.append("- Extra keys: `" + "`, `".join(item.extra_keys) + "`")
        else:
            lines.append("- Extra keys: none")
        if item.parse_warnings:
            lines.append("- Parse warnings:")
            for warning in item.parse_warnings:
                lines.append(f"  - {warning}")
        lines.append("")
        lines.append("Masked effective values:")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("|---|---|")
        for key, value in item.masked_values.items():
            lines.append(f"| `{key}` | `{value}` |")
        if not item.masked_values:
            lines.append("| _none_ | _none_ |")
        lines.append("")

    lines.append("## Consistency checks")
    lines.append("")
    lines.append("| Status | Code | Message | Evidence |")
    lines.append("|---|---|---|---|")
    for check in result.checks:
        lines.append(f"| {check.status} | `{check.code}` | {check.message} | `{check.evidence or ''}` |")
    if not result.checks:
        lines.append("| skipped | `no_project_root` | Checks were skipped. | |")
    lines.append("")

    lines.append("## Actions")
    lines.append("")
    if result.actions:
        for action in result.actions:
            path = f" `{action.path}`" if action.path else ""
            lines.append(f"- `{action.status}` `{action.code}`{path} — {action.message}")
    else:
        lines.append("- No actions.")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking env findings.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")

    lines.append("## Next safe actions")
    lines.append("")
    for action in result.next_actions:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_env_reports(project_root: Path, result: EnvPlanResult, command: str) -> Path:
    report_dir = create_report_dir(project_root, command)
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / f"{command}.json", result, command=command)
    (report_dir / "report.md").write_text(render_env_report(result), encoding="utf-8")
    return report_dir


def print_env_summary(result: EnvPlanResult) -> None:
    print_header(f"devbootstrap {result.mode}")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    if result.files:
        print("\nEnv files:")
        for item in result.files:
            print(
                f"  - {item.name}: target={'exists' if item.target_exists else 'missing'}, "
                f"missing_keys={len(item.missing_keys)}, extra_keys={len(item.extra_keys)}"
            )
    if result.checks:
        print("\nConsistency:")
        for check in result.checks:
            label = check.status.upper()
            print(f"  - {label} {check.code}: {check.message}")
    if result.actions:
        print("\nActions:")
        for action in result.actions:
            print(f"  - {action.status.upper()} {action.code}: {action.message}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking env findings")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_plan(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_env_plan(project_root, invoked_from, mode="plan")
    if project_root is not None and not args.no_write_report:
        write_env_reports(project_root, result, "plan")
    print_env_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if any(failure.get("code") == "invalid_project_root" for failure in result.failures) else 0


def command_prepare_env(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    if project_root is None:
        result = build_env_plan(project_root, invoked_from, mode="prepare-env")
        print_env_summary(result)
        return 1
    applied_actions = apply_prepare_env(project_root, add_missing_keys=args.add_missing_keys)
    result = build_env_plan(project_root, invoked_from, mode="prepare-env")
    result.actions = applied_actions + result.actions
    if not any(action.status == "failed" for action in applied_actions):
        result.next_actions.insert(0, "Run `python tools/devbootstrap.py plan` to review the effective masked env baseline.")
    if not args.no_write_report:
        write_env_reports(project_root, result, "prepare-env")
    print_env_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if any(action.status == "failed" for action in applied_actions) else 0


def run_process_probe(
    name: str,
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 10,
    env_extra: dict[str, str] | None = None,
) -> ProcessProbe:
    executable = command[0]
    if resolve_executable_path(executable) is None:
        return ProcessProbe(name=name, command=command, available=False, error="not found on PATH")
    execution_command = command_for_subprocess(command)
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        completed = subprocess.run(
            execution_command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return ProcessProbe(name=name, command=command, available=False, error="command not found")
    except subprocess.TimeoutExpired as exc:
        return ProcessProbe(
            name=name,
            command=command,
            available=True,
            returncode=None,
            stdout=safe_decode(exc.stdout).strip(),
            stderr=safe_decode(exc.stderr).strip(),
            error="timeout",
        )
    except OSError as exc:
        return ProcessProbe(name=name, command=command, available=False, error=str(exc))
    return ProcessProbe(
        name=name,
        command=command,
        available=True,
        returncode=completed.returncode,
        stdout=safe_decode(completed.stdout).strip(),
        stderr=safe_decode(completed.stderr).strip(),
    )


def process_probe_ok(probe: ProcessProbe | None) -> bool:
    return bool(probe and probe.available and probe.returncode == 0)


def first_output_line(probe: ProcessProbe | None) -> str:
    if probe is None:
        return ""
    text = probe.stdout or probe.stderr or probe.error or ""
    return text.splitlines()[0] if text else ""


def command_as_text(command: list[str] | None) -> str:
    if not command:
        return ""
    return subprocess.list2cmdline([str(part) for part in command])


def effective_env_values_for(project_root: Path, name: str) -> dict[str, str]:
    contract = ENV_CONTRACTS[name]
    example_values, _ = parse_env_file(project_root / contract["example"])
    target_values, _ = parse_env_file(project_root / contract["target"])
    return env_effective_values(example_values, target_values)


def default_port_for_database_scheme(scheme: str | None) -> int | None:
    if scheme in {"postgres", "postgresql"}:
        return 5432
    return None


def parse_database_url_probe(value: str | None) -> DatabaseUrlProbe:
    if not value:
        return DatabaseUrlProbe(raw_present=False, warnings=["DATABASE__URL is missing or empty"])
    warnings: list[str] = []
    try:
        parsed = urllib.parse.urlsplit(value)
    except Exception as exc:
        return DatabaseUrlProbe(raw_present=True, masked_url="***", warnings=[f"could not parse DATABASE__URL: {exc}"])
    scheme = parsed.scheme or None
    host = parsed.hostname or None
    port = parsed.port or default_port_for_database_scheme(scheme)
    database = parsed.path.lstrip("/") or None
    username = urllib.parse.unquote(parsed.username or "") or None
    if scheme not in {"postgres", "postgresql"}:
        warnings.append(f"unexpected database URL scheme: {scheme or '<missing>'}")
    if not host:
        warnings.append("database host is missing")
    if not port:
        warnings.append("database port is missing")
    if not database:
        warnings.append("database name is missing")
    if not username:
        warnings.append("database username is missing")
    return DatabaseUrlProbe(
        raw_present=True,
        masked_url=mask_database_url(value),
        scheme=scheme,
        host=host,
        port=port,
        database=database,
        username=username,
        has_password=parsed.password is not None,
        warnings=warnings,
    )


def psql_env_from_database_url(value: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(value)
    env: dict[str, str] = {}
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    elif default_port_for_database_scheme(parsed.scheme):
        env["PGPORT"] = str(default_port_for_database_scheme(parsed.scheme))
    if parsed.username:
        env["PGUSER"] = urllib.parse.unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = urllib.parse.unquote(parsed.password)
    database = parsed.path.lstrip("/")
    if database:
        env["PGDATABASE"] = database
    return env


def sanitize_postgres_output(text: str, db_url: str | None) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if db_url:
        cleaned = cleaned.replace(db_url, mask_database_url(db_url))
        try:
            parsed = urllib.parse.urlsplit(db_url)
            if parsed.password:
                cleaned = cleaned.replace(urllib.parse.unquote(parsed.password), "***")
        except Exception:
            pass
    return "\n".join(cleaned.splitlines()[:6])


def classify_psql_failure(probe: ProcessProbe, db_url: str | None) -> str:
    text = sanitize_postgres_output((probe.stderr or probe.stdout or probe.error or ""), db_url).lower()
    if "password authentication failed" in text or "authentication failed" in text:
        return "auth_failed"
    if "role" in text and "does not exist" in text:
        return "auth_failed"
    if "database" in text and "does not exist" in text:
        return "db_missing"
    if "connection refused" in text or "could not connect" in text:
        return "port_closed"
    if "timeout" in text:
        return "connect_timeout"
    return "psql_failed"


def probe_psql_database(db_url: str | None, project_root: Path) -> ProcessProbe:
    if not db_url:
        return ProcessProbe(name="psql", command=["psql"], available=False, error="DATABASE__URL is missing")
    env_extra = psql_env_from_database_url(db_url)
    command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", "select current_database() || '|' || current_user"]
    probe = run_process_probe("psql", command, cwd=project_root, timeout=8, env_extra=env_extra)
    probe.stdout = sanitize_postgres_output(probe.stdout, db_url)
    probe.stderr = sanitize_postgres_output(probe.stderr, db_url)
    return probe


def probe_pg_isready(db_url: str | None, project_root: Path) -> ProcessProbe:
    if not db_url:
        return ProcessProbe(name="pg_isready", command=["pg_isready"], available=False, error="DATABASE__URL is missing")
    env_extra = psql_env_from_database_url(db_url)
    command = ["pg_isready"]
    if "PGHOST" in env_extra:
        command.extend(["-h", env_extra["PGHOST"]])
    if "PGPORT" in env_extra:
        command.extend(["-p", env_extra["PGPORT"]])
    if "PGUSER" in env_extra:
        command.extend(["-U", env_extra["PGUSER"]])
    if "PGDATABASE" in env_extra:
        command.extend(["-d", env_extra["PGDATABASE"]])
    probe = run_process_probe("pg_isready", command, cwd=project_root, timeout=8, env_extra=env_extra)
    probe.stdout = sanitize_postgres_output(probe.stdout, db_url)
    probe.stderr = sanitize_postgres_output(probe.stderr, db_url)
    return probe


def detect_compose_command(project_root: Path) -> tuple[list[str], ProcessProbe]:
    docker_compose = run_process_probe("docker_compose", ["docker", "compose", "version"], cwd=project_root, timeout=8)
    if process_probe_ok(docker_compose):
        return ["docker", "compose"], docker_compose
    legacy = run_process_probe("docker_compose_legacy", ["docker-compose", "version"], cwd=project_root, timeout=8)
    if process_probe_ok(legacy):
        return ["docker-compose"], legacy
    evidence_parts = []
    for probe in (docker_compose, legacy):
        evidence = first_output_line(probe)
        if evidence:
            evidence_parts.append(f"{probe.name}: {evidence}")
    return [], ProcessProbe(
        name="compose",
        command=["docker", "compose", "version"],
        available=False,
        error="; ".join(evidence_parts) or "Docker Compose is not available",
    )


def compose_base_command(compose_command: list[str], project_root: Path) -> list[str]:
    return [*compose_command, "-f", str(project_root / COMPOSE_FILE)]


def probe_compose_status(project_root: Path, compose_command: list[str]) -> ProcessProbe:
    if not compose_command:
        return ProcessProbe(name="compose_status", command=[], available=False, error="compose command is unavailable")
    command = [*compose_base_command(compose_command, project_root), "ps", POSTGRES_SERVICE_NAME]
    return run_process_probe("compose_status", command, cwd=project_root, timeout=12)


def probe_postgres_container_health(project_root: Path) -> ProcessProbe:
    command = ["docker", "inspect", "--format", "{{json .State.Health}}", POSTGRES_CONTAINER_NAME]
    return run_process_probe("docker_health", command, cwd=project_root, timeout=8)


def classify_postgres_state(
    db_url_probe: DatabaseUrlProbe | None,
    port_probe: PortProbe | None,
    psql_probe: ProcessProbe | None,
) -> str:
    if db_url_probe is None or not db_url_probe.raw_present or db_url_probe.warnings:
        return "database_url_invalid"
    if psql_probe and process_probe_ok(psql_probe):
        return "ready"
    if port_probe and not port_probe.open:
        return "port_closed"
    if psql_probe and psql_probe.available and psql_probe.returncode not in (0, None):
        return classify_psql_failure(psql_probe, db_url_probe.masked_url)
    if port_probe and port_probe.open and (psql_probe is None or not psql_probe.available):
        return "port_open_unverified"
    return "unknown"


def build_postgres_checks(result: PostgresResult, db_url: str | None) -> None:
    if result.database_url is None or not result.database_url.raw_present:
        result.checks.append(PostgresCheck("database_url", "fail", "DATABASE__URL is missing."))
    elif result.database_url.warnings:
        result.checks.append(
            PostgresCheck(
                "database_url",
                "warn",
                "DATABASE__URL was parsed but has suspicious fields.",
                "; ".join(result.database_url.warnings),
            )
        )
    else:
        result.checks.append(
            PostgresCheck(
                "database_url",
                "ok",
                "DATABASE__URL points to a PostgreSQL target.",
                f"host={result.database_url.host}, port={result.database_url.port}, db={result.database_url.database}, user={result.database_url.username}, url={result.database_url.masked_url}",
            )
        )

    if result.port:
        result.checks.append(
            PostgresCheck(
                "postgres_tcp_port",
                "ok" if result.port.open else "warn",
                f"TCP port {result.port.host}:{result.port.port} is {'open' if result.port.open else 'closed/unreachable'}.",
                "tcp connect succeeded" if result.port.open else (result.port.error or ""),
            )
        )

    if result.psql:
        if process_probe_ok(result.psql):
            result.checks.append(PostgresCheck("psql_probe", "ok", "psql can connect and run a tiny query.", result.psql.stdout))
        elif not result.psql.available:
            result.checks.append(PostgresCheck("psql_probe", "warn", "psql is not available; auth/db-name validation is limited.", result.psql.error))
        else:
            result.checks.append(
                PostgresCheck(
                    "psql_probe",
                    "fail",
                    "psql could not connect to the configured database.",
                    result.psql.stderr or result.psql.stdout or result.psql.error,
                )
            )

    if result.pg_isready:
        if process_probe_ok(result.pg_isready):
            result.checks.append(PostgresCheck("pg_isready", "ok", "pg_isready reports PostgreSQL as accepting connections.", result.pg_isready.stdout))
        elif not result.pg_isready.available:
            result.checks.append(PostgresCheck("pg_isready", "warn", "pg_isready is not available; readiness fallback skipped.", result.pg_isready.error))
        else:
            result.checks.append(PostgresCheck("pg_isready", "warn", "pg_isready did not report a ready server.", result.pg_isready.stderr or result.pg_isready.stdout))

    if result.compose_status:
        status = "ok" if process_probe_ok(result.compose_status) else "warn"
        result.checks.append(PostgresCheck("compose_status", status, "docker compose service status probe completed.", result.compose_status.stdout or result.compose_status.stderr or result.compose_status.error))
    if result.docker_health:
        status = "ok" if process_probe_ok(result.docker_health) else "warn"
        result.checks.append(PostgresCheck("docker_health", status, "Docker container health probe completed.", result.docker_health.stdout or result.docker_health.stderr or result.docker_health.error))


def build_postgres_result(project_root: Path | None, invoked_from: Path, *, mode: str, dry_run: bool = False) -> PostgresResult:
    result = PostgresResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        mode=mode,
        dry_run=dry_run,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        return result

    backend_env = effective_env_values_for(project_root, "backend")
    db_url = backend_env.get("DATABASE__URL")
    result.database_url = parse_database_url_probe(db_url)
    host = result.database_url.host or "127.0.0.1"
    port = result.database_url.port or DEFAULT_PORTS["postgres"]
    result.port = probe_port("postgres", port, host=host)
    result.psql = probe_psql_database(db_url, project_root)
    result.pg_isready = probe_pg_isready(db_url, project_root)
    result.docker = run_process_probe("docker", ["docker", "--version"], cwd=project_root, timeout=8)
    result.docker_daemon = run_process_probe("docker_daemon", ["docker", "info", "--format", "{{.ServerVersion}}"], cwd=project_root, timeout=12)
    result.compose_command, result.compose = detect_compose_command(project_root)
    if result.compose_command:
        result.compose_status = probe_compose_status(project_root, result.compose_command)
    if process_probe_ok(result.docker):
        result.docker_health = probe_postgres_container_health(project_root)

    result.classification = classify_postgres_state(result.database_url, result.port, result.psql)
    build_postgres_checks(result, db_url)

    if result.classification == "ready":
        result.next_actions.append("PostgreSQL is reachable. Continue with `python tools/devbootstrap.py check-backend` in Phase 4.")
    elif result.classification == "port_closed":
        result.next_actions.append("PostgreSQL port is closed. Run `python tools/devbootstrap.py start-db` to try docker compose postgres.")
    elif result.classification == "port_open_unverified":
        result.warnings.append({"code": "postgres_unverified", "message": "Port is open, but psql is unavailable, so auth/db-name were not verified."})
        result.next_actions.append("Install psql or verify DATABASE__URL manually before backend startup.")
    elif result.classification in {"auth_failed", "db_missing"}:
        result.failures.append({"code": result.classification, "message": "Configured PostgreSQL is reachable but does not accept the configured credentials/database."})
        result.next_actions.append("Fix backend/.env DATABASE__URL or prepare the expected database/user before starting backend.")
    elif result.classification == "database_url_invalid":
        result.failures.append({"code": "database_url_invalid", "message": "DATABASE__URL is missing or invalid."})
        result.next_actions.append("Run `python tools/devbootstrap.py prepare-env` and review backend/.env.")
    else:
        result.warnings.append({"code": "postgres_state_unknown", "message": "PostgreSQL state could not be classified confidently."})
        result.next_actions.append("Review the report evidence before starting backend.")
    return result


def refresh_postgres_after_start(result: PostgresResult, project_root: Path, db_url: str | None) -> None:
    if not result.database_url:
        return
    host = result.database_url.host or "127.0.0.1"
    port = result.database_url.port or DEFAULT_PORTS["postgres"]
    result.port = probe_port("postgres", port, host=host)
    result.psql = probe_psql_database(db_url, project_root)
    result.pg_isready = probe_pg_isready(db_url, project_root)
    if result.compose_command:
        result.compose_status = probe_compose_status(project_root, result.compose_command)
    if process_probe_ok(result.docker):
        result.docker_health = probe_postgres_container_health(project_root)
    result.classification = classify_postgres_state(result.database_url, result.port, result.psql)
    result.checks = []
    build_postgres_checks(result, db_url)


def apply_start_db(result: PostgresResult, project_root: Path, *, timeout_seconds: int) -> None:
    backend_env = effective_env_values_for(project_root, "backend")
    db_url = backend_env.get("DATABASE__URL")

    if result.classification == "ready":
        result.actions.append(PostgresAction("start_db_noop", "ok", "Configured PostgreSQL is already reachable; compose start skipped."))
        return
    if result.classification not in {"port_closed"}:
        result.actions.append(
            PostgresAction(
                "start_db_skipped",
                "skipped",
                "Port is not closed, so devbootstrap will not start compose to avoid interfering with an existing/foreign PostgreSQL.",
            )
        )
        return
    if result.dry_run:
        compose_cmd = result.compose_command or ["docker", "compose"]
        command = [*compose_base_command(compose_cmd, project_root), "up", "-d", POSTGRES_SERVICE_NAME]
        result.actions.append(PostgresAction("compose_up", "planned", "Would start postgres through docker compose because the configured port is closed.", command_as_text(command)))
        if not process_probe_ok(result.docker):
            result.warnings.append({"code": "docker_unavailable", "message": "Docker CLI is unavailable right now; real start-db would fail until Docker is installed."})
        elif not process_probe_ok(result.docker_daemon):
            result.warnings.append({"code": "docker_daemon_unavailable", "message": "Docker daemon is unavailable right now; real start-db would fail until Docker is running."})
        if not result.compose_command:
            result.warnings.append({"code": "compose_unavailable", "message": "Docker Compose is unavailable right now; real start-db would fail until Compose is installed."})
        return
    if not process_probe_ok(result.docker):
        result.failures.append({"code": "docker_unavailable", "message": "Docker CLI is unavailable; cannot start compose postgres."})
        result.actions.append(PostgresAction("compose_up", "failed", "Docker CLI is unavailable."))
        return
    if not process_probe_ok(result.docker_daemon):
        evidence = first_output_line(result.docker_daemon)
        result.failures.append({"code": "docker_daemon_unavailable", "message": "Docker daemon is unavailable; cannot start compose postgres."})
        result.actions.append(PostgresAction("compose_up", "failed", "Docker daemon is unavailable.", evidence=evidence))
        return
    if not result.compose_command:
        result.failures.append({"code": "compose_unavailable", "message": "Docker Compose is unavailable; cannot start compose postgres."})
        result.actions.append(PostgresAction("compose_up", "failed", "Docker Compose is unavailable.", evidence=first_output_line(result.compose)))
        return

    command = [*compose_base_command(result.compose_command, project_root), "up", "-d", POSTGRES_SERVICE_NAME]
    started = run_process_probe("compose_up", command, cwd=project_root, timeout=max(30, timeout_seconds))
    if process_probe_ok(started):
        result.actions.append(PostgresAction("compose_up", "done", "Started postgres through docker compose.", command_as_text(command), started.stdout or started.stderr))
    else:
        result.failures.append({"code": "compose_up_failed", "message": "docker compose up failed."})
        result.actions.append(PostgresAction("compose_up", "failed", "docker compose up failed.", command_as_text(command), started.stderr or started.stdout or started.error))
        return

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        refresh_postgres_after_start(result, project_root, db_url)
        if result.classification == "ready" or (result.port and result.port.open and not result.psql.available):
            break
        time.sleep(2)
    refresh_postgres_after_start(result, project_root, db_url)
    if result.classification == "ready":
        result.actions.append(PostgresAction("wait_postgres", "done", "PostgreSQL became queryable before timeout."))
    elif result.port and result.port.open and result.psql and not result.psql.available:
        result.actions.append(PostgresAction("wait_postgres", "partial", "PostgreSQL TCP port opened, but psql is unavailable for auth/db verification."))
    else:
        result.failures.append({"code": "postgres_wait_timeout", "message": "PostgreSQL did not become ready before timeout."})
        result.actions.append(PostgresAction("wait_postgres", "failed", f"Timed out after {timeout_seconds} seconds.", evidence=result.classification))


def render_postgres_report(result: PostgresResult) -> str:
    lines: list[str] = []
    title = "devbootstrap start-db report" if result.mode == "start-db" else "devbootstrap postgres diagnose report"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Mode: `{result.mode}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append("")

    lines.append("## Database target")
    lines.append("")
    if result.database_url:
        lines.append(f"- URL: `{result.database_url.masked_url or '<missing>'}`")
        lines.append(f"- Host: `{result.database_url.host or '<missing>'}`")
        lines.append(f"- Port: `{result.database_url.port or '<missing>'}`")
        lines.append(f"- Database: `{result.database_url.database or '<missing>'}`")
        lines.append(f"- User: `{result.database_url.username or '<missing>'}`")
        lines.append(f"- Password present: `{result.database_url.has_password}`")
        if result.database_url.warnings:
            lines.append("- Warnings:")
            for warning in result.database_url.warnings:
                lines.append(f"  - {warning}")
    else:
        lines.append("Database URL was not parsed.")
    lines.append("")

    lines.append("## Probes")
    lines.append("")
    lines.append("| Probe | Status | Evidence |")
    lines.append("|---|---|---|")
    if result.port:
        lines.append(f"| TCP `{result.port.host}:{result.port.port}` | {'open' if result.port.open else 'closed'} | `{result.port.error or 'tcp connect succeeded'}` |")
    for name, probe in [
        ("psql", result.psql),
        ("pg_isready", result.pg_isready),
        ("docker", result.docker),
        ("docker daemon", result.docker_daemon),
        ("compose", result.compose),
        ("compose status", result.compose_status),
        ("docker health", result.docker_health),
    ]:
        if probe is None:
            continue
        if not probe.available:
            status = "unavailable"
        elif probe.returncode == 0:
            status = "ok"
        elif probe.returncode is None:
            status = "unknown"
        else:
            status = f"exit {probe.returncode}"
        evidence = probe.stdout or probe.stderr or probe.error or ""
        lines.append(f"| {name} | {status} | `{evidence}` |")
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    lines.append("| Status | Code | Message | Evidence |")
    lines.append("|---|---|---|---|")
    for check in result.checks:
        lines.append(f"| {check.status} | `{check.code}` | {check.message} | `{check.evidence or ''}` |")
    if not result.checks:
        lines.append("| skipped | `no_checks` | Checks were skipped. | |")
    lines.append("")

    lines.append("## Actions")
    lines.append("")
    if result.actions:
        for action in result.actions:
            command = f" command=`{action.command}`" if action.command else ""
            evidence = f" Evidence: `{action.evidence}`" if action.evidence else ""
            lines.append(f"- `{action.status}` `{action.code}` — {action.message}{command}.{evidence}")
    else:
        lines.append("- No actions.")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking PostgreSQL findings.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")

    lines.append("## Next safe actions")
    lines.append("")
    for action in result.next_actions:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_postgres_reports(project_root: Path, result: PostgresResult, command: str) -> Path:
    report_dir = create_report_dir(project_root, command)
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / f"{command}.json", result, command=command)
    (report_dir / "report.md").write_text(render_postgres_report(result), encoding="utf-8")
    return report_dir


def print_postgres_summary(result: PostgresResult) -> None:
    print_header(f"devbootstrap {result.mode}")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Classification: {result.classification}")
    if result.database_url:
        print(
            "Database: "
            f"host={result.database_url.host or '<missing>'} "
            f"port={result.database_url.port or '<missing>'} "
            f"db={result.database_url.database or '<missing>'} "
            f"user={result.database_url.username or '<missing>'} "
            f"url={result.database_url.masked_url or '<missing>'}"
        )
    if result.port:
        print(f"TCP: {result.port.host}:{result.port.port} {'open' if result.port.open else 'closed'}")
    print("\nChecks:")
    for check in result.checks:
        label = check.status.upper()
        evidence = f" — {check.evidence}" if check.evidence else ""
        print(f"  - {label} {check.code}: {check.message}{evidence}")
    if result.actions:
        print("\nActions:")
        for action in result.actions:
            print(f"  - {action.status.upper()} {action.code}: {action.message}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking PostgreSQL findings")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_diagnose_postgres(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_postgres_result(project_root, invoked_from, mode="diagnose-postgres")
    if project_root is not None and not args.no_write_report:
        write_postgres_reports(project_root, result, "diagnose-postgres")
    print_postgres_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.classification == "invalid_project_root" else 0


def command_start_db(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_postgres_result(project_root, invoked_from, mode="start-db", dry_run=args.dry_run)
    if project_root is not None:
        apply_start_db(result, project_root, timeout_seconds=args.timeout_seconds)
    if project_root is not None and not args.no_write_report:
        write_postgres_reports(project_root, result, "start-db")
    print_postgres_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0


@dataclass
class BackendCheck:
    code: str
    status: str
    message: str
    evidence: str | None = None


@dataclass
class BackendAction:
    code: str
    status: str
    message: str
    command: str | None = None
    evidence: str | None = None


@dataclass
class BackendResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    mode: str
    dry_run: bool = False
    backend_host: str | None = None
    backend_port: int | None = None
    backend_port_parse_error: str | None = None
    backend_port_probe: PortProbe | None = None
    health: list[HttpProbe] = field(default_factory=list)
    state_backend: dict[str, Any] = field(default_factory=dict)
    cargo_version: ProcessProbe | None = None
    rustc_version: ProcessProbe | None = None
    cargo_metadata: ProcessProbe | None = None
    cargo_check: ProcessProbe | None = None
    process_pid: int | None = None
    process_alive: bool | None = None
    process_returncode: int | None = None
    run_id: str | None = None
    log_path: str | None = None
    classification: str = "unknown"
    checks: list[BackendCheck] = field(default_factory=list)
    actions: list[BackendAction] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    report_dir: str | None = None


def backend_effective_env(project_root: Path) -> dict[str, str]:
    return effective_env_values_for(project_root, "backend")


def parse_backend_host_port(project_root: Path) -> tuple[str, int, str | None]:
    values = backend_effective_env(project_root)
    host = values.get("APP__HOST", "127.0.0.1") or "127.0.0.1"
    raw_port = values.get("APP__PORT", str(DEFAULT_PORTS["backend"])) or str(DEFAULT_PORTS["backend"])
    try:
        port = int(raw_port)
    except ValueError:
        return host, DEFAULT_PORTS["backend"], f"APP__PORT is not an integer: {raw_port}"
    if port <= 0 or port > 65535:
        return host, DEFAULT_PORTS["backend"], f"APP__PORT is outside TCP port range: {raw_port}"
    return host, port, None


def http_probe_host(bind_host: str | None) -> str:
    if bind_host in {None, "", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return str(bind_host)


def backend_health_urls(host: str | None, port: int | None) -> dict[str, str]:
    probe_host = http_probe_host(host)
    probe_port = port or DEFAULT_PORTS["backend"]
    return {
        "backend_health_root": f"http://{probe_host}:{probe_port}/health",
        "backend_health_api": f"http://{probe_host}:{probe_port}/api/v1/health",
    }


def probe_backend_health(host: str | None, port: int | None, *, timeout: float = 1.5) -> list[HttpProbe]:
    return [probe_http(name, url, timeout=timeout) for name, url in backend_health_urls(host, port).items()]


def backend_health_ready(probes: list[HttpProbe]) -> bool:
    expected = {"backend_health_root", "backend_health_api"}
    seen = {probe.name for probe in probes if probe.reachable and probe.status and 200 <= probe.status < 300}
    return expected.issubset(seen)


def command_output_text(probe: ProcessProbe | None) -> str:
    if probe is None:
        return ""
    return "\n".join(part for part in [probe.stdout, probe.stderr, probe.error or ""] if part).strip()


def tail_text(text: str, *, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def read_log_tail(path: Path | None, *, max_chars: int = 20000) -> str:
    if path is None or not path.exists():
        return ""
    try:
        return tail_text(path.read_text(encoding="utf-8", errors="replace"), max_chars=max_chars)
    except OSError as exc:
        return f"<could not read log: {exc}>"


def sanitize_backend_log(text: str, project_root: Path | None = None) -> str:
    if not text:
        return ""
    cleaned = text
    if project_root is not None:
        db_url = backend_effective_env(project_root).get("DATABASE__URL")
        if db_url:
            cleaned = cleaned.replace(db_url, mask_database_url(db_url))
            try:
                parsed = urllib.parse.urlsplit(db_url)
                if parsed.password:
                    cleaned = cleaned.replace(urllib.parse.unquote(parsed.password), "***")
            except Exception:
                pass
    return "\n".join(cleaned.strip().splitlines()[-40:])


def classify_backend_failure(text: str, default: str) -> str:
    lower = text.lower()
    if "address already in use" in lower or "os error 98" in lower or "os error 10048" in lower:
        return "port_conflict"
    if "migration" in lower and "missing in the resolved migrations" in lower:
        return "migration_drift"
    if "migration" in lower and ("failed" in lower or "error" in lower):
        return "migration_failed"
    if "password authentication failed" in lower or "authentication failed" in lower:
        return "postgres_auth_failed"
    if "database" in lower and "does not exist" in lower:
        return "database_missing"
    if "connection refused" in lower or "could not connect" in lower or "connection error" in lower:
        return "postgres_unavailable"
    if "could not compile" in lower or "compilation failed" in lower or "error[" in lower:
        return "cargo_check_failed"
    if "timeout" in lower:
        return "backend_health_timeout"
    return default


def run_backend_command_probe(
    name: str,
    command: list[str],
    *,
    project_root: Path,
    cwd: Path,
    timeout: int,
    log_path: Path | None = None,
) -> ProcessProbe:
    probe = run_process_probe(name, command, cwd=cwd, timeout=timeout)
    if log_path is not None:
        lines = [
            f"$ {command_as_text(command)}",
            f"cwd: {rel(cwd, project_root)}",
            f"exit: {probe.returncode if probe.returncode is not None else probe.error or '<none>'}",
            "",
            "## stdout",
            probe.stdout or "<empty>",
            "",
            "## stderr",
            probe.stderr or probe.error or "<empty>",
            "",
        ]
        log_path.write_text("\n".join(lines), encoding="utf-8")
    return probe


def state_backend_entry(project_root: Path) -> dict[str, Any]:
    state = read_json(project_root / BOOTSTRAP_DIR_NAME / "state.json")
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    backend = processes.get("backend") if isinstance(processes.get("backend"), dict) else {}
    if not backend:
        return {}
    pid_raw = backend.get("pid")
    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        pid = -1
    backend = dict(backend)
    backend["alive"] = pid_alive(pid)
    return backend


def update_process_state(
    project_root: Path,
    *,
    process_name: str,
    pid: int,
    cwd: Path,
    command: list[str],
    started_at: str,
    run_id_value: str,
    log_path: Path | None,
    report_dir: Path | None,
) -> None:
    state_path = project_root / BOOTSTRAP_DIR_NAME / "state.json"
    state = read_json(state_path)
    if "_error" in state:
        state = {}
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    processes[process_name] = {
        "pid": pid,
        "cwd": rel(cwd, project_root),
        "command": command_as_text(command),
        "startedAt": started_at,
        "runId": run_id_value,
        "logPath": rel(log_path, project_root) if log_path else None,
    }
    state["version"] = STATE_VERSION
    state["activeRunId"] = run_id_value
    state["processes"] = processes
    last_reports = state.get("lastReports") if isinstance(state.get("lastReports"), list) else []
    if report_dir is not None:
        last_reports.append(rel(report_dir, project_root))
        state["lastReports"] = last_reports[-20:]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)


def build_backend_result(project_root: Path | None, invoked_from: Path, *, mode: str, dry_run: bool = False) -> BackendResult:
    result = BackendResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        mode=mode,
        dry_run=dry_run,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        return result

    host, port, port_error = parse_backend_host_port(project_root)
    result.backend_host = host
    result.backend_port = port
    result.backend_port_parse_error = port_error
    result.backend_port_probe = probe_port("backend", port, host=http_probe_host(host))
    result.health = probe_backend_health(host, port)
    result.state_backend = state_backend_entry(project_root)
    result.cargo_version = run_process_probe("cargo_version", ["cargo", "--version"], cwd=project_root, timeout=8)
    result.rustc_version = run_process_probe("rustc_version", ["rustc", "--version"], cwd=project_root, timeout=8)

    if port_error:
        result.warnings.append({"code": "backend_port_parse", "message": port_error})
    if result.state_backend:
        if result.state_backend.get("alive"):
            result.warnings.append(
                {
                    "code": "backend_process_registered",
                    "message": f"state.json already contains alive backend pid={result.state_backend.get('pid')}.",
                }
            )
        else:
            result.warnings.append(
                {
                    "code": "backend_stale_process",
                    "message": f"state.json contains stale backend pid={result.state_backend.get('pid')}; it is not alive.",
                }
            )
    return result


def add_backend_preflight_checks(result: BackendResult) -> None:
    if result.cargo_version:
        status = "ok" if process_probe_ok(result.cargo_version) else "fail"
        result.checks.append(BackendCheck("cargo_version", status, "Cargo availability check.", first_output_line(result.cargo_version)))
    if result.rustc_version:
        status = "ok" if process_probe_ok(result.rustc_version) else "fail"
        result.checks.append(BackendCheck("rustc_version", status, "Rust compiler availability check.", first_output_line(result.rustc_version)))
    if result.backend_port_probe:
        status = "warn" if result.backend_port_probe.open else "ok"
        message = f"Backend TCP port {result.backend_port_probe.host}:{result.backend_port_probe.port} is {'open' if result.backend_port_probe.open else 'closed/free'}."
        evidence = "tcp connect succeeded" if result.backend_port_probe.open else (result.backend_port_probe.error or "")
        result.checks.append(BackendCheck("backend_port_preflight", status, message, evidence))
    if result.health:
        for probe in result.health:
            status = "ok" if probe.reachable and probe.status and 200 <= probe.status < 300 else "warn"
            evidence = probe.error or (f"{probe.duration_ms} ms" if probe.duration_ms is not None else None)
            message = f"{probe.url} returned HTTP {probe.status}." if probe.reachable else f"{probe.url} is not reachable."
            result.checks.append(BackendCheck(probe.name, status, message, evidence))


def finalize_backend_check_classification(result: BackendResult, project_root: Path, *, operation: str) -> None:
    add_backend_preflight_checks(result)
    if not process_probe_ok(result.cargo_version):
        result.classification = "missing_prerequisite"
        result.failures.append({"code": "missing_cargo", "message": "cargo is not available on PATH."})
        result.next_actions.append("Install Rust/Cargo or use a shell where cargo is available, then rerun check-backend.")
        return
    if not process_probe_ok(result.rustc_version):
        result.classification = "missing_prerequisite"
        result.failures.append({"code": "missing_rustc", "message": "rustc is not available on PATH."})
        result.next_actions.append("Install Rust toolchain or repair PATH, then rerun check-backend.")
        return
    if result.cargo_metadata is not None:
        status = "ok" if process_probe_ok(result.cargo_metadata) else "fail"
        result.checks.append(BackendCheck("cargo_metadata", status, "cargo metadata completed.", first_output_line(result.cargo_metadata)))
        if not process_probe_ok(result.cargo_metadata):
            text = command_output_text(result.cargo_metadata)
            result.classification = classify_backend_failure(text, "cargo_metadata_failed")
            result.failures.append({"code": result.classification, "message": "cargo metadata failed."})
            result.next_actions.append("Review cargo-metadata.log and Cargo.toml/Cargo.lock before trying to run the backend.")
            return
    if result.cargo_check is not None:
        status = "ok" if process_probe_ok(result.cargo_check) else "fail"
        result.checks.append(BackendCheck("cargo_check", status, "cargo check completed.", first_output_line(result.cargo_check)))
        if not process_probe_ok(result.cargo_check):
            text = command_output_text(result.cargo_check)
            result.classification = classify_backend_failure(text, "cargo_check_failed")
            result.failures.append({"code": result.classification, "message": "cargo check failed."})
            result.next_actions.append("Fix the Rust compile error from cargo-check.log. Do not start backend until cargo check passes.")
            return
    if operation == "check-backend":
        result.classification = "backend_check_ok"
        result.next_actions.append("Backend compile preflight passed. Continue with `python tools/devbootstrap.py start-backend` when PostgreSQL is ready.")


def render_backend_report(result: BackendResult) -> str:
    lines: list[str] = []
    lines.append(f"# devbootstrap {result.mode} report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    if result.backend_host is not None and result.backend_port is not None:
        lines.append(f"- Backend bind/probe: `{result.backend_host}:{result.backend_port}`")
    if result.process_pid is not None:
        lines.append(f"- Backend PID: `{result.process_pid}`")
    if result.log_path:
        lines.append(f"- Backend log: `{result.log_path}`")
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    if result.checks:
        lines.append("| Status | Code | Message | Evidence |")
        lines.append("|---|---|---|---|")
        for check in result.checks:
            evidence = (check.evidence or "").replace("\n", "<br>")
            lines.append(f"| {check.status} | `{check.code}` | {check.message} | `{evidence}` |")
    else:
        lines.append("No checks recorded.")
    lines.append("")

    lines.append("## Actions")
    lines.append("")
    if result.actions:
        for action in result.actions:
            command = f" `{action.command}`" if action.command else ""
            evidence = f" Evidence: `{action.evidence}`" if action.evidence else ""
            lines.append(f"- **{action.status}** `{action.code}` — {action.message}{command}.{evidence}")
    else:
        lines.append("No actions were executed.")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No backend findings.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")

    lines.append("## Next safe actions")
    lines.append("")
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- Continue with the next devbootstrap phase.")
    lines.append("")
    return "\n".join(lines)


def write_backend_reports(project_root: Path, result: BackendResult, command: str, report_dir: Path | None = None) -> Path:
    if report_dir is None:
        report_dir = create_report_dir(project_root, command)
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / f"{command}.json", result, command=command)
    (report_dir / "report.md").write_text(render_backend_report(result), encoding="utf-8")
    return report_dir


def print_backend_summary(result: BackendResult) -> None:
    print_header(f"devbootstrap {result.mode}")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Classification: {result.classification}")
    if result.backend_host is not None and result.backend_port is not None:
        print(f"Backend target: {result.backend_host}:{result.backend_port}")
    if result.process_pid is not None:
        alive_text = "alive" if result.process_alive else "not alive"
        print(f"Backend process: pid={result.process_pid} {alive_text}")
    print("\nChecks:")
    for check in result.checks:
        evidence = f" — {check.evidence}" if check.evidence else ""
        print(f"  - {check.status.upper()} {check.code}: {check.message}{evidence}")
    if result.actions:
        print("\nActions:")
        for action in result.actions:
            command = f" — {action.command}" if action.command else ""
            evidence = f" — {action.evidence}" if action.evidence else ""
            print(f"  - {action.status.upper()} {action.code}: {action.message}{command}{evidence}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no backend findings")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_check_backend(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_backend_result(project_root, invoked_from, mode="check-backend", dry_run=args.dry_run)
    report_dir: Path | None = None
    if project_root is not None and not args.no_write_report:
        report_dir = create_report_dir(project_root, "check-backend")
        result.report_dir = rel(report_dir, project_root)
    if project_root is not None:
        backend_dir = project_root / "backend"
        if args.dry_run:
            result.actions.append(BackendAction("cargo_metadata", "planned", "Would run cargo metadata for backend.", "cargo metadata --format-version 1 --no-deps"))
            result.actions.append(BackendAction("cargo_check", "planned", "Would run cargo check for backend.", "cargo check"))
            result.classification = "dry_run"
            result.next_actions.append("Run without --dry-run to execute cargo metadata and cargo check.")
            add_backend_preflight_checks(result)
        else:
            metadata_log = report_dir / "cargo-metadata.log" if report_dir else None
            check_log = report_dir / "cargo-check.log" if report_dir else None
            result.cargo_metadata = run_backend_command_probe(
                "cargo_metadata",
                ["cargo", "metadata", "--format-version", "1", "--no-deps"],
                project_root=project_root,
                cwd=backend_dir,
                timeout=args.metadata_timeout_seconds,
                log_path=metadata_log,
            )
            if process_probe_ok(result.cargo_metadata):
                result.cargo_check = run_backend_command_probe(
                    "cargo_check",
                    ["cargo", "check"],
                    project_root=project_root,
                    cwd=backend_dir,
                    timeout=args.timeout_seconds,
                    log_path=check_log,
                )
            finalize_backend_check_classification(result, project_root, operation="check-backend")
    if project_root is not None and not args.no_write_report:
        write_backend_reports(project_root, result, "check-backend", report_dir)
    print_backend_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0


def launch_backend_process(project_root: Path, report_dir: Path) -> tuple[subprocess.Popen[Any], Path]:
    backend_dir = project_root / "backend"
    log_path = report_dir / "backend.log"
    command = ["cargo", "run", "--bin", "p2p-planner-backend"]
    execution_command = command_for_subprocess(command)
    log_handle = log_path.open("ab", buffering=0)
    header = "\n".join(
        [
            f"== devbootstrap start-backend {iso_now()} ==",
            f"$ {command_as_text(command)}",
            f"resolved: {command_as_text(execution_command)}",
            f"cwd: {rel(backend_dir, project_root)}",
            "",
        ]
    ).encode("utf-8", errors="replace")
    log_handle.write(header)
    try:
        process = subprocess.Popen(
            execution_command,
            cwd=str(backend_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            **popen_process_group_kwargs(),
        )
    except Exception:
        log_handle.close()
        raise
    # The child keeps the file descriptor open. The parent can close its copy.
    log_handle.close()
    return process, log_path


def wait_for_backend_health(process: subprocess.Popen[Any], host: str | None, port: int | None, *, timeout_seconds: int) -> tuple[bool, list[HttpProbe], int | None]:
    deadline = time.monotonic() + timeout_seconds
    last_probes: list[HttpProbe] = []
    while time.monotonic() < deadline:
        returncode = process.poll()
        last_probes = probe_backend_health(host, port, timeout=1.0)
        if backend_health_ready(last_probes):
            return True, last_probes, returncode
        if returncode is not None:
            return False, last_probes, returncode
        time.sleep(1.0)
    return False, last_probes, process.poll()


def command_start_backend(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_backend_result(project_root, invoked_from, mode="start-backend", dry_run=args.dry_run)
    report_dir: Path | None = None
    if project_root is not None and (not args.no_write_report or not args.dry_run):
        report_dir = create_report_dir(project_root, "start-backend")
        result.report_dir = rel(report_dir, project_root)

    if project_root is not None:
        add_backend_preflight_checks(result)
        if backend_health_ready(result.health):
            result.classification = "backend_already_running"
            result.actions.append(BackendAction("start_backend_noop", "ok", "Backend health is already reachable; cargo run was not started."))
            result.next_actions.append("Continue with frontend phases or run smoke checks.")
        elif result.backend_port_probe and result.backend_port_probe.open:
            result.classification = "port_conflict"
            result.failures.append({"code": "port_conflict", "message": "Backend port is open but health endpoints are not healthy. devbootstrap will not kill a foreign process."})
            result.next_actions.append("Inspect the process on the backend port manually, or stop the old backend you own and rerun start-backend.")
        elif not process_probe_ok(result.cargo_version):
            result.classification = "missing_prerequisite"
            result.failures.append({"code": "missing_cargo", "message": "cargo is not available on PATH."})
            result.next_actions.append("Install Rust/Cargo or use a shell where cargo is available, then rerun start-backend.")
        elif args.dry_run:
            result.classification = "dry_run"
            result.actions.append(BackendAction("cargo_run", "planned", "Would start the p2p-planner-backend binary with cargo run and wait for health.", "cargo run --bin p2p-planner-backend"))
            result.next_actions.append("Run without --dry-run when PostgreSQL is ready.")
        else:
            command = ["cargo", "run", "--bin", "p2p-planner-backend"]
            run_id_value = run_id("start-backend")
            result.run_id = run_id_value
            try:
                process, log_path = launch_backend_process(project_root, report_dir or create_report_dir(project_root, "start-backend"))
                if result.report_dir is None:
                    result.report_dir = rel(log_path.parent, project_root)
                result.process_pid = process.pid
                result.log_path = rel(log_path, project_root)
                result.actions.append(BackendAction("cargo_run", "started", "Started backend process with cargo run.", command_as_text(command), f"pid={process.pid}"))
                ready, probes, returncode = wait_for_backend_health(process, result.backend_host, result.backend_port, timeout_seconds=args.timeout_seconds)
                result.health = probes
                result.process_returncode = returncode
                result.process_alive = process.poll() is None
                if ready:
                    result.classification = "backend_started"
                    result.checks.append(BackendCheck("backend_health_wait", "ok", "Backend health endpoints became ready.", f"timeout={args.timeout_seconds}s"))
                    update_process_state(
                        project_root,
                        process_name="backend",
                        pid=process.pid,
                        cwd=project_root / "backend",
                        command=command,
                        started_at=result.generated_at,
                        run_id_value=run_id_value,
                        log_path=log_path,
                        report_dir=log_path.parent,
                    )
                    result.next_actions.append("Backend is running. Continue with frontend preparation/start phases.")
                else:
                    log_tail = sanitize_backend_log(read_log_tail(log_path), project_root)
                    default = "backend_start_failed" if returncode is not None else "backend_health_timeout"
                    result.classification = classify_backend_failure(log_tail, default)
                    result.checks.append(BackendCheck("backend_health_wait", "fail", "Backend health endpoints did not become ready.", f"timeout={args.timeout_seconds}s"))
                    result.failures.append({"code": result.classification, "message": "Backend did not reach healthy state after cargo run."})
                    if result.process_alive:
                        update_process_state(
                            project_root,
                            process_name="backend",
                            pid=process.pid,
                            cwd=project_root / "backend",
                            command=command,
                            started_at=result.generated_at,
                            run_id_value=run_id_value,
                            log_path=log_path,
                            report_dir=log_path.parent,
                        )
                        result.next_actions.append("Backend process is still alive but health timed out. Inspect backend.log, then run `python tools/devbootstrap.py stop` if the tracked backend must be cleaned up.")
                    else:
                        result.next_actions.append("Inspect backend.log for the classified failure before retrying.")
            except FileNotFoundError:
                result.classification = "missing_prerequisite"
                result.failures.append({"code": "missing_cargo", "message": "cargo run could not be started because cargo was not found."})
            except OSError as exc:
                result.classification = "backend_start_failed"
                result.failures.append({"code": "backend_start_failed", "message": f"Could not start cargo run: {exc}"})
    if project_root is not None and report_dir is not None:
        write_backend_reports(project_root, result, "start-backend", report_dir)
    print_backend_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0


@dataclass
class FrontendCheck:
    code: str
    status: str
    message: str
    evidence: str | None = None


@dataclass
class FrontendAction:
    code: str
    status: str
    message: str
    command: str | None = None
    evidence: str | None = None


@dataclass
class FrontendResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    mode: str
    dry_run: bool = False
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 5173
    frontend_url: str | None = None
    api_base_url: str | None = None
    package_json_exists: bool = False
    package_lock_exists: bool = False
    node_modules_exists: bool = False
    package_scripts: dict[str, str] = field(default_factory=dict)
    package_json_hash: str | None = None
    package_lock_hash: str | None = None
    install_marker_path: str | None = None
    install_marker_valid: bool = False
    install_command: list[str] = field(default_factory=list)
    node_version: ProcessProbe | None = None
    npm_version: ProcessProbe | None = None
    frontend_port_probe: PortProbe | None = None
    frontend_root_probe: HttpProbe | None = None
    api_probe: HttpProbe | None = None
    backend_health: list[HttpProbe] = field(default_factory=list)
    state_frontend: dict[str, Any] = field(default_factory=dict)
    process_pid: int | None = None
    process_alive: bool | None = None
    process_returncode: int | None = None
    run_id: str | None = None
    log_path: str | None = None
    detected_urls: list[str] = field(default_factory=list)
    npm_install: ProcessProbe | None = None
    classification: str = "unknown"
    checks: list[FrontendCheck] = field(default_factory=list)
    actions: list[FrontendAction] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    report_dir: str | None = None


def frontend_effective_env(project_root: Path) -> dict[str, str]:
    return effective_env_values_for(project_root, "frontend")


def frontend_install_marker_path(project_root: Path) -> Path:
    return project_root / BOOTSTRAP_DIR_NAME / "frontend-install.json"


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_frontend_package(project_root: Path) -> tuple[dict[str, Any], str | None]:
    package_path = project_root / "frontend" / "package.json"
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "frontend/package.json is missing"
    except json.JSONDecodeError as exc:
        return {}, f"frontend/package.json is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "frontend/package.json root is not an object"
    return data, None


def frontend_scripts_from_package(package_data: dict[str, Any]) -> dict[str, str]:
    scripts = package_data.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items()}


def parse_frontend_host_port(project_root: Path) -> tuple[str, int, str | None]:
    values = frontend_effective_env(project_root)
    host = values.get("VITE_DEV_HOST") or values.get("VITE_HOST") or "127.0.0.1"
    raw_port = values.get("VITE_DEV_PORT") or values.get("VITE_PORT") or str(DEFAULT_PORTS["frontend"])
    try:
        port = int(raw_port)
    except ValueError:
        return host, DEFAULT_PORTS["frontend"], f"Frontend port is not an integer: {raw_port}"
    if port <= 0 or port > 65535:
        return host, DEFAULT_PORTS["frontend"], f"Frontend port is outside TCP port range: {raw_port}"
    return host, port, None


def frontend_root_url(host: str, port: int) -> str:
    return f"http://{http_probe_host(host)}:{port}/"


def frontend_api_health_url(api_base_url: str | None) -> str | None:
    if not api_base_url:
        return None
    base = api_base_url.rstrip("/")
    if not base:
        return None
    return f"{base}/health"


def load_frontend_install_marker(project_root: Path) -> dict[str, Any]:
    return read_json(frontend_install_marker_path(project_root))


def normalize_frontend_prepare_dep_mode(value: str | None) -> str:
    mode = (value or DEFAULT_FRONTEND_PREPARE_DEP_MODE).strip().lower()
    if mode == "missing-or-stale":
        return "stale"
    if mode not in FRONTEND_PREPARE_DEP_MODES:
        return DEFAULT_FRONTEND_PREPARE_DEP_MODE
    return mode


def process_probe_version_value(probe: ProcessProbe | None) -> str | None:
    if not process_probe_ok(probe):
        return None
    return first_output_line(probe)


def frontend_install_platform_fingerprint() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def frontend_install_marker_mismatch_reasons(
    project_root: Path,
    package_json_hash: str | None,
    package_lock_hash: str | None,
    *,
    node_version: str | None = None,
    npm_version: str | None = None,
) -> list[str]:
    marker_path = frontend_install_marker_path(project_root)
    node_modules_path = project_root / "frontend" / "node_modules"
    marker = load_frontend_install_marker(project_root)
    reasons: list[str] = []
    if not node_modules_path.is_dir():
        reasons.append("frontend/node_modules is missing")
    if not marker_path.is_file():
        reasons.append("frontend install marker is missing")
        return reasons
    if "_error" in marker:
        reasons.append(f"frontend install marker cannot be read: {marker.get('_error')}")
        return reasons
    if marker.get("packageJsonSha256") != package_json_hash:
        reasons.append("frontend/package.json hash differs from install marker")
    if marker.get("packageLockSha256") != package_lock_hash:
        reasons.append("frontend/package-lock.json hash differs from install marker")
    marker_platform = marker.get("platform") if isinstance(marker.get("platform"), dict) else {}
    current_platform = frontend_install_platform_fingerprint()
    for key in ["system", "machine"]:
        if marker_platform.get(key) != current_platform.get(key):
            reasons.append(f"platform {key} differs from install marker")
    if node_version and marker.get("nodeVersion") != node_version:
        reasons.append("Node.js version differs from install marker")
    if npm_version and marker.get("npmVersion") != npm_version:
        reasons.append("npm version differs from install marker")
    return reasons


def frontend_install_marker_matches(
    project_root: Path,
    package_json_hash: str | None,
    package_lock_hash: str | None,
    *,
    node_version: str | None = None,
    npm_version: str | None = None,
) -> bool:
    return not frontend_install_marker_mismatch_reasons(
        project_root,
        package_json_hash,
        package_lock_hash,
        node_version=node_version,
        npm_version=npm_version,
    )


def write_frontend_install_marker(project_root: Path, result: FrontendResult, command: list[str], *, install_mode: str) -> None:
    marker_path = frontend_install_marker_path(project_root)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "version": STATE_VERSION,
        "generatedAt": iso_now(),
        "toolVersion": TOOL_VERSION,
        "command": command_as_text(command),
        "commandList": command,
        "installMode": install_mode,
        "packageManager": "npm",
        "packageJsonSha256": result.package_json_hash,
        "packageLockSha256": result.package_lock_hash,
        "nodeVersion": process_probe_version_value(result.node_version),
        "npmVersion": process_probe_version_value(result.npm_version),
        "platform": frontend_install_platform_fingerprint(),
    }
    write_json(marker_path, marker)


def frontend_install_command(project_root: Path) -> list[str]:
    if (project_root / "frontend" / "package-lock.json").is_file():
        return ["npm", "ci"]
    return ["npm", "install"]


def frontend_prepare_should_install(result: FrontendResult, mode: str) -> tuple[bool, str]:
    normalized = normalize_frontend_prepare_dep_mode(mode)
    if normalized == "always":
        return True, "prepare mode is always"
    if normalized == "never":
        return False, "prepare mode is never"
    if normalized == "missing":
        if not result.node_modules_exists:
            return True, "frontend/node_modules is missing"
        return False, "prepare mode is missing and frontend/node_modules already exists"
    if not frontend_dependencies_current(result):
        return True, "frontend dependencies are missing or stale"
    return False, "frontend dependencies are current"


def state_process_entry(project_root: Path, process_name: str) -> dict[str, Any]:
    state = read_json(project_root / BOOTSTRAP_DIR_NAME / "state.json")
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    entry = processes.get(process_name) if isinstance(processes.get(process_name), dict) else {}
    if not entry:
        return {}
    pid_raw = entry.get("pid")
    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        pid = -1
    entry = dict(entry)
    entry["alive"] = pid_alive(pid)
    return entry


def build_frontend_result(project_root: Path | None, invoked_from: Path, *, mode: str, dry_run: bool = False) -> FrontendResult:
    result = FrontendResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        mode=mode,
        dry_run=dry_run,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        return result

    host, port, port_error = parse_frontend_host_port(project_root)
    result.frontend_host = host
    result.frontend_port = port
    result.frontend_url = frontend_root_url(host, port)
    values = frontend_effective_env(project_root)
    result.api_base_url = values.get("VITE_API_BASE_URL")

    package_data, package_error = read_frontend_package(project_root)
    result.package_json_exists = (project_root / "frontend" / "package.json").is_file()
    result.package_lock_exists = (project_root / "frontend" / "package-lock.json").is_file()
    result.node_modules_exists = (project_root / "frontend" / "node_modules").is_dir()
    result.package_scripts = frontend_scripts_from_package(package_data)
    result.package_json_hash = sha256_file(project_root / "frontend" / "package.json")
    result.package_lock_hash = sha256_file(project_root / "frontend" / "package-lock.json")
    result.install_marker_path = rel(frontend_install_marker_path(project_root), project_root)
    result.install_command = frontend_install_command(project_root)
    result.node_version = run_process_probe("node_version", ["node", "--version"], cwd=project_root, timeout=8)
    result.npm_version = run_process_probe("npm_version", ["npm", "--version"], cwd=project_root, timeout=8)
    result.install_marker_valid = frontend_install_marker_matches(
        project_root,
        result.package_json_hash,
        result.package_lock_hash,
        node_version=process_probe_version_value(result.node_version),
        npm_version=process_probe_version_value(result.npm_version),
    )
    result.frontend_port_probe = probe_port("frontend", port, host=http_probe_host(host))
    result.frontend_root_probe = probe_http("frontend_root", result.frontend_url)
    api_health = frontend_api_health_url(result.api_base_url)
    if api_health:
        result.api_probe = probe_http("frontend_api_base_health", api_health)
    backend_host, backend_port, _ = parse_backend_host_port(project_root)
    result.backend_health = probe_backend_health(backend_host, backend_port)
    result.state_frontend = state_process_entry(project_root, "frontend")

    if port_error:
        result.warnings.append({"code": "frontend_port_parse", "message": port_error})
    if package_error:
        result.failures.append({"code": "frontend_package_invalid", "message": package_error})
    if result.state_frontend:
        if result.state_frontend.get("alive"):
            result.warnings.append(
                {
                    "code": "frontend_process_registered",
                    "message": f"state.json already contains alive frontend pid={result.state_frontend.get('pid')}.",
                }
            )
        else:
            result.warnings.append(
                {
                    "code": "frontend_stale_process",
                    "message": f"state.json contains stale frontend pid={result.state_frontend.get('pid')}; it is not alive.",
                }
            )
    return result


def add_frontend_preflight_checks(result: FrontendResult, project_root: Path | None = None) -> None:
    if result.node_version:
        status = "ok" if process_probe_ok(result.node_version) else "fail"
        result.checks.append(FrontendCheck("node_version", status, "Node.js availability check.", first_output_line(result.node_version)))
    if result.npm_version:
        status = "ok" if process_probe_ok(result.npm_version) else "fail"
        result.checks.append(FrontendCheck("npm_version", status, "npm availability check.", first_output_line(result.npm_version)))
    result.checks.append(
        FrontendCheck(
            "package_json",
            "ok" if result.package_json_exists else "fail",
            "frontend/package.json presence check.",
        )
    )
    result.checks.append(
        FrontendCheck(
            "package_lock",
            "ok" if result.package_lock_exists else "warn",
            "frontend/package-lock.json presence check; npm ci is preferred when it exists.",
        )
    )
    dev_script = result.package_scripts.get("dev")
    result.checks.append(
        FrontendCheck(
            "frontend_dev_script",
            "ok" if dev_script else "fail",
            "package.json contains scripts.dev for Vite startup.",
            dev_script,
        )
    )
    result.checks.append(
        FrontendCheck(
            "node_modules",
            "ok" if result.node_modules_exists else "warn",
            "frontend/node_modules presence check.",
            "install marker valid" if result.install_marker_valid else "install marker missing or stale",
        )
    )
    if result.frontend_port_probe:
        status = "warn" if result.frontend_port_probe.open else "ok"
        message = f"Frontend TCP port {result.frontend_port_probe.host}:{result.frontend_port_probe.port} is {'open' if result.frontend_port_probe.open else 'closed/free'}."
        evidence = "tcp connect succeeded" if result.frontend_port_probe.open else (result.frontend_port_probe.error or "")
        result.checks.append(FrontendCheck("frontend_port_preflight", status, message, evidence))
    if result.frontend_root_probe:
        status = "ok" if result.frontend_root_probe.reachable and result.frontend_root_probe.status and 200 <= result.frontend_root_probe.status < 500 else "warn"
        message = f"{result.frontend_root_probe.url} returned HTTP {result.frontend_root_probe.status}." if result.frontend_root_probe.reachable else f"{result.frontend_root_probe.url} is not reachable."
        result.checks.append(FrontendCheck("frontend_root", status, message, result.frontend_root_probe.error))
    add_frontend_api_checks(result, project_root)


def add_frontend_api_checks(result: FrontendResult, project_root: Path | None) -> None:
    api_base = result.api_base_url or ""
    if not api_base:
        result.checks.append(FrontendCheck("frontend_api_base_url", "warn", "VITE_API_BASE_URL is missing from effective frontend env."))
        result.warnings.append({"code": "frontend_api_base_missing", "message": "VITE_API_BASE_URL is missing; browser requests may use an unintended fallback."})
        return
    if api_base.rstrip("/").endswith("/api/v1"):
        result.checks.append(FrontendCheck("frontend_api_base_path", "ok", "VITE_API_BASE_URL ends with /api/v1.", api_base))
    else:
        result.checks.append(FrontendCheck("frontend_api_base_path", "warn", "VITE_API_BASE_URL should normally end with /api/v1.", api_base))
        result.warnings.append({"code": "frontend_api_base_path", "message": "VITE_API_BASE_URL does not end with /api/v1."})
    if project_root is not None:
        _, backend_port, _ = parse_backend_host_port(project_root)
        api_port = parse_url_port(api_base)
        if str(api_port) == str(backend_port):
            result.checks.append(FrontendCheck("frontend_api_backend_port_match", "ok", "VITE_API_BASE_URL points to the configured backend port.", f"api={api_port}, backend={backend_port}"))
        else:
            result.checks.append(FrontendCheck("frontend_api_backend_port_match", "warn", "VITE_API_BASE_URL does not point to the configured backend port.", f"api={api_port}, backend={backend_port}"))
            result.warnings.append({"code": "frontend_api_backend_mismatch", "message": f"VITE_API_BASE_URL port {api_port} does not match backend APP__PORT {backend_port}."})
    if result.api_probe:
        status = "ok" if result.api_probe.reachable and result.api_probe.status and 200 <= result.api_probe.status < 300 else "warn"
        message = f"{result.api_probe.url} returned HTTP {result.api_probe.status}." if result.api_probe.reachable else f"{result.api_probe.url} is not reachable."
        result.checks.append(FrontendCheck("frontend_api_health", status, message, result.api_probe.error))
        if status != "ok":
            result.warnings.append({"code": "frontend_api_unreachable", "message": "Backend API health derived from VITE_API_BASE_URL is not reachable yet."})


def frontend_dependencies_current(result: FrontendResult) -> bool:
    return bool(result.node_modules_exists and result.install_marker_valid)


def render_frontend_report(result: FrontendResult) -> str:
    lines: list[str] = []
    lines.append(f"# devbootstrap {result.mode} report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    lines.append(f"- Frontend URL: `{result.frontend_url or '<unknown>'}`")
    lines.append(f"- API base URL: `{result.api_base_url or '<missing>'}`")
    if result.process_pid is not None:
        lines.append(f"- Frontend PID: `{result.process_pid}`")
    if result.log_path:
        lines.append(f"- Frontend log: `{result.log_path}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append("")

    lines.append("## Package")
    lines.append("")
    lines.append(f"- `frontend/package.json`: `{result.package_json_exists}`")
    lines.append(f"- `frontend/package-lock.json`: `{result.package_lock_exists}`")
    lines.append(f"- `frontend/node_modules`: `{result.node_modules_exists}`")
    lines.append(f"- Install marker: `{result.install_marker_path}` valid=`{result.install_marker_valid}`")
    lines.append(f"- Install command: `{command_as_text(result.install_command)}`")
    lines.append(f"- package.json SHA-256: `{result.package_json_hash or '<missing>'}`")
    lines.append(f"- package-lock.json SHA-256: `{result.package_lock_hash or '<missing>'}`")
    lines.append(f"- Platform fingerprint: `{frontend_install_platform_fingerprint()}`")
    lines.append("")
    lines.append("### Scripts")
    lines.append("")
    if result.package_scripts:
        for name, script in sorted(result.package_scripts.items()):
            lines.append(f"- `{name}`: `{script}`")
    else:
        lines.append("- No package scripts discovered.")
    lines.append("")

    lines.append("## Checks")
    lines.append("")
    if result.checks:
        lines.append("| Code | Status | Message | Evidence |")
        lines.append("|---|---|---|---|")
        for check in result.checks:
            lines.append(f"| `{check.code}` | {check.status} | {check.message} | `{check.evidence or ''}` |")
    else:
        lines.append("- No frontend checks recorded.")
    lines.append("")

    lines.append("## Actions")
    lines.append("")
    if result.actions:
        lines.append("| Code | Status | Message | Command | Evidence |")
        lines.append("|---|---|---|---|---|")
        for action in result.actions:
            lines.append(f"| `{action.code}` | {action.status} | {action.message} | `{action.command or ''}` | `{action.evidence or ''}` |")
    else:
        lines.append("- No frontend actions recorded.")
    lines.append("")

    if result.detected_urls:
        lines.append("## Detected dev server URLs")
        lines.append("")
        for url in result.detected_urls:
            lines.append(f"- `{url}`")
        lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No frontend findings.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")

    lines.append("## Next safe actions")
    lines.append("")
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- Continue with the next devbootstrap phase.")
    lines.append("")
    return "\n".join(lines)


def write_frontend_reports(project_root: Path, result: FrontendResult, command: str, report_dir: Path | None = None) -> Path:
    if report_dir is None:
        report_dir = create_report_dir(project_root, command)
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / f"{command}.json", result, command=command)
    (report_dir / "report.md").write_text(render_frontend_report(result), encoding="utf-8")
    return report_dir


def print_frontend_summary(result: FrontendResult) -> None:
    print_header(f"devbootstrap {result.mode}")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Frontend URL: {result.frontend_url or '<unknown>'}")
    print(f"API base URL: {result.api_base_url or '<missing>'}")
    print(f"Classification: {result.classification}")
    if result.process_pid is not None:
        alive_text = "alive" if result.process_alive else "not alive"
        print(f"Frontend process: pid={result.process_pid} {alive_text}")
    if result.log_path:
        print(f"Log: {result.log_path}")
    if result.checks:
        print("\nChecks:")
        for check in result.checks:
            evidence = f" — {check.evidence}" if check.evidence else ""
            print(f"  - {check.status.upper()} {check.code}: {check.message}{evidence}")
    if result.actions:
        print("\nActions:")
        for action in result.actions:
            command = f" [{action.command}]" if action.command else ""
            evidence = f" — {action.evidence}" if action.evidence else ""
            print(f"  - {action.status.upper()} {action.code}: {action.message}{command}{evidence}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no frontend findings")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_prepare_frontend(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    install_mode = "always" if args.force_install else normalize_frontend_prepare_dep_mode(getattr(args, "install_mode", None))
    result = build_frontend_result(project_root, invoked_from, mode="prepare-frontend", dry_run=args.dry_run)
    report_dir: Path | None = None
    if project_root is not None and not args.no_write_report:
        report_dir = create_report_dir(project_root, "prepare-frontend")
    if project_root is not None:
        add_frontend_preflight_checks(result, project_root)
        should_install, install_reason = frontend_prepare_should_install(result, install_mode)
        result.actions.append(
            FrontendAction(
                "dependency_prepare_policy",
                "ok",
                f"Dependency preparation mode is `{install_mode}`.",
                evidence=install_reason,
            )
        )
        if not process_probe_ok(result.node_version):
            result.classification = "missing_prerequisite"
            result.failures.append({"code": "missing_node", "message": "node is not available on PATH."})
            result.next_actions.append("Install Node.js or use a shell where node/npm are available, then rerun prepare-frontend.")
        elif not process_probe_ok(result.npm_version):
            result.classification = "missing_prerequisite"
            result.failures.append({"code": "missing_npm", "message": "npm is not available on PATH."})
            result.next_actions.append("Install npm or repair PATH, then rerun prepare-frontend.")
        elif not result.package_json_exists:
            result.classification = "frontend_package_invalid"
            result.next_actions.append("Restore frontend/package.json from the project archive before installing dependencies.")
        elif not should_install and frontend_dependencies_current(result):
            result.classification = "frontend_dependencies_current"
            result.actions.append(FrontendAction("npm_install_noop", "ok", "frontend/node_modules matches the devbootstrap install marker; install skipped.", evidence=install_reason))
            result.next_actions.append("Frontend dependencies look current. Continue with `python tools/devbootstrap.py start-frontend`.")
        elif not should_install:
            result.classification = "frontend_dependencies_stale" if result.node_modules_exists else "frontend_dependencies_missing"
            result.failures.append({"code": result.classification, "message": f"Frontend dependencies are not current and prepare mode `{install_mode}` did not permit installation."})
            result.next_actions.append("Rerun with `--install-mode=stale` or `--force-install` to repair missing/stale frontend dependencies.")
        elif not result.package_lock_exists and not args.allow_npm_install_without_lock:
            result.classification = "frontend_lockfile_missing"
            result.failures.append({"code": "frontend_lockfile_missing", "message": "frontend/package-lock.json is missing; devbootstrap will not fall back to npm install without explicit opt-in."})
            result.next_actions.append("Restore package-lock.json, or rerun with `--allow-npm-install-without-lock` when creating/updating the lockfile is intentional.")
        elif args.dry_run:
            result.classification = "frontend_prepare_planned"
            result.actions.append(FrontendAction("npm_install", "planned", "Would install frontend dependencies.", command_as_text(result.install_command), install_reason))
            result.next_actions.append("Run without --dry-run to install/update frontend dependencies.")
        else:
            before_package_hash = sha256_file(project_root / "frontend" / "package.json")
            before_lock_hash = sha256_file(project_root / "frontend" / "package-lock.json")
            log_path = report_dir / "npm-install.log" if report_dir is not None else None
            result.actions.append(FrontendAction("npm_install", "started", "Installing frontend dependencies.", command_as_text(result.install_command), install_reason))
            result.npm_install = run_frontend_command_probe(
                "npm_install",
                result.install_command,
                project_root=project_root,
                cwd=project_root / "frontend",
                timeout=args.timeout_seconds,
                log_path=log_path,
            )
            after_package_hash = sha256_file(project_root / "frontend" / "package.json")
            after_lock_hash = sha256_file(project_root / "frontend" / "package-lock.json")
            if not process_probe_ok(result.npm_install):
                result.classification = classify_frontend_failure(command_output_text(result.npm_install), "frontend_install_failed")
                result.failures.append({"code": result.classification, "message": "Frontend dependency installation failed."})
                result.next_actions.append("Inspect npm-install.log, fix npm/network/lockfile issues, then rerun prepare-frontend.")
            elif before_package_hash != after_package_hash:
                result.classification = "frontend_manifest_changed_by_install"
                result.failures.append({"code": result.classification, "message": "npm install changed frontend/package.json; release-gates will not hide manifest changes."})
                result.next_actions.append("Inspect frontend/package.json changes and commit/fix them in a separate patch before rerunning release-gates.")
            elif before_lock_hash != after_lock_hash:
                result.classification = "frontend_lockfile_changed_by_install"
                result.failures.append({"code": result.classification, "message": "npm install changed frontend/package-lock.json; release-gates will not hide lockfile changes."})
                result.next_actions.append("Inspect package-lock.json changes and commit/fix them in a separate patch before rerunning release-gates.")
            else:
                result.package_json_hash = after_package_hash
                result.package_lock_hash = after_lock_hash
                result.node_modules_exists = (project_root / "frontend" / "node_modules").is_dir()
                if not result.node_modules_exists:
                    result.classification = "frontend_dependencies_missing"
                    result.failures.append({"code": result.classification, "message": "npm command succeeded but frontend/node_modules is still missing."})
                else:
                    result.install_marker_valid = True
                    write_frontend_install_marker(project_root, result, result.install_command, install_mode=install_mode)
                    result.actions.append(FrontendAction("install_marker", "ok", "Updated frontend install marker.", evidence=result.install_marker_path))
                    result.classification = "frontend_dependencies_ready"
                    result.next_actions.append("Frontend dependencies are ready. Continue with `python tools/devbootstrap.py start-frontend`.")
    if project_root is not None and report_dir is not None:
        write_frontend_reports(project_root, result, "prepare-frontend", report_dir)
    print_frontend_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0



def run_frontend_command_probe(
    name: str,
    command: list[str],
    *,
    project_root: Path,
    cwd: Path,
    timeout: int,
    log_path: Path | None = None,
) -> ProcessProbe:
    probe = run_process_probe(name, command, cwd=cwd, timeout=timeout, env_extra={"PYTHONDONTWRITEBYTECODE": "1"})
    if log_path is not None:
        lines = [
            f"$ {command_as_text(command)}",
            f"cwd: {rel(cwd, project_root)}",
            f"exit: {probe.returncode if probe.returncode is not None else probe.error or '<none>'}",
            "",
            "## stdout",
            sanitize_frontend_log(probe.stdout, project_root) or "<empty>",
            "",
            "## stderr",
            sanitize_frontend_log(probe.stderr or probe.error or "", project_root) or "<empty>",
            "",
        ]
        log_path.write_text("\n".join(lines), encoding="utf-8")
    return probe



def frontend_vite_entry_command(project_root: Path, host: str, port: int) -> list[str] | None:
    package_data, package_error = read_frontend_package(project_root)
    if package_error:
        return None
    dev_script = frontend_scripts_from_package(package_data).get("dev", "").strip()
    vite_entry = project_root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    if dev_script == "vite" and vite_entry.is_file():
        return ["node", "node_modules/vite/bin/vite.js", "--host", host, "--port", str(port), "--strictPort"]
    return None


def frontend_dev_launch_command(project_root: Path, host: str, port: int) -> tuple[list[str], str, str]:
    direct_vite = frontend_vite_entry_command(project_root, host, port)
    if direct_vite is not None:
        return direct_vite, "vite_direct", "Started Vite dev server directly through node."
    return (
        ["npm", "run", "dev", "--", "--host", host, "--port", str(port), "--strictPort"],
        "npm_run_dev",
        "Started frontend process with npm run dev.",
    )


def launch_frontend_process(project_root: Path, report_dir: Path, host: str, port: int) -> tuple[subprocess.Popen[Any], Path, list[str], str, str]:
    frontend_dir = project_root / "frontend"
    log_path = report_dir / "frontend.log"
    command, action_code, action_message = frontend_dev_launch_command(project_root, host, port)
    execution_command = command_for_subprocess(command)
    with log_path.open("ab") as log_file:
        header = "\n".join(
            [
                f"== devbootstrap start-frontend {iso_now()} ==",
                f"$ {command_as_text(command)}",
                f"resolved: {command_as_text(execution_command)}",
                f"cwd: {rel(frontend_dir, project_root)}",
                "",
            ]
        ).encode("utf-8", errors="replace")
        log_file.write(header)
        log_file.flush()
        process = subprocess.Popen(
            execution_command,
            cwd=str(frontend_dir),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            **popen_process_group_kwargs(),
        )
    return process, log_path, command, action_code, action_message


def frontend_ready(probe: HttpProbe | None) -> bool:
    return bool(probe and probe.reachable and probe.status is not None and 200 <= probe.status < 500)


def wait_for_frontend_root(process: subprocess.Popen[Any], url: str, *, timeout_seconds: int) -> tuple[bool, HttpProbe | None, int | None]:
    deadline = time.monotonic() + timeout_seconds
    last_probe: HttpProbe | None = None
    while time.monotonic() < deadline:
        returncode = process.poll()
        last_probe = probe_http("frontend_root", url, timeout=1.0)
        if frontend_ready(last_probe):
            return True, last_probe, returncode
        if returncode is not None:
            return False, last_probe, returncode
        time.sleep(1.0)
    return False, last_probe, process.poll()


def extract_frontend_urls(log_text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s'\"<>]+", log_text)
    cleaned: list[str] = []
    for url in urls:
        url = url.rstrip(".,)")
        if url not in cleaned:
            cleaned.append(url)
    return cleaned[:10]


def sanitize_frontend_log(text: str, project_root: Path | None = None) -> str:
    if not text:
        return ""
    cleaned = text
    if project_root is not None:
        api_base = frontend_effective_env(project_root).get("VITE_API_BASE_URL")
        if api_base and is_secret_key("VITE_API_BASE_URL"):
            cleaned = cleaned.replace(api_base, "***")
    return "\n".join(cleaned.strip().splitlines()[-60:])


def npm_missing_in_output(lower: str) -> bool:
    return any(
        fragment in lower
        for fragment in [
            "fail npm_version",
            "missing_npm",
            "npm is not available",
            "required command is unavailable: npm",
            "command not found",
            "not found on path",
            "no such file or directory",
            "[winerror 2]",
            "не удается найти указанный файл",
        ]
    )


def npm_lockfile_mismatch_in_output(lower: str) -> bool:
    return any(
        fragment in lower
        for fragment in [
            "npm err! code eusage",
            "npm ci can only install packages when your package.json and package-lock.json are in sync",
            "missing:",
            "invalid:",
            "from lock file",
            "lock file's",
        ]
    ) and any(fragment in lower for fragment in ["npm err!", "npm ci", "package-lock", "lock file"])


def classify_frontend_failure(text: str, default: str) -> str:
    lower = text.lower()
    if npm_missing_in_output(lower):
        return "frontend_dependencies_missing"
    if "eaddrinuse" in lower or "address already in use" in lower:
        return "frontend_port_conflict"
    if "missing script" in lower or "script not found" in lower:
        return "frontend_script_missing"
    if "cannot find module" in lower or "module not found" in lower:
        return "frontend_dependency_missing"
    if any(token in lower for token in ["econnreset", "etimedout", "eai_again", "enotfound", "socket timeout", "network timeout"]):
        return "dependency_network_unavailable"
    if "npm err!" in lower and "network" in lower:
        return "dependency_network_unavailable"
    if npm_lockfile_mismatch_in_output(lower):
        return "frontend_lockfile_mismatch"
    if "eresolve" in lower or "unable to resolve dependency tree" in lower:
        return "frontend_dependency_conflict"
    if "enoent" in lower and "package.json" in lower:
        return "frontend_package_invalid"
    return default


def command_start_frontend(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_frontend_result(project_root, invoked_from, mode="start-frontend", dry_run=args.dry_run)
    report_dir: Path | None = None
    if project_root is not None and (not args.no_write_report or not args.dry_run):
        report_dir = create_report_dir(project_root, "start-frontend")
    if project_root is not None:
        add_frontend_preflight_checks(result, project_root)
        if not process_probe_ok(result.node_version):
            result.classification = "missing_prerequisite"
            result.failures.append({"code": "missing_node", "message": "node is not available on PATH."})
            result.next_actions.append("Install Node.js or use a shell where node/npm are available, then rerun start-frontend.")
        elif not process_probe_ok(result.npm_version):
            result.classification = "missing_prerequisite"
            result.failures.append({"code": "missing_npm", "message": "npm is not available on PATH."})
            result.next_actions.append("Install npm or repair PATH, then rerun start-frontend.")
        elif not result.package_scripts.get("dev"):
            result.classification = "frontend_script_missing"
            result.failures.append({"code": "frontend_script_missing", "message": "frontend/package.json does not contain scripts.dev."})
            result.next_actions.append("Restore the frontend dev script before trying to start Vite.")
        elif not result.node_modules_exists:
            result.classification = "frontend_dependencies_missing"
            result.failures.append({"code": "frontend_dependencies_missing", "message": "frontend/node_modules is missing."})
            result.next_actions.append("Run `python tools/devbootstrap.py prepare-frontend` first.")
        elif result.frontend_root_probe and frontend_ready(result.frontend_root_probe):
            result.classification = "frontend_already_running"
            result.actions.append(FrontendAction("start_frontend_noop", "ok", "Frontend root is already reachable; npm run dev was not started."))
            result.next_actions.append("Frontend is reachable. Continue with browser/manual checks or the future smoke phase.")
        elif result.frontend_port_probe and result.frontend_port_probe.open:
            result.classification = "frontend_port_conflict"
            result.failures.append({"code": "frontend_port_conflict", "message": "Frontend port is open but the frontend root probe is not healthy. devbootstrap will not kill a foreign process."})
            result.next_actions.append("Inspect the process on the Vite port manually, or stop the old frontend you own and rerun start-frontend.")
        elif args.dry_run:
            command, action_code, action_message = frontend_dev_launch_command(project_root, result.frontend_host, result.frontend_port)
            result.classification = "frontend_start_planned"
            result.actions.append(FrontendAction(action_code, "planned", action_message.replace("Started", "Would start"), command_as_text(command)))
            result.next_actions.append("Run without --dry-run to start frontend.")
        else:
            run_id_value = run_id("start-frontend")
            try:
                process, log_path, command, action_code, action_message = launch_frontend_process(project_root, report_dir or create_report_dir(project_root, "start-frontend"), result.frontend_host, result.frontend_port)
                result.process_pid = process.pid
                result.process_alive = pid_alive(process.pid)
                result.run_id = run_id_value
                result.log_path = rel(log_path, project_root)
                result.actions.append(FrontendAction(action_code, "started", action_message, command_as_text(command), f"pid={process.pid}"))
                ready, probe, returncode = wait_for_frontend_root(process, result.frontend_url or frontend_root_url(result.frontend_host, result.frontend_port), timeout_seconds=args.timeout_seconds)
                result.frontend_root_probe = probe
                result.process_returncode = returncode
                result.process_alive = pid_alive(process.pid) if returncode is None else False
                result.detected_urls = extract_frontend_urls(read_log_tail(log_path))
                if ready:
                    result.classification = "frontend_started"
                    result.checks.append(FrontendCheck("frontend_root_wait", "ok", "Frontend root became reachable.", f"timeout={args.timeout_seconds}s"))
                    update_process_state(
                        project_root,
                        process_name="frontend",
                        pid=process.pid,
                        cwd=project_root / "frontend",
                        command=command,
                        started_at=result.generated_at,
                        run_id_value=run_id_value,
                        log_path=log_path,
                        report_dir=log_path.parent,
                    )
                    result.next_actions.append("Frontend is running. Continue with browser/manual checks or the future smoke phase.")
                else:
                    log_tail = sanitize_frontend_log(read_log_tail(log_path), project_root)
                    default = "frontend_start_failed" if returncode is not None else "frontend_health_timeout"
                    result.classification = classify_frontend_failure(log_tail, default)
                    result.checks.append(FrontendCheck("frontend_root_wait", "fail", "Frontend root did not become reachable.", f"timeout={args.timeout_seconds}s"))
                    result.failures.append({"code": result.classification, "message": "Frontend did not reach ready state after starting the dev server."})
                    if result.process_alive:
                        update_process_state(
                            project_root,
                            process_name="frontend",
                            pid=process.pid,
                            cwd=project_root / "frontend",
                            command=command,
                            started_at=result.generated_at,
                            run_id_value=run_id_value,
                            log_path=log_path,
                            report_dir=log_path.parent,
                        )
                        result.next_actions.append("Frontend process is still alive but root timed out. Inspect frontend.log, then run `python tools/devbootstrap.py stop` if the tracked frontend must be cleaned up.")
                    else:
                        result.next_actions.append("Inspect frontend.log for the classified failure before retrying.")
            except FileNotFoundError:
                result.classification = "missing_prerequisite"
                result.failures.append({"code": "missing_npm", "message": "Frontend dev server could not be started because npm was not found."})
            except OSError as exc:
                result.classification = "frontend_start_failed"
                result.failures.append({"code": "frontend_start_failed", "message": f"Could not start frontend dev server: {exc}"})
    if project_root is not None and report_dir is not None:
        write_frontend_reports(project_root, result, "start-frontend", report_dir)
    print_frontend_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0



@dataclass
class SmokeStep:
    name: str
    status: str
    message: str
    classification: str = "unknown"
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    log_path: str | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    level: str
    allow_dev_db_write: bool
    report_dir: str | None = None
    backend_urls: dict[str, str] = field(default_factory=dict)
    frontend_url: str | None = None
    api_base_url: str | None = None
    database_url: DatabaseUrlProbe | None = None
    test_database_url_present: bool = False
    steps: list[SmokeStep] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    classification: str = "unknown"


def smoke_command_display(command: list[str]) -> str:
    return " ".join(command)


def smoke_log_path(report_dir: Path, step_name: str, suffix: str = "log") -> Path:
    index = len(list(report_dir.glob("*.log"))) + len(list(report_dir.glob("*.json"))) + 1
    return report_dir / f"{index:02d}_{step_name}.{suffix}"


def write_smoke_probe_log(project_root: Path, report_dir: Path, step_name: str, payload: dict[str, Any]) -> str:
    path = smoke_log_path(report_dir, step_name, "json")
    write_json(path, payload)
    return rel(path, project_root)


def run_smoke_process_step(
    *,
    project_root: Path,
    report_dir: Path,
    name: str,
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    env_extra: dict[str, str] | None = None,
) -> SmokeStep:
    started = time.monotonic()
    log_path = smoke_log_path(report_dir, name, "log")
    probe = run_process_probe(name, command, cwd=cwd, timeout=timeout_seconds, env_extra=env_extra)
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = probe.stdout or ""
    stderr = probe.stderr or probe.error or ""
    log_path.write_text(
        "\n".join(
            [
                f"$ {smoke_command_display(command)}",
                f"cwd: {rel(cwd, project_root)}",
                f"exit: {probe.returncode if probe.returncode is not None else probe.error or '<none>'}",
                f"duration_ms: {duration_ms}",
                "",
                "## stdout",
                stdout or "<empty>",
                "",
                "## stderr",
                stderr or "<empty>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if not probe.available:
        return SmokeStep(
            name=name,
            status="failed",
            message=f"required command is unavailable: {command[0]}",
            classification="missing_prerequisite",
            command=command,
            returncode=probe.returncode,
            log_path=rel(log_path, project_root),
            duration_ms=duration_ms,
        )
    if probe.returncode == 0:
        return SmokeStep(
            name=name,
            status="ok",
            message="step completed",
            classification="ok",
            command=command,
            returncode=probe.returncode,
            log_path=rel(log_path, project_root),
            duration_ms=duration_ms,
        )
    output = "\n".join(part for part in [stdout, stderr] if part)
    if probe.error == "timeout":
        classification = f"{name}_timeout"
        message = f"step timed out after {timeout_seconds}s"
    else:
        classification = classify_smoke_process_failure(name, output)
        message = "step failed; see log"
    return SmokeStep(
        name=name,
        status="failed",
        message=message,
        classification=classification,
        command=command,
        returncode=probe.returncode,
        log_path=rel(log_path, project_root),
        duration_ms=duration_ms,
    )


def playwright_browser_prerequisite_missing_in_output(lower_output: str) -> bool:
    return (
        "executable doesn't exist" in lower_output
        or "browser executable" in lower_output and "missing" in lower_output
        or "please run" in lower_output and "playwright install" in lower_output
        or "looks like playwright test or playwright was just installed or updated" in lower_output
        or "browserType.launch".lower() in lower_output and "playwright install" in lower_output
    )


def classify_smoke_process_failure(name: str, output: str) -> str:
    lower = output.lower()
    if "command not found" in lower or "not found on path" in lower:
        return "missing_prerequisite"
    if "connection refused" in lower or "failed to fetch" in lower or "networkerror" in lower:
        return "runtime_unreachable"
    if "unauthorized" in lower or "authentication is required" in lower:
        return "auth_flow_failed"
    if "playwright" in lower and playwright_browser_prerequisite_missing_in_output(lower):
        return "browser_smoke_prerequisite"
    if "failed" in lower or "error" in lower:
        return f"{name}_failed"
    return f"{name}_failed"


def add_smoke_step(result: SmokeResult, step: SmokeStep) -> bool:
    result.steps.append(step)
    if step.status == "failed":
        result.failures.append({"code": step.classification, "message": f"{step.name}: {step.message}"})
        if result.classification == "unknown":
            result.classification = step.classification
        if step.log_path:
            result.next_actions.append(f"Inspect `{step.log_path}` before rerunning `python tools/devbootstrap.py smoke --level {result.level}`.")
        return False
    return True


def smoke_expected_base_url(project_root: Path) -> str:
    frontend_env = frontend_effective_env(project_root)
    api_base = frontend_env.get("VITE_API_BASE_URL")
    if api_base:
        return api_base.rstrip("/")
    host, port, _ = parse_backend_host_port(project_root)
    return f"http://{http_probe_host(host)}:{port}/api/v1"


def build_smoke_result(project_root: Path | None, invoked_from: Path, *, level: str, allow_dev_db_write: bool) -> SmokeResult:
    result = SmokeResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        level=level,
        allow_dev_db_write=allow_dev_db_write,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        return result

    host, port, _ = parse_backend_host_port(project_root)
    result.backend_urls = backend_health_urls(host, port)
    frontend_host, frontend_port, _ = parse_frontend_host_port(project_root)
    result.frontend_url = frontend_root_url(frontend_host, frontend_port)
    result.api_base_url = smoke_expected_base_url(project_root)
    db_url = os.environ.get("TEST_DATABASE_URL") or backend_effective_env(project_root).get("TEST_DATABASE_URL") or backend_effective_env(project_root).get("DATABASE__URL")
    result.database_url = parse_database_url_probe(db_url)
    result.test_database_url_present = bool(os.environ.get("TEST_DATABASE_URL") or backend_effective_env(project_root).get("TEST_DATABASE_URL"))
    return result


def add_quick_smoke(project_root: Path, report_dir: Path, result: SmokeResult) -> bool:
    host, port, _ = parse_backend_host_port(project_root)
    backend_probes = probe_backend_health(host, port, timeout=2.0)
    frontend_host, frontend_port, _ = parse_frontend_host_port(project_root)
    frontend_url = frontend_root_url(frontend_host, frontend_port)
    frontend_probe = probe_http("frontend_root", frontend_url, timeout=2.0)
    result.backend_urls = backend_health_urls(host, port)
    result.frontend_url = frontend_url
    payload = {
        "backend": as_jsonable(backend_probes),
        "frontend": as_jsonable(frontend_probe),
    }
    log_rel = write_smoke_probe_log(project_root, report_dir, "quick_http", payload)
    backend_ok = backend_health_ready(backend_probes)
    frontend_ok = frontend_ready(frontend_probe)
    if backend_ok and frontend_ok:
        return add_smoke_step(
            result,
            SmokeStep(
                name="quick_http",
                status="ok",
                message="backend health and frontend root are reachable",
                classification="ok",
                log_path=log_rel,
                details={"backend_ok": backend_ok, "frontend_ok": frontend_ok},
            ),
        )
    classification = "runtime_unreachable"
    if not backend_ok and frontend_ok:
        classification = "backend_unreachable"
    elif backend_ok and not frontend_ok:
        classification = "frontend_unreachable"
    return add_smoke_step(
        result,
        SmokeStep(
            name="quick_http",
            status="failed",
            message="backend/frontend HTTP probes are not all healthy",
            classification=classification,
            log_path=log_rel,
            details={"backend_ok": backend_ok, "frontend_ok": frontend_ok},
        ),
    )


def add_smoke_db_guard(project_root: Path, report_dir: Path, result: SmokeResult) -> bool:
    db_probe = result.database_url
    db_name = db_probe.database if db_probe else None
    payload = {
        "testDatabaseUrlPresent": result.test_database_url_present,
        "allowDevDbWrite": result.allow_dev_db_write,
        "database": as_jsonable(db_probe),
        "reason": "backend smoke creates/updates data through the live backend API",
    }
    log_rel = write_smoke_probe_log(project_root, report_dir, "db_write_guard", payload)
    if result.test_database_url_present:
        result.warnings.append(
            {
                "code": "test_database_url_present",
                "message": "TEST_DATABASE_URL is present. Verify the already running backend was started against the intended test database.",
            }
        )
        return add_smoke_step(
            result,
            SmokeStep(
                name="db_write_guard",
                status="ok",
                message="TEST_DATABASE_URL is present; write-capable smoke may proceed",
                classification="ok",
                log_path=log_rel,
                details={"database": db_name},
            ),
        )
    if result.allow_dev_db_write:
        if db_name == "p2p_planner":
            result.warnings.append(
                {
                    "code": "smoke_writes_dev_database",
                    "message": "Smoke is allowed to write to the regular p2p_planner database by explicit --allow-dev-db-write.",
                }
            )
        return add_smoke_step(
            result,
            SmokeStep(
                name="db_write_guard",
                status="ok",
                message="--allow-dev-db-write was provided; write-capable smoke may proceed",
                classification="ok",
                log_path=log_rel,
                details={"database": db_name},
            ),
        )
    return add_smoke_step(
        result,
        SmokeStep(
            name="db_write_guard",
            status="failed",
            message="standard/full smoke may write data; set TEST_DATABASE_URL or pass --allow-dev-db-write",
            classification="smoke_db_write_guard",
            log_path=log_rel,
            details={"database": db_name},
        ),
    )


def add_backend_python_smoke(project_root: Path, report_dir: Path, result: SmokeResult, *, timeout_seconds: int) -> bool:
    smoke_path = project_root / "backend" / "tests" / "smoke_core_api.py"
    if not smoke_path.is_file():
        return add_smoke_step(
            result,
            SmokeStep(
                name="backend_python_smoke",
                status="failed",
                message="backend/tests/smoke_core_api.py is missing",
                classification="backend_smoke_missing",
            ),
        )
    env_extra = {"BASE_URL": (result.api_base_url or smoke_expected_base_url(project_root)).rstrip("/")}
    if os.environ.get("TEST_DATABASE_URL"):
        env_extra["TEST_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    step = run_smoke_process_step(
        project_root=project_root,
        report_dir=report_dir,
        name="backend_python_smoke",
        command=[sys.executable, "tests/smoke_core_api.py"],
        cwd=project_root / "backend",
        timeout_seconds=timeout_seconds,
        env_extra=env_extra,
    )
    if step.status == "failed" and step.classification == "backend_python_smoke_failed":
        step.classification = "backend_smoke_failed"
    return add_smoke_step(result, step)


def add_frontend_unit_smoke(project_root: Path, report_dir: Path, result: SmokeResult, *, timeout_seconds: int) -> bool:
    package_data, package_error = read_frontend_package(project_root)
    if package_error:
        return add_smoke_step(
            result,
            SmokeStep("frontend_test_run", "failed", package_error, classification="frontend_package_invalid"),
        )
    scripts = frontend_scripts_from_package(package_data)
    if "test:run" not in scripts:
        return add_smoke_step(
            result,
            SmokeStep("frontend_test_run", "failed", "package.json does not define scripts.test:run", classification="frontend_test_script_missing"),
        )
    step = run_smoke_process_step(
        project_root=project_root,
        report_dir=report_dir,
        name="frontend_test_run",
        command=["npm", "run", "test:run"],
        cwd=project_root / "frontend",
        timeout_seconds=timeout_seconds,
    )
    if step.status == "failed" and step.classification == "frontend_test_run_failed":
        step.classification = "frontend_tests_failed"
    return add_smoke_step(result, step)


def add_browser_smoke(project_root: Path, report_dir: Path, result: SmokeResult, *, timeout_seconds: int) -> bool:
    package_data, package_error = read_frontend_package(project_root)
    if package_error:
        return add_smoke_step(
            result,
            SmokeStep("browser_smoke", "failed", package_error, classification="frontend_package_invalid"),
        )
    scripts = frontend_scripts_from_package(package_data)
    if "test:browser" not in scripts:
        return add_smoke_step(
            result,
            SmokeStep("browser_smoke", "failed", "package.json does not define scripts.test:browser", classification="browser_smoke_script_missing"),
        )
    step = run_smoke_process_step(
        project_root=project_root,
        report_dir=report_dir,
        name="browser_smoke",
        command=["npm", "run", "test:browser"],
        cwd=project_root / "frontend",
        timeout_seconds=timeout_seconds,
    )
    if step.status == "failed" and step.classification == "browser_smoke_failed":
        output_tail = read_log_tail(project_root / step.log_path if step.log_path else None)
        if "playwright" in output_tail.lower() and "install" in output_tail.lower():
            step.classification = "browser_smoke_prerequisite"
    return add_smoke_step(result, step)


def render_smoke_report(result: SmokeResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap smoke report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Level: `{result.level}`")
    lines.append(f"- Allow dev DB write: `{result.allow_dev_db_write}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append("")
    lines.append("## Runtime targets")
    lines.append("")
    for name, url in result.backend_urls.items():
        lines.append(f"- `{name}`: `{url}`")
    if result.frontend_url:
        lines.append(f"- `frontend`: `{result.frontend_url}`")
    if result.api_base_url:
        lines.append(f"- `api base`: `{result.api_base_url}`")
    if result.database_url:
        lines.append(f"- `database`: `{result.database_url.masked_url or '<missing>'}`")
        lines.append(f"- `database name`: `{result.database_url.database or '<unknown>'}`")
    lines.append(f"- `TEST_DATABASE_URL present`: `{result.test_database_url_present}`")
    lines.append("")
    lines.append("## Steps")
    lines.append("")
    lines.append("| Step | Status | Classification | Return | Duration | Log | Message |")
    lines.append("|---|---|---|---:|---:|---|---|")
    for step in result.steps:
        ret = "" if step.returncode is None else str(step.returncode)
        duration = "" if step.duration_ms is None else str(step.duration_ms)
        log = f"`{step.log_path}`" if step.log_path else ""
        lines.append(f"| `{step.name}` | {step.status} | `{step.classification}` | {ret} | {duration} ms | {log} | {step.message} |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking findings from smoke gates.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")
    lines.append("## Next safe actions")
    lines.append("")
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    elif result.classification == "ok":
        lines.append("- Smoke gates passed for the selected level.")
    else:
        lines.append("- Inspect the step logs above and rerun smoke after fixing the classified issue.")
    lines.append("")
    return "\n".join(lines)


def write_smoke_reports(project_root: Path, result: SmokeResult, report_dir: Path, run_id_value: str) -> None:
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / "smoke.json", result, command="smoke")
    (report_dir / "report.md").write_text(render_smoke_report(result), encoding="utf-8")
    append_report_to_state(project_root, report_dir, run_id_value)


def print_smoke_summary(result: SmokeResult) -> None:
    print_header("devbootstrap smoke")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Level: {result.level}")
    print(f"Classification: {result.classification}")
    if result.backend_urls or result.frontend_url:
        print("\nRuntime targets:")
        for name, url in result.backend_urls.items():
            print(f"  - {name}: {url}")
        if result.frontend_url:
            print(f"  - frontend: {result.frontend_url}")
    print("\nSteps:")
    for step in result.steps:
        suffix = f" — {step.log_path}" if step.log_path else ""
        print(f"  - {step.status.upper()} {step.name}: {step.message}{suffix}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking findings from smoke gates")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_smoke(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_smoke_result(project_root, invoked_from, level=args.level, allow_dev_db_write=args.allow_dev_db_write)
    report_dir: Path | None = None
    if project_root is not None:
        if args.no_write_report:
            report_dir = Path(tempfile.mkdtemp(prefix="devbootstrap-smoke-"))
        else:
            smoke_run_id = run_id("smoke")
            report_dir = project_root / BOOTSTRAP_DIR_NAME / "runs" / smoke_run_id
            report_dir.mkdir(parents=True, exist_ok=False)
            result.report_dir = rel(report_dir, project_root)

    keep_going = not result.failures and project_root is not None and report_dir is not None
    if keep_going:
        keep_going = add_quick_smoke(project_root, report_dir, result)
    if keep_going and args.level in {"standard", "full"}:
        keep_going = add_smoke_db_guard(project_root, report_dir, result)
    if keep_going and args.level in {"standard", "full"}:
        keep_going = add_backend_python_smoke(project_root, report_dir, result, timeout_seconds=args.timeout_seconds)
    if keep_going and args.level in {"standard", "full"}:
        keep_going = add_frontend_unit_smoke(project_root, report_dir, result, timeout_seconds=args.timeout_seconds)
    if keep_going and args.level == "full":
        keep_going = add_browser_smoke(project_root, report_dir, result, timeout_seconds=args.timeout_seconds)

    if result.classification == "unknown":
        result.classification = "ok" if keep_going else "failed"
    if result.classification == "ok":
        result.next_actions.append("Selected smoke gates passed. Continue manual validation or run a higher --level if needed.")
    if project_root is not None and report_dir is not None and not args.no_write_report:
        write_smoke_reports(project_root, result, report_dir, smoke_run_id)
    print_smoke_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures else 0


@dataclass
class UpStep:
    name: str
    status: str
    message: str
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    log_path: str | None = None
    duration_ms: int | None = None
    blocking: bool = True
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    dry_run: bool
    smoke_level: str
    yes: bool
    run_id: str
    report_dir: str | None = None
    backend_urls: dict[str, str] = field(default_factory=dict)
    frontend_url: str | None = None
    steps: list[UpStep] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    classification: str = "unknown"


@dataclass
class StopTarget:
    name: str
    pid: int | None
    cwd: str | None = None
    command: str | None = None
    log_path: str | None = None
    run_id: str | None = None
    alive_before: bool = False
    alive_after: bool | None = None
    verification_status: str = "unknown"
    verification_evidence: str | None = None
    action: str = "pending"
    error: str | None = None


@dataclass
class StopDbAction:
    status: str
    message: str
    command: str | None = None
    evidence: str | None = None


@dataclass
class StopResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    dry_run: bool
    include_db: bool
    force: bool
    timeout_seconds: int
    run_id: str
    report_dir: str | None = None
    classification: str = "unknown"
    targets: list[StopTarget] = field(default_factory=list)
    db_action: StopDbAction | None = None
    ports_after: list[PortProbe] = field(default_factory=list)
    http_after: list[HttpProbe] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


def append_report_to_state(project_root: Path, report_dir: Path, run_id_value: str) -> None:
    state_path = project_root / BOOTSTRAP_DIR_NAME / "state.json"
    state = read_json(state_path)
    if "_error" in state:
        state = {}
    state["version"] = STATE_VERSION
    state["activeRunId"] = run_id_value
    processes = state.get("processes") if isinstance(state.get("processes"), dict) else {}
    state["processes"] = processes
    last_reports = state.get("lastReports") if isinstance(state.get("lastReports"), list) else []
    last_reports.append(rel(report_dir, project_root))
    state["lastReports"] = last_reports[-20:]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)


def up_command_display(command: list[str]) -> str:
    return " ".join(command)


def run_up_subcommand(
    *,
    project_root: Path,
    report_dir: Path,
    step_name: str,
    command: list[str],
    timeout_seconds: int,
) -> UpStep:
    started = time.monotonic()
    log_path = report_dir / f"{len(list(report_dir.glob('*.log'))) + 1:02d}_{step_name}.log"
    full_command = [sys.executable, str(project_root / "tools" / "devbootstrap.py"), *command]
    try:
        completed = subprocess.run(
            full_command,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = safe_decode(completed.stdout)
        stderr = safe_decode(completed.stderr)
        duration_ms = int((time.monotonic() - started) * 1000)
        log_path.write_text(
            "\n".join(
                [
                    f"$ {up_command_display(full_command)}",
                    f"cwd: {project_root}",
                    f"exit: {completed.returncode}",
                    f"duration_ms: {duration_ms}",
                    "",
                    "## stdout",
                    stdout or "<empty>",
                    "",
                    "## stderr",
                    stderr or "<empty>",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        status = "ok" if completed.returncode == 0 else "failed"
        message = "step completed" if completed.returncode == 0 else "step failed; see log"
        return UpStep(
            name=step_name,
            status=status,
            message=message,
            command=full_command,
            returncode=completed.returncode,
            log_path=rel(log_path, project_root),
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_path.write_text(
            "\n".join(
                [
                    f"$ {up_command_display(full_command)}",
                    f"cwd: {project_root}",
                    "exit: timeout",
                    f"duration_ms: {duration_ms}",
                    "",
                    "## stdout",
                    safe_decode(exc.stdout) or "<empty>",
                    "",
                    "## stderr",
                    safe_decode(exc.stderr) or "<empty>",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return UpStep(
            name=step_name,
            status="failed",
            message=f"step timed out after {timeout_seconds}s; see log",
            command=full_command,
            returncode=None,
            log_path=rel(log_path, project_root),
            duration_ms=duration_ms,
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        log_path.write_text(
            f"$ {up_command_display(full_command)}\ncwd: {project_root}\nerror: {exc}\n",
            encoding="utf-8",
        )
        return UpStep(
            name=step_name,
            status="failed",
            message=f"could not execute step: {exc}",
            command=full_command,
            returncode=None,
            log_path=rel(log_path, project_root),
            duration_ms=duration_ms,
        )


def add_up_step(result: UpResult, step: UpStep) -> bool:
    result.steps.append(step)
    if step.status == "failed":
        result.failures.append({"code": f"up_{step.name}_failed", "message": step.message})
        result.classification = f"failed_at_{step.name}"
        result.next_actions.append(f"Inspect `{step.log_path}` and rerun `python tools/devbootstrap.py {step.name.replace('_', '-')}` or `up` after fixing the issue.")
        return False
    if step.status == "warn":
        result.warnings.append({"code": f"up_{step.name}_warning", "message": step.message})
    return True


def add_up_skipped_step(result: UpResult, name: str, message: str) -> None:
    result.steps.append(UpStep(name=name, status="skipped", message=message, blocking=False))


def run_up_smoke(project_root: Path, report_dir: Path, result: UpResult, *, dry_run: bool, allow_dev_db_write: bool, timeout_seconds: int) -> bool:
    if result.smoke_level == "none":
        add_up_skipped_step(result, "smoke", "smoke-level=none; smoke gates skipped")
        return True
    if dry_run:
        result.steps.append(UpStep("smoke", "planned", f"would run smoke --level {result.smoke_level}", blocking=True))
        return True
    command = ["smoke", "--level", result.smoke_level, "--no-write-report", "--json", "--timeout-seconds", str(timeout_seconds)]
    if allow_dev_db_write:
        command.append("--allow-dev-db-write")
    step = run_up_subcommand(
        project_root=project_root,
        report_dir=report_dir,
        step_name="smoke",
        command=command,
        timeout_seconds=timeout_seconds + 30,
    )
    return add_up_step(result, step)


def render_up_report(result: UpResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap up report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Run ID: `{result.run_id}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    lines.append(f"- Smoke level: `{result.smoke_level}`")
    lines.append(f"- Classification: `{result.classification}`")
    if result.backend_urls:
        lines.append("")
        lines.append("## Runtime URLs")
        lines.append("")
        for name, url in result.backend_urls.items():
            lines.append(f"- `{name}`: `{url}`")
        if result.frontend_url:
            lines.append(f"- `frontend`: `{result.frontend_url}`")
    lines.append("")
    lines.append("## Pipeline steps")
    lines.append("")
    lines.append("| Step | Status | Return | Duration | Log | Message |")
    lines.append("|---|---|---:|---:|---|---|")
    for step in result.steps:
        ret = "" if step.returncode is None else str(step.returncode)
        duration = "" if step.duration_ms is None else str(step.duration_ms)
        log = f"`{step.log_path}`" if step.log_path else ""
        lines.append(f"| `{step.name}` | {step.status} | {ret} | {duration} ms | {log} | {step.message} |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking findings from up pipeline.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")
    lines.append("## Next safe actions")
    lines.append("")
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    elif result.classification == "ok":
        lines.append("- Open the frontend URL and continue manual development checks.")
        lines.append("- Use `python tools/devbootstrap.py status` to inspect tracked processes.")
    else:
        lines.append("- Inspect the step logs above and rerun `python tools/devbootstrap.py up` after fixing the issue.")
    lines.append("")
    return "\n".join(lines)


def write_up_reports(project_root: Path, result: UpResult, report_dir: Path) -> None:
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / "up.json", result, command="up")
    (report_dir / "report.md").write_text(render_up_report(result), encoding="utf-8")
    append_report_to_state(project_root, report_dir, result.run_id)


def print_up_summary(result: UpResult) -> None:
    print_header("devbootstrap up")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Classification: {result.classification}")
    print(f"Dry run: {result.dry_run}")
    if result.backend_urls or result.frontend_url:
        print("\nRuntime URLs:")
        for name, url in result.backend_urls.items():
            print(f"  - {name}: {url}")
        if result.frontend_url:
            print(f"  - frontend: {result.frontend_url}")
    print("\nSteps:")
    for step in result.steps:
        suffix = f" — {step.log_path}" if step.log_path else ""
        print(f"  - {step.status.upper()} {step.name}: {step.message}{suffix}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking findings from up pipeline")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_up(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    run_id_value = run_id("up")
    result = UpResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        dry_run=args.dry_run,
        smoke_level=args.smoke_level,
        yes=args.yes,
        run_id=run_id_value,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        print_up_summary(result)
        if args.json:
            print("\nJSON:")
            print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
        return 1

    report_dir = project_root / BOOTSTRAP_DIR_NAME / "runs" / run_id_value
    report_dir.mkdir(parents=True, exist_ok=False)
    result.report_dir = rel(report_dir, project_root)

    timeout = max(30, args.step_timeout_seconds)
    pipeline: list[tuple[str, list[str], int]] = [
        ("diagnose", ["diagnose", "--no-write-report", "--json"], timeout),
        ("plan", ["plan", "--no-write-report", "--json"], timeout),
    ]

    if args.dry_run:
        pipeline.append(("prepare_env", ["plan", "--no-write-report", "--json"], timeout))
    else:
        pipeline.append(("prepare_env", ["prepare-env", "--no-write-report", "--json"], timeout))

    if args.skip_db_start:
        pipeline.append(("start_db", ["__skip__", "--skip-db-start was provided"], 0))
    else:
        command = ["start-db", "--no-write-report", "--json", "--timeout-seconds", str(args.db_timeout_seconds)]
        if args.dry_run:
            command.insert(1, "--dry-run")
        pipeline.append(("start_db", command, args.db_timeout_seconds + 30))

    if args.skip_cargo_check:
        pipeline.append(("check_backend", ["__skip__", "--skip-cargo-check was provided"], 0))
    else:
        command = ["check-backend", "--no-write-report", "--json", "--timeout-seconds", str(args.cargo_check_timeout_seconds)]
        if args.dry_run:
            command.insert(1, "--dry-run")
        pipeline.append(("check_backend", command, args.cargo_check_timeout_seconds + 30))

    if args.skip_backend_start:
        pipeline.append(("start_backend", ["__skip__", "--skip-backend-start was provided"], 0))
    else:
        command = ["start-backend", "--no-write-report", "--json", "--timeout-seconds", str(args.backend_timeout_seconds)]
        if args.dry_run:
            command.insert(1, "--dry-run")
        pipeline.append(("start_backend", command, args.backend_timeout_seconds + 30))

    if args.skip_install:
        pipeline.append(("prepare_frontend", ["__skip__", "--skip-install was provided"], 0))
    else:
        command = ["prepare-frontend", "--no-write-report", "--json", "--timeout-seconds", str(args.npm_timeout_seconds)]
        if args.dry_run:
            command.insert(1, "--dry-run")
        pipeline.append(("prepare_frontend", command, args.npm_timeout_seconds + 30))

    if args.skip_frontend_start:
        pipeline.append(("start_frontend", ["__skip__", "--skip-frontend-start was provided"], 0))
    else:
        command = ["start-frontend", "--no-write-report", "--json", "--timeout-seconds", str(args.frontend_timeout_seconds)]
        if args.dry_run:
            command.insert(1, "--dry-run")
        pipeline.append(("start_frontend", command, args.frontend_timeout_seconds + 30))

    keep_going = True
    for step_name, command, step_timeout in pipeline:
        if not keep_going:
            add_up_skipped_step(result, step_name, "skipped because an earlier blocking step failed")
            continue
        if command and command[0] == "__skip__":
            add_up_skipped_step(result, step_name, command[1] if len(command) > 1 else "step skipped")
            continue
        step = run_up_subcommand(
            project_root=project_root,
            report_dir=report_dir,
            step_name=step_name,
            command=command,
            timeout_seconds=step_timeout,
        )
        if args.dry_run and step_name == "prepare_env" and step.status == "ok":
            step.status = "planned"
            step.message = "would create missing env files from examples; see env plan log"
        keep_going = add_up_step(result, step)

    if keep_going:
        keep_going = run_up_smoke(
            project_root,
            report_dir,
            result,
            dry_run=args.dry_run,
            allow_dev_db_write=args.allow_dev_db_write,
            timeout_seconds=args.smoke_timeout_seconds,
        )
    else:
        add_up_skipped_step(result, "smoke", "skipped because an earlier blocking step failed")

    if result.classification == "unknown":
        result.classification = "dry_run" if args.dry_run else "ok"
    if result.classification == "ok":
        host, port, _ = parse_backend_host_port(project_root)
        result.backend_urls = backend_health_urls(host, port)
        frontend_host, frontend_port, _ = parse_frontend_host_port(project_root)
        result.frontend_url = frontend_root_url(frontend_host, frontend_port)
        result.next_actions.append("Backend and frontend look alive. Continue manual checks or run `python tools/devbootstrap.py smoke --level standard`.")
    write_up_reports(project_root, result, report_dir)
    print_up_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures and not args.dry_run else 0


@dataclass
class GateSpec:
    name: str
    cwd: str
    command: list[str] = field(default_factory=list)
    description: str = ""
    required: bool = True
    timeout_seconds: int = TIMEOUT_POLICY["release_gate"]
    env_extra: dict[str, str] = field(default_factory=dict)
    not_implemented_reason: str | None = None
    skip_reason: str | None = None
    skip_status: str = "skipped_prerequisite"
    skip_classification: str = "skipped_prerequisite"
    internal_check: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    name: str
    status: str
    classification: str
    message: str
    cwd: str
    command: list[str] = field(default_factory=list)
    required: bool = True
    returncode: int | None = None
    duration_ms: int | None = None
    log_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ManagedTestDatabaseState:
    enabled: bool
    retention: str
    run_id: str
    status: str = "disabled"
    classification: str = "disabled"
    message: str = "managed test database is disabled"
    backend: str = "native-psql"
    created_at: str | None = None
    source: str | None = None
    database_name: str | None = None
    database_url: str | None = None
    masked_database_url: str | None = None
    maintenance_url: str | None = None
    masked_maintenance_url: str | None = None
    metadata_path: str | None = None
    cleanup_command: str | None = None
    create_command: list[str] = field(default_factory=list)
    drop_command: list[str] = field(default_factory=list)
    dump_command: list[str] = field(default_factory=list)
    dump_path: str | None = None
    retained: bool | None = None
    failure_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReleaseGatesManagedRuntimeProcess:
    name: str
    process: subprocess.Popen[Any]
    log_path: Path
    command: list[str]
    cwd: Path
    host: str
    port: int
    url: str


@dataclass
class ManagedRuntimeState:
    enabled: bool
    run_id: str
    status: str = "disabled"
    classification: str = "disabled"
    message: str = "managed runtime is disabled"
    backend_host: str = "127.0.0.1"
    backend_port: int | None = None
    frontend_host: str = "127.0.0.1"
    frontend_port: int | None = None
    backend_api_base_url: str | None = None
    backend_health_url: str | None = None
    frontend_url: str | None = None
    database_source: str | None = None
    masked_database_url: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    backend_pid: int | None = None
    frontend_pid: int | None = None
    runtime_state_path: str | None = None
    env_diff_path: str | None = None
    managed_urls_path: str | None = None
    backend_log_path: str | None = None
    frontend_log_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReleaseGatesProfilePlan:
    profile: str
    explicit_profile: bool
    description: str
    dry_run: bool
    explicit_overrides: dict[str, Any] = field(default_factory=dict)
    effective_options: dict[str, Any] = field(default_factory=dict)
    allowed_side_effects: list[dict[str, str]] = field(default_factory=list)
    denied_side_effects: list[dict[str, str]] = field(default_factory=list)
    planned_gates: list[str] = field(default_factory=list)
    consent_summary_path: str | None = None


@dataclass
class ReleaseGatesResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    run_id: str
    dry_run: bool
    timeout_seconds: int
    report_dir: str | None = None
    archive_path: str | None = None
    remediation_bundle_path: str | None = None
    profile_plan: ReleaseGatesProfilePlan | None = None
    managed_test_db: ManagedTestDatabaseState | None = None
    managed_runtime: ManagedRuntimeState | None = None
    overall_status: str = "unknown"
    classification: str = "unknown"
    gates: list[GateResult] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


RELEASE_GATES_ARCHIVE_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "target",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
}
RELEASE_GATES_ARCHIVE_EXCLUDED_NAMES = {".env"}
RELEASE_GATES_ARCHIVE_EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".tsbuildinfo")
CLEAN_MACHINE_PROFILES = ("dry", "deps", "runtime", "clean-machine-dry", "clean-machine-deps", "clean-machine-runtime")
CLEAN_MACHINE_RETENTION_POLICIES = ("delete-always", "keep-on-failure", "keep-always")
DEFAULT_CLEAN_MACHINE_PROFILE = "dry"
DEFAULT_CLEAN_MACHINE_RETENTION = "keep-on-failure"
RELEASE_GATES_AUTOPSY_CONTRACT_VERSION = "phase-7"
RELEASE_GATES_PROFILES = ("diagnostic", "prepared-local", "isolated-db", "managed-runtime", "full-local-release")
RELEASE_GATES_DEFAULT_PROFILE = "diagnostic"
RELEASE_GATES_PROFILE_DESCRIPTIONS = {
    "diagnostic": "Safe read-mostly baseline: self-check, diagnose, default classifiers and docs gates without managed installs, databases or processes.",
    "prepared-local": "Local dependency-prepared profile: allow npm/cargo/playwright cache preparation, then run frontend/backend gates that can use local prepared dependencies.",
    "isolated-db": "Managed database profile: create an ephemeral PostgreSQL test database for DB-writing Rust/Python gates and drop/retain it by policy.",
    "managed-runtime": "Owned runtime profile: create a managed test DB, start isolated backend/frontend processes on dynamic ports and route smoke/browser gates to them.",
    "full-local-release": "Maximum local release signal: prepare dependencies, use managed DB/runtime, run the real-backend browser path and include a dry clean-machine sandbox.",
}
RELEASE_GATES_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "diagnostic": {
        "allow_dev_db_write": False,
        "managed_runtime": False,
        "managed_test_db": False,
        "test_db_retention": "keep-on-failure",
        "start_db_if_needed": False,
        "dump_test_db_on_failure": False,
        "prepare_deps": "never",
        "install_playwright_browsers": False,
        "include_real_backend_browser": False,
        "include_clean_machine": False,
        "clean_machine_profile": DEFAULT_CLEAN_MACHINE_PROFILE,
        "clean_machine_retention": DEFAULT_CLEAN_MACHINE_RETENTION,
    },
    "prepared-local": {
        "allow_dev_db_write": False,
        "managed_runtime": False,
        "managed_test_db": False,
        "test_db_retention": "keep-on-failure",
        "start_db_if_needed": False,
        "dump_test_db_on_failure": False,
        "prepare_deps": DEFAULT_FRONTEND_PREPARE_DEP_MODE,
        "install_playwright_browsers": False,
        "include_real_backend_browser": False,
        "include_clean_machine": False,
        "clean_machine_profile": DEFAULT_CLEAN_MACHINE_PROFILE,
        "clean_machine_retention": DEFAULT_CLEAN_MACHINE_RETENTION,
    },
    "isolated-db": {
        "allow_dev_db_write": False,
        "managed_runtime": False,
        "managed_test_db": True,
        "test_db_retention": "keep-on-failure",
        "start_db_if_needed": False,
        "dump_test_db_on_failure": True,
        "prepare_deps": "never",
        "install_playwright_browsers": False,
        "include_real_backend_browser": False,
        "include_clean_machine": False,
        "clean_machine_profile": DEFAULT_CLEAN_MACHINE_PROFILE,
        "clean_machine_retention": DEFAULT_CLEAN_MACHINE_RETENTION,
    },
    "managed-runtime": {
        "allow_dev_db_write": False,
        "managed_runtime": True,
        "managed_test_db": True,
        "test_db_retention": "keep-on-failure",
        "start_db_if_needed": False,
        "dump_test_db_on_failure": True,
        "prepare_deps": "never",
        "install_playwright_browsers": False,
        "include_real_backend_browser": False,
        "include_clean_machine": False,
        "clean_machine_profile": DEFAULT_CLEAN_MACHINE_PROFILE,
        "clean_machine_retention": DEFAULT_CLEAN_MACHINE_RETENTION,
    },
    "full-local-release": {
        "allow_dev_db_write": False,
        "managed_runtime": True,
        "managed_test_db": True,
        "test_db_retention": "keep-on-failure",
        "start_db_if_needed": False,
        "dump_test_db_on_failure": True,
        "prepare_deps": DEFAULT_FRONTEND_PREPARE_DEP_MODE,
        "install_playwright_browsers": False,
        "include_real_backend_browser": False,
        "include_clean_machine": True,
        "clean_machine_profile": DEFAULT_CLEAN_MACHINE_PROFILE,
        "clean_machine_retention": DEFAULT_CLEAN_MACHINE_RETENTION,
    },
}
CLEAN_MACHINE_REQUIRED_PATHS = [
    "backend/Cargo.toml",
    "backend/build.rs",
    "backend/migrations",
    "frontend/package.json",
    "frontend/package-lock.json",
    "docker-compose.dev.yml",
    "README.md",
    "tools/devbootstrap.py",
]


def release_gate_command_display(command: list[str]) -> str:
    return " ".join(command)


def release_gate_log_path(logs_dir: Path, index: int, step_name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", step_name).strip("._") or "gate"
    return logs_dir / f"{index:02d}_{safe_name}.log"


def release_gate_sanitize_output(project_root: Path | None, text: str) -> str:
    if not text:
        return ""
    cleaned = text
    values: dict[str, str] = {}
    if project_root is not None:
        for relative in ["backend/.env", "backend/.env.example", "frontend/.env.local", "frontend/.env.example"]:
            parsed, _ = parse_env_file(project_root / relative)
            values.update(parsed)
    for key, value in os.environ.items():
        if is_secret_key(key):
            values.setdefault(key, value)
    for key, value in values.items():
        if not value:
            continue
        masked = mask_value(key, value)
        if masked != value:
            cleaned = cleaned.replace(value, masked)
            if key.upper() in {"DATABASE__URL", "DATABASE_URL"}:
                try:
                    parsed = urllib.parse.urlsplit(value)
                    if parsed.password:
                        password = urllib.parse.unquote(parsed.password)
                        if len(password) >= 8 and password.lower() not in {"postgres", "password", "planner"}:
                            cleaned = cleaned.replace(password, "***")
                except Exception:
                    pass
    cleaned = re.sub(r"(postgres(?:ql)?://[^:\s/@]+:)[^@\s]+(@)", r"\1***\2", cleaned)
    return cleaned


def rust_test_output_has_ignored_tests(output: str) -> bool:
    for match in re.finditer(r"(?:^|[;\s])([1-9]\d*)\s+ignored\b", output, flags=re.IGNORECASE | re.MULTILINE):
        try:
            if int(match.group(1)) > 0:
                return True
        except ValueError:
            continue
    return False


def classify_gate_output(name: str, stdout: str, stderr: str, error: str | None, returncode: int | None) -> tuple[str, str, str]:
    output = "\n".join(part for part in [stdout, stderr, error or ""] if part)
    lower = output.lower()
    if error == "timeout":
        return "timeout", f"{name}_timeout", "gate timed out"
    if returncode == 0:
        if "test result:" in lower and rust_test_output_has_ignored_tests(output):
            return "partial_pass", "critical_tests_ignored", "command exited 0, but one or more Rust tests were ignored"
        return "ok", "ok", "gate completed"
    if name.startswith("frontend_uiux_"):
        if returncode == 2 or '"status": "skipped_prerequisite"' in output:
            classification = "REL-ENV" if "REL-ENV" in output or "browser" in lower else "REL-UIUX-PREREQ"
            return "skipped_prerequisite", classification, "UIX prerequisite is unavailable; see evidence report"
        for code in ["REL-SEC", "REL-FE", "REL-BE", "REL-DB", "REL-PROC", "REL-UIUX"]:
            if code in output:
                return "failed", code, "UIX evidence gate failed; see report"
        return "failed", "REL-UIUX", "UIX evidence gate failed; see report"
    if name == "frontend_prepare_dependencies" and npm_missing_in_output(lower):
        return "infra_failed", "frontend_dependencies_missing", "npm is unavailable or could not be launched for frontend dependency preparation"
    if "playwright" in lower and playwright_browser_prerequisite_missing_in_output(lower):
        return "infra_failed", "browser_smoke_prerequisite", "Playwright browser prerequisite appears to be missing"
    if name in {"frontend_prepare_dependencies", "playwright_install", "backend_dependency_warmup"} and any(token in lower for token in ["econnreset", "etimedout", "eai_again", "enotfound", "socket timeout", "network timeout", "failed to download"]):
        return "infra_failed", "dependency_network_unavailable", "dependency network/cache prerequisite is unavailable"
    if name == "frontend_prepare_dependencies" and npm_lockfile_mismatch_in_output(lower):
        return "infra_failed", "frontend_lockfile_mismatch", "frontend lockfile is out of sync with package.json"
    if "command not found" in lower or "not found on path" in lower or "no such file or directory" in lower or "[winerror 2]" in lower:
        return "infra_failed", "missing_prerequisite", "required command or file is unavailable"
    if "connection refused" in lower or "networkerror" in lower or "failed to fetch" in lower:
        return "infra_failed", "runtime_unreachable", "runtime prerequisite is unreachable"
    return "failed", f"{name}_failed", "gate failed; see log"


def run_gate_process_step(
    *,
    project_root: Path,
    logs_dir: Path,
    index: int,
    spec: GateSpec,
    timeout_seconds: int,
    dry_run: bool = False,
) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, spec.name)
    cwd = project_root / spec.cwd if spec.cwd else project_root
    if spec.skip_reason:
        message = spec.skip_reason
        log_path.write_text(
            "\n".join(
                [
                    f"# {spec.name}",
                    f"status: {spec.skip_status}",
                    f"classification: {spec.skip_classification}",
                    f"cwd: {spec.cwd or '.'}",
                    f"reason: {message}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return GateResult(
            name=spec.name,
            status=spec.skip_status,
            classification=spec.skip_classification,
            message=message,
            cwd=spec.cwd or ".",
            command=spec.command,
            required=spec.required,
            log_path=rel(log_path, project_root),
            details=spec.details,
        )
    if spec.not_implemented_reason:
        message = spec.not_implemented_reason
        log_path.write_text(
            "\n".join(
                [
                    f"# {spec.name}",
                    "status: not_implemented",
                    f"cwd: {spec.cwd or '.'}",
                    f"reason: {message}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return GateResult(
            name=spec.name,
            status="not_implemented",
            classification="not_implemented",
            message=message,
            cwd=spec.cwd or ".",
            command=spec.command,
            required=spec.required,
            log_path=rel(log_path, project_root),
            details=spec.details,
        )
    if dry_run:
        command_text = release_gate_command_display(spec.command) if spec.command else f"internal:{spec.internal_check or spec.name}"
        log_path.write_text(
            "\n".join(
                [
                    f"$ {command_text}",
                    f"cwd: {spec.cwd or '.'}",
                    "status: planned",
                    "reason: --dry-run was provided; command was not executed",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return GateResult(
            name=spec.name,
            status="planned",
            classification="dry_run",
            message="would run gate command",
            cwd=spec.cwd or ".",
            command=spec.command,
            required=spec.required,
            log_path=rel(log_path, project_root),
            details=spec.details,
        )
    if spec.internal_check:
        return run_release_gate_internal_step(
            project_root=project_root,
            logs_dir=logs_dir,
            index=index,
            spec=spec,
            timeout_seconds=timeout_seconds,
        )
    started = time.monotonic()
    env_extra = {"PYTHONDONTWRITEBYTECODE": "1"}
    env_extra.update(spec.env_extra)
    probe = run_process_probe(spec.name, spec.command, cwd=cwd, timeout=timeout_seconds, env_extra=env_extra)
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = release_gate_sanitize_output(project_root, probe.stdout or "")
    stderr = release_gate_sanitize_output(project_root, probe.stderr or probe.error or "")
    status, classification, message = classify_gate_output(spec.name, stdout, stderr, probe.error, probe.returncode)
    if not probe.available:
        status, classification, message = "infra_failed", "missing_prerequisite", f"required command is unavailable: {spec.command[0]}"
    log_path.write_text(
        "\n".join(
            [
                f"$ {release_gate_command_display(spec.command)}",
                f"cwd: {spec.cwd or '.'}",
                f"exit: {probe.returncode if probe.returncode is not None else probe.error or '<none>'}",
                f"duration_ms: {duration_ms}",
                f"status: {status}",
                f"classification: {classification}",
                "",
                "## stdout",
                stdout or "<empty>",
                "",
                "## stderr",
                stderr or "<empty>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name=spec.name,
        status=status,
        classification=classification,
        message=message,
        cwd=spec.cwd or ".",
        command=spec.command,
        required=spec.required,
        returncode=probe.returncode,
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details=spec.details,
    )



def postgres_quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def release_gate_safe_managed_db_name(tool_version: str, run_id_value: str) -> str:
    version = re.sub(r"[^a-zA-Z0-9]+", "_", tool_version).strip("_").lower() or "tool"
    timestamp = now_utc().strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha256(f"{run_id_value}|{timestamp}|{os.getpid()}".encode("utf-8")).hexdigest()[:8]
    name = f"p2pkanban_rg_{version}_{timestamp}_{digest}"
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:63]


def release_gate_database_url_source(project_root: Path) -> tuple[str | None, str | None]:
    for key in ["DATABASE__URL", "DATABASE_URL"]:
        value = os.environ.get(key)
        if value:
            return value, f"environment {key}"
    backend_values = backend_effective_env(project_root)
    for key in ["DATABASE__URL", "DATABASE_URL"]:
        value = backend_values.get(key)
        if value:
            return value, f"backend effective env {key}"
    return None, None


def replace_database_name_in_url(value: str, database_name: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    path = "/" + urllib.parse.quote(database_name, safe="")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def database_url_with_credentials(value: str, *, database_name: str, username: str | None, password: str | None) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    auth = ""
    if username:
        auth = urllib.parse.quote(username, safe="")
        if password is not None:
            auth += ":" + urllib.parse.quote(password, safe="")
        auth += "@"
    path = "/" + urllib.parse.quote(database_name, safe="")
    return urllib.parse.urlunsplit((parsed.scheme, auth + host + port, path, parsed.query, parsed.fragment))


def release_gate_managed_db_env(database_url: str) -> dict[str, str]:
    return {
        "DATABASE__URL": database_url,
        "DATABASE_URL": database_url,
        "TEST_DATABASE_URL": database_url,
    }


def release_gate_managed_db_cleanup_command(maintenance_url: str, database_name: str) -> str:
    env = psql_env_from_database_url(maintenance_url)
    visible_env = []
    for key in ["PGHOST", "PGPORT", "PGUSER", "PGDATABASE"]:
        if env.get(key):
            visible_env.append(f"{key}={env[key]}")
    quoted = postgres_quote_identifier(database_name)
    sql = f"DROP DATABASE IF EXISTS {quoted};"
    return " ".join([*visible_env, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-c", repr(sql)]).strip()



def managed_test_db_public_payload(state: ManagedTestDatabaseState) -> dict[str, Any]:
    payload = as_jsonable(state)
    # Raw PostgreSQL URLs may contain passwords. Reports and patchable bundles should only
    # expose masked URLs; the live in-memory state keeps raw URLs only for subprocess env.
    payload["database_url"] = state.masked_database_url
    payload["maintenance_url"] = state.masked_maintenance_url
    details = payload.get("details")
    if isinstance(details, dict):
        for key in ["databaseUrl", "maintenanceUrl"]:
            if key in details and isinstance(details[key], str):
                details[key] = mask_database_url(details[key])
    return payload


def classify_managed_db_psql_failure(probe: ProcessProbe, db_url: str | None) -> str:
    text = sanitize_postgres_output("\n".join(part for part in [probe.stderr, probe.stdout, probe.error or ""] if part), db_url).lower()
    if not probe.available:
        return "postgres_client_missing"
    if "permission denied to create database" in text or "must be member" in text or "permission denied" in text:
        return "postgres_createdb_permission_denied"
    if "password authentication failed" in text or "authentication failed" in text or ("role" in text and "does not exist" in text):
        return "postgres_auth_failed"
    if "could not connect" in text or "connection refused" in text or "no such file" in text:
        return "postgres_unavailable"
    if "timeout" in text:
        return "postgres_connect_timeout"
    if "already exists" in text:
        return "managed_test_db_name_collision"
    return "managed_test_db_psql_failed"


def build_release_gates_managed_test_database(
    project_root: Path,
    run_dir: Path,
    *,
    run_id_value: str,
    retention: str,
    dry_run: bool,
    start_db_if_needed: bool,
    test_db_admin_user: str | None = None,
    test_db_admin_password: str | None = None,
    test_db_admin_password_env: str | None = None,
    test_db_maintenance_db: str = "postgres",
) -> ManagedTestDatabaseState:
    state = ManagedTestDatabaseState(enabled=True, retention=retention, run_id=run_id_value, created_at=iso_now())
    metadata_path = run_dir / "managed-test-db.json"
    state.metadata_path = rel(metadata_path, project_root)

    source_url, source = release_gate_database_url_source(project_root)
    state.source = source
    if not source_url:
        state.status = "infra_failed"
        state.classification = "managed_test_db_source_missing"
        state.message = "DATABASE__URL/DATABASE_URL is absent; cannot derive PostgreSQL connection target for managed test DB."
        return state

    source_probe = parse_database_url_probe(source_url)
    state.details["sourceUrl"] = source_probe.masked_url
    state.details["sourceWarnings"] = source_probe.warnings
    if source_probe.warnings or source_probe.scheme not in {"postgres", "postgresql"}:
        state.status = "infra_failed"
        state.classification = "managed_test_db_source_invalid"
        state.message = "DATABASE__URL/DATABASE_URL is not a complete PostgreSQL URL."
        return state

    admin_password_value = test_db_admin_password
    admin_password_source: str | None = "flag" if test_db_admin_password is not None else None
    if admin_password_value is None and test_db_admin_password_env:
        admin_password_value = os.environ.get(test_db_admin_password_env)
        admin_password_source = f"env:{test_db_admin_password_env}" if admin_password_value is not None else f"missing-env:{test_db_admin_password_env}"
        if admin_password_value is None and dry_run:
            admin_password_source = f"env:{test_db_admin_password_env}:not-read-dry-run"
        elif admin_password_value is None:
            state.status = "infra_failed"
            state.classification = "managed_test_db_admin_password_missing"
            state.message = f"--test-db-admin-password-env={test_db_admin_password_env} was provided, but that environment variable is not set."
            state.details["adminCredentials"] = {"user": test_db_admin_user, "passwordSource": admin_password_source}
            write_json(metadata_path, managed_test_db_public_payload(state))
            return state

    maintenance_database = test_db_maintenance_db or "postgres"
    admin_credentials_overridden = bool(test_db_admin_user or admin_password_value is not None)
    admin_user = test_db_admin_user or (source_probe.username if admin_credentials_overridden else None)

    database_name = release_gate_safe_managed_db_name(TOOL_VERSION, run_id_value)
    if admin_credentials_overridden:
        # Use the explicit maintenance/admin identity as the runtime identity too.
        # Host/port/query still come from DATABASE__URL, but that URL may contain
        # a stale password for a dev role that cannot authenticate on this machine.
        # Without this, CREATE DATABASE can succeed while sqlx tests and the
        # managed backend fail immediately on authentication.
        database_url = database_url_with_credentials(source_url, database_name=database_name, username=admin_user, password=admin_password_value)
        runtime_user = admin_user or source_probe.username
        runtime_password_source = admin_password_source or ("source-url" if source_probe.has_password else "none")
        runtime_credentials_source = "admin-credentials"
        owner_user = runtime_user
        maintenance_url = database_url_with_credentials(source_url, database_name=maintenance_database, username=admin_user, password=admin_password_value)
    else:
        database_url = replace_database_name_in_url(source_url, database_name)
        runtime_user = source_probe.username
        runtime_password_source = "source-url" if source_probe.has_password else "none"
        runtime_credentials_source = "source-url"
        owner_user = source_probe.username
        maintenance_url = replace_database_name_in_url(source_url, maintenance_database)
    state.details["maintenanceDatabase"] = maintenance_database
    state.details["adminCredentials"] = {
        "overridden": admin_credentials_overridden,
        "user": admin_user or source_probe.username,
        "passwordSource": admin_password_source or ("source-url" if source_probe.has_password else "none"),
    }
    state.details["runtimeCredentials"] = {
        "source": runtime_credentials_source,
        "user": runtime_user,
        "passwordSource": runtime_password_source,
    }
    state.database_name = database_name
    state.database_url = database_url
    state.masked_database_url = mask_database_url(database_url)
    state.maintenance_url = maintenance_url
    state.masked_maintenance_url = mask_database_url(maintenance_url)
    state.cleanup_command = release_gate_managed_db_cleanup_command(maintenance_url, database_name)
    owner_clause = f" OWNER {postgres_quote_identifier(owner_user)}" if owner_user else ""
    create_sql = f"CREATE DATABASE {postgres_quote_identifier(database_name)}{owner_clause};"
    state.create_command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", create_sql]
    drop_sql = f"DROP DATABASE IF EXISTS {postgres_quote_identifier(database_name)};"
    state.drop_command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", drop_sql]

    if dry_run:
        state.status = "planned"
        state.classification = "dry_run"
        state.message = "would create managed PostgreSQL test database"
        write_json(metadata_path, managed_test_db_public_payload(state))
        return state

    if start_db_if_needed:
        db_port = source_probe.port or DEFAULT_PORTS["postgres"]
        db_host = source_probe.host or "127.0.0.1"
        if not probe_port("managed_test_db_postgres_port", db_port, host=db_host).open:
            pg_result = build_postgres_result(project_root, Path.cwd(), mode="start-db")
            apply_start_db(pg_result, project_root, timeout_seconds=TIMEOUT_POLICY["postgres_ready"])
            state.details["startDbIfNeeded"] = as_jsonable(pg_result.actions)

    if shutil.which("psql") is None:
        state.status = "infra_failed"
        state.classification = "postgres_client_missing"
        state.message = "psql is not available on PATH; managed test DB cannot be created safely."
        write_json(metadata_path, managed_test_db_public_payload(state))
        return state

    ready_probe = probe_pg_isready(maintenance_url, project_root)
    state.details["pgIsReady"] = as_jsonable(ready_probe)
    if not process_probe_ok(ready_probe):
        state.status = "infra_failed"
        state.classification = classify_managed_db_psql_failure(ready_probe, maintenance_url)
        state.message = "PostgreSQL maintenance target is not reachable."
        write_json(metadata_path, managed_test_db_public_payload(state))
        return state

    env_extra = psql_env_from_database_url(maintenance_url)
    create_probe = run_process_probe("managed_test_db_create", state.create_command, cwd=project_root, timeout=30, env_extra=env_extra)
    create_probe.stdout = sanitize_postgres_output(create_probe.stdout, maintenance_url)
    create_probe.stderr = sanitize_postgres_output(create_probe.stderr, maintenance_url)
    state.details["createProbe"] = as_jsonable(create_probe)
    if not process_probe_ok(create_probe):
        state.status = "infra_failed"
        state.classification = classify_managed_db_psql_failure(create_probe, maintenance_url)
        state.message = "Failed to create managed PostgreSQL test database."
        write_json(metadata_path, managed_test_db_public_payload(state))
        return state

    runtime_connect_command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-Atc", "SELECT 1;"]
    runtime_probe = run_process_probe("managed_test_db_runtime_connect", runtime_connect_command, cwd=project_root, timeout=30, env_extra=psql_env_from_database_url(database_url))
    runtime_probe.stdout = sanitize_postgres_output(runtime_probe.stdout, database_url)
    runtime_probe.stderr = sanitize_postgres_output(runtime_probe.stderr, database_url)
    state.details["runtimeConnectProbe"] = as_jsonable(runtime_probe)
    if not process_probe_ok(runtime_probe):
        drop_probe = run_process_probe("managed_test_db_drop_after_runtime_connect_failure", state.drop_command, cwd=project_root, timeout=30, env_extra=env_extra)
        drop_probe.stdout = sanitize_postgres_output(drop_probe.stdout, maintenance_url)
        drop_probe.stderr = sanitize_postgres_output(drop_probe.stderr, maintenance_url)
        state.details["dropAfterRuntimeConnectFailureProbe"] = as_jsonable(drop_probe)
        state.retained = not process_probe_ok(drop_probe)
        state.status = "infra_failed"
        state.failure_code = classify_managed_db_psql_failure(runtime_probe, database_url)
        state.classification = "managed_test_db_runtime_connection_failed"
        state.message = "Managed PostgreSQL test database was created, but runtime credentials cannot connect to it."
        write_json(metadata_path, managed_test_db_public_payload(state))
        return state

    state.status = "ok"
    state.classification = "managed_test_db_created"
    state.message = "managed PostgreSQL test database created"
    write_json(metadata_path, managed_test_db_public_payload(state))
    return state


def release_gates_managed_db_prepare_result(project_root: Path, logs_dir: Path, index: int, state: ManagedTestDatabaseState) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, "managed_test_db_prepare")
    lines = [
        "# managed_test_db_prepare",
        f"status: {state.status}",
        f"classification: {state.classification}",
        f"retention: {state.retention}",
        f"database: {state.database_name or '<none>'}",
        f"url: {state.masked_database_url or '<none>'}",
        f"maintenance_url: {state.masked_maintenance_url or '<none>'}",
        f"metadata: {state.metadata_path or '<none>'}",
        f"cleanup: {state.cleanup_command or '<none>'}",
        f"message: {state.message}",
        "",
        json.dumps(managed_test_db_public_payload(state), ensure_ascii=False, indent=2),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return GateResult(
        name="managed_test_db_prepare",
        status=state.status,
        classification=state.classification,
        message=state.message,
        cwd=".",
        command=state.create_command,
        required=True,
        log_path=rel(log_path, project_root),
        details=managed_test_db_public_payload(state),
    )



def managed_runtime_public_payload(state: ManagedRuntimeState) -> dict[str, Any]:
    payload = as_jsonable(state)
    # Managed runtime never exposes raw database URLs. Only the masked copy is stored.
    if isinstance(payload.get("details"), dict):
        details = payload["details"]
        for key, value in list(details.items()):
            if isinstance(value, str) and value.startswith(("postgres://", "postgresql://")):
                details[key] = mask_database_url(value)
    return payload


def find_available_tcp_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def build_managed_runtime_state(project_root: Path, run_dir: Path, run_id_value: str) -> ManagedRuntimeState:
    backend_host = "127.0.0.1"
    frontend_host = "127.0.0.1"
    backend_port = find_available_tcp_port(backend_host)
    frontend_port = find_available_tcp_port(frontend_host)
    if frontend_port == backend_port:
        frontend_port = find_available_tcp_port(frontend_host)
    state = ManagedRuntimeState(
        enabled=True,
        run_id=run_id_value,
        status="planned",
        classification="managed_runtime_planned",
        message="managed backend/frontend runtime is planned",
        backend_host=backend_host,
        backend_port=backend_port,
        frontend_host=frontend_host,
        frontend_port=frontend_port,
        backend_api_base_url=f"http://{backend_host}:{backend_port}/api/v1",
        backend_health_url=f"http://{backend_host}:{backend_port}/api/v1/health",
        frontend_url=f"http://{frontend_host}:{frontend_port}/",
        runtime_state_path=rel(run_dir / "logs" / "runtime-state.json", project_root),
        env_diff_path=rel(run_dir / "logs" / "runtime-env-diff.md", project_root),
        managed_urls_path=rel(run_dir / "logs" / "managed-urls.env", project_root),
    )
    return state


def release_gate_managed_runtime_database_url(
    project_root: Path,
    *,
    managed_test_db_url: str | None,
    allow_dev_db_write: bool,
) -> tuple[str | None, str]:
    if managed_test_db_url:
        return managed_test_db_url, "managed ephemeral test database"
    test_db_url, test_db_source = release_gate_explicit_test_database_url(project_root)
    if test_db_url:
        return test_db_url, test_db_source or "TEST_DATABASE_URL"
    if allow_dev_db_write:
        source_url, source = release_gate_database_url_source(project_root)
        if source_url:
            return source_url, source or "configured backend database"
    return None, "managed runtime needs --managed-test-db, TEST_DATABASE_URL, or explicit --allow-dev-db-write"


def release_gate_managed_browser_env(state: ManagedRuntimeState) -> dict[str, str]:
    env: dict[str, str] = {}
    if state.backend_api_base_url:
        env["VITE_API_BASE_URL"] = state.backend_api_base_url.rstrip("/")
    if state.frontend_url:
        env["PLAYWRIGHT_BASE_URL"] = state.frontend_url.rstrip("/")
        env["PLAYWRIGHT_WEB_SERVER_URL"] = state.frontend_url.rstrip("/")
    if state.frontend_host:
        env["PLAYWRIGHT_FRONTEND_HOST"] = state.frontend_host
    if state.frontend_port:
        env["PLAYWRIGHT_FRONTEND_PORT"] = str(state.frontend_port)
    return env


def release_gate_managed_backend_cors_env(project_root: Path, state: ManagedRuntimeState) -> dict[str, str]:
    """Return backend CORS overrides for an owned managed frontend on a dynamic port.

    The local managed runtime intentionally starts Vite on an arbitrary free port.
    The backend default allowlist only covers the usual Vite ports, so the
    real-backend browser gate can be blocked by CORS even though backend,
    frontend and Playwright are all healthy.  This override is scoped to the
    managed backend process only and never writes project env files.
    """

    frontend_origin = parse_url_origin((state.frontend_url or "").rstrip("/"))
    if not frontend_origin:
        return {}

    configured = split_csv(backend_effective_env(project_root).get("HTTP__CORS_ALLOWED_ORIGINS", ""))
    origins: list[str] = []

    def add_origin(value: str | None) -> None:
        normalized = (value or "").strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)

    for origin in configured:
        add_origin(origin)
    add_origin(frontend_origin)

    try:
        parsed = urllib.parse.urlsplit(frontend_origin)
    except Exception:
        parsed = None
    if parsed and parsed.scheme and parsed.hostname:
        port = f":{parsed.port}" if parsed.port is not None else ""
        if parsed.hostname == "127.0.0.1":
            add_origin(f"{parsed.scheme}://localhost{port}")
        elif parsed.hostname == "localhost":
            add_origin(f"{parsed.scheme}://127.0.0.1{port}")

    return {"HTTP__CORS_ALLOWED_ORIGINS": ",".join(origins)}


def write_release_gates_runtime_files(
    project_root: Path,
    logs_dir: Path,
    state: ManagedRuntimeState,
    *,
    backend_env_diff: dict[str, str] | None = None,
    frontend_env_diff: dict[str, str] | None = None,
) -> None:
    state.runtime_state_path = rel(logs_dir / "runtime-state.json", project_root)
    state.env_diff_path = rel(logs_dir / "runtime-env-diff.md", project_root)
    state.managed_urls_path = rel(logs_dir / "managed-urls.env", project_root)
    write_json(logs_dir / "runtime-state.json", managed_runtime_public_payload(state))

    url_lines = [
        f"MANAGED_BACKEND_API_BASE_URL={state.backend_api_base_url or ''}",
        f"MANAGED_BACKEND_HEALTH_URL={state.backend_health_url or ''}",
        f"MANAGED_FRONTEND_URL={state.frontend_url or ''}",
    ]
    (logs_dir / "managed-urls.env").write_text("\n".join(url_lines) + "\n", encoding="utf-8")

    lines = ["# Managed runtime environment diff", ""]
    for title, values in [("Backend", backend_env_diff or {}), ("Frontend", frontend_env_diff or {})]:
        lines.append(f"## {title}")
        lines.append("")
        if not values:
            lines.append("- <none>")
        else:
            for key in sorted(values):
                value = values[key]
                if is_secret_key(key) or key in {"DATABASE__URL", "DATABASE_URL", "TEST_DATABASE_URL"}:
                    value = mask_value(key, value)
                    if key in {"DATABASE__URL", "DATABASE_URL", "TEST_DATABASE_URL"}:
                        value = mask_database_url(values[key])
                lines.append(f"- `{key}` = `{value}`")
        lines.append("")
    (logs_dir / "runtime-env-diff.md").write_text("\n".join(lines), encoding="utf-8")


def release_gates_managed_runtime_plan_result(project_root: Path, logs_dir: Path, index: int, state: ManagedRuntimeState) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, "managed_runtime_plan")
    state.status = "planned"
    state.classification = "dry_run"
    state.message = "would start isolated backend/frontend runtime on dynamic ports"
    write_release_gates_runtime_files(project_root, logs_dir, state)
    log_path.write_text(
        "\n".join(
            [
                "# managed_runtime_plan",
                "status: planned",
                "classification: dry_run",
                f"backend_api_base_url: {state.backend_api_base_url}",
                f"frontend_url: {state.frontend_url}",
                f"runtime_state: {state.runtime_state_path}",
                "",
                json.dumps(managed_runtime_public_payload(state), ensure_ascii=False, indent=2),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name="managed_runtime_plan",
        status="planned",
        classification="dry_run",
        message=state.message,
        cwd=".",
        command=[sys.executable, "tools/devbootstrap.py", "release-gates", "--managed-runtime"],
        log_path=rel(log_path, project_root),
        details=managed_runtime_public_payload(state),
    )


def release_gates_managed_runtime_db_unavailable_result(
    project_root: Path,
    logs_dir: Path,
    index: int,
    state: ManagedRuntimeState,
    reason: str,
) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, "managed_runtime_db")
    state.status = "infra_failed"
    state.classification = "managed_runtime_db_unavailable"
    state.message = reason
    write_release_gates_runtime_files(project_root, logs_dir, state)
    log_path.write_text(
        "\n".join(
            [
                "# managed_runtime_db",
                "status: infra_failed",
                "classification: managed_runtime_db_unavailable",
                f"reason: {reason}",
                f"runtime_state: {state.runtime_state_path}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name="managed_runtime_db",
        status="infra_failed",
        classification="managed_runtime_db_unavailable",
        message=reason,
        cwd=".",
        command=[],
        required=True,
        log_path=rel(log_path, project_root),
        details=managed_runtime_public_payload(state),
    )

def start_release_gates_managed_backend(
    project_root: Path,
    logs_dir: Path,
    index: int,
    state: ManagedRuntimeState,
    database_url: str,
    timeout_seconds: int,
) -> tuple[GateResult, ReleaseGatesManagedRuntimeProcess | None]:
    log_path = release_gate_log_path(logs_dir, index, "managed_backend_start")
    host = state.backend_host
    port = state.backend_port or DEFAULT_PORTS["backend"]
    health_before = probe_backend_health(host, port, timeout=0.8)
    port_probe = probe_port("managed_backend", port, host=http_probe_host(host), timeout=0.4)
    details: dict[str, Any] = {
        "maskedDatabaseUrl": mask_database_url(database_url),
        "host": host,
        "port": port,
        "apiBaseUrl": state.backend_api_base_url,
        "healthBefore": as_jsonable(health_before),
        "portBefore": as_jsonable(port_probe),
    }
    if backend_health_ready(health_before) or port_probe.open:
        message = "Selected managed backend port is already occupied; release-gates will not reuse or kill a foreign/live backend."
        state.status = "infra_failed"
        state.classification = "managed_backend_port_occupied"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state)
        log_path.write_text("\n".join(["# managed_backend_start", "status: infra_failed", "classification: managed_backend_port_occupied", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_backend_start",
            status="infra_failed",
            classification="managed_backend_port_occupied",
            message=message,
            cwd="backend",
            command=["cargo", "run", "--bin", "p2p-planner-backend"],
            log_path=rel(log_path, project_root),
            details=details,
        ), None
    if shutil.which("cargo") is None:
        message = "cargo is not available on PATH; managed backend cannot be started."
        state.status = "infra_failed"
        state.classification = "missing_cargo"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state)
        log_path.write_text("\n".join(["# managed_backend_start", "status: infra_failed", "classification: missing_cargo", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_backend_start",
            status="infra_failed",
            classification="missing_cargo",
            message=message,
            cwd="backend",
            command=["cargo", "run", "--bin", "p2p-planner-backend"],
            log_path=rel(log_path, project_root),
            details=details,
        ), None

    backend_dir = project_root / "backend"
    backend_log_path = logs_dir / f"{index:02d}_managed_backend_process.log"
    command = ["cargo", "run", "--bin", "p2p-planner-backend"]
    execution_command = command_for_subprocess(command)
    backend_env_diff = release_gate_managed_db_env(database_url)
    backend_env_diff.update(release_gate_managed_backend_cors_env(project_root, state))
    backend_env_diff.update({"APP__HOST": host, "APP__PORT": str(port), "PYTHONDONTWRITEBYTECODE": "1"})
    frontend_env_diff = release_gate_managed_browser_env(state)
    state.backend_log_path = rel(backend_log_path, project_root)
    state.masked_database_url = mask_database_url(database_url)
    write_release_gates_runtime_files(project_root, logs_dir, state, backend_env_diff=backend_env_diff, frontend_env_diff=frontend_env_diff)

    log_handle = backend_log_path.open("ab", buffering=0)
    header = "\n".join(
        [
            f"== managed release-gates backend {iso_now()} ==",
            f"$ {command_as_text(command)}",
            f"resolved: {command_as_text(execution_command)}",
            f"cwd: {rel(backend_dir, project_root)}",
            f"APP__HOST: {host}",
            f"APP__PORT: {port}",
            f"DATABASE__URL: {mask_database_url(database_url)}",
            f"HTTP__CORS_ALLOWED_ORIGINS: {backend_env_diff.get('HTTP__CORS_ALLOWED_ORIGINS', '<unchanged>')}",
            "",
        ]
    ).encode("utf-8", errors="replace")
    log_handle.write(header)
    env = os.environ.copy()
    env.update(backend_env_diff)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            execution_command,
            cwd=str(backend_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            **popen_process_group_kwargs(),
        )
    except OSError as exc:
        log_handle.close()
        message = f"Could not start managed backend: {exc}"
        state.status = "infra_failed"
        state.classification = "backend_start_failed"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state, backend_env_diff=backend_env_diff, frontend_env_diff=frontend_env_diff)
        log_path.write_text("\n".join(["# managed_backend_start", "status: infra_failed", "classification: backend_start_failed", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_backend_start",
            status="infra_failed",
            classification="backend_start_failed",
            message=message,
            cwd="backend",
            command=command,
            log_path=rel(log_path, project_root),
            details=details,
        ), None
    finally:
        try:
            log_handle.close()
        except Exception:
            pass

    state.backend_pid = process.pid
    state.started_at = state.started_at or iso_now()
    ready, probes, returncode = wait_for_backend_health(process, host, port, timeout_seconds=timeout_seconds)
    duration_ms = int((time.monotonic() - started) * 1000)
    details.update({"pid": process.pid, "healthAfter": as_jsonable(probes), "processReturncode": returncode, "processLog": rel(backend_log_path, project_root)})
    if ready:
        message = "managed backend started against the selected test database on a dynamic port"
        status = "ok"
        classification = "managed_backend_started"
        state.status = "backend_started"
        state.classification = classification
        state.message = message
        runtime_process = ReleaseGatesManagedRuntimeProcess(
            name="backend",
            process=process,
            log_path=backend_log_path,
            command=command,
            cwd=backend_dir,
            host=host,
            port=port,
            url=state.backend_api_base_url or f"http://{host}:{port}/api/v1",
        )
    else:
        log_tail = sanitize_backend_log(read_log_tail(backend_log_path), project_root)
        classification = classify_backend_failure(log_tail, "backend_health_timeout" if returncode is None else "backend_start_failed")
        message = "managed backend did not become healthy; see managed backend process log"
        status = "infra_failed" if classification in {"postgres_unavailable", "database_missing", "postgres_auth_failed", "backend_health_timeout", "missing_prerequisite"} else "failed"
        state.status = status
        state.classification = classification
        state.message = message
        runtime_process = None
        if process.poll() is None:
            stop_managed_popen(process, timeout_seconds=5)
    write_release_gates_runtime_files(project_root, logs_dir, state, backend_env_diff=backend_env_diff, frontend_env_diff=frontend_env_diff)
    log_path.write_text(
        "\n".join(
            [
                "# managed_backend_start",
                f"status: {status}",
                f"classification: {classification}",
                f"duration_ms: {duration_ms}",
                f"process_log: {rel(backend_log_path, project_root)}",
                f"message: {message}",
                "",
                json.dumps(details, ensure_ascii=False, indent=2),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name="managed_backend_start",
        status=status,
        classification=classification,
        message=message,
        cwd="backend",
        command=command,
        returncode=returncode,
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details=details,
    ), runtime_process

def managed_frontend_http_ready(probe: HttpProbe | None) -> bool:
    return bool(probe and probe.reachable and probe.status is not None and 200 <= probe.status < 300)


def wait_for_managed_frontend_root(process: subprocess.Popen[Any], url: str, *, timeout_seconds: int) -> tuple[bool, HttpProbe | None, int | None]:
    deadline = time.monotonic() + timeout_seconds
    last_probe: HttpProbe | None = None
    while time.monotonic() < deadline:
        returncode = process.poll()
        last_probe = probe_http("managed_frontend_root", url, timeout=1.0)
        if managed_frontend_http_ready(last_probe):
            return True, last_probe, returncode
        if returncode is not None:
            return False, last_probe, returncode
        time.sleep(1.0)
    return False, last_probe, process.poll()


def start_release_gates_managed_frontend(
    project_root: Path,
    logs_dir: Path,
    index: int,
    state: ManagedRuntimeState,
    timeout_seconds: int,
) -> tuple[GateResult, ReleaseGatesManagedRuntimeProcess | None]:
    log_path = release_gate_log_path(logs_dir, index, "managed_frontend_start")
    host = state.frontend_host
    port = state.frontend_port or DEFAULT_PORTS["frontend"]
    frontend_url = state.frontend_url or f"http://{host}:{port}/"
    root_before = probe_http("managed_frontend_root", frontend_url, timeout=0.8)
    port_probe = probe_port("managed_frontend", port, host=http_probe_host(host), timeout=0.4)
    details: dict[str, Any] = {
        "host": host,
        "port": port,
        "frontendUrl": frontend_url,
        "apiBaseUrl": state.backend_api_base_url,
        "rootBefore": as_jsonable(root_before),
        "portBefore": as_jsonable(port_probe),
    }
    if managed_frontend_http_ready(root_before) or port_probe.open:
        message = "Selected managed frontend port is already occupied; release-gates will not reuse or kill a foreign/live frontend."
        state.status = "infra_failed"
        state.classification = "managed_frontend_port_occupied"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state)
        log_path.write_text("\n".join(["# managed_frontend_start", "status: infra_failed", "classification: managed_frontend_port_occupied", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_frontend_start",
            status="infra_failed",
            classification="managed_frontend_port_occupied",
            message=message,
            cwd="frontend",
            command=["npm", "run", "dev"],
            log_path=rel(log_path, project_root),
            details=details,
        ), None
    if shutil.which("npm") is None:
        message = "npm is not available on PATH; managed frontend cannot be started."
        state.status = "infra_failed"
        state.classification = "missing_npm"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state)
        log_path.write_text("\n".join(["# managed_frontend_start", "status: infra_failed", "classification: missing_npm", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_frontend_start",
            status="infra_failed",
            classification="missing_npm",
            message=message,
            cwd="frontend",
            command=["npm", "run", "dev"],
            log_path=rel(log_path, project_root),
            details=details,
        ), None

    frontend_dir = project_root / "frontend"
    frontend_log_path = logs_dir / f"{index:02d}_managed_frontend_process.log"
    command = ["npm", "run", "dev", "--", "--host", host, "--port", str(port), "--strictPort"]
    execution_command = command_for_subprocess(command)
    backend_env_diff: dict[str, str] = {}
    frontend_env_diff = release_gate_managed_browser_env(state)
    frontend_env_diff["PYTHONDONTWRITEBYTECODE"] = "1"
    state.frontend_log_path = rel(frontend_log_path, project_root)
    write_release_gates_runtime_files(project_root, logs_dir, state, backend_env_diff=backend_env_diff, frontend_env_diff=frontend_env_diff)

    log_handle = frontend_log_path.open("ab", buffering=0)
    header = "\n".join(
        [
            f"== managed release-gates frontend {iso_now()} ==",
            f"$ {command_as_text(command)}",
            f"resolved: {command_as_text(execution_command)}",
            f"cwd: {rel(frontend_dir, project_root)}",
            f"VITE_API_BASE_URL: {state.backend_api_base_url or '<none>'}",
            f"frontend_url: {frontend_url}",
            "",
        ]
    ).encode("utf-8", errors="replace")
    log_handle.write(header)
    env = os.environ.copy()
    env.update(frontend_env_diff)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            execution_command,
            cwd=str(frontend_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            **popen_process_group_kwargs(),
        )
    except OSError as exc:
        log_handle.close()
        message = f"Could not start managed frontend: {exc}"
        state.status = "infra_failed"
        state.classification = "frontend_start_failed"
        state.message = message
        write_release_gates_runtime_files(project_root, logs_dir, state, frontend_env_diff=frontend_env_diff)
        log_path.write_text("\n".join(["# managed_frontend_start", "status: infra_failed", "classification: frontend_start_failed", message, ""]), encoding="utf-8")
        return GateResult(
            name="managed_frontend_start",
            status="infra_failed",
            classification="frontend_start_failed",
            message=message,
            cwd="frontend",
            command=command,
            log_path=rel(log_path, project_root),
            details=details,
        ), None
    finally:
        try:
            log_handle.close()
        except Exception:
            pass

    state.frontend_pid = process.pid
    state.started_at = state.started_at or iso_now()
    ready, probe, returncode = wait_for_managed_frontend_root(process, frontend_url, timeout_seconds=timeout_seconds)
    duration_ms = int((time.monotonic() - started) * 1000)
    details.update({"pid": process.pid, "rootAfter": as_jsonable(probe), "processReturncode": returncode, "processLog": rel(frontend_log_path, project_root)})
    if ready:
        message = "managed frontend started on a dynamic port with managed backend API base URL"
        status = "ok"
        classification = "managed_frontend_started"
        state.status = "runtime_started"
        state.classification = classification
        state.message = message
        runtime_process = ReleaseGatesManagedRuntimeProcess(
            name="frontend",
            process=process,
            log_path=frontend_log_path,
            command=command,
            cwd=frontend_dir,
            host=host,
            port=port,
            url=frontend_url,
        )
    else:
        log_tail = sanitize_frontend_log(read_log_tail(frontend_log_path), project_root)
        classification = classify_frontend_failure(log_tail, "frontend_health_timeout" if returncode is None else "frontend_start_failed")
        message = "managed frontend did not become healthy; see managed frontend process log"
        status = "infra_failed" if classification in {"frontend_health_timeout", "frontend_dependency_missing", "frontend_port_conflict", "dependency_network_unavailable", "missing_prerequisite"} else "failed"
        state.status = status
        state.classification = classification
        state.message = message
        runtime_process = None
        if process.poll() is None:
            stop_managed_popen(process, timeout_seconds=5)
    write_release_gates_runtime_files(project_root, logs_dir, state, frontend_env_diff=frontend_env_diff)
    log_path.write_text(
        "\n".join(
            [
                "# managed_frontend_start",
                f"status: {status}",
                f"classification: {classification}",
                f"duration_ms: {duration_ms}",
                f"process_log: {rel(frontend_log_path, project_root)}",
                f"message: {message}",
                "",
                json.dumps(details, ensure_ascii=False, indent=2),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name="managed_frontend_start",
        status=status,
        classification=classification,
        message=message,
        cwd="frontend",
        command=command,
        returncode=returncode,
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details=details,
    ), runtime_process


def wait_for_popen_exit(process: subprocess.Popen[Any], timeout_seconds: float) -> bool:
    try:
        process.wait(timeout=max(0.0, timeout_seconds))
        return True
    except subprocess.TimeoutExpired:
        return process.poll() is not None


def stop_managed_popen(process: subprocess.Popen[Any], *, timeout_seconds: int) -> tuple[str, str | None, list[str]]:
    steps: list[str] = []
    if process.poll() is not None:
        return "already_exited", None, steps

    if os.name == "nt":
        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
        if ctrl_break is not None:
            try:
                process.send_signal(ctrl_break)
                steps.append("ctrl_break")
                if wait_for_popen_exit(process, min(3, timeout_seconds)):
                    return "stopped", None, steps
            except (OSError, ValueError) as exc:
                steps.append(f"ctrl_break_failed:{exc}")
        try:
            process.terminate()
            steps.append("terminate")
            if wait_for_popen_exit(process, max(1, timeout_seconds - 3)):
                return "stopped", None, steps
        except OSError as exc:
            steps.append(f"terminate_failed:{exc}")
        taskkill_command = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
        try:
            completed = subprocess.run(
                taskkill_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
            steps.append(f"taskkill_exit:{completed.returncode}")
            if wait_for_popen_exit(process, 5):
                return "force_stopped", None, steps
            error_text = safe_decode(completed.stderr or completed.stdout).strip()
            return "failed", error_text or "process still alive after taskkill", steps
        except (OSError, subprocess.TimeoutExpired) as exc:
            steps.append(f"taskkill_failed:{exc}")
            return "failed", str(exc), steps

    try:
        send_signal_to_owned_process(process.pid, signal.SIGTERM)
        steps.append("sigterm")
        if wait_for_popen_exit(process, timeout_seconds):
            return "stopped", None, steps
    except ProcessLookupError:
        return "already_exited", None, steps
    except OSError as exc:
        steps.append(f"sigterm_failed:{exc}")
        return "failed", str(exc), steps

    try:
        send_signal_to_owned_process(process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        steps.append("sigkill")
        if wait_for_popen_exit(process, 5):
            return "force_stopped", None, steps
    except ProcessLookupError:
        return "already_exited", None, steps
    except OSError as exc:
        steps.append(f"sigkill_failed:{exc}")
        return "failed", str(exc), steps
    return "failed", "process still alive after force kill", steps


def stop_release_gates_managed_process(project_root: Path, logs_dir: Path, index: int, runtime_process: ReleaseGatesManagedRuntimeProcess) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, f"managed_{runtime_process.name}_stop")
    started = time.monotonic()
    action, error, steps = stop_managed_popen(runtime_process.process, timeout_seconds=TIMEOUT_POLICY["stop_grace"])
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "ok" if action in {"stopped", "force_stopped", "already_exited"} else "infra_failed"
    classification = f"managed_{runtime_process.name}_stopped" if status == "ok" else f"managed_{runtime_process.name}_stop_failed"
    message = f"managed {runtime_process.name} stopped" if status == "ok" else f"managed {runtime_process.name} stop failed"
    lines = [
        f"# managed_{runtime_process.name}_stop",
        f"status: {status}",
        f"classification: {classification}",
        f"pid: {runtime_process.process.pid}",
        f"action: {action}",
        f"steps: {', '.join(steps) if steps else '<none>'}",
        f"duration_ms: {duration_ms}",
        f"process_log: {rel(runtime_process.log_path, project_root)}",
    ]
    if error:
        lines.append(f"error: {error}")
    lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return GateResult(
        name=f"managed_{runtime_process.name}_stop",
        status=status,
        classification=classification,
        message=message,
        cwd=rel(runtime_process.cwd, project_root),
        command=["stop-managed-process", str(runtime_process.process.pid)],
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details={"pid": runtime_process.process.pid, "action": action, "steps": steps, "processLog": rel(runtime_process.log_path, project_root), "error": error},
    )


def release_gates_skip_for_frontend_prepare_failed(project_root: Path, logs_dir: Path, index: int, spec: GateSpec, blocker: GateResult) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, spec.name)
    message = f"Skipped because frontend_prepare_dependencies did not pass: {blocker.classification} — {blocker.message}"
    log_path.write_text(
        "\n".join(
            [
                f"# {spec.name}",
                "status: skipped_prerequisite",
                "classification: frontend_prepare_dependencies_failed",
                f"cwd: {spec.cwd or '.'}",
                f"reason: {message}",
                f"blocked_by_log: {blocker.log_path or '<none>'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    details = dict(spec.details)
    details["blockedBy"] = {"gate": blocker.name, "status": blocker.status, "classification": blocker.classification, "logPath": blocker.log_path}
    return GateResult(
        name=spec.name,
        status="skipped_prerequisite",
        classification="frontend_prepare_dependencies_failed",
        message=message,
        cwd=spec.cwd or ".",
        command=spec.command,
        required=spec.required,
        log_path=rel(log_path, project_root),
        details=details,
    )


def release_gates_skip_for_managed_runtime_unavailable(project_root: Path, logs_dir: Path, index: int, spec: GateSpec, reason: str) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, spec.name)
    message = f"Skipped because managed runtime is unavailable: {reason}"
    log_path.write_text(
        "\n".join(
            [
                f"# {spec.name}",
                "status: skipped_prerequisite",
                "classification: managed_runtime_unavailable",
                f"cwd: {spec.cwd or '.'}",
                f"reason: {message}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name=spec.name,
        status="skipped_prerequisite",
        classification="managed_runtime_unavailable",
        message=message,
        cwd=spec.cwd or ".",
        command=spec.command,
        required=spec.required,
        log_path=rel(log_path, project_root),
        details=spec.details,
    )


def finalize_release_gates_managed_test_database(
    project_root: Path,
    logs_dir: Path,
    index: int,
    state: ManagedTestDatabaseState,
    *,
    release_succeeded: bool,
    dump_on_failure: bool,
) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, "managed_test_db_retention")
    if state.status == "planned":
        state.retained = None
        state.message = "would apply managed test DB retention after release-gates"
        status = "planned"
        classification = "dry_run"
        message = state.message
    elif state.status != "ok" or not state.database_name or not state.maintenance_url:
        status = "skipped_prerequisite"
        classification = "managed_test_db_not_created"
        message = "managed test DB was not created; retention step skipped"
    else:
        should_drop = state.retention == "drop-always" or (state.retention == "keep-on-failure" and release_succeeded)
        should_keep = not should_drop
        if dump_on_failure and not release_succeeded:
            dump_path = logs_dir.parent / f"{state.database_name}.dump"
            state.dump_path = rel(dump_path, project_root)
            state.dump_command = ["pg_dump", "--format=custom", "--file", str(dump_path), state.database_name]
            if shutil.which("pg_dump") is not None:
                dump_env = psql_env_from_database_url(state.maintenance_url or state.database_url or "")
                dump_probe = run_process_probe("managed_test_db_dump", state.dump_command, cwd=project_root, timeout=120, env_extra=dump_env)
                state.details["dumpProbe"] = as_jsonable(dump_probe)
            else:
                state.details["dumpProbe"] = {"available": False, "error": "pg_dump not found on PATH"}
        if should_keep:
            state.retained = True
            state.message = "managed test DB kept by retention policy"
            status = "ok"
            classification = "managed_test_db_retained"
            message = state.message
        else:
            env_extra = psql_env_from_database_url(state.maintenance_url)
            drop_probe = run_process_probe("managed_test_db_drop", state.drop_command, cwd=project_root, timeout=30, env_extra=env_extra)
            drop_probe.stdout = sanitize_postgres_output(drop_probe.stdout, state.maintenance_url)
            drop_probe.stderr = sanitize_postgres_output(drop_probe.stderr, state.maintenance_url)
            state.details["dropProbe"] = as_jsonable(drop_probe)
            if process_probe_ok(drop_probe):
                state.retained = False
                state.message = "managed test DB dropped by retention policy"
                status = "ok"
                classification = "managed_test_db_dropped"
                message = state.message
            else:
                state.retained = True
                state.failure_code = classify_managed_db_psql_failure(drop_probe, state.maintenance_url)
                state.message = "failed to drop managed test DB; it was left for manual cleanup"
                status = "infra_failed"
                classification = state.failure_code or "managed_test_db_drop_failed"
                message = state.message
    if state.metadata_path:
        metadata_path = project_root / state.metadata_path
        write_json(metadata_path, managed_test_db_public_payload(state))
    log_path.write_text(
        "\n".join(
            [
                "# managed_test_db_retention",
                f"status: {status}",
                f"classification: {classification}",
                f"retention: {state.retention}",
                f"release_succeeded: {release_succeeded}",
                f"retained: {state.retained}",
                f"database: {state.database_name or '<none>'}",
                f"cleanup: {state.cleanup_command or '<none>'}",
                f"message: {message}",
                "",
                json.dumps(managed_test_db_public_payload(state), ensure_ascii=False, indent=2),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name="managed_test_db_retention",
        status=status,
        classification=classification,
        message=message,
        cwd=".",
        command=state.drop_command if state.drop_command else [],
        required=True,
        log_path=rel(log_path, project_root),
        details=managed_test_db_public_payload(state),
    )

def release_gate_database_env(project_root: Path) -> tuple[dict[str, str], str | None]:
    env_extra: dict[str, str] = {}
    if os.environ.get("TEST_DATABASE_URL"):
        env_extra["TEST_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
        return env_extra, "environment TEST_DATABASE_URL"
    if os.environ.get("DATABASE_URL"):
        env_extra["TEST_DATABASE_URL"] = os.environ["DATABASE_URL"]
        return env_extra, "environment DATABASE_URL mapped to TEST_DATABASE_URL"

    backend_values, _ = parse_env_file(project_root / "backend" / ".env")
    for key in ["TEST_DATABASE_URL", "DATABASE__URL", "DATABASE_URL"]:
        value = backend_values.get(key)
        if value:
            env_extra["TEST_DATABASE_URL"] = value
            return env_extra, f"backend env {key} mapped to TEST_DATABASE_URL"
    return env_extra, None


def release_gate_explicit_test_database_url(project_root: Path) -> tuple[str | None, str | None]:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"], "environment TEST_DATABASE_URL"
    backend_values, _ = parse_env_file(project_root / "backend" / ".env")
    if backend_values.get("TEST_DATABASE_URL"):
        return backend_values["TEST_DATABASE_URL"], "backend env TEST_DATABASE_URL"
    return None, None


def release_gate_smoke_env(project_root: Path) -> dict[str, str]:
    env_extra = {"BASE_URL": smoke_expected_base_url(project_root).rstrip("/"), "PYTHONDONTWRITEBYTECODE": "1"}
    test_db_url, _ = release_gate_explicit_test_database_url(project_root)
    if test_db_url:
        env_extra["TEST_DATABASE_URL"] = test_db_url
    return env_extra


def release_gate_smoke_allowed(project_root: Path, allow_dev_db_write: bool) -> tuple[bool, str]:
    if allow_dev_db_write:
        return True, "--allow-dev-db-write was provided"
    _, db_source = release_gate_explicit_test_database_url(project_root)
    if db_source:
        return True, db_source
    return False, "backend Python smoke writes through the live backend API; set TEST_DATABASE_URL or pass --allow-dev-db-write"


def playwright_browser_cache_roots(project_root: Path) -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured == "0":
        roots.append(project_root / "frontend" / "node_modules" / "playwright-core" / ".local-browsers")
    elif configured:
        roots.append(Path(configured).expanduser())

    home = Path.home()
    if platform.system().lower().startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots.append(Path(local_app_data) / "ms-playwright")
    elif platform.system().lower() == "darwin":
        roots.append(home / "Library" / "Caches" / "ms-playwright")
    else:
        roots.append(home / ".cache" / "ms-playwright")
    return list(dict.fromkeys(roots))


def playwright_chromium_executable_present(project_root: Path) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    executable_names = {"chrome", "chrome.exe", "headless_shell", "headless_shell.exe", "chromium", "chromium.exe"}
    for root in playwright_browser_cache_roots(project_root):
        evidence.append(str(root))
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if path.is_file() and path.name in executable_names and "chrom" in path.as_posix().lower():
                    return True, evidence + [str(path)]
        except OSError as exc:
            evidence.append(f"could not inspect {root}: {exc}")
    return False, evidence


def frontend_package_has_dependency(package_data: dict[str, Any], dependency_name: str) -> bool:
    for field_name in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
        value = package_data.get(field_name)
        if isinstance(value, dict) and dependency_name in value:
            return True
    return False


def release_gate_frontend_dependency_status(project_root: Path) -> tuple[bool, str | None, dict[str, Any]]:
    package_data, package_error = read_frontend_package(project_root)
    package_json_path = project_root / "frontend" / "package.json"
    package_lock_path = project_root / "frontend" / "package-lock.json"
    node_modules_path = project_root / "frontend" / "node_modules"
    marker_path = frontend_install_marker_path(project_root)
    package_json_hash = sha256_file(package_json_path)
    package_lock_hash = sha256_file(package_lock_path)
    node_probe = run_process_probe("node_version", ["node", "--version"], cwd=project_root, timeout=8)
    npm_probe = run_process_probe("npm_version", ["npm", "--version"], cwd=project_root, timeout=8)
    node_version = process_probe_version_value(node_probe)
    npm_version = process_probe_version_value(npm_probe)
    marker = load_frontend_install_marker(project_root)
    marker_reasons = frontend_install_marker_mismatch_reasons(
        project_root,
        package_json_hash,
        package_lock_hash,
        node_version=node_version,
        npm_version=npm_version,
    )
    marker_valid = not marker_reasons
    marker_error = marker.get("_error") if isinstance(marker, dict) else None
    details: dict[str, Any] = {
        "packageError": package_error,
        "packageJsonExists": package_json_path.is_file(),
        "packageLockExists": package_lock_path.is_file(),
        "nodeModulesExists": node_modules_path.is_dir(),
        "installMarkerPath": rel(marker_path, project_root),
        "installMarkerExists": marker_path.is_file(),
        "installMarkerValid": marker_valid,
        "installMarkerMismatchReasons": marker_reasons,
        "installMarkerError": marker_error,
        "packageJsonSha256": package_json_hash,
        "packageLockSha256": package_lock_hash,
        "markerPackageJsonSha256": marker.get("packageJsonSha256") if isinstance(marker, dict) else None,
        "markerPackageLockSha256": marker.get("packageLockSha256") if isinstance(marker, dict) else None,
        "markerNodeVersion": marker.get("nodeVersion") if isinstance(marker, dict) else None,
        "markerNpmVersion": marker.get("npmVersion") if isinstance(marker, dict) else None,
        "nodeVersion": node_version,
        "npmVersion": npm_version,
        "platform": frontend_install_platform_fingerprint(),
        "markerPlatform": marker.get("platform") if isinstance(marker, dict) else None,
        "installCommand": release_gate_command_display(frontend_install_command(project_root)),
    }
    findings: list[str] = []
    if package_error:
        findings.append(package_error)
    if not process_probe_ok(node_probe):
        findings.append("node is not available on PATH")
    if not process_probe_ok(npm_probe):
        findings.append("npm is not available on PATH")
    if not package_lock_path.is_file():
        findings.append("frontend/package-lock.json is missing")
    findings.extend(marker_reasons)

    _ = package_data
    if findings:
        reason = "; ".join(findings) + "; run `python tools/devbootstrap.py release-gates --prepare-deps` or `python tools/devbootstrap.py prepare-frontend --install-mode=stale` before frontend gates."
        return False, reason, details
    return True, None, details

def release_gate_frontend_dependency_skip_spec(
    *,
    name: str,
    command: list[str],
    description: str,
    reason: str,
    details: dict[str, Any],
    timeout_seconds: int = 600,
    required: bool = True,
) -> GateSpec:
    return GateSpec(
        name=name,
        cwd="frontend",
        command=command,
        description=description,
        required=required,
        timeout_seconds=timeout_seconds,
        skip_status="infra_failed",
        skip_classification="frontend_dependencies_missing",
        skip_reason=reason,
        details=details,
    )


def release_gate_path_has_text(path: Path, required_fragments: list[str]) -> tuple[bool, list[str], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, required_fragments, f"{path.as_posix()} is missing"
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        return False, missing, "missing required fragments: " + ", ".join(missing)
    return True, [], f"{len(required_fragments)} required fragments found"


def release_gate_check_readme_startup_commands(project_root: Path) -> tuple[str, str, str, list[str], dict[str, Any]]:
    required = [
        "python tools/devbootstrap.py release-gates",
        "python tools/devbootstrap.py up --dry-run",
        "python tools/devbootstrap.py smoke --level quick",
    ]
    ok, missing, message = release_gate_path_has_text(project_root / "README.md", required)
    lines = ["# README startup commands gate", f"status: {'ok' if ok else 'failed'}", message]
    if missing:
        lines.append("missing:")
        lines.extend(f"- {item}" for item in missing)
    details = {"path": "README.md", "requiredFragments": required, "missingFragments": missing}
    if ok:
        return "ok", "ok", "README contains current devbootstrap startup/release-gates commands", lines, details
    return "failed", "readme_startup_commands_missing", message, lines, details


def release_gate_check_known_limitations(project_root: Path) -> tuple[str, str, str, list[str], dict[str, Any]]:
    candidates = [
        project_root / "docs" / "product" / "v1-known-limitations.md",
        project_root / "docs" / "product" / "release-notes-v1.md",
        project_root / "docs" / "product" / "v1-release-notes.md",
    ]
    required_any = ["Known limitations", "Ограничения", "known limitations", "limitations"]
    evidence: list[str] = ["# release notes / known limitations gate"]
    found_path: Path | None = None
    found_text = ""
    for path in candidates:
        if not path.exists():
            evidence.append(f"missing: {path.relative_to(project_root).as_posix()}")
            continue
        text = path.read_text(encoding="utf-8")
        if any(fragment in text for fragment in required_any):
            found_path = path
            found_text = text
            break
        evidence.append(f"present_without_required_marker: {path.relative_to(project_root).as_posix()}")
    details = {"candidatePaths": [path.relative_to(project_root).as_posix() for path in candidates], "foundPath": rel(found_path, project_root) if found_path else None}
    if found_path is None:
        message = "No release notes / known limitations document with an explicit limitations marker was found."
        evidence.extend(["status: failed", message])
        return "failed", "release_notes_known_limitations_missing", message, evidence, details
    important_markers = ["real backend product path", "clean-machine", "release-gates"]
    missing_markers = [marker for marker in important_markers if marker.lower() not in found_text.lower()]
    details["missingRecommendedMarkers"] = missing_markers
    if missing_markers:
        message = "Known limitations document exists but misses release-gates-specific markers: " + ", ".join(missing_markers)
        evidence.extend(["status: failed", message])
        return "failed", "release_notes_known_limitations_incomplete", message, evidence, details
    message = f"Known limitations document found: {found_path.relative_to(project_root).as_posix()}"
    evidence.extend(["status: ok", message])
    return "ok", "ok", message, evidence, details


def release_gate_check_v1_checklist(project_root: Path) -> tuple[str, str, str, list[str], dict[str, Any]]:
    required = [
        "## 7. Testing and release gates",
        "`cargo test`",
        "`python tests/smoke_core_api.py`",
        "`npm run build`",
        "`npm run test:run`",
        "`npm run test:browser`",
        "UIX real-backend core flow",
        "Clean-machine quickstart проверен",
    ]
    path = project_root / "docs" / "product" / "v1-remaining-checklist.md"
    ok, missing, message = release_gate_path_has_text(path, required)
    lines = ["# v1 remaining checklist release-gates gate", f"status: {'ok' if ok else 'failed'}", message]
    if missing:
        lines.append("missing:")
        lines.extend(f"- {item}" for item in missing)
    details = {"path": "docs/product/v1-remaining-checklist.md", "requiredFragments": required, "missingFragments": missing}
    if ok:
        return "ok", "ok", "v1 remaining checklist contains the Testing and release gates matrix", lines, details
    return "failed", "v1_remaining_checklist_release_gates_missing", message, lines, details



def parse_optional_bool_arg(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got: {value}")


def release_gates_profile_defaults(profile: str | None) -> dict[str, Any]:
    selected = profile or RELEASE_GATES_DEFAULT_PROFILE
    if selected not in RELEASE_GATES_PROFILE_DEFAULTS:
        selected = RELEASE_GATES_DEFAULT_PROFILE
    return dict(RELEASE_GATES_PROFILE_DEFAULTS[selected])


def release_gates_add_side_effect(items: list[dict[str, str]], category: str, description: str) -> None:
    item = {"category": category, "description": description}
    if item not in items:
        items.append(item)


def build_release_gates_side_effects(options: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    allowed: list[dict[str, str]] = []
    denied: list[dict[str, str]] = []
    prepare_deps = str(options.get("prepare_deps") or "never")
    if prepare_deps != "never":
        release_gates_add_side_effect(
            allowed,
            "write-project-cache",
            f"prepare frontend/backend dependency caches with prepare-deps={prepare_deps}; source files and lockfiles remain read-only",
        )
        release_gates_add_side_effect(
            allowed,
            "network-download",
            "npm/cargo may download dependency artifacts when the local cache is missing or stale",
        )
    if options.get("install_playwright_browsers"):
        release_gates_add_side_effect(
            allowed,
            "write-project-cache",
            "install Playwright Chromium browser binaries through npx playwright install chromium",
        )
        release_gates_add_side_effect(
            allowed,
            "network-download",
            "Playwright may download browser binaries when they are missing",
        )
    if options.get("managed_test_db"):
        release_gates_add_side_effect(
            allowed,
            "create-database",
            "create one PostgreSQL test database owned by this release-gates run",
        )
        release_gates_add_side_effect(
            allowed,
            "write-database",
            "route DB integration tests and smoke writes to the managed test database",
        )
        release_gates_add_side_effect(
            allowed,
            "delete-database",
            "drop only the managed test database according to the configured retention policy",
        )
    if options.get("allow_dev_db_write"):
        release_gates_add_side_effect(
            allowed,
            "write-database",
            "explicitly allow write-capable smoke/browser gates to use the configured live/dev database",
        )
    if options.get("managed_runtime") or options.get("managed_test_db"):
        release_gates_add_side_effect(
            allowed,
            "start-process",
            "start backend/frontend processes owned by this release-gates run on dynamic loopback ports",
        )
        release_gates_add_side_effect(
            allowed,
            "stop-process",
            "stop only managed runtime PIDs recorded by this release-gates run",
        )
    if options.get("start_db_if_needed"):
        release_gates_add_side_effect(
            allowed,
            "start-process",
            "start the project Docker Compose PostgreSQL service if the configured PostgreSQL port is closed",
        )
    if options.get("dump_test_db_on_failure"):
        release_gates_add_side_effect(
            allowed,
            "write-project-cache",
            "write a pg_dump artifact into the release-gates run directory when a managed DB failure is retained",
        )
    if options.get("include_clean_machine"):
        release_gates_add_side_effect(
            allowed,
            "write-temp-sandbox",
            "copy the project into a temporary clean-machine sandbox with generated/local state excluded",
        )

    release_gates_add_side_effect(denied, "write-project-files", "no source files, env files or lockfiles are modified by release-gates")
    release_gates_add_side_effect(denied, "delete-database", "no database is dropped unless it was created and registered by the current managed DB run")
    release_gates_add_side_effect(denied, "stop-process", "no foreign process is killed merely because it occupies a legacy or selected port")
    if not options.get("allow_dev_db_write"):
        release_gates_add_side_effect(denied, "write-database", "writes to the configured live/dev database are denied without --allow-dev-db-write")
    if prepare_deps == "never" and not options.get("install_playwright_browsers"):
        release_gates_add_side_effect(denied, "network-download", "dependency/browser downloads are not intentionally initiated by the selected profile")
    release_gates_add_side_effect(denied, "write-project-files", "fallback npm install without package-lock.json remains denied")
    return allowed, denied


def build_release_gates_planned_gates(options: dict[str, Any]) -> list[str]:
    gates = ["self_check", "diagnose", "backend_cargo_test_default", "docs gates"]
    if str(options.get("prepare_deps") or "never") != "never":
        gates.extend(["frontend_prepare_dependencies", "backend_dependency_warmup"])
    if options.get("managed_test_db"):
        gates.extend(["managed_test_db_prepare", "backend_cargo_test_db_ignored", "backend_python_smoke_first/second"])
    if options.get("managed_runtime") or options.get("managed_test_db"):
        gates.extend(["managed_runtime_plan/start/stop", "managed frontend/browser URLs"])
    gates.extend(["frontend_build", "frontend_unit_integration", "frontend_browser_smoke"])
    if options.get("install_playwright_browsers"):
        gates.append("playwright_install when Chromium is missing")
    if options.get("include_real_backend_browser"):
        gates.append("browser_real_backend_path")
    if options.get("include_clean_machine"):
        gates.append(f"clean_machine_sandbox:{options.get('clean_machine_profile') or DEFAULT_CLEAN_MACHINE_PROFILE}")
    return gates


def resolve_release_gates_profile_args(args: argparse.Namespace) -> ReleaseGatesProfilePlan:
    requested_profile = getattr(args, "profile", None)
    explicit_profile = bool(requested_profile)
    profile = requested_profile or RELEASE_GATES_DEFAULT_PROFILE
    defaults = release_gates_profile_defaults(profile)
    explicit_overrides: dict[str, Any] = {}

    bool_options = [
        "allow_dev_db_write",
        "managed_runtime",
        "managed_test_db",
        "start_db_if_needed",
        "dump_test_db_on_failure",
        "install_playwright_browsers",
        "include_real_backend_browser",
        "include_clean_machine",
    ]
    effective: dict[str, Any] = {}
    for name in bool_options:
        raw_value = getattr(args, name, None)
        if raw_value is None:
            effective[name] = bool(defaults.get(name, False))
        else:
            effective[name] = bool(raw_value)
            explicit_overrides[name] = bool(raw_value)
        setattr(args, name, effective[name])

    if getattr(args, "prepare_deps", None) is not None:
        prepare_deps = normalize_frontend_prepare_dep_mode(args.prepare_deps)
        explicit_overrides["prepare_deps"] = prepare_deps
    elif getattr(args, "prepare_frontend", False):
        prepare_deps = DEFAULT_FRONTEND_PREPARE_DEP_MODE
        explicit_overrides["prepare_deps"] = prepare_deps
        explicit_overrides["prepare_frontend"] = True
    else:
        prepare_deps = str(defaults.get("prepare_deps") or "never")
    args.prepare_deps = prepare_deps

    if getattr(args, "test_db_retention", None) is not None:
        test_db_retention = str(args.test_db_retention)
        explicit_overrides["test_db_retention"] = test_db_retention
    else:
        test_db_retention = str(defaults.get("test_db_retention") or "keep-on-failure")
    args.test_db_retention = test_db_retention

    if getattr(args, "clean_machine_profile", None) is not None:
        clean_machine_profile = normalize_clean_machine_profile(str(args.clean_machine_profile))
        explicit_overrides["clean_machine_profile"] = clean_machine_profile
    else:
        clean_machine_profile = normalize_clean_machine_profile(str(defaults.get("clean_machine_profile") or DEFAULT_CLEAN_MACHINE_PROFILE))
    args.clean_machine_profile = clean_machine_profile

    if getattr(args, "clean_machine_retention", None) is not None:
        clean_machine_retention = str(args.clean_machine_retention)
        explicit_overrides["clean_machine_retention"] = clean_machine_retention
    else:
        clean_machine_retention = str(defaults.get("clean_machine_retention") or DEFAULT_CLEAN_MACHINE_RETENTION)
    args.clean_machine_retention = clean_machine_retention

    test_db_maintenance_db = str(getattr(args, "test_db_maintenance_db", None) or "postgres")
    args.test_db_maintenance_db = test_db_maintenance_db
    if test_db_maintenance_db != "postgres":
        explicit_overrides["test_db_maintenance_db"] = test_db_maintenance_db
    if getattr(args, "test_db_admin_user", None):
        explicit_overrides["test_db_admin_user"] = str(args.test_db_admin_user)
    if getattr(args, "test_db_admin_password_env", None):
        explicit_overrides["test_db_admin_password_env"] = str(args.test_db_admin_password_env)
    if getattr(args, "test_db_admin_password", None) is not None:
        explicit_overrides["test_db_admin_password"] = "<provided>"

    effective.update(
        {
            "profile": profile,
            "prepare_deps": prepare_deps,
            "test_db_retention": test_db_retention,
            "test_db_maintenance_db": test_db_maintenance_db,
            "test_db_admin_user": getattr(args, "test_db_admin_user", None) or "<source-url-user>",
            "test_db_admin_password": "<provided>" if getattr(args, "test_db_admin_password", None) is not None else "<not-provided>",
            "test_db_admin_password_env": getattr(args, "test_db_admin_password_env", None) or "<not-provided>",
            "clean_machine_profile": clean_machine_profile,
            "clean_machine_retention": clean_machine_retention,
            "real_backend_browser_spec": getattr(args, "real_backend_browser_spec", "e2e/smoke/real-backend.smoke.spec.ts"),
        }
    )
    allowed, denied = build_release_gates_side_effects(effective)
    return ReleaseGatesProfilePlan(
        profile=profile,
        explicit_profile=explicit_profile,
        description=RELEASE_GATES_PROFILE_DESCRIPTIONS.get(profile, RELEASE_GATES_PROFILE_DESCRIPTIONS[RELEASE_GATES_DEFAULT_PROFILE]),
        dry_run=bool(getattr(args, "dry_run", False)),
        explicit_overrides=explicit_overrides,
        effective_options=effective,
        allowed_side_effects=allowed,
        denied_side_effects=denied,
        planned_gates=build_release_gates_planned_gates(effective),
    )


def render_release_gates_profile_plan(plan: ReleaseGatesProfilePlan) -> str:
    lines: list[str] = []
    lines.append("# release-gates profile and consent plan")
    lines.append("")
    lines.append(f"- Profile: `{plan.profile}`")
    lines.append(f"- Explicit profile: `{plan.explicit_profile}`")
    lines.append(f"- Dry run: `{plan.dry_run}`")
    lines.append(f"- Description: {plan.description}")
    if plan.consent_summary_path:
        lines.append(f"- Bundle path: `{plan.consent_summary_path}`")
    lines.append("")
    lines.append("## Effective options")
    lines.append("")
    for key in sorted(plan.effective_options):
        value = plan.effective_options[key]
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Explicit overrides")
    lines.append("")
    if plan.explicit_overrides:
        for key in sorted(plan.explicit_overrides):
            lines.append(f"- `{key}`: `{plan.explicit_overrides[key]}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Allowed scoped side effects")
    lines.append("")
    if plan.allowed_side_effects:
        for item in plan.allowed_side_effects:
            lines.append(f"- `{item['category']}` — {item['description']}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Denied unscoped side effects")
    lines.append("")
    for item in plan.denied_side_effects:
        lines.append(f"- `{item['category']}` — {item['description']}")
    lines.append("")
    lines.append("## Planned gate families")
    lines.append("")
    for gate in plan.planned_gates:
        lines.append(f"- `{gate}`")
    if plan.dry_run:
        lines.append("")
        lines.append("Dry-run guarantee: no database is created, no dependency install is executed, no process is started and no clean-machine sandbox is copied.")
    return "\n".join(lines) + "\n"


def write_release_gates_profile_plan(project_root: Path, run_dir: Path, plan: ReleaseGatesProfilePlan) -> None:
    path = run_dir / "release-gates-consent.md"
    plan.consent_summary_path = rel(path, project_root)
    path.write_text(render_release_gates_profile_plan(plan), encoding="utf-8")
    write_json(run_dir / "release-gates-consent.json", as_jsonable(plan))


def print_release_gates_profile_consent(plan: ReleaseGatesProfilePlan) -> None:
    print(f"release-gates profile: {plan.profile} (explicit={plan.explicit_profile})")
    if plan.consent_summary_path:
        print(f"Consent plan: {plan.consent_summary_path}")
    allowed = ", ".join(sorted({item["category"] for item in plan.allowed_side_effects})) or "none"
    denied = ", ".join(sorted({item["category"] for item in plan.denied_side_effects})) or "none"
    print(f"Allowed scoped side effects: {allowed}")
    print(f"Denied unscoped side effects: {denied}")


def normalize_clean_machine_profile(value: str | None) -> str:
    normalized = (value or DEFAULT_CLEAN_MACHINE_PROFILE).strip().lower().replace("_", "-")
    if normalized.startswith("clean-machine-"):
        normalized = normalized.removeprefix("clean-machine-")
    if normalized not in {"dry", "deps", "runtime"}:
        raise ValueError(f"unknown clean-machine profile: {value}")
    return normalized


def release_gate_clean_machine_excluded_names() -> set[str]:
    return {
        ".git",
        BOOTSTRAP_DIR_NAME,
        ".venv",
        "node_modules",
        "target",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".pytest_cache",
    }


def release_gate_clean_machine_ignore_factory(project_root: Path, exclusions: list[str]):
    excluded_names = release_gate_clean_machine_excluded_names()

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        directory_path = Path(directory)
        try:
            directory_relative = directory_path.relative_to(project_root).as_posix()
        except ValueError:
            directory_relative = "."
        for name in names:
            path = directory_path / name
            relative = name if directory_relative == "." else f"{directory_relative}/{name}"
            reason: str | None = None
            if name in excluded_names:
                reason = "generated/local state directory"
            elif name in {".env", ".env.local"} or (name.startswith(".env.") and name != ".env.example"):
                reason = "local environment file"
            elif name.endswith(RELEASE_GATES_ARCHIVE_EXCLUDED_SUFFIXES):
                reason = "generated artifact suffix"
            elif directory_path.name == "release" and name.endswith((".zip", ".exe")):
                reason = "large release payload"
            if reason:
                ignored.add(name)
                exclusions.append(f"{relative} — {reason}")
        return ignored

    return ignore


def release_gate_clean_machine_ignore(directory: str, names: list[str]) -> set[str]:
    # Backward-compatible ignore callback for older internal callers.
    return release_gate_clean_machine_ignore_factory(Path(directory), [])(directory, names)


def clean_machine_file_list(clean_root: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(clean_root.rglob("*")):
        if path.is_file():
            files.append(path.relative_to(clean_root).as_posix())
    return files


def clean_machine_required_path_results(clean_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative in CLEAN_MACHINE_REQUIRED_PATHS:
        path = clean_root / relative
        exists = path.exists()
        kind = "directory" if path.is_dir() else "file" if path.is_file() else "missing"
        checks.append({"path": relative, "exists": exists, "kind": kind})
        if not exists:
            missing.append(relative)
    return checks, missing


def release_gate_clean_machine_commands(profile: str) -> list[list[str]]:
    normalized = normalize_clean_machine_profile(profile)
    commands = [
        [sys.executable, "tools/devbootstrap.py", "self-check", "--no-write-report"],
        [sys.executable, "tools/devbootstrap.py", "diagnose", "--no-write-report"],
        [sys.executable, "tools/devbootstrap.py", "plan", "--no-write-report"],
        [sys.executable, "tools/devbootstrap.py", "prepare-env", "--no-write-report"],
        [
            sys.executable,
            "tools/devbootstrap.py",
            "up",
            "--dry-run",
            "--skip-db-start",
            "--skip-cargo-check",
            "--skip-install",
            "--skip-backend-start",
            "--skip-frontend-start",
            "--smoke-level",
            "none",
            "--step-timeout-seconds",
            "30",
            "--db-timeout-seconds",
            "5",
            "--cargo-check-timeout-seconds",
            "5",
            "--backend-timeout-seconds",
            "5",
            "--npm-timeout-seconds",
            "5",
            "--frontend-timeout-seconds",
            "5",
            "--smoke-timeout-seconds",
            "5",
        ],
    ]
    if normalized in {"deps", "runtime"}:
        commands.extend(
            [
                [sys.executable, "tools/devbootstrap.py", "prepare-frontend", "--install-mode=stale", "--no-write-report"],
                ["cargo", "test", "--no-run"],
            ]
        )
    if normalized == "runtime":
        commands.append(
            [
                sys.executable,
                "tools/devbootstrap.py",
                "release-gates",
                "--managed-test-db",
                "--managed-runtime",
                "--prepare-deps",
                "--test-db-retention=drop-always",
            ]
        )
    return commands


def run_clean_machine_command(
    *,
    clean_root: Path,
    command: list[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    cwd = clean_root / "backend" if command[:3] == ["cargo", "test", "--no-run"] else clean_root
    started = time.monotonic()
    probe = run_process_probe(
        "clean_machine_sandbox",
        command,
        cwd=cwd,
        timeout=timeout_seconds,
        env_extra={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = release_gate_sanitize_output(clean_root, probe.stdout or "")
    stderr = release_gate_sanitize_output(clean_root, probe.stderr or probe.error or "")
    status, classification, message = classify_gate_output("clean_machine_sandbox", stdout, stderr, probe.error, probe.returncode)
    if not probe.available:
        status, classification, message = "infra_failed", "missing_prerequisite", f"required command is unavailable: {command[0]}"
    return {
        "command": command,
        "cwd": rel(cwd, clean_root),
        "returncode": probe.returncode,
        "durationMs": duration_ms,
        "status": status,
        "classification": classification,
        "message": message,
        "stdout": stdout,
        "stderr": stderr,
        "error": probe.error,
    }


def write_clean_machine_bundle(
    *,
    project_root: Path,
    clean_logs_dir: Path,
    payload: dict[str, Any],
    commands: list[dict[str, Any]],
    file_list: list[str],
    exclusions: list[str],
) -> None:
    clean_logs_dir.mkdir(parents=True, exist_ok=True)
    write_json(clean_logs_dir / "clean-machine.json", payload)
    (clean_logs_dir / "file-list.txt").write_text("\n".join(file_list) + ("\n" if file_list else ""), encoding="utf-8")
    (clean_logs_dir / "exclusions.txt").write_text("\n".join(exclusions) + ("\n" if exclusions else ""), encoding="utf-8")
    command_lines: list[str] = []
    for item in commands:
        command_lines.extend(
            [
                f"$ {release_gate_command_display(item['command'])}",
                f"cwd: {item['cwd']}",
                f"exit: {item['returncode'] if item['returncode'] is not None else item.get('error') or '<none>'}",
                f"duration_ms: {item['durationMs']}",
                f"status: {item['status']}",
                f"classification: {item['classification']}",
                "stdout:",
                item.get("stdout") or "<empty>",
                "stderr:",
                item.get("stderr") or "<empty>",
                "",
            ]
        )
    (clean_logs_dir / "commands.log").write_text("\n".join(command_lines), encoding="utf-8")
    report_lines = [
        "# clean-machine sandbox gate",
        "",
        f"- Status: `{payload['status']}`",
        f"- Classification: `{payload['classification']}`",
        f"- Profile: `{payload['profile']}`",
        f"- Sandbox: `{payload['sandboxPath']}`",
        f"- Retention: `{payload['retention']}`",
        f"- Kept: `{payload['kept']}`",
        f"- Cleanup: `{payload['cleanupCommand'] or '<none>'}`",
        f"- File count: `{len(file_list)}`",
        f"- Exclusions: `{len(exclusions)}`",
        "",
        "## Required files",
        "",
    ]
    for item in payload.get("requiredFiles", []):
        report_lines.append(f"- {'OK' if item['exists'] else 'MISSING'} `{item['path']}` ({item['kind']})")
    report_lines.extend(["", "## Commands", ""])
    for item in commands:
        report_lines.append(f"- `{release_gate_command_display(item['command'])}` — `{item['status']}` / `{item['classification']}`")
    report_lines.extend(["", "See also `commands.log`, `file-list.txt`, `exclusions.txt` and `clean-machine.json`.", ""])
    (clean_logs_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")


def run_release_gate_clean_machine_sandbox_step(
    *,
    project_root: Path,
    logs_dir: Path,
    index: int,
    spec: GateSpec,
    timeout_seconds: int,
) -> GateResult:
    log_path = release_gate_log_path(logs_dir, index, spec.name)
    clean_logs_dir = logs_dir / "clean-machine"
    profile = normalize_clean_machine_profile(str(spec.details.get("cleanMachineProfile") or DEFAULT_CLEAN_MACHINE_PROFILE))
    retention = str(spec.details.get("cleanMachineRetention") or DEFAULT_CLEAN_MACHINE_RETENTION)
    if retention not in CLEAN_MACHINE_RETENTION_POLICIES:
        retention = DEFAULT_CLEAN_MACHINE_RETENTION
    started = time.monotonic()
    sandbox_parent = Path(tempfile.mkdtemp(prefix=f"devbootstrap-clean-machine-{spec.details.get('runId', 'run')}-"))
    clean_root = sandbox_parent / project_root.name
    exclusions: list[str] = []
    commands: list[dict[str, Any]] = []
    file_list: list[str] = []
    status = "ok"
    classification = "ok"
    message = "clean-machine sandbox completed"
    kept = False
    cleanup_command = f"rm -rf {sandbox_parent}"
    required_results: list[dict[str, Any]] = []
    missing_required: list[str] = []
    try:
        shutil.copytree(project_root, clean_root, ignore=release_gate_clean_machine_ignore_factory(project_root, exclusions))
        file_list = clean_machine_file_list(clean_root)
        required_results, missing_required = clean_machine_required_path_results(clean_root)
        if missing_required:
            status = "failed"
            classification = "clean_machine_required_files_missing"
            message = "clean-machine sandbox is missing required files: " + ", ".join(missing_required)
        else:
            for command in release_gate_clean_machine_commands(profile):
                item = run_clean_machine_command(clean_root=clean_root, command=command, timeout_seconds=timeout_seconds)
                commands.append(item)
                if item["status"] != "ok":
                    status = item["status"]
                    classification = item["classification"]
                    message = item["message"]
                    break
    except Exception as exc:
        status = "failed"
        classification = "clean_machine_sandbox_error"
        message = f"clean-machine sandbox raised {exc.__class__.__name__}: {exc}"
    finally:
        kept = retention == "keep-always" or (retention == "keep-on-failure" and status != "ok")
        if not kept:
            shutil.rmtree(sandbox_parent, ignore_errors=True)
    duration_ms = int((time.monotonic() - started) * 1000)
    payload = {
        "status": status,
        "classification": classification,
        "message": message,
        "profile": profile,
        "retention": retention,
        "sandboxPath": str(sandbox_parent),
        "projectCopy": str(clean_root),
        "kept": kept,
        "cleanupCommand": cleanup_command if kept else None,
        "durationMs": duration_ms,
        "requiredFiles": required_results,
        "missingRequiredFiles": missing_required,
        "commands": [
            {key: value for key, value in item.items() if key not in {"stdout", "stderr"}}
            for item in commands
        ],
        "bundleFiles": {
            "report": rel(clean_logs_dir / "report.md", project_root),
            "json": rel(clean_logs_dir / "clean-machine.json", project_root),
            "fileList": rel(clean_logs_dir / "file-list.txt", project_root),
            "exclusions": rel(clean_logs_dir / "exclusions.txt", project_root),
            "commandsLog": rel(clean_logs_dir / "commands.log", project_root),
        },
    }
    write_clean_machine_bundle(
        project_root=project_root,
        clean_logs_dir=clean_logs_dir,
        payload=payload,
        commands=commands,
        file_list=file_list,
        exclusions=exclusions,
    )
    log_path.write_text(
        "\n".join(
            [
                f"# {spec.name}",
                f"internal_check: {spec.internal_check}",
                f"cwd: {spec.cwd or '.'}",
                f"duration_ms: {duration_ms}",
                f"status: {status}",
                f"classification: {classification}",
                f"profile: {profile}",
                f"sandbox: {sandbox_parent}",
                f"kept: {kept}",
                f"cleanup: {cleanup_command if kept else '<deleted>'}",
                f"report: {rel(clean_logs_dir / 'report.md', project_root)}",
                f"json: {rel(clean_logs_dir / 'clean-machine.json', project_root)}",
                f"commands_log: {rel(clean_logs_dir / 'commands.log', project_root)}",
                "",
                message,
                "",
            ]
        ),
        encoding="utf-8",
    )
    details = dict(spec.details)
    details.update(payload)
    return GateResult(
        name=spec.name,
        status=status,
        classification=classification,
        message=message,
        cwd=spec.cwd or ".",
        command=spec.command,
        required=spec.required,
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details=details,
    )


def release_gate_run_clean_machine_quickstart(project_root: Path, timeout_seconds: int) -> tuple[str, str, str, list[str], dict[str, Any]]:
    # Compatibility shim for older internal check names. The full implementation is
    # run_release_gate_clean_machine_sandbox_step(), which can write the structured
    # logs/clean-machine bundle.
    evidence = ["# clean-machine quickstart gate", "superseded by clean_machine_sandbox"]
    details = {"profile": DEFAULT_CLEAN_MACHINE_PROFILE}
    return "ok", "ok", "clean-machine quickstart compatibility shim", evidence, details


def run_release_gate_internal_check(project_root: Path, spec: GateSpec, timeout_seconds: int) -> tuple[str, str, str, list[str], dict[str, Any]]:
    if spec.internal_check == "docs_readme_startup_commands_present":
        return release_gate_check_readme_startup_commands(project_root)
    if spec.internal_check == "docs_release_notes_known_limitations_present":
        return release_gate_check_known_limitations(project_root)
    if spec.internal_check == "docs_v1_remaining_checklist_release_gates_present":
        return release_gate_check_v1_checklist(project_root)
    if spec.internal_check == "clean_machine_quickstart":
        return release_gate_run_clean_machine_quickstart(project_root, timeout_seconds)
    return "failed", "unknown_internal_gate", f"unknown internal release gate: {spec.internal_check}", [f"unknown internal release gate: {spec.internal_check}"], {}


def run_release_gate_internal_step(
    *,
    project_root: Path,
    logs_dir: Path,
    index: int,
    spec: GateSpec,
    timeout_seconds: int,
) -> GateResult:
    if spec.internal_check == "clean_machine_sandbox":
        return run_release_gate_clean_machine_sandbox_step(
            project_root=project_root,
            logs_dir=logs_dir,
            index=index,
            spec=spec,
            timeout_seconds=timeout_seconds,
        )
    log_path = release_gate_log_path(logs_dir, index, spec.name)
    started = time.monotonic()
    try:
        status, classification, message, lines, details = run_release_gate_internal_check(project_root, spec, timeout_seconds)
    except Exception as exc:
        status = "failed"
        classification = "internal_gate_error"
        message = f"internal gate raised {exc.__class__.__name__}: {exc}"
        lines = [message]
        details = {}
    duration_ms = int((time.monotonic() - started) * 1000)
    merged_details = dict(spec.details)
    merged_details.update(details)
    log_path.write_text(
        "\n".join(
            [
                f"# {spec.name}",
                f"internal_check: {spec.internal_check}",
                f"cwd: {spec.cwd or '.'}",
                f"duration_ms: {duration_ms}",
                f"status: {status}",
                f"classification: {classification}",
                "",
                *lines,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GateResult(
        name=spec.name,
        status=status,
        classification=classification,
        message=message,
        cwd=spec.cwd or ".",
        command=spec.command,
        required=spec.required,
        duration_ms=duration_ms,
        log_path=rel(log_path, project_root),
        details=merged_details,
    )


def build_release_gate_specs(
    project_root: Path,
    *,
    allow_dev_db_write: bool = False,
    install_playwright_browsers: bool = False,
    include_real_backend_browser: bool = False,
    real_backend_browser_spec: str = "e2e/smoke/real-backend.smoke.spec.ts",
    include_clean_machine: bool = False,
    clean_machine_profile: str = DEFAULT_CLEAN_MACHINE_PROFILE,
    clean_machine_retention: str = DEFAULT_CLEAN_MACHINE_RETENTION,
    dry_run: bool = False,
    managed_test_db_url: str | None = None,
    managed_test_db_requested: bool = False,
    managed_runtime_requested: bool = False,
    managed_backend_api_base_url: str | None = None,
    managed_frontend_url: str | None = None,
    managed_frontend_host: str | None = None,
    managed_frontend_port: int | None = None,
    smoke_run_id: str | None = None,
) -> list[GateSpec]:
    specs: list[GateSpec] = [
        GateSpec(
            name="self_check",
            cwd=".",
            command=[sys.executable, "tools/devbootstrap.py", "self-check", "--no-write-report", "--json"],
            description="Run devbootstrap internal stdlib fixtures before aggregating release-gates.",
            timeout_seconds=120,
        ),
        GateSpec(
            name="diagnose",
            cwd=".",
            command=[sys.executable, "tools/devbootstrap.py", "diagnose", "--no-write-report", "--json"],
            description="Capture read-only environment diagnostics for the release-gates bundle.",
            timeout_seconds=120,
        ),
        GateSpec(
            name="backend_cargo_test_default",
            cwd="backend",
            command=["cargo", "test"],
            description="Run the default Rust test profile and detect ignored critical tests.",
            timeout_seconds=900,
        ),
    ]

    if managed_test_db_url:
        db_env_extra = release_gate_managed_db_env(managed_test_db_url)
        db_source = "managed ephemeral test database"
    else:
        db_env_extra, db_source = release_gate_database_env(project_root)
    if db_source or dry_run:
        details = {"databaseEnvSource": db_source, "managedTestDb": bool(managed_test_db_url)}
        if managed_test_db_url:
            details["maskedDatabaseUrl"] = mask_database_url(managed_test_db_url)
        if dry_run and not db_source:
            details["dryRunPrerequisiteBypassed"] = True
        specs.append(
            GateSpec(
                name="backend_cargo_test_db_ignored",
                cwd="backend",
                command=["cargo", "test", "--", "--include-ignored"],
                description="Force ignored DB integration tests to run with TEST_DATABASE_URL.",
                timeout_seconds=900,
                env_extra=db_env_extra,
                details=details,
            )
        )
    else:
        reason = "TEST_DATABASE_URL is absent and no DATABASE__URL/DATABASE_URL was found in backend env; DB integration tests cannot be executed safely."
        classification = "db_test_prerequisite_missing"
        if managed_test_db_requested:
            reason = "--managed-test-db was requested, but managed test DB was not created; DB integration tests cannot run safely."
            classification = "managed_test_db_unavailable"
        specs.append(
            GateSpec(
                name="backend_cargo_test_db_ignored",
                cwd="backend",
                command=["cargo", "test", "--", "--include-ignored"],
                description="Force ignored DB integration tests to run with TEST_DATABASE_URL.",
                skip_reason=reason,
                skip_classification=classification,
                details={"databaseEnvSource": None, "managedTestDbRequested": managed_test_db_requested},
            )
        )

    if managed_test_db_url:
        smoke_allowed, smoke_reason = True, "managed ephemeral test database"
        smoke_env = release_gate_smoke_env(project_root)
        smoke_env.update(release_gate_managed_db_env(managed_test_db_url))
        if managed_backend_api_base_url:
            smoke_env["BASE_URL"] = managed_backend_api_base_url.rstrip("/")
    elif managed_test_db_requested:
        smoke_allowed = False
        smoke_reason = "--managed-test-db was requested, but managed test DB was not created; backend smoke cannot run safely."
        smoke_env = release_gate_smoke_env(project_root)
    else:
        smoke_allowed, smoke_reason = release_gate_smoke_allowed(project_root, allow_dev_db_write)
        smoke_env = release_gate_smoke_env(project_root)
        if managed_backend_api_base_url:
            smoke_env["BASE_URL"] = managed_backend_api_base_url.rstrip("/")
    if smoke_run_id:
        smoke_env.setdefault("SMOKE_RUN_ID", smoke_run_id)
    for smoke_name in ["backend_python_smoke_first", "backend_python_smoke_second"]:
        if smoke_allowed or dry_run:
            details = {"smokePermission": smoke_reason, "managedTestDb": bool(managed_test_db_url), "managedRuntime": managed_runtime_requested}
            if managed_test_db_url:
                details["maskedDatabaseUrl"] = mask_database_url(managed_test_db_url)
            if managed_backend_api_base_url:
                details["baseUrl"] = managed_backend_api_base_url.rstrip("/")
            if dry_run and not smoke_allowed:
                details["dryRunPrerequisiteBypassed"] = True
            specs.append(
                GateSpec(
                    name=smoke_name,
                    cwd="backend",
                    command=[sys.executable, "tests/smoke_core_api.py"],
                    description="Run backend black-box smoke against the live backend API; second run checks idempotency.",
                    timeout_seconds=900,
                    env_extra=smoke_env,
                    details=details,
                )
            )
        else:
            specs.append(
                GateSpec(
                    name=smoke_name,
                    cwd="backend",
                    command=[sys.executable, "tests/smoke_core_api.py"],
                    description="Run backend black-box smoke against the live backend API; second run checks idempotency.",
                    skip_reason=smoke_reason,
                    skip_classification="managed_test_db_unavailable" if managed_test_db_requested else "smoke_db_write_guard",
                    details={"smokePermission": smoke_reason, "managedTestDbRequested": managed_test_db_requested},
                )
            )

    frontend_deps_ready, frontend_deps_reason, frontend_deps_details = release_gate_frontend_dependency_status(project_root)
    frontend_build_details = {"frontendDependencies": frontend_deps_details}
    frontend_test_details = {"frontendDependencies": frontend_deps_details}
    if dry_run or frontend_deps_ready:
        if dry_run and not frontend_deps_ready:
            frontend_build_details["dryRunPrerequisiteBypassed"] = True
            frontend_test_details["dryRunPrerequisiteBypassed"] = True
        specs.extend(
            [
                GateSpec(
                    name="frontend_build",
                    cwd="frontend",
                    command=["npm", "run", "build"],
                    description="Run TypeScript/Vite production build.",
                    timeout_seconds=600,
                    details=frontend_build_details,
                ),
                GateSpec(
                    name="frontend_unit_integration",
                    cwd="frontend",
                    command=["npm", "run", "test:run"],
                    description="Run Vitest unit/integration tests.",
                    timeout_seconds=600,
                    details=frontend_test_details,
                ),
            ]
        )
    else:
        dependency_reason = frontend_deps_reason or "frontend dependencies are missing or stale; run `python tools/devbootstrap.py prepare-frontend --force-install` before release-gates."
        specs.extend(
            [
                release_gate_frontend_dependency_skip_spec(
                    name="frontend_build",
                    command=["npm", "run", "build"],
                    description="Run TypeScript/Vite production build.",
                    reason=dependency_reason,
                    details=frontend_build_details,
                ),
                release_gate_frontend_dependency_skip_spec(
                    name="frontend_unit_integration",
                    command=["npm", "run", "test:run"],
                    description="Run Vitest unit/integration tests.",
                    reason=dependency_reason,
                    details=frontend_test_details,
                ),
            ]
        )

    uiux_run_id = smoke_run_id or "manual-release-gates"
    uiux_root = f".dev-bootstrap/runs/{uiux_run_id}/uiux-evidence"
    specs.append(
        GateSpec(
            name="frontend_uiux_validate_scenarios",
            cwd=".",
            command=[sys.executable, "-B", "tools/uiux_evidence.py", "validate-scenarios", "--report-dir", f"{uiux_root}/validate-scenarios", "--json"],
            description="Validate custom UI/UX Evidence Runner scenario JSON and frontend data-testid marker contract.",
            timeout_seconds=120,
            details={"evidenceDir": f"{uiux_root}/validate-scenarios", "runner": "tools/uiux_evidence.py"},
        )
    )
    specs.append(
        GateSpec(
            name="frontend_uiux_browser_discovery",
            cwd=".",
            command=[sys.executable, "-B", "tools/uiux_evidence.py", "discover-browser", "--report-dir", f"{uiux_root}/browser-discovery", "--json"],
            description="Discover a system Chromium-compatible browser without downloading Playwright browser revisions.",
            timeout_seconds=120,
            details={"evidenceDir": f"{uiux_root}/browser-discovery", "runner": "tools/uiux_evidence.py", "downloadsBrowser": False},
        )
    )

    uiux_boot_command = [sys.executable, "-B", "tools/uiux_evidence.py", "boot", "--report-dir", f"{uiux_root}/boot", "--json"]
    uiux_boot_details: dict[str, Any] = {"evidenceDir": f"{uiux_root}/boot", "runner": "tools/uiux_evidence.py", "managedRuntime": managed_runtime_requested}
    if managed_frontend_url:
        uiux_boot_command.extend(["--base-url", managed_frontend_url.rstrip("/") + "/"])
        uiux_boot_details["frontendUrl"] = managed_frontend_url.rstrip("/") + "/"
        if managed_backend_api_base_url:
            uiux_boot_command.extend(["--api-base-url", managed_backend_api_base_url.rstrip("/")])
            uiux_boot_details["apiBaseUrl"] = managed_backend_api_base_url.rstrip("/")
    else:
        uiux_boot_command.append("--start-frontend")
        uiux_boot_details["startsOwnedFrontend"] = True
    uiux_mocked_command = [sys.executable, "-B", "tools/uiux_evidence.py", "scenario", "--name", "mocked-core-flow", "--start-frontend", "--report-dir", f"{uiux_root}/mocked-core-flow", "--json"]
    uiux_mocked_details: dict[str, Any] = {"evidenceDir": f"{uiux_root}/mocked-core-flow", "runner": "tools/uiux_evidence.py", "startsOwnedFrontend": True, "usesMockApi": True}
    if frontend_deps_ready or dry_run:
        if dry_run and not frontend_deps_ready:
            uiux_boot_details["dryRunPrerequisiteBypassed"] = True
            uiux_mocked_details["dryRunPrerequisiteBypassed"] = True
        specs.append(
            GateSpec(
                name="frontend_uiux_boot",
                cwd=".",
                command=uiux_boot_command,
                description="Open the web UI and capture DOM/console/storage/network boot evidence through the custom UIX runner.",
                timeout_seconds=300,
                details=uiux_boot_details,
            )
        )
        specs.append(
            GateSpec(
                name="frontend_uiux_mocked_core_flow",
                cwd=".",
                command=uiux_mocked_command,
                description="Run deterministic workspace→board→column→card UI flow against a runner-owned mock API without Playwright.",
                timeout_seconds=420,
                details=uiux_mocked_details,
            )
        )
    else:
        dependency_reason = frontend_deps_reason or "frontend dependencies are missing or stale; run `python tools/devbootstrap.py release-gates --prepare-deps` before UIX browser gates."
        specs.append(
            GateSpec(
                name="frontend_uiux_boot",
                cwd=".",
                command=uiux_boot_command,
                description="Open the web UI and capture DOM/console/storage/network boot evidence through the custom UIX runner.",
                skip_status="infra_failed",
                skip_classification="frontend_dependencies_missing",
                skip_reason=dependency_reason,
                details=uiux_boot_details,
            )
        )
        specs.append(
            GateSpec(
                name="frontend_uiux_mocked_core_flow",
                cwd=".",
                command=uiux_mocked_command,
                description="Run deterministic workspace→board→column→card UI flow against a runner-owned mock API without Playwright.",
                skip_status="infra_failed",
                skip_classification="frontend_dependencies_missing",
                skip_reason=dependency_reason,
                details=uiux_mocked_details,
            )
        )

    uiux_real_allowed = bool(managed_runtime_requested and managed_backend_api_base_url and managed_frontend_url and managed_test_db_url)
    uiux_real_details: dict[str, Any] = {
        "evidenceDir": f"{uiux_root}/real-backend-core-flow",
        "runner": "tools/uiux_evidence.py",
        "managedRuntime": managed_runtime_requested,
        "managedTestDb": bool(managed_test_db_url),
        "requiresSafeDatabase": True,
    }
    uiux_real_command = [sys.executable, "-B", "tools/uiux_evidence.py", "scenario", "--name", "real-backend-core-flow", "--report-dir", f"{uiux_root}/real-backend-core-flow", "--json"]
    if managed_frontend_url:
        uiux_real_command.extend(["--base-url", managed_frontend_url.rstrip("/") + "/"])
        uiux_real_details["frontendUrl"] = managed_frontend_url.rstrip("/") + "/"
    if managed_backend_api_base_url:
        uiux_real_command.extend(["--api-base-url", managed_backend_api_base_url.rstrip("/")])
        uiux_real_details["apiBaseUrl"] = managed_backend_api_base_url.rstrip("/")
    if managed_test_db_url:
        uiux_real_details["maskedDatabaseUrl"] = mask_database_url(managed_test_db_url)
    if uiux_real_allowed or dry_run:
        if dry_run and not uiux_real_allowed:
            uiux_real_details["dryRunPrerequisiteBypassed"] = True
        specs.append(
            GateSpec(
                name="frontend_uiux_real_backend_core_flow",
                cwd=".",
                command=uiux_real_command,
                description="Run real backend workspace→board→column→card UI evidence against managed frontend/backend/test DB.",
                timeout_seconds=600,
                details=uiux_real_details,
            )
        )
    else:
        uiux_real_required = True
        uiux_real_skip_status = "skipped_prerequisite"
        if not managed_runtime_requested:
            uiux_real_required = False
            uiux_real_skip_status = "skipped_optional"
            uiux_real_reason = "real-backend UIX flow requires --managed-runtime so devbootstrap owns frontend/backend process state."
            uiux_real_classification = "managed_runtime_required"
        elif not managed_test_db_url:
            uiux_real_reason = "real-backend UIX flow requires a managed or explicit safe test database."
            uiux_real_classification = "managed_test_db_unavailable" if managed_test_db_requested else "real_backend_uiux_write_guard"
        else:
            uiux_real_reason = "managed frontend/backend URLs are unavailable for real-backend UIX flow."
            uiux_real_classification = "managed_runtime_unavailable"
        specs.append(
            GateSpec(
                name="frontend_uiux_real_backend_core_flow",
                cwd=".",
                command=uiux_real_command,
                required=uiux_real_required,
                description="Run real backend workspace→board→column→card UI evidence against managed frontend/backend/test DB.",
                skip_status=uiux_real_skip_status,
                skip_reason=uiux_real_reason,
                skip_classification=uiux_real_classification,
                details=uiux_real_details,
            )
        )

    package_data, package_error = read_frontend_package(project_root)
    scripts = frontend_scripts_from_package(package_data) if not package_error else {}
    playwright_dependency_present = bool(package_data) and frontend_package_has_dependency(package_data, "@playwright/test")
    playwright_node_package_present = (project_root / "frontend" / "node_modules" / "@playwright" / "test").exists()
    chromium_present, chromium_evidence = playwright_chromium_executable_present(project_root)
    browser_details = {
        "packageError": package_error,
        "scriptPresent": "test:browser" in scripts,
        "dependencyPresent": playwright_dependency_present,
        "nodePackagePresent": playwright_node_package_present,
        "chromiumExecutablePresent": chromium_present,
        "checkedBrowserCacheRoots": chromium_evidence,
        "frontendDependencies": frontend_deps_details,
        "managedRuntime": managed_runtime_requested,
    }
    browser_env: dict[str, str] = {}
    if managed_backend_api_base_url:
        browser_env["VITE_API_BASE_URL"] = managed_backend_api_base_url.rstrip("/")
        browser_details["apiBaseUrl"] = managed_backend_api_base_url.rstrip("/")
    if managed_frontend_url:
        browser_env["PLAYWRIGHT_BASE_URL"] = managed_frontend_url.rstrip("/")
        browser_env["PLAYWRIGHT_WEB_SERVER_URL"] = managed_frontend_url.rstrip("/")
        browser_details["frontendUrl"] = managed_frontend_url.rstrip("/")
    if managed_frontend_host:
        browser_env["PLAYWRIGHT_FRONTEND_HOST"] = managed_frontend_host
    if managed_frontend_port:
        browser_env["PLAYWRIGHT_FRONTEND_PORT"] = str(managed_frontend_port)

    if not frontend_deps_ready and not dry_run:
        specs.append(
            release_gate_frontend_dependency_skip_spec(
                name="frontend_browser_smoke",
                command=["npm", "run", "test:browser"],
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                reason=frontend_deps_reason or "frontend dependencies are missing or stale; run `python tools/devbootstrap.py prepare-frontend --force-install` before release-gates.",
                details=browser_details,
                required=False,
            )
        )
    elif package_error:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                skip_status="infra_failed",
                skip_classification="frontend_package_invalid",
                skip_reason=package_error,
                details=browser_details,
            )
        )
    elif "test:browser" not in scripts:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                skip_status="failed",
                skip_classification="browser_smoke_script_missing",
                skip_reason="frontend/package.json does not define scripts.test:browser",
                details=browser_details,
            )
        )
    elif not playwright_dependency_present:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                skip_status="infra_failed",
                skip_classification="browser_smoke_prerequisite",
                skip_reason="Playwright package is not declared in frontend/package.json; add @playwright/test before running browser smoke.",
                details=browser_details,
            )
        )
    elif not playwright_node_package_present and not dry_run:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                skip_status="infra_failed",
                skip_classification="browser_smoke_prerequisite",
                skip_reason="Playwright package is not installed in frontend/node_modules; run prepare-frontend or npm ci first.",
                details=browser_details,
            )
        )
    elif install_playwright_browsers:
        install_details = dict(browser_details)
        install_details["playwrightInstallPolicy"] = "explicit_ensure_current_revision"
        install_details["playwrightInstallReason"] = (
            "--install-playwright-browsers was provided; run npx playwright install chromium even when an older "
            "Chromium executable is present, because Playwright pins browser revisions and stale cache scans can be false positives."
        )
        specs.append(
            GateSpec(
                name="playwright_install",
                cwd="frontend",
                command=["npx", "playwright", "install", "chromium"],
                required=False,
                description="Ensure the Playwright Chromium browser revision required by the installed @playwright/test package is present.",
                timeout_seconds=900,
                details=install_details,
            )
        )
        browser_after_install_details = dict(browser_details)
        browser_after_install_details["playwrightInstallGate"] = "playwright_install"
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke after explicit browser install/ensure attempt.",
                timeout_seconds=600,
                env_extra=browser_env,
                details=browser_after_install_details,
            )
        )
    elif dry_run and not package_error and "test:browser" in scripts and playwright_dependency_present:
        browser_details["dryRunPrerequisiteBypassed"] = not playwright_node_package_present or not chromium_present
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                timeout_seconds=600,
                env_extra=browser_env,
                details=browser_details,
            )
        )
    elif not chromium_present:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                skip_status="infra_failed",
                skip_classification="browser_smoke_prerequisite",
                skip_reason="Playwright Chromium browser executable is missing; rerun with --install-playwright-browsers or run npx playwright install manually.",
                details=browser_details,
            )
        )
    else:
        specs.append(
            GateSpec(
                name="frontend_browser_smoke",
                cwd="frontend",
                command=["npm", "run", "test:browser"],
                required=False,
                description="Run legacy optional Playwright browser smoke during UIX transition.",
                timeout_seconds=600,
                env_extra=browser_env,
                details=browser_details,
            )
        )

    real_backend_spec = Path(real_backend_browser_spec)
    real_backend_spec_project_path = project_root / "frontend" / real_backend_spec
    if managed_test_db_url:
        real_backend_allowed, real_backend_reason = True, "managed ephemeral test database"
    elif managed_test_db_requested:
        real_backend_allowed = False
        real_backend_reason = "--managed-test-db was requested, but managed test DB was not created; real-backend browser smoke cannot run safely."
    else:
        real_backend_allowed, real_backend_reason = release_gate_smoke_allowed(project_root, allow_dev_db_write)
    real_backend_details = {
        "specPath": real_backend_spec.as_posix(),
        "specExists": real_backend_spec_project_path.exists(),
        "writePermission": real_backend_reason,
        "requiresNoPageRouteMocks": True,
        "mockedBrowserSmokeDoesNotSatisfyThisGate": True,
        "managedTestDb": bool(managed_test_db_url),
        "managedRuntime": managed_runtime_requested,
    }
    if managed_backend_api_base_url:
        real_backend_details["apiBaseUrl"] = managed_backend_api_base_url.rstrip("/")
    if managed_frontend_url:
        real_backend_details["frontendUrl"] = managed_frontend_url.rstrip("/")
    if managed_test_db_url:
        real_backend_details["maskedDatabaseUrl"] = mask_database_url(managed_test_db_url)
    if not frontend_deps_ready and not dry_run:
        specs.append(
            release_gate_frontend_dependency_skip_spec(
                name="browser_real_backend_path",
                command=["npm", "run", "test:browser:real-backend"],
                description="Run legacy optional Playwright browser path against a live backend without page.route API mocks.",
                reason=frontend_deps_reason or "frontend dependencies are missing or stale; run `python tools/devbootstrap.py prepare-frontend --install-mode=stale` before real-backend browser gates.",
                details=real_backend_details,
                required=False,
            )
        )
    elif real_backend_spec_project_path.exists() and (include_real_backend_browser or dry_run) and (real_backend_allowed or dry_run):
        if dry_run and not real_backend_allowed:
            real_backend_details["dryRunPrerequisiteBypassed"] = True
        specs.append(
            GateSpec(
                name="browser_real_backend_path",
                cwd="frontend",
                command=["npm", "run", "test:browser:real-backend"],
                required=False,
                description="Run legacy optional Playwright browser path against a live backend without page.route API mocks.",
                timeout_seconds=900,
                env_extra=browser_env,
                details=real_backend_details,
            )
        )
    elif real_backend_spec_project_path.exists() and not include_real_backend_browser:
        specs.append(
            GateSpec(
                name="browser_real_backend_path",
                cwd="frontend",
                command=["npm", "run", "test:browser:real-backend"],
                required=False,
                description="Legacy real-backend Playwright path exists but is opt-in during UIX transition.",
                skip_reason="Pass --include-real-backend-browser plus TEST_DATABASE_URL or --allow-dev-db-write to execute this write-capable browser gate.",
                skip_classification="real_backend_browser_opt_in_required",
                details=real_backend_details,
            )
        )
    elif real_backend_spec_project_path.exists():
        specs.append(
            GateSpec(
                name="browser_real_backend_path",
                cwd="frontend",
                command=["npm", "run", "test:browser:real-backend"],
                required=False,
                description="Legacy real-backend Playwright path exists but cannot run without explicit write permission.",
                skip_reason=real_backend_reason,
                skip_classification="managed_test_db_unavailable" if managed_test_db_requested else "real_backend_browser_write_guard",
                details=real_backend_details,
            )
        )
    else:
        specs.append(
            GateSpec(
                name="browser_real_backend_path",
                cwd="frontend",
                command=["npm", "run", "test:browser:real-backend"],
                required=False,
                description="Legacy dedicated real-backend Playwright path without API mocks.",
                not_implemented_reason="Dedicated real-backend browser spec is missing; mocked browser smoke must not close this checklist item.",
                details=real_backend_details,
            )
        )

    specs.extend(
        [
            GateSpec(
                name="readme_startup_commands_present",
                cwd=".",
                command=[],
                description="Check that README documents current devbootstrap startup and release-gates commands.",
                internal_check="docs_readme_startup_commands_present",
            ),
            GateSpec(
                name="release_notes_known_limitations_present",
                cwd=".",
                command=[],
                description="Check that release notes / known limitations are present and explicit.",
                internal_check="docs_release_notes_known_limitations_present",
            ),
            GateSpec(
                name="v1_remaining_checklist_release_gates_present",
                cwd=".",
                command=[],
                description="Check that v1 remaining checklist still contains Testing and release gates.",
                internal_check="docs_v1_remaining_checklist_release_gates_present",
            ),
        ]
    )

    normalized_clean_machine_profile = normalize_clean_machine_profile(clean_machine_profile)
    if include_clean_machine:
        specs.append(
            GateSpec(
                name="clean_machine_sandbox",
                cwd=".",
                command=[],
                description="Run a clean-machine sandbox copy with generated/local state excluded and a profile-specific quickstart path.",
                timeout_seconds=1800 if normalized_clean_machine_profile == "runtime" else 1200 if normalized_clean_machine_profile == "deps" else 900,
                internal_check="clean_machine_sandbox",
                details={
                    "cleanMachineProfile": normalized_clean_machine_profile,
                    "cleanMachineRetention": clean_machine_retention,
                },
            )
        )
    else:
        specs.append(
            GateSpec(
                name="clean_machine_sandbox",
                cwd=".",
                command=[],
                description="Optional clean-machine sandbox gate.",
                required=False,
                skip_status="skipped_optional",
                skip_classification="clean_machine_optional_not_requested",
                skip_reason="Clean-machine sandbox is optional; pass --include-clean-machine to run it in a temporary project copy.",
                details={"cleanMachineProfile": normalized_clean_machine_profile},
            )
        )
    return specs


def release_gates_critical_ignored_covered(gates: list[GateResult]) -> bool:
    return any(gate.name == "backend_cargo_test_db_ignored" and gate.status == "ok" for gate in gates)


def release_gates_effective_required_statuses(gates: list[GateResult]) -> set[str]:
    ignored_covered = release_gates_critical_ignored_covered(gates)
    statuses: set[str] = set()
    for gate in gates:
        if not gate.required:
            continue
        if ignored_covered and gate.classification == "critical_tests_ignored":
            continue
        statuses.add(gate.status)
    return statuses


def release_gates_overall_status(gates: list[GateResult], *, dry_run: bool) -> tuple[str, str]:
    if dry_run:
        return "dry_run", "release_gates_dry_run"
    statuses = release_gates_effective_required_statuses(gates)
    if "failed" in statuses:
        return "failed", "release_gates_failed"
    if "timeout" in statuses:
        return "failed", "release_gates_timeout"
    if "infra_failed" in statuses:
        return "infra_failed", "release_gates_infra_failed"
    if "not_implemented" in statuses or "skipped_prerequisite" in statuses:
        return "incomplete", "release_gates_incomplete"
    if "partial_pass" in statuses:
        return "partial_pass", "release_gates_partial_pass"
    if statuses and statuses.issubset({"ok"}):
        return "ok", "release_gates_ok"
    return "unknown", "release_gates_unknown"


def release_gates_next_action_for_code(code: str) -> str | None:
    actions = {
        "missing_prerequisite": "Install the missing command shown in the gate log or use a shell where it is on PATH, then rerun release-gates.",
        "frontend_dependencies_missing": "Run `python tools/devbootstrap.py prepare-frontend --install-mode=stale` first or rerun `python tools/devbootstrap.py release-gates --prepare-deps`; on Windows, if npm is found as npm.CMD but still fails, use this patched devbootstrap command resolver before editing package-lock.json.",
        "frontend_prepare_dependencies_failed": "Fix the primary `frontend_prepare_dependencies` gate first, then rerun downstream frontend/browser gates.",
        "frontend_dependencies_stale": "Run `python tools/devbootstrap.py release-gates --prepare-deps` or `python tools/devbootstrap.py prepare-frontend --install-mode=stale` to refresh the frontend install marker after package/lockfile/runtime changes.",
        "frontend_lockfile_mismatch": "Fix frontend/package-lock.json in a separate patch, then rerun release-gates; release-gates will not silently update lockfiles.",
        "dependency_network_unavailable": "Restore network/package-cache access and rerun dependency preparation; this is an infrastructure failure, not a product test failure.",
        "browser_smoke_prerequisite": "Install/refresh the package-pinned Playwright browser revision by rerunning with `--install-playwright-browsers` or by running `cd frontend && npx playwright install chromium`.",
        "playwright_install_failed": "Inspect the `playwright_install` gate log; Playwright browser installation was explicitly requested but did not complete.",
        "db_test_prerequisite_missing": "Prepare a write-safe test DB, export `TEST_DATABASE_URL`, or rerun with `python tools/devbootstrap.py release-gates --managed-test-db`; see `docs/dev-bootstrap/release-gates-test-database.md`.",
        "managed_test_db_source_missing": "Set backend `DATABASE__URL`/`DATABASE_URL` or copy `backend/.env.example` to `backend/.env`, then rerun `release-gates --managed-test-db`.",
        "managed_test_db_source_invalid": "Fix backend `DATABASE__URL`/`DATABASE_URL`; managed test DB needs a complete PostgreSQL URL with host, port, database and user.",
        "postgres_client_missing": "Install PostgreSQL client tools (`psql`, optionally `pg_dump`) or use a shell where they are on PATH before rerunning `release-gates --managed-test-db`.",
        "managed_test_db_admin_password_missing": "Set the environment variable named by `--test-db-admin-password-env` or pass `--test-db-admin-password` before rerunning managed DB release-gates.",
        "postgres_auth_failed": "Pass a PostgreSQL maintenance role explicitly, for example `--test-db-admin-user postgres --test-db-admin-password-env P2P_TEST_DB_ADMIN_PASSWORD`, or fix the password in backend `DATABASE__URL`.",
        "postgres_createdb_permission_denied": "Use a PostgreSQL role with CREATEDB privilege, for example `--test-db-admin-user <role> --test-db-admin-password-env <ENV_VAR>`, or start the project compose PostgreSQL and rerun `release-gates --managed-test-db --start-db-if-needed`.",
        "postgres_unavailable": "Start PostgreSQL first, or rerun with `--managed-test-db --start-db-if-needed` to allow devbootstrap to start the project compose PostgreSQL when the configured port is closed.",
        "managed_test_db_unavailable": "Inspect the `managed_test_db_prepare` gate log, fix PostgreSQL capability, then rerun `release-gates --managed-test-db`.",
        "managed_runtime_db_unavailable": "Use `--managed-test-db`, set TEST_DATABASE_URL, or explicitly pass `--allow-dev-db-write` before running `release-gates --managed-runtime`.",
        "managed_backend_port_occupied": "Rerun release-gates; managed runtime uses dynamic ports and refuses to reuse a foreign/live backend if the selected port races.",
        "managed_frontend_port_occupied": "Rerun release-gates; managed runtime uses dynamic ports and refuses to reuse a foreign/live frontend if the selected port races.",
        "managed_runtime_unavailable": "Inspect managed runtime start gates and `logs/runtime-state.json`, then rerun after fixing backend/frontend startup failures.",
        "managed_backend_unavailable": "Inspect `managed_backend_start` and the managed backend process log, then rerun after freeing the backend port and fixing startup failures.",
        "managed_backend_stop_failed": "Inspect the owned managed backend stop log; on Windows this should use CTRL_BREAK/terminate/taskkill only for the current run's Popen-owned process tree.",
        "managed_frontend_stop_failed": "Inspect the owned managed frontend stop log; on Windows this should use CTRL_BREAK/terminate/taskkill only for the current run's Popen-owned process tree.",
        "managed_frontend_started": "Managed frontend started; continue with browser gates.",
        "port_binder_probe_failed": "Inspect loopback socket permissions and local security tooling; dynamic managed-runtime ports depend on binding 127.0.0.1:0 safely.",
        "dirty_state_smoke_risk": "Keep backend smoke idempotent: use run-scoped users and avoid assertions that require a pristine shared dev database.",
        "db_capability_probe_source_missing": "Set backend `DATABASE__URL`/`DATABASE_URL` or use managed DB flags before treating DB-writing gates as executable.",
        "launcher_dry_run_missing_prerequisite": "Install or expose the missing launcher command on PATH; command-resolution artifacts show the exact unresolved executable.",
        "smoke_db_write_guard": "For backend Python smoke, restart the live backend against the test DB and set `TEST_DATABASE_URL`; use `--allow-dev-db-write` only when the configured dev DB is disposable.",
        "real_backend_browser_opt_in_required": "After frontend deps and write-safe DB are ready, add `--include-real-backend-browser` to run the no-mock browser path.",
        "real_backend_browser_write_guard": "Set `TEST_DATABASE_URL` and restart backend against that DB before running `--include-real-backend-browser`, or consciously pass `--allow-dev-db-write`.",
        "runtime_unreachable": "Run `python tools/devbootstrap.py status`; if backend/frontend ports are stale or foreign, run `python tools/devbootstrap.py stop` for tracked processes and restart with `python tools/devbootstrap.py up`.",
        "frontend_port_conflict": "Inspect the process occupying the frontend port; devbootstrap will not kill a foreign process automatically. Use `status`, `stop`, then `up` when it is your tracked process.",
        "clean_machine_optional_not_requested": "For final release review, rerun with `--include-clean-machine` after required gates are no longer blocked.",
    }
    return actions.get(code)


def release_gates_add_unique_action(actions: list[str], action: str, seen: set[str]) -> None:
    if action not in seen:
        actions.append(action)
        seen.add(action)


def finalize_release_gates_result(result: ReleaseGatesResult) -> None:
    result.overall_status, result.classification = release_gates_overall_status(result.gates, dry_run=result.dry_run)
    result.findings.clear()
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    for gate in result.gates:
        if ignored_covered and gate.classification == "critical_tests_ignored":
            continue
        if gate.status not in {"ok", "planned"}:
            severity = "warn" if (not gate.required or gate.status in {"partial_pass", "not_implemented", "skipped_prerequisite", "skipped_optional"}) else "fail"
            result.findings.append(
                {
                    "severity": severity,
                    "code": gate.classification,
                    "message": f"{gate.name}: {gate.message}",
                }
            )
    result.next_actions.clear()
    seen_actions: set[str] = set()
    if result.dry_run:
        release_gates_add_unique_action(result.next_actions, "Run `python tools/devbootstrap.py release-gates` without --dry-run to execute implemented gates and create a fresh bundle.", seen_actions)
    elif result.overall_status == "ok":
        release_gates_add_unique_action(result.next_actions, "Configured release-gates passed; continue with later release validation or manual review.", seen_actions)
    else:
        priority = [
            "managed_test_db_source_missing",
            "managed_test_db_source_invalid",
            "postgres_client_missing",
            "postgres_createdb_permission_denied",
            "postgres_unavailable",
            "managed_test_db_unavailable",
            "managed_runtime_db_unavailable",
            "managed_runtime_unavailable",
            "managed_backend_port_occupied",
            "managed_frontend_port_occupied",
            "managed_backend_unavailable",
            "managed_backend_stop_failed",
            "managed_frontend_stop_failed",
            "port_binder_probe_failed",
            "db_capability_probe_source_missing",
            "launcher_dry_run_missing_prerequisite",
            "dirty_state_smoke_risk",
            "frontend_dependencies_missing",
            "frontend_prepare_dependencies_failed",
            "browser_smoke_prerequisite",
            "db_test_prerequisite_missing",
            "smoke_db_write_guard",
            "real_backend_browser_write_guard",
            "real_backend_browser_opt_in_required",
            "runtime_unreachable",
            "frontend_port_conflict",
            "clean_machine_optional_not_requested",
        ]
        codes = {finding["code"] for finding in result.findings}
        for code in priority:
            if code in codes:
                action = release_gates_next_action_for_code(code)
                if action:
                    release_gates_add_unique_action(result.next_actions, action, seen_actions)
        if result.overall_status == "incomplete":
            release_gates_add_unique_action(result.next_actions, "Resolve skipped prerequisites, run opt-in real-backend browser/clean-machine gates when needed, or implement missing release-gates before treating this as a full v1 release signal.", seen_actions)
        if result.managed_test_db and result.managed_test_db.retained and result.managed_test_db.cleanup_command:
            release_gates_add_unique_action(
                result.next_actions,
                f"Managed test DB was retained by policy; clean it up when no longer needed with `{result.managed_test_db.cleanup_command}`.",
                seen_actions,
            )
        if not result.next_actions:
            release_gates_add_unique_action(result.next_actions, "Inspect release-gates logs and fix the classified finding before rerunning.", seen_actions)




def release_gates_normalized_status(gate: GateResult) -> str:
    if gate.status == "ok":
        return "passed"
    if gate.status == "failed":
        return "failed"
    if gate.status == "timeout":
        return "infra_failed"
    if gate.status == "infra_failed":
        return "infra_failed"
    if gate.status == "skipped_prerequisite":
        return "skipped_prerequisite"
    if gate.status == "skipped_optional":
        return "skipped_optional"
    if gate.status == "partial_pass":
        return "partial_pass"
    if gate.status == "not_implemented":
        return "skipped_prerequisite"
    if gate.status == "planned":
        return "planned"
    return gate.status or "unknown"


def release_gates_gate_area(gate: GateResult) -> str:
    name = gate.name
    classification = gate.classification
    if "clean_machine" in name:
        return "clean-machine"
    if name.startswith("frontend") or "browser" in name or "playwright" in name:
        return "frontend"
    if name.startswith("backend") or "cargo" in name or "smoke" in name:
        return "backend"
    if "runtime" in name:
        return "runtime"
    if "db" in name or "postgres" in classification:
        return "database"
    if name.startswith("docs") or "readme" in name or "checklist" in name or "release_notes" in name:
        return "docs"
    return "tooling"


def release_gates_status_meaning(status: str) -> str:
    meanings = {
        "passed": "Gate реально выполнился и прошел.",
        "failed": "Gate реально выполнился и нашел defect/test failure.",
        "infra_failed": "Gate не смог проверить продукт из-за окружения/tooling.",
        "skipped_prerequisite": "Gate безопасно пропущен из-за отсутствующего prerequisite.",
        "skipped_optional": "Gate intentionally optional.",
        "partial_pass": "Команда завершилась успешно, но release confidence неполный.",
        "planned": "Dry-run plan: gate был запланирован, но не выполнялся.",
    }
    return meanings.get(status, "Нормализованный статус без отдельного описания.")


def release_gates_classification_family(code: str) -> str:
    if code in {"ok", "release_gates_ok"}:
        return "passed"
    if code in {"release_gates_dry_run"}:
        return "planned"
    infra_markers = (
        "missing",
        "stale",
        "prerequisite",
        "unavailable",
        "permission_denied",
        "port_occupied",
        "network",
        "runtime_unreachable",
        "write_guard",
        "opt_in_required",
        "source_invalid",
        "source_missing",
        "lockfile_mismatch",
    )
    if any(marker in code for marker in infra_markers):
        return "infrastructure"
    if code.endswith("optional_not_requested") or code.startswith("clean_machine_optional"):
        return "optional"
    if code == "critical_tests_ignored":
        return "incomplete_signal"
    return "product_or_contract"


def release_gates_gate_ledger_entry(gate: GateResult) -> dict[str, Any]:
    normalized_status = release_gates_normalized_status(gate)
    return {
        "name": gate.name,
        "area": release_gates_gate_area(gate),
        "status": normalized_status,
        "rawStatus": gate.status,
        "classification": gate.classification,
        "classificationFamily": release_gates_classification_family(gate.classification),
        "problemId": release_gates_problem_id_for_code(gate.classification),
        "nextAction": release_gates_next_action_for_code(gate.classification),
        "required": gate.required,
        "message": gate.message,
        "cwd": gate.cwd,
        "command": release_gate_command_display(gate.command) if gate.command else None,
        "returncode": gate.returncode,
        "durationMs": gate.duration_ms,
        "logPath": gate.log_path,
        "meaning": release_gates_status_meaning(normalized_status),
        "details": gate.details,
    }


def release_gates_build_ledger(result: ReleaseGatesResult) -> dict[str, Any]:
    entries = [release_gates_gate_ledger_entry(gate) for gate in result.gates]
    counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry["status"])
        counts[status] = counts.get(status, 0) + 1
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    blockers = [
        entry
        for entry in entries
        if entry["required"]
        and entry["status"] in {"failed", "infra_failed", "skipped_prerequisite", "partial_pass"}
        and not (ignored_covered and entry["classification"] == "critical_tests_ignored")
    ]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "overallStatus": result.overall_status,
        "classification": result.classification,
        "releaseConfidence": release_gates_release_confidence(result),
        "productRegressionsProven": release_gates_product_regressions_proven(result),
        "countsByStatus": counts,
        "blockers": blockers,
        "gates": entries,
    }


def release_gates_release_confidence(result: ReleaseGatesResult) -> str:
    if result.dry_run:
        return "planned-only"
    if result.overall_status == "ok":
        return "complete-for-configured-gates"
    if result.overall_status in {"incomplete", "partial_pass", "infra_failed"}:
        return "incomplete"
    if result.overall_status == "failed":
        return "failed"
    return "unknown"


def release_gates_product_regressions_proven(result: ReleaseGatesResult) -> str:
    product_failures = [
        gate
        for gate in result.gates
        if gate.required
        and gate.status == "failed"
        and release_gates_classification_family(gate.classification) == "product_or_contract"
    ]
    if product_failures:
        return "yes"
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    unknown_signal = [
        gate
        for gate in result.gates
        if gate.required
        and release_gates_normalized_status(gate) in {"infra_failed", "skipped_prerequisite", "partial_pass"}
        and not (ignored_covered and gate.classification == "critical_tests_ignored")
    ]
    if unknown_signal:
        return "none-proven-but-incomplete"
    return "none"


def release_gates_infrastructure_blockers(result: ReleaseGatesResult) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for gate in result.gates:
        status = release_gates_normalized_status(gate)
        family = release_gates_classification_family(gate.classification)
        if status in {"infra_failed", "skipped_prerequisite"} or family == "infrastructure":
            blockers.append(
                {
                    "gate": gate.name,
                    "code": gate.classification,
                    "status": status,
                    "message": gate.message,
                    "nextAction": release_gates_next_action_for_code(gate.classification) or "Inspect the gate log and rerun release-gates after fixing this prerequisite.",
                }
            )
    return blockers


def release_gates_unverified_areas(result: ReleaseGatesResult) -> list[dict[str, str]]:
    areas: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    for gate in result.gates:
        if ignored_covered and gate.classification == "critical_tests_ignored":
            continue
        status = release_gates_normalized_status(gate)
        if status not in {"infra_failed", "skipped_prerequisite", "skipped_optional", "partial_pass", "planned"}:
            continue
        area = release_gates_gate_area(gate)
        key = (area, gate.name)
        if key in seen:
            continue
        seen.add(key)
        areas.append({"area": area, "gate": gate.name, "status": status, "reason": gate.message})
    return areas


def sha256_tree(project_root: Path, relative_path: str, suffixes: tuple[str, ...] | None = None) -> str | None:
    root = project_root / relative_path
    if not root.exists():
        return None
    digest = hashlib.sha256()
    if root.is_file():
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(root.read_bytes())
        return digest.hexdigest()
    found = False
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        try:
            rel_path = path.relative_to(project_root).as_posix()
        except ValueError:
            continue
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        found = True
    return digest.hexdigest() if found else None


def release_gates_environment_fingerprint(project_root: Path, result: ReleaseGatesResult) -> dict[str, Any]:
    frontend_ready, frontend_reason, frontend_details = release_gate_frontend_dependency_status(project_root)
    tool_names = ["git", "cargo", "rustc", "node", "npm", "docker", "docker_compose", "docker_compose_legacy", "psql", "pg_isready"]
    tools: dict[str, Any] = {}
    for name in tool_names:
        command = TOOL_COMMANDS.get(name)
        if not command:
            continue
        probe = probe_tool(name, command)
        tools[name] = as_jsonable(probe)
    ports = {name: as_jsonable(probe_port(name, port)) for name, port in DEFAULT_PORTS.items()}
    http = {name: as_jsonable(probe_http(name, url)) for name, url in HEALTH_URLS.items()}
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "pythonExecutable": sys.executable,
        },
        "tools": tools,
        "ports": ports,
        "http": http,
        "frontendDependencies": {
            "ready": frontend_ready,
            "reason": frontend_reason,
            "details": frontend_details,
        },
        "hashes": {
            "frontendPackageJsonSha256": sha256_file(project_root / "frontend" / "package.json"),
            "frontendPackageLockSha256": sha256_file(project_root / "frontend" / "package-lock.json"),
            "backendCargoTomlSha256": sha256_file(project_root / "backend" / "Cargo.toml"),
            "backendCargoLockSha256": sha256_file(project_root / "backend" / "Cargo.lock"),
            "backendMigrationsSha256": sha256_tree(project_root, "backend/migrations", (".sql",)),
            "devbootstrapSha256": sha256_file(project_root / "tools" / "devbootstrap.py"),
        },
        "backend": {
            "buildRsPresent": (project_root / "backend" / "build.rs").is_file(),
            "migrationsPathPresent": (project_root / "backend" / "migrations").is_dir(),
        },
        "state": summarize_state(project_root),
        "managedTestDb": managed_test_db_public_payload(result.managed_test_db) if result.managed_test_db else None,
        "managedRuntime": managed_runtime_public_payload(result.managed_runtime) if result.managed_runtime else None,
    }



def release_gates_command_resolution_report(project_root: Path, result: ReleaseGatesResult) -> dict[str, Any]:
    gate_commands: list[dict[str, Any]] = []
    for gate in result.gates:
        if not gate.command:
            continue
        details = command_resolution_details(gate.command)
        gate_commands.append(
            {
                "gate": gate.name,
                "status": gate.status,
                "classification": gate.classification,
                "required": gate.required,
                "cwd": gate.cwd,
                "command": details,
                "available": bool(details.get("resolvedExecutable")),
            }
        )
    tool_commands: dict[str, Any] = {}
    for name, command in TOOL_COMMANDS.items():
        details = command_resolution_details(command)
        tool_commands[name] = {
            "command": details,
            "available": bool(details.get("resolvedExecutable")),
        }
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "platform": {"osName": os.name, "system": platform.system()},
        "purpose": "Explain exactly how every release-gates command is resolved before execution, especially on Windows .cmd/.bat launchers.",
        "toolCommands": tool_commands,
        "gateCommands": gate_commands,
    }


def render_release_gates_command_resolution_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# release-gates command resolution")
    lines.append("")
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Generated: `{report.get('generatedAt')}`")
    lines.append("")
    lines.append("## Gate commands")
    lines.append("")
    lines.append("| Gate | Status | CWD | Display command | Resolved executable | Execution command |")
    lines.append("|---|---|---|---|---|---|")
    for item in report.get("gateCommands", []):
        command = item.get("command") if isinstance(item.get("command"), dict) else {}
        lines.append(
            "| "
            + f"`{item.get('gate')}` | `{item.get('status')}` | `{item.get('cwd')}` | "
            + f"`{command.get('displayCommand') or ''}` | `{command.get('resolvedExecutable') or '<missing>'}` | `{command.get('executionCommand') or ''}` |"
        )
    if not report.get("gateCommands"):
        lines.append("| `<none>` | | | | | |")
    lines.append("")
    lines.append("## Tool commands")
    lines.append("")
    lines.append("| Tool | Available | Resolved executable | Version command |")
    lines.append("|---|---:|---|---|")
    tool_commands = report.get("toolCommands") if isinstance(report.get("toolCommands"), dict) else {}
    for name, item in sorted(tool_commands.items()):
        command = item.get("command") if isinstance(item.get("command"), dict) else {}
        lines.append(f"| `{name}` | {bool(item.get('available'))} | `{command.get('resolvedExecutable') or '<missing>'}` | `{command.get('displayCommand') or ''}` |")
    lines.append("")
    return "\n".join(lines)


def release_gates_secret_sources(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    sources: list[dict[str, Any]] = []
    secret_values: dict[str, str] = {}
    for relative in ["backend/.env", "backend/.env.example", "frontend/.env.local", "frontend/.env.example"]:
        values, warnings = parse_env_file(project_root / relative)
        secret_keys = sorted(key for key in values if is_secret_key(key))
        for key in secret_keys:
            value = values.get(key, "")
            if value:
                secret_values[f"{relative}:{key}"] = value
        sources.append(
            {
                "path": relative,
                "exists": (project_root / relative).is_file(),
                "secretKeys": secret_keys,
                "parseWarnings": warnings,
            }
        )
    env_secret_keys = sorted(key for key, value in os.environ.items() if value and is_secret_key(key))
    release_gates_env_value_allowlist = {
        "DATABASE__URL",
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "P2P_TEST_DB_ADMIN_PASSWORD",
        "PGPASSWORD",
    }
    for key in env_secret_keys:
        # The report inventories all secret-like environment key names, but the
        # raw-value scan only uses release-gates input variables. CI/sandbox
        # environments often contain unrelated secrets whose common-looking
        # values can create false positives in plain documentation text.
        if key.upper() in release_gates_env_value_allowlist:
            secret_values[f"env:{key}"] = os.environ[key]
    sources.append({"path": "process-environment", "exists": True, "secretKeys": env_secret_keys, "scannedValueKeys": sorted(release_gates_env_value_allowlist.intersection({key.upper() for key in env_secret_keys})), "parseWarnings": []})
    return sources, secret_values


def release_gates_scan_file_for_raw_secret_hits(path: Path, secret_values: dict[str, str]) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    hits: list[str] = []
    for label, value in secret_values.items():
        if not value or len(value) < 4:
            continue
        if value.lower() in {"true", "false", "none", "null", "password", "postgres", "planner", "localhost", "127.0.0.1"}:
            continue
        masked = mask_value(label.split(":")[-1], value)
        if masked == value:
            continue
        if value in text:
            hits.append(label)
    return sorted(set(hits))


def release_gates_redaction_report(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    sources, secret_values = release_gates_secret_sources(project_root)
    files_with_hits: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_dir() or path.suffix == ".zip":
            continue
        hits = release_gates_scan_file_for_raw_secret_hits(path, secret_values)
        if hits:
            files_with_hits.append(
                {
                    "path": path.relative_to(run_dir).as_posix(),
                    "secretSourceLabels": hits,
                }
            )
    status = "ok" if not files_with_hits else "raw_secret_hits_detected"
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "status": status,
        "purpose": "Document which redaction rules were applied and whether generated release-gates artifacts still contain known raw secret values.",
        "rules": [
            "mask DATABASE__URL and DATABASE_URL credentials",
            "mask environment/file keys containing SECRET, PASSWORD, TOKEN or COOKIE",
            "sanitize release gate stdout/stderr before writing logs",
            "exclude .env/.env.* and release-gates nested zip files from the shareable archive",
        ],
        "sources": sources,
        "rawSecretHitFiles": files_with_hits,
        "notes": [
            "Secret values themselves are never written to this report.",
            "Default/demo values such as postgres/password/planner/localhost are ignored to avoid noisy false positives.",
        ],
    }


def render_release_gates_redaction_report_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# release-gates redaction report")
    lines.append("")
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Status: `{report.get('status')}`")
    lines.append("")
    lines.append("## Rules")
    lines.append("")
    for rule in report.get("rules", []):
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("## Sensitive source inventory")
    lines.append("")
    lines.append("| Source | Exists | Secret keys |")
    lines.append("|---|---:|---|")
    for source in report.get("sources", []):
        keys = ", ".join(f"`{key}`" for key in source.get("secretKeys", [])) or "none"
        lines.append(f"| `{source.get('path')}` | {bool(source.get('exists'))} | {keys} |")
    lines.append("")
    hits = report.get("rawSecretHitFiles") if isinstance(report.get("rawSecretHitFiles"), list) else []
    lines.append("## Raw secret scan")
    lines.append("")
    if not hits:
        lines.append("No generated release-gates artifact contained a known raw secret value from scanned env sources.")
    else:
        for item in hits:
            labels = ", ".join(f"`{label}`" for label in item.get("secretSourceLabels", []))
            lines.append(f"- `{item.get('path')}` contains raw values from {labels}")
    lines.append("")
    return "\n".join(lines)


def release_gates_required_bundle_artifacts() -> list[dict[str, Any]]:
    return [
        {"path": "bundle-manifest.json", "required": True, "description": "Machine-readable autopsy bundle manifest."},
        {"path": "artifact-completeness.json", "required": True, "description": "Machine-readable required artifact completeness check."},
        {"path": "artifact-completeness.md", "required": True, "description": "Human-readable required artifact completeness check."},
        {"path": "summary.txt", "required": True, "description": "Compact terminal-independent run summary."},
        {"path": "release-gates.md", "required": True, "description": "Human-readable release-gates report."},
        {"path": "release-gates.json", "required": True, "description": "Machine-readable release-gates JSON envelope."},
        {"path": "release-gates-consent.json", "required": True, "description": "Machine-readable profile consent and scoped side-effect plan."},
        {"path": "release-gates-consent.md", "required": True, "description": "Human-readable profile consent and scoped side-effect plan."},
        {"path": "environment-fingerprint.json", "required": True, "description": "Root environment fingerprint for quick bundle triage."},
        {"path": "command-resolution.json", "required": True, "description": "Machine-readable command resolution artifact."},
        {"path": "command-resolution.md", "required": True, "description": "Human-readable command resolution artifact."},
        {"path": "redaction-report.json", "required": True, "description": "Machine-readable redaction and raw-secret scan report."},
        {"path": "redaction-report.md", "required": True, "description": "Human-readable redaction and raw-secret scan report."},
        {"path": "logs/", "required": True, "description": "Per-gate logs directory."},
        {"path": "remediation/gate-ledger.json", "required": True, "description": "Machine-readable gate ledger."},
        {"path": "remediation/gate-ledger.md", "required": True, "description": "Human-readable gate ledger."},
        {"path": "remediation/problem-ledger.json", "required": True, "description": "Machine-readable durable problem ledger with stable REL-* IDs."},
        {"path": "remediation/problem-ledger.md", "required": True, "description": "Human-readable durable problem ledger."},
        {"path": "remediation/probe-ledger.json", "required": True, "description": "Machine-readable probe ledger skeleton for every gate."},
        {"path": "remediation/probe-ledger.md", "required": True, "description": "Human-readable probe ledger skeleton."},
        {"path": "remediation/decision-ledger-template.json", "required": True, "description": "Machine-readable decision ledger template."},
        {"path": "remediation/decision-ledger-template.md", "required": True, "description": "Human-readable decision ledger template."},
        {"path": "remediation/provocation-matrix.json", "required": True, "description": "Machine-readable controlled diagnostic provocation matrix."},
        {"path": "remediation/provocation-matrix.md", "required": True, "description": "Human-readable controlled diagnostic provocation matrix."},
        {"path": "remediation/controlled-mutators.json", "required": True, "description": "Machine-readable Phase 4 controlled mutators and cleanup ledger."},
        {"path": "remediation/controlled-mutators.md", "required": True, "description": "Human-readable Phase 4 controlled mutators and cleanup ledger."},
        {"path": "remediation/repeatability-loop.json", "required": True, "description": "Machine-readable Phase 5 repeatability loop and ledger comparison report."},
        {"path": "remediation/repeatability-loop.md", "required": True, "description": "Human-readable Phase 5 repeatability loop report."},
        {"path": "release-confidence-gate.json", "required": True, "description": "Machine-readable Phase 6 release confidence score, caps and decision."},
        {"path": "release-confidence-gate.md", "required": True, "description": "Human-readable Phase 6 release confidence gate report."},
        {"path": "v1-release-readiness.md", "required": True, "description": "Human-readable v1 release readiness decision summary."},
        {"path": "remediation/regression-memory.json", "required": True, "description": "Machine-readable Phase 7 continuous memory and regression protection report."},
        {"path": "remediation/regression-memory.md", "required": True, "description": "Human-readable Phase 7 continuous memory and regression protection report."},
        {"path": "remediation/recurring-family-counts.json", "required": True, "description": "Machine-readable recurring REL-* family counts across release-gates history."},
        {"path": "remediation/recurring-family-counts.md", "required": True, "description": "Human-readable recurring REL-* family counts across release-gates history."},
        {"path": "remediation/prerequisites.md", "required": True, "description": "Prerequisite blocker report."},
        {"path": "remediation/skipped-gates.md", "required": True, "description": "Skipped/unverified gate report."},
        {"path": "remediation/next-actions.md", "required": True, "description": "Targeted next actions."},
        {"path": "remediation/rerun-commands.md", "required": True, "description": "Targeted rerun commands."},
        {"path": "remediation/environment-fingerprint.json", "required": True, "description": "Environment fingerprint mirrored inside remediation bundle."},
    ]


def release_gates_artifact_record(run_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    relative = str(spec["path"])
    required = bool(spec.get("required", True))
    path = run_dir / relative.rstrip("/")
    if relative.endswith("/"):
        exists = path.is_dir()
        child_count = len([item for item in path.rglob("*") if item.is_file()]) if exists else 0
        status = "present" if exists and child_count > 0 else "unavailable"
        return {
            "path": relative,
            "required": required,
            "status": status,
            "description": spec.get("description"),
            "type": "directory",
            "childFileCount": child_count,
        }
    if relative in {"artifact-completeness.json", "artifact-completeness.md"} and not path.exists():
        return {
            "path": relative,
            "required": required,
            "status": "generated_by_current_check",
            "description": spec.get("description"),
            "type": "file",
            "sizeBytes": None,
            "sha256": None,
        }
    exists = path.is_file()
    return {
        "path": relative,
        "required": required,
        "status": "present" if exists else "unavailable",
        "description": spec.get("description"),
        "type": "file",
        "sizeBytes": path.stat().st_size if exists else None,
        "sha256": sha256_file(path) if exists else None,
    }


def release_gates_artifact_completeness(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    artifacts = [release_gates_artifact_record(run_dir, spec) for spec in release_gates_required_bundle_artifacts()]
    missing_required = [item for item in artifacts if item.get("required") and item.get("status") == "unavailable"]
    redaction_payload = read_json(run_dir / "redaction-report.json")
    if redaction_payload.get("status") == "raw_secret_hits_detected":
        missing_required.append({"path": "redaction-report.json", "status": "raw_secret_hits_detected", "required": True})
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "overallStatus": "ok" if not missing_required else "failed",
        "missingRequiredArtifacts": missing_required,
        "artifacts": artifacts,
        "policy": "Required artifacts must be present or explicitly generated by the current completeness check before the archive is created.",
    }


def render_release_gates_artifact_completeness_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# release-gates artifact completeness")
    lines.append("")
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Overall: `{report.get('overallStatus')}`")
    lines.append("")
    lines.append("| Artifact | Required | Status | Notes |")
    lines.append("|---|---:|---|---|")
    for item in report.get("artifacts", []):
        notes = item.get("description") or ""
        if item.get("type") == "directory":
            notes += f"; files={item.get('childFileCount')}"
        elif item.get("sizeBytes") is not None:
            notes += f"; bytes={item.get('sizeBytes')}"
        lines.append(f"| `{item.get('path')}` | {bool(item.get('required'))} | `{item.get('status')}` | {notes} |")
    missing = report.get("missingRequiredArtifacts") if isinstance(report.get("missingRequiredArtifacts"), list) else []
    lines.append("")
    if missing:
        lines.append("## Missing or unsafe required artifacts")
        lines.append("")
        for item in missing:
            lines.append(f"- `{item.get('path')}` — `{item.get('status')}`")
    else:
        lines.append("All required autopsy artifacts are present for this bundle contract.")
    lines.append("")
    return "\n".join(lines)


def release_gates_bundle_manifest(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    artifacts = [release_gates_artifact_record(run_dir, spec) for spec in release_gates_required_bundle_artifacts()]
    return {
        "schemaVersion": 1,
        "bundleType": "devbootstrap-release-gates-autopsy",
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "generatedAt": iso_now(),
        "toolVersion": result.tool_version,
        "runId": result.run_id,
        "dryRun": result.dry_run,
        "projectRoot": result.project_root,
        "invokedFrom": result.invoked_from,
        "overallStatus": result.overall_status,
        "classification": result.classification,
        "profile": result.profile_plan.profile if result.profile_plan else None,
        "archivePath": result.archive_path,
        "requiredArtifacts": artifacts,
        "gates": [release_gates_gate_ledger_entry(gate) for gate in result.gates],
        "redactionReport": "redaction-report.json",
        "artifactCompleteness": "artifact-completeness.json",
        "environmentFingerprint": "environment-fingerprint.json",
        "commandResolution": "command-resolution.json",
        "problemLedger": "remediation/problem-ledger.json",
        "probeLedger": "remediation/probe-ledger.json",
        "decisionLedgerTemplate": "remediation/decision-ledger-template.json",
        "provocationMatrix": "remediation/provocation-matrix.json",
        "controlledMutators": "remediation/controlled-mutators.json",
        "repeatabilityLoop": "remediation/repeatability-loop.json",
        "releaseConfidenceGate": "release-confidence-gate.json",
        "v1ReleaseReadiness": "v1-release-readiness.md",
        "regressionMemory": "remediation/regression-memory.json",
        "recurringFamilyCounts": "remediation/recurring-family-counts.json",
        "profileConsent": "release-gates-consent.json",
    }


def release_gates_autopsy_bundle_paths(result: ReleaseGatesResult) -> dict[str, Any] | None:
    if not result.report_dir:
        return None
    base = result.report_dir.rstrip("/")
    return {
        "manifestPath": f"{base}/bundle-manifest.json",
        "artifactCompletenessPath": f"{base}/artifact-completeness.json",
        "environmentFingerprintPath": f"{base}/environment-fingerprint.json",
        "commandResolutionPath": f"{base}/command-resolution.json",
        "redactionReportPath": f"{base}/redaction-report.json",
        "profileConsentPath": f"{base}/release-gates-consent.json",
        "problemLedgerPath": f"{base}/remediation/problem-ledger.json",
        "probeLedgerPath": f"{base}/remediation/probe-ledger.json",
        "decisionLedgerTemplatePath": f"{base}/remediation/decision-ledger-template.json",
        "provocationMatrixPath": f"{base}/remediation/provocation-matrix.json",
        "controlledMutatorsPath": f"{base}/remediation/controlled-mutators.json",
        "repeatabilityLoopPath": f"{base}/remediation/repeatability-loop.json",
        "releaseConfidenceGatePath": f"{base}/release-confidence-gate.json",
        "v1ReleaseReadinessPath": f"{base}/v1-release-readiness.md",
        "regressionMemoryPath": f"{base}/remediation/regression-memory.json",
        "recurringFamilyCountsPath": f"{base}/remediation/recurring-family-counts.json",
    }

def render_release_gates_gate_ledger_md(ledger: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# release-gates gate ledger")
    lines.append("")
    lines.append(f"- Run ID: `{ledger.get('runId')}`")
    lines.append(f"- Overall: `{ledger.get('overallStatus')}`")
    lines.append(f"- Classification: `{ledger.get('classification')}`")
    lines.append(f"- Release confidence: `{ledger.get('releaseConfidence')}`")
    lines.append(f"- Product regressions proven: `{ledger.get('productRegressionsProven')}`")
    lines.append("")
    counts = ledger.get("countsByStatus") if isinstance(ledger.get("countsByStatus"), dict) else {}
    if counts:
        lines.append("## Counts by status")
        lines.append("")
        for status, count in sorted(counts.items()):
            lines.append(f"- `{status}`: {count}")
        lines.append("")
    lines.append("## Gates")
    lines.append("")
    lines.append("| Gate | Area | Status | Classification | Required | Log |")
    lines.append("|---|---|---|---|---:|---|")
    for entry in ledger.get("gates", []):
        log = f"`{entry.get('logPath')}`" if entry.get("logPath") else ""
        lines.append(
            f"| `{entry.get('name')}` | `{entry.get('area')}` | `{entry.get('status')}` | `{entry.get('classification')}` | {entry.get('required')} | {log} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_release_gates_prerequisites_md(result: ReleaseGatesResult, blockers: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# release-gates prerequisites")
    lines.append("")
    if not blockers:
        lines.append("No missing infrastructure prerequisites were detected by the configured gates.")
        lines.append("")
        return "\n".join(lines)
    lines.append("These blockers prevented release-gates from converting skipped/infra checks into real product signal:")
    lines.append("")
    for blocker in blockers:
        lines.append(f"- `{blocker['code']}` from `{blocker['gate']}` — {blocker['message']}")
        lines.append(f"  - Next action: {blocker['nextAction']}")
    lines.append("")
    return "\n".join(lines)


def render_release_gates_skipped_gates_md(unverified: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# release-gates skipped and unverified gates")
    lines.append("")
    if not unverified:
        lines.append("No skipped, planned or partial gates were recorded.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Area | Gate | Status | Reason |")
    lines.append("|---|---|---|---|")
    for item in unverified:
        reason = str(item["reason"]).replace("\n", " ").replace("|", "\\|")
        lines.append(f"| `{item['area']}` | `{item['gate']}` | `{item['status']}` | {reason} |")
    lines.append("")
    return "\n".join(lines)


def release_gates_rerun_commands(result: ReleaseGatesResult, blockers: list[dict[str, str]]) -> list[str]:
    commands: list[str] = []
    codes = {blocker["code"] for blocker in blockers}
    if result.dry_run:
        commands.append("python tools/devbootstrap.py release-gates")
    if any(code in codes for code in {"frontend_dependencies_missing", "frontend_dependencies_stale", "frontend_prepare_dependencies_failed"}):
        commands.append("python tools/devbootstrap.py prepare-frontend --install-mode=stale")
    if any(code in codes for code in {"frontend_dependencies_missing", "frontend_dependencies_stale", "frontend_prepare_dependencies_failed"}):
        commands.append("python tools/devbootstrap.py release-gates --prepare-deps")
    if "browser_smoke_prerequisite" in codes:
        commands.append("python tools/devbootstrap.py release-gates --prepare-deps --install-playwright-browsers")
    if any(code in codes for code in {"REL-ENV", "REL-UIUX-PREREQ"}):
        commands.append("python -B tools/uiux_evidence.py discover-browser")
    if any(code in codes for code in {"db_test_prerequisite_missing", "smoke_db_write_guard", "real_backend_browser_write_guard", "managed_runtime_db_unavailable"}):
        commands.append("python tools/devbootstrap.py release-gates --managed-test-db --managed-runtime")
    if "real_backend_browser_opt_in_required" in codes:
        commands.append("python tools/devbootstrap.py release-gates --managed-test-db --managed-runtime --include-real-backend-browser")
    if any(code.startswith("managed_") or code.startswith("postgres_") for code in codes):
        commands.append("python tools/devbootstrap.py release-gates --profile isolated-db")
    if "clean_machine_optional_not_requested" in codes:
        commands.append("python tools/devbootstrap.py release-gates --include-clean-machine --clean-machine-profile=dry")
    if result.profile_plan and result.profile_plan.profile != "full-local-release":
        commands.append("python tools/devbootstrap.py release-gates --profile full-local-release")
    if not commands:
        commands.append("python tools/devbootstrap.py release-gates")
    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command not in seen:
            deduped.append(command)
            seen.add(command)
    return deduped


def render_release_gates_next_actions_md(result: ReleaseGatesResult) -> str:
    lines = ["# release-gates next actions", ""]
    if result.next_actions:
        for action in result.next_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- No next actions were generated.")
    if result.managed_test_db and result.managed_test_db.retained and result.managed_test_db.cleanup_command:
        lines.extend(
            [
                "",
                "## Retained managed test DB",
                "",
                "The managed test database was kept by retention policy because the run did not fully pass.",
                "",
                "Cleanup when it is no longer needed:",
                "",
                "```bash",
                result.managed_test_db.cleanup_command,
                "```",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def render_release_gates_rerun_commands_md(commands: list[str]) -> str:
    lines = ["# release-gates rerun commands", ""]
    lines.append("Commands are derived from the current blockers rather than generic advice.")
    lines.append("")
    for command in commands:
        lines.append("```bash")
        lines.append(command)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)




def release_gates_problem_id_for_code(code: str) -> str | None:
    if not code or code in {"ok", "dry_run", "release_gates_ok", "release_gates_dry_run"}:
        return None
    exact = {
        "critical_tests_ignored": "REL-DB-001",
        "db_test_prerequisite_missing": "REL-DB-001",
        "smoke_db_write_guard": "REL-SMOKE-001",
        "real_backend_browser_write_guard": "REL-BROWSER-001",
        "real_backend_browser_opt_in_required": "REL-BROWSER-001",
        "browser_smoke_prerequisite": "REL-BROWSER-002",
        "playwright_install_failed": "REL-BROWSER-002",
        "REL-UIUX": "REL-UIUX-001",
        "REL-FE": "REL-UIUX-001",
        "REL-BE": "REL-UIUX-001",
        "REL-DB": "REL-DB-001",
        "REL-ENV": "REL-UIUX-PREREQ",
        "REL-SEC": "REL-SEC-001",
        "real_backend_uiux_write_guard": "REL-UIUX-001",
        "managed_runtime_required": "REL-PROC-001",
        "runtime_unreachable": "REL-PROC-001",
        "frontend_port_conflict": "REL-PORT-001",
        "clean_machine_optional_not_requested": "REL-CLEAN-001",
        "port_binder_probe_failed": "REL-PORT-001",
        "dirty_state_smoke_risk": "REL-SMOKE-001",
        "db_capability_probe_source_missing": "REL-DB-002",
        "launcher_dry_run_missing_prerequisite": "REL-WIN-001",
        "release_gates_infra_failed": "REL-ART-001",
        "release_gates_incomplete": "REL-ART-001",
        "release_gates_failed": "REL-ART-001",
        "release_gates_timeout": "REL-ART-001",
        "release_gates_unknown": "REL-ART-001",
    }
    if code in exact:
        return exact[code]
    prefix_map = [
        (("frontend_uiux_",), "REL-UIUX-001"),
        (("frontend_dependencies_", "frontend_prepare_", "frontend_lockfile_", "dependency_network_"), "REL-FE-001"),
        (("managed_test_db_", "postgres_", "db_capability_probe_"), "REL-DB-002"),
        (("managed_runtime_db_",), "REL-DB-001"),
        (("managed_backend_port_", "managed_frontend_port_"), "REL-PORT-001"),
        (("managed_runtime_", "managed_backend_", "managed_frontend_"), "REL-PROC-001"),
        (("docs_",), "REL-DOCS-001"),
        (("clean_machine_",), "REL-CLEAN-001"),
    ]
    for prefixes, problem_id in prefix_map:
        if code.startswith(prefixes):
            return problem_id
    digest = hashlib.sha1(code.encode("utf-8")).hexdigest()[:8].upper()
    return f"REL-UNMAPPED-{digest}"


def release_gates_problem_family(problem_id: str | None) -> str:
    if not problem_id:
        return "none"
    if problem_id.startswith("REL-UNMAPPED-"):
        return "REL-UNMAPPED"
    parts = problem_id.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else problem_id


def release_gates_problem_status_for_gate(gate: GateResult) -> str:
    normalized = release_gates_normalized_status(gate)
    if normalized in {"failed", "infra_failed"}:
        return "observed"
    if normalized in {"skipped_prerequisite", "partial_pass"}:
        return "remediation_planned"
    if normalized == "skipped_optional":
        return "accepted_non_blocking"
    if normalized == "planned":
        return "suspected"
    return "guarded"


def release_gates_problem_severity_for_gate(gate: GateResult) -> str:
    normalized = release_gates_normalized_status(gate)
    if gate.required and normalized in {"failed", "infra_failed", "skipped_prerequisite", "partial_pass"}:
        return "blocks_release"
    if normalized in {"skipped_optional", "planned"}:
        return "non_blocking_signal_gap"
    return "informational"


def release_gates_problem_ledger(result: ReleaseGatesResult, rerun_commands: list[str]) -> dict[str, Any]:
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    problems: dict[str, dict[str, Any]] = {}
    for gate in result.gates:
        if ignored_covered and gate.classification == "critical_tests_ignored":
            continue
        normalized = release_gates_normalized_status(gate)
        include = normalized in {"failed", "infra_failed", "skipped_prerequisite", "partial_pass", "skipped_optional"}
        if not include:
            continue
        problem_id = release_gates_problem_id_for_code(gate.classification)
        if not problem_id:
            continue
        entry = problems.setdefault(
            problem_id,
            {
                "id": problem_id,
                "family": release_gates_problem_family(problem_id),
                "status": release_gates_problem_status_for_gate(gate),
                "severity": release_gates_problem_severity_for_gate(gate),
                "classificationCodes": [],
                "ownerLayers": [],
                "summary": gate.message,
                "evidence": [],
                "nextActions": [],
                "rerunCommands": [],
                "confidence": "runtime_observed" if normalized in {"failed", "infra_failed"} else "classified_signal",
            },
        )
        if gate.classification not in entry["classificationCodes"]:
            entry["classificationCodes"].append(gate.classification)
        area = release_gates_gate_area(gate)
        if area not in entry["ownerLayers"]:
            entry["ownerLayers"].append(area)
        # Keep the strongest blocking severity/status seen for this problem.
        if entry["severity"] != "blocks_release" and release_gates_problem_severity_for_gate(gate) == "blocks_release":
            entry["severity"] = "blocks_release"
        if entry["status"] == "suspected" and normalized not in {"planned", "skipped_optional"}:
            entry["status"] = release_gates_problem_status_for_gate(gate)
        evidence = {
            "gate": gate.name,
            "status": normalized,
            "rawStatus": gate.status,
            "classification": gate.classification,
            "message": gate.message,
            "required": gate.required,
            "logPath": gate.log_path,
        }
        entry["evidence"].append(evidence)
        next_action = release_gates_next_action_for_code(gate.classification)
        if next_action and next_action not in entry["nextActions"]:
            entry["nextActions"].append(next_action)
    for entry in problems.values():
        if not entry["nextActions"]:
            entry["nextActions"].append("Inspect the listed gate logs and classify the blocker before changing product/runtime behavior.")
        entry["rerunCommands"] = list(rerun_commands)
    unresolved = [entry for entry in problems.values() if entry["severity"] == "blocks_release"]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "ledgerType": "problem-ledger",
        "policy": "Stable REL-* IDs group repeated failures across release-gates runs; unresolved blockers must have a next action before remediation.",
        "overallStatus": "blocked" if unresolved else "no_blocking_problems_detected",
        "unresolvedBlockerCount": len(unresolved),
        "problems": sorted(problems.values(), key=lambda item: (item["severity"] != "blocks_release", item["id"])),
    }


def render_release_gates_problem_ledger_md(ledger: dict[str, Any]) -> str:
    lines = ["# release-gates problem ledger", ""]
    lines.append(f"- Run ID: `{ledger.get('runId')}`")
    lines.append(f"- Overall: `{ledger.get('overallStatus')}`")
    lines.append(f"- Unresolved blockers: `{ledger.get('unresolvedBlockerCount')}`")
    lines.append("")
    problems = ledger.get("problems") if isinstance(ledger.get("problems"), list) else []
    if not problems:
        lines.append("No unresolved or skipped release-gates problems were classified in this run.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Problem ID | Family | Status | Severity | Classifications | Next action |")
    lines.append("|---|---|---|---|---|---|")
    for problem in problems:
        codes = ", ".join(f"`{code}`" for code in problem.get("classificationCodes", []))
        action = (problem.get("nextActions") or [""])[0].replace("\n", " ").replace("|", "\\|")
        lines.append(
            f"| `{problem.get('id')}` | `{problem.get('family')}` | `{problem.get('status')}` | `{problem.get('severity')}` | {codes} | {action} |"
        )
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    for problem in problems:
        lines.append(f"### `{problem.get('id')}`")
        lines.append("")
        for evidence in problem.get("evidence", []):
            log = f"; log `{evidence.get('logPath')}`" if evidence.get("logPath") else ""
            lines.append(f"- `{evidence.get('gate')}` — `{evidence.get('status')}` / `{evidence.get('classification')}`{log}: {evidence.get('message')}")
        lines.append("")
    return "\n".join(lines)


def release_gates_probe_ledger(result: ReleaseGatesResult) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for gate in result.gates:
        problem_id = release_gates_problem_id_for_code(gate.classification)
        probes.append(
            {
                "probeId": f"gate:{gate.name}",
                "kind": "release-gate",
                "area": release_gates_gate_area(gate),
                "problemId": problem_id,
                "status": release_gates_normalized_status(gate),
                "classification": gate.classification,
                "required": gate.required,
                "command": release_gate_command_display(gate.command) if gate.command else None,
                "logPath": gate.log_path,
                "coverageRole": "regression_or_prerequisite_signal" if gate.required else "optional_signal",
            }
        )
    missing_problem_links = [
        probe
        for probe in probes
        if probe["status"] in {"failed", "infra_failed", "skipped_prerequisite", "partial_pass", "skipped_optional"}
        and not probe.get("problemId")
    ]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "ledgerType": "probe-ledger",
        "policy": "Every release gate is tracked as a probe; failing/skipped probes should link to a stable Problem Ledger ID.",
        "missingProblemLinkCount": len(missing_problem_links),
        "probes": probes,
    }


def render_release_gates_probe_ledger_md(ledger: dict[str, Any]) -> str:
    lines = ["# release-gates probe ledger", ""]
    lines.append(f"- Run ID: `{ledger.get('runId')}`")
    lines.append(f"- Missing problem links: `{ledger.get('missingProblemLinkCount')}`")
    lines.append("")
    lines.append("| Probe | Area | Status | Classification | Problem ID | Required | Log |")
    lines.append("|---|---|---|---|---|---:|---|")
    for probe in ledger.get("probes", []):
        log = f"`{probe.get('logPath')}`" if probe.get("logPath") else ""
        problem_id = f"`{probe.get('problemId')}`" if probe.get("problemId") else ""
        lines.append(
            f"| `{probe.get('probeId')}` | `{probe.get('area')}` | `{probe.get('status')}` | `{probe.get('classification')}` | {problem_id} | {probe.get('required')} | {log} |"
        )
    lines.append("")
    return "\n".join(lines)


def release_gates_decision_ledger_template(result: ReleaseGatesResult, problem_ledger: dict[str, Any]) -> dict[str, Any]:
    problem_ids = [problem.get("id") for problem in problem_ledger.get("problems", []) if problem.get("id")]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "ledgerType": "decision-ledger-template",
        "policy": "Copy one template entry per remediation decision into project docs or the next patch summary before changing behavior.",
        "template": {
            "decisionId": f"DEC-{result.run_id}-001",
            "problemIds": problem_ids,
            "status": "proposed",
            "context": "What evidence from problem-ledger/probe-ledger forced this decision?",
            "optionsConsidered": ["Option A", "Option B"],
            "chosenOption": "",
            "rationale": "",
            "risks": [],
            "acceptanceChecks": [],
            "rollbackPlan": "",
        },
    }


def render_release_gates_decision_ledger_template_md(template: dict[str, Any]) -> str:
    decision = template.get("template") if isinstance(template.get("template"), dict) else {}
    lines = ["# release-gates decision ledger template", ""]
    lines.append(f"- Run ID: `{template.get('runId')}`")
    lines.append(f"- Decision ID: `{decision.get('decisionId')}`")
    lines.append(f"- Status: `{decision.get('status')}`")
    lines.append("")
    lines.append("Use this template when a blocker requires a behavior-changing remediation patch.")
    lines.append("")
    lines.append("## Problem IDs")
    lines.append("")
    problem_ids = decision.get("problemIds") if isinstance(decision.get("problemIds"), list) else []
    if problem_ids:
        for problem_id in problem_ids:
            lines.append(f"- `{problem_id}`")
    else:
        lines.append("- `<none from this run>`")
    lines.append("")
    lines.append("## Decision record")
    lines.append("")
    lines.append("```text")
    lines.append("context: What evidence from problem-ledger/probe-ledger forced this decision?")
    lines.append("optionsConsidered:")
    lines.append("  - Option A")
    lines.append("  - Option B")
    lines.append("chosenOption:")
    lines.append("rationale:")
    lines.append("risks:")
    lines.append("acceptanceChecks:")
    lines.append("rollbackPlan:")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def release_gates_low_risk_port_binder_probe() -> dict[str, Any]:
    started = time.monotonic()
    host = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, 0))
            sock.listen(1)
            bound_host, bound_port = sock.getsockname()[:2]
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "probeId": "provocation:low-risk-port-binder",
            "purpose": "Prove that managed runtime can request a disposable loopback port without touching fixed project ports.",
            "status": "ok",
            "classification": "ok",
            "host": bound_host,
            "requestedPort": 0,
            "allocatedPort": bound_port,
            "durationMs": duration_ms,
            "sideEffects": ["temporarily bound 127.0.0.1:0 during this Python process only"],
        }
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "probeId": "provocation:low-risk-port-binder",
            "purpose": "Prove that managed runtime can request a disposable loopback port without touching fixed project ports.",
            "status": "infra_failed",
            "classification": "port_binder_probe_failed",
            "host": host,
            "requestedPort": 0,
            "allocatedPort": None,
            "durationMs": duration_ms,
            "error": f"{exc.__class__.__name__}: {exc}",
            "sideEffects": ["no persistent side effects"],
        }


def release_gates_launcher_dry_run_matrix() -> list[dict[str, Any]]:
    matrix_commands = {
        "python": [sys.executable, "--version"],
        "git": ["git", "--version"],
        "cargo": ["cargo", "--version"],
        "npm": ["npm", "--version"],
        "node": ["node", "--version"],
        "docker_compose": ["docker", "compose", "version"],
        "psql": ["psql", "--version"],
    }
    rows: list[dict[str, Any]] = []
    for name, command in matrix_commands.items():
        details = command_resolution_details(command)
        resolved = bool(details.get("resolvedExecutable"))
        classification = "ok" if resolved else "launcher_dry_run_missing_prerequisite"
        rows.append(
            {
                "probeId": f"provocation:launcher:{name}",
                "name": name,
                "status": "ok" if resolved else "skipped_prerequisite",
                "classification": classification,
                "command": details,
                "sideEffects": ["dry-run command resolution only; command was not executed"],
            }
        )
    return rows


def release_gates_db_capability_probes(project_root: Path) -> list[dict[str, Any]]:
    raw_url, source = release_gate_database_url_source(project_root)
    parsed = parse_database_url_probe(raw_url)
    psql_resolution = command_resolution_details(["psql", "--version"])
    pg_isready_resolution = command_resolution_details(["pg_isready", "--version"])
    source_available = bool(raw_url and not parsed.warnings)
    return [
        {
            "probeId": "provocation:db:url-contract",
            "status": "ok" if source_available else "skipped_prerequisite",
            "classification": "ok" if source_available else "db_capability_probe_source_missing",
            "source": source,
            "databaseUrl": as_jsonable(parsed),
            "sideEffects": ["read environment files and process environment only; no database connection attempted"],
        },
        {
            "probeId": "provocation:db:psql-launcher",
            "status": "ok" if psql_resolution.get("resolvedExecutable") else "skipped_prerequisite",
            "classification": "ok" if psql_resolution.get("resolvedExecutable") else "postgres_client_missing",
            "command": psql_resolution,
            "sideEffects": ["dry-run command resolution only; psql was not executed"],
        },
        {
            "probeId": "provocation:db:pg-isready-launcher",
            "status": "ok" if pg_isready_resolution.get("resolvedExecutable") else "skipped_prerequisite",
            "classification": "ok" if pg_isready_resolution.get("resolvedExecutable") else "postgres_client_missing",
            "command": pg_isready_resolution,
            "sideEffects": ["dry-run command resolution only; pg_isready was not executed"],
        },
    ]


def release_gates_dirty_state_smoke_probe(project_root: Path) -> dict[str, Any]:
    smoke_path = project_root / "backend" / "tests" / "smoke_core_api.py"
    text = ""
    try:
        text = smoke_path.read_text(encoding="utf-8")
        read_error = None
    except OSError as exc:
        read_error = f"{exc.__class__.__name__}: {exc}"
    run_scoped_user = "SMOKE_RUN_ID" in text and "smoke-user-" in text
    # Keep this heuristic conservative: only known brittle phrase patterns make it risky.
    brittle_markers = [
        "me appearance default isCustomized == false",
        "isCustomized == False",
        "isCustomized == false",
    ]
    brittle_hits = [marker for marker in brittle_markers if marker in text]
    status = "ok" if run_scoped_user and not brittle_hits and read_error is None else "skipped_prerequisite" if read_error else "infra_failed"
    classification = "ok" if status == "ok" else "dirty_state_smoke_risk"
    return {
        "probeId": "provocation:dirty-state-smoke",
        "status": status,
        "classification": classification,
        "smokePath": rel(smoke_path, project_root),
        "exists": smoke_path.is_file(),
        "readError": read_error,
        "runScopedUserDetected": run_scoped_user,
        "brittleDefaultStateMarkers": brittle_hits,
        "sideEffects": ["static source inspection only; smoke was not executed"],
        "nextAction": release_gates_next_action_for_code(classification),
    }


def release_gates_clean_machine_dry_profile_probe(project_root: Path) -> dict[str, Any]:
    required_results, missing_required = clean_machine_required_path_results(project_root)
    commands = release_gate_clean_machine_commands("dry")
    return {
        "probeId": "provocation:clean-machine-dry-profile",
        "status": "ok" if not missing_required else "skipped_prerequisite",
        "classification": "ok" if not missing_required else "clean_machine_required_files_missing",
        "profile": "dry",
        "requiredFiles": required_results,
        "missingRequiredFiles": missing_required,
        "plannedCommands": [release_gate_command_display(command) for command in commands],
        "sideEffects": ["dry profile planning only; no clean-machine copy was created by this matrix probe"],
    }


def release_gates_provocation_matrix(project_root: Path, result: ReleaseGatesResult) -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    probes.append(release_gates_low_risk_port_binder_probe())
    probes.extend(release_gates_launcher_dry_run_matrix())
    probes.extend(release_gates_db_capability_probes(project_root))
    probes.append(release_gates_dirty_state_smoke_probe(project_root))
    probes.append(release_gates_clean_machine_dry_profile_probe(project_root))
    for probe in probes:
        classification = str(probe.get("classification") or "")
        if classification and classification != "ok":
            probe.setdefault("problemId", release_gates_problem_id_for_code(classification))
            probe.setdefault("nextAction", release_gates_next_action_for_code(classification))
    failures = [probe for probe in probes if probe.get("status") in {"failed", "infra_failed"}]
    skipped = [probe for probe in probes if str(probe.get("status", "")).startswith("skipped")]
    classifications = sorted({str(probe.get("classification")) for probe in probes if probe.get("classification") and probe.get("classification") != "ok"})
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "matrixType": "diagnostic-provocation-matrix",
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "purpose": "Catch expected low-risk release/dev failures before users hit them accidentally, without destructive mutation.",
        "overallStatus": "failed" if failures else "incomplete" if skipped else "ok",
        "classificationCodes": classifications,
        "sideEffectPolicy": "Read-only/dry-run except for binding a temporary loopback port 0 inside the current Python process.",
        "probes": probes,
    }


def render_release_gates_provocation_matrix_md(matrix: dict[str, Any]) -> str:
    lines = ["# release-gates diagnostic provocation matrix", ""]
    lines.append(f"- Run ID: `{matrix.get('runId')}`")
    lines.append(f"- Overall: `{matrix.get('overallStatus')}`")
    lines.append(f"- Contract: `{matrix.get('contractVersion')}`")
    lines.append("")
    lines.append("Phase 3 intentionally provokes only low-risk diagnostic conditions. It must not create databases, install dependencies, start long-lived runtimes or modify project files.")
    lines.append("")
    lines.append("| Probe | Status | Classification | Problem ID | Side effects |")
    lines.append("|---|---|---|---|---|")
    for probe in matrix.get("probes", []):
        side_effects = "; ".join(str(item) for item in probe.get("sideEffects", [])) or "none"
        side_effects = side_effects.replace("|", "\\|")
        problem_id = f"`{probe.get('problemId')}`" if probe.get("problemId") else ""
        lines.append(f"| `{probe.get('probeId')}` | `{probe.get('status')}` | `{probe.get('classification')}` | {problem_id} | {side_effects} |")
    lines.append("")
    codes = matrix.get("classificationCodes") if isinstance(matrix.get("classificationCodes"), list) else []
    if codes:
        lines.append("## Non-ok classifications")
        lines.append("")
        for code in codes:
            action = release_gates_next_action_for_code(str(code)) or "Inspect the probe entry and related release-gates logs."
            lines.append(f"- `{code}` — {action}")
        lines.append("")
    return "\n".join(lines)


def release_gates_find_gate(result: ReleaseGatesResult, name: str) -> GateResult | None:
    for gate in reversed(result.gates):
        if gate.name == name:
            return gate
    return None


def release_gates_controlled_mutator_item(
    *,
    mutator_id: str,
    title: str,
    enabled: bool,
    status: str,
    classification: str,
    side_effects: list[str],
    cleanup: list[str],
    rollback: list[str],
    evidence: list[str],
    unsafe: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mutatorId": mutator_id,
        "title": title,
        "enabled": enabled,
        "status": status,
        "classification": classification,
        "unsafe": unsafe,
        "sideEffects": side_effects,
        "cleanup": cleanup,
        "rollback": rollback,
        "evidence": evidence,
        "details": details or {},
    }


def release_gates_playwright_cleanup_hints(project_root: Path) -> list[str]:
    hints: list[str] = []
    for root in playwright_browser_cache_roots(project_root):
        hints.append(f"remove Playwright browser cache manually if desired: {root}")
    return hints or ["no Playwright browser cache roots could be determined"]


def release_gates_controlled_mutators(project_root: Path, result: ReleaseGatesResult) -> dict[str, Any]:
    profile_options = result.profile_plan.effective_options if result.profile_plan else {}
    mutators: list[dict[str, Any]] = []

    db_state = result.managed_test_db
    db_enabled = bool(db_state and db_state.enabled) or bool(profile_options.get("managed_test_db"))
    db_cleanup: list[str] = []
    db_evidence: list[str] = []
    db_details: dict[str, Any] = {"retention": profile_options.get("test_db_retention")}
    if db_state:
        db_details.update(managed_test_db_public_payload(db_state))
        if db_state.cleanup_command:
            db_cleanup.append(db_state.cleanup_command)
        if db_state.metadata_path:
            db_evidence.append(db_state.metadata_path)
        gate = release_gates_find_gate(result, "managed_test_db_retention") or release_gates_find_gate(result, "managed_test_db_prepare")
        if gate and gate.log_path:
            db_evidence.append(gate.log_path)
    mutators.append(
        release_gates_controlled_mutator_item(
            mutator_id="managed-test-database",
            title="Managed PostgreSQL test database",
            enabled=db_enabled,
            status=db_state.status if db_state else "disabled",
            classification=db_state.classification if db_state else "disabled",
            side_effects=[
                "creates at most one per-run PostgreSQL database when --managed-test-db/profile requires it",
                "routes DB-writing release gates to that isolated database",
                "drops or retains only the registered managed database according to retention policy",
            ] if db_enabled else [],
            cleanup=db_cleanup or (["dry-run only; no database was created"] if result.dry_run and db_enabled else ["no managed database cleanup required"]),
            rollback=["rerun the cleanup command from managed-test-db.json if a retained DB is no longer needed"],
            evidence=db_evidence,
            details=db_details,
        )
    )

    runtime_state = result.managed_runtime
    runtime_enabled = bool(runtime_state and runtime_state.enabled) or bool(profile_options.get("managed_runtime") or profile_options.get("managed_test_db"))
    runtime_evidence: list[str] = []
    runtime_cleanup: list[str] = []
    if runtime_state:
        for maybe_path in [runtime_state.runtime_state_path, runtime_state.env_diff_path, runtime_state.managed_urls_path, runtime_state.backend_log_path, runtime_state.frontend_log_path]:
            if maybe_path:
                runtime_evidence.append(maybe_path)
        for gate_name in ["managed_frontend_stop", "managed_backend_stop"]:
            gate = release_gates_find_gate(result, gate_name)
            if gate and gate.log_path:
                runtime_evidence.append(gate.log_path)
        if runtime_state.backend_pid:
            runtime_cleanup.append(f"owned backend PID {runtime_state.backend_pid} should have been stopped by release-gates; if still alive, use devbootstrap stop verification before killing it")
        if runtime_state.frontend_pid:
            runtime_cleanup.append(f"owned frontend PID {runtime_state.frontend_pid} should have been stopped by release-gates; if still alive, use devbootstrap stop verification before killing it")
    mutators.append(
        release_gates_controlled_mutator_item(
            mutator_id="managed-runtime-dynamic-ports",
            title="Managed backend/frontend runtime on dynamic ports",
            enabled=runtime_enabled,
            status=runtime_state.status if runtime_state else "disabled",
            classification=runtime_state.classification if runtime_state else "disabled",
            side_effects=[
                "allocates loopback ports with port 0 and refuses occupied selected ports",
                "starts only backend/frontend processes owned by this release-gates run",
                "writes runtime-state, env-diff and managed-urls artifacts into the run directory",
            ] if runtime_enabled else [],
            cleanup=runtime_cleanup or (["dry-run only; no processes were started"] if result.dry_run and runtime_enabled else ["no managed runtime cleanup required"]),
            rollback=["inspect logs/runtime-state.json before stopping any leftover process; do not kill unrelated live processes"],
            evidence=runtime_evidence,
            details=managed_runtime_public_payload(runtime_state) if runtime_state else {},
        )
    )

    prepare_mode = str(profile_options.get("prepare_deps") or "never")
    prepare_gate = release_gates_find_gate(result, "frontend_prepare_dependencies")
    warmup_gate = release_gates_find_gate(result, "backend_dependency_warmup")
    deps_evidence = [gate.log_path for gate in [prepare_gate, warmup_gate] if gate and gate.log_path]
    mutators.append(
        release_gates_controlled_mutator_item(
            mutator_id="dependency-preparation",
            title="Dependency preparation with marker and consent",
            enabled=prepare_mode != "never" or bool(prepare_gate or warmup_gate),
            status=prepare_gate.status if prepare_gate else ("planned" if result.dry_run and prepare_mode != "never" else "disabled"),
            classification=prepare_gate.classification if prepare_gate else ("dry_run" if result.dry_run and prepare_mode != "never" else "disabled"),
            side_effects=[
                "may populate frontend/node_modules and npm cache according to prepare-deps mode",
                "may populate Cargo build/dependency cache via cargo test --no-run",
                "updates only devbootstrap install marker; source files and lockfiles remain read-only",
            ] if prepare_mode != "never" or prepare_gate else [],
            cleanup=[
                "optional manual cleanup: remove frontend/node_modules to reclaim space",
                "optional manual cleanup: remove backend/target or Cargo cache outside the project if desired",
            ] if prepare_mode != "never" or prepare_gate else ["no dependency preparation cleanup required"],
            rollback=["do not rollback package-lock/Cargo.lock; release-gates does not modify them"],
            evidence=deps_evidence,
            details={"prepareDepsMode": prepare_mode, "frontendPrepareGate": as_jsonable(prepare_gate) if prepare_gate else None, "backendWarmupGate": as_jsonable(warmup_gate) if warmup_gate else None},
        )
    )

    playwright_gate = release_gates_find_gate(result, "playwright_install")
    install_playwright_enabled = bool(profile_options.get("install_playwright_browsers")) or bool(playwright_gate)
    mutators.append(
        release_gates_controlled_mutator_item(
            mutator_id="playwright-browser-install",
            title="Optional Playwright browser install",
            enabled=install_playwright_enabled,
            status=playwright_gate.status if playwright_gate else ("planned" if result.dry_run and install_playwright_enabled else "disabled"),
            classification=playwright_gate.classification if playwright_gate else ("dry_run" if result.dry_run and install_playwright_enabled else "disabled"),
            side_effects=[
                "runs npx playwright install chromium only after explicit --install-playwright-browsers/profile consent",
                "may download Chromium into the Playwright browser cache",
            ] if install_playwright_enabled else [],
            cleanup=release_gates_playwright_cleanup_hints(project_root) if install_playwright_enabled else ["no Playwright browser install cleanup required"],
            rollback=["remove only Playwright cache directories you intentionally own; do not remove project source files"],
            evidence=[playwright_gate.log_path] if playwright_gate and playwright_gate.log_path else [],
            details={"installPlaywrightBrowsers": bool(profile_options.get("install_playwright_browsers")), "gate": as_jsonable(playwright_gate) if playwright_gate else None},
        )
    )

    clean_gate = release_gates_find_gate(result, "clean_machine_sandbox")
    clean_enabled = bool(profile_options.get("include_clean_machine")) or bool(clean_gate and clean_gate.status not in {"skipped_optional"})
    clean_cleanup: list[str] = []
    clean_details = as_jsonable(clean_gate.details) if clean_gate else {}
    if clean_gate and isinstance(clean_gate.details, dict):
        command = clean_gate.details.get("cleanupCommand")
        if isinstance(command, str) and command:
            clean_cleanup.append(command)
        elif clean_gate.details.get("kept") is False:
            clean_cleanup.append("clean-machine sandbox was deleted automatically")
    mutators.append(
        release_gates_controlled_mutator_item(
            mutator_id="clean-machine-sandbox",
            title="Clean-machine sandbox copy",
            enabled=clean_enabled,
            status=clean_gate.status if clean_gate else ("planned" if result.dry_run and clean_enabled else "disabled"),
            classification=clean_gate.classification if clean_gate else ("dry_run" if result.dry_run and clean_enabled else "disabled"),
            side_effects=[
                "copies the project to a temporary sandbox with generated/local state excluded",
                "runs only the selected clean-machine profile commands inside that sandbox",
                "retains or deletes the sandbox according to clean-machine retention policy",
            ] if clean_enabled else [],
            cleanup=clean_cleanup or (["dry-run only; no sandbox was copied"] if result.dry_run and clean_enabled else ["no clean-machine sandbox cleanup required"]),
            rollback=["if retained, delete only the sandbox parent path recorded in clean-machine.json/report.md"],
            evidence=[clean_gate.log_path] if clean_gate and clean_gate.log_path else [],
            details=clean_details,
        )
    )

    unsafe_mutations = [item for item in mutators if item.get("unsafe")]
    enabled_mutators = [item for item in mutators if item.get("enabled")]
    cleanup_missing = [item["mutatorId"] for item in enabled_mutators if not item.get("cleanup")]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "phase": "phase-4-controlled-mutators-rollout",
        "purpose": "Document every allowed release-gates mutation, consent source, side effects and cleanup/rollback instructions in one durable artifact.",
        "profile": result.profile_plan.profile if result.profile_plan else None,
        "dryRun": result.dry_run,
        "allowedScopedSideEffects": result.profile_plan.allowed_side_effects if result.profile_plan else [],
        "deniedUnscopedSideEffects": result.profile_plan.denied_side_effects if result.profile_plan else [],
        "unsafeMutationCount": len(unsafe_mutations),
        "cleanupCoverage": "ok" if not cleanup_missing else "incomplete",
        "cleanupMissingFor": cleanup_missing,
        "mutators": mutators,
    }


def render_release_gates_controlled_mutators_md(report: dict[str, Any]) -> str:
    lines = ["# release-gates controlled mutators", ""]
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Contract: `{report.get('contractVersion')}`")
    lines.append(f"- Profile: `{report.get('profile')}`")
    lines.append(f"- Dry run: `{report.get('dryRun')}`")
    lines.append(f"- Unsafe mutation count: `{report.get('unsafeMutationCount')}`")
    lines.append(f"- Cleanup coverage: `{report.get('cleanupCoverage')}`")
    lines.append("")
    lines.append("Phase 4 allows only scoped, explicit and logged mutators. Project source files, env files, lockfiles, foreign processes and unregistered databases remain out of scope.")
    lines.append("")
    lines.append("## Mutators")
    lines.append("")
    lines.append("| Mutator | Enabled | Status | Classification | Cleanup |")
    lines.append("|---|---:|---|---|---|")
    for item in report.get("mutators", []):
        cleanup = "; ".join(str(value) for value in item.get("cleanup", [])) or "none"
        cleanup = cleanup.replace("|", "\\|")
        lines.append(f"| `{item.get('mutatorId')}` | `{item.get('enabled')}` | `{item.get('status')}` | `{item.get('classification')}` | {cleanup} |")
    lines.append("")
    lines.append("## Allowed scoped side effects")
    lines.append("")
    allowed = report.get("allowedScopedSideEffects") if isinstance(report.get("allowedScopedSideEffects"), list) else []
    if allowed:
        for item in allowed:
            lines.append(f"- `{item.get('category')}` — {item.get('description')}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Denied unscoped side effects")
    lines.append("")
    denied = report.get("deniedUnscopedSideEffects") if isinstance(report.get("deniedUnscopedSideEffects"), list) else []
    if denied:
        for item in denied:
            lines.append(f"- `{item.get('category')}` — {item.get('description')}")
    else:
        lines.append("- none")
    lines.append("")
    for item in report.get("mutators", []):
        lines.append(f"## {item.get('title')}")
        lines.append("")
        lines.append(f"- ID: `{item.get('mutatorId')}`")
        lines.append(f"- Enabled: `{item.get('enabled')}`")
        lines.append(f"- Status: `{item.get('status')}`")
        lines.append(f"- Classification: `{item.get('classification')}`")
        side_effects = item.get("sideEffects") if isinstance(item.get("sideEffects"), list) else []
        lines.append("- Side effects: " + ("; ".join(str(value) for value in side_effects) if side_effects else "none"))
        cleanup = item.get("cleanup") if isinstance(item.get("cleanup"), list) else []
        lines.append("- Cleanup: " + ("; ".join(str(value) for value in cleanup) if cleanup else "none"))
        rollback = item.get("rollback") if isinstance(item.get("rollback"), list) else []
        lines.append("- Rollback: " + ("; ".join(str(value) for value in rollback) if rollback else "none"))
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        lines.append("- Evidence: " + ("; ".join(f"`{value}`" for value in evidence) if evidence else "none"))
        lines.append("")
    return "\n".join(lines)


def release_gates_gate_signature_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gates = payload.get("gates") if isinstance(payload.get("gates"), list) else []
    signature: dict[str, dict[str, Any]] = {}
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        name = str(gate.get("name") or "").strip()
        if not name:
            continue
        signature[name] = {
            "status": gate.get("status"),
            "classification": gate.get("classification"),
            "required": bool(gate.get("required", True)),
        }
    return signature


def release_gates_current_payload_for_repeatability(result: ReleaseGatesResult) -> dict[str, Any]:
    return {
        "generatedAt": result.generated_at,
        "runId": result.run_id,
        "dryRun": result.dry_run,
        "overallStatus": result.overall_status,
        "classification": result.classification,
        "profilePlan": as_jsonable(result.profile_plan) if result.profile_plan else None,
        "gates": [as_jsonable(gate) for gate in result.gates],
    }


def release_gates_profile_from_payload(payload: dict[str, Any]) -> str | None:
    profile_plan = payload.get("profilePlan")
    if isinstance(profile_plan, dict):
        profile = profile_plan.get("profile")
        return str(profile) if profile else None
    profile = payload.get("profile")
    return str(profile) if profile else None


def release_gates_previous_run_payloads(project_root: Path, current_report_dir: str | None, limit: int = 12) -> list[dict[str, Any]]:
    runs_root = project_root / BOOTSTRAP_DIR_NAME / "runs"
    if not runs_root.is_dir():
        return []
    current_abs: Path | None = None
    if current_report_dir:
        current_abs = (project_root / current_report_dir).resolve()
    candidates: list[tuple[float, Path]] = []
    for path in runs_root.glob("*/release-gates.json"):
        try:
            if current_abs is not None and path.parent.resolve() == current_abs:
                continue
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    payloads: list[dict[str, Any]] = []
    for _, path in sorted(candidates, reverse=True)[:limit]:
        payload = read_json(path)
        if payload.get("command") != "release-gates" and "gates" not in payload:
            continue
        payload["_path"] = rel(path, project_root)
        payloads.append(payload)
    return payloads


def release_gates_gate_signature_similarity(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    current_sig = release_gates_gate_signature_from_payload(current)
    previous_sig = release_gates_gate_signature_from_payload(previous)
    common = sorted(set(current_sig) & set(previous_sig))
    compared: list[dict[str, Any]] = []
    matches = 0
    for name in common:
        cur = current_sig[name]
        prev = previous_sig[name]
        match = cur.get("status") == prev.get("status") and cur.get("classification") == prev.get("classification")
        if match:
            matches += 1
        compared.append(
            {
                "gate": name,
                "matches": match,
                "current": {"status": cur.get("status"), "classification": cur.get("classification")},
                "previous": {"status": prev.get("status"), "classification": prev.get("classification")},
            }
        )
    ratio = (matches / len(common)) if common else 0.0
    return {
        "commonGateCount": len(common),
        "matchingGateCount": matches,
        "gateStabilityRatio": round(ratio, 3),
        "comparedGates": compared,
    }


def release_gates_repeatability_component(name: str, status: str, score: float, evidence: list[str], notes: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "score": round(max(0.0, min(1.0, score)), 3),
        "evidence": evidence,
        "notes": notes,
    }


def release_gates_repeatability_loop(project_root: Path, result: ReleaseGatesResult) -> dict[str, Any]:
    current = release_gates_current_payload_for_repeatability(result)
    current_profile = release_gates_profile_from_payload(current)
    previous_runs = release_gates_previous_run_payloads(project_root, result.report_dir)
    same_profile_runs = [payload for payload in previous_runs if release_gates_profile_from_payload(payload) == current_profile]
    latest_same_profile = same_profile_runs[0] if same_profile_runs else None
    components: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    if result.dry_run:
        components.append(
            release_gates_repeatability_component(
                "same-profile-repeat",
                "planned-only",
                0.0,
                [],
                ["Current run is a dry-run; execute the same profile twice without --dry-run before claiming repeatability."],
            )
        )
    elif latest_same_profile:
        similarity = release_gates_gate_signature_similarity(current, latest_same_profile)
        overall_matches = current.get("overallStatus") == latest_same_profile.get("overallStatus") and current.get("classification") == latest_same_profile.get("classification")
        score = similarity["gateStabilityRatio"] * 0.8 + (0.2 if overall_matches else 0.0)
        status = "verified" if overall_matches and similarity["gateStabilityRatio"] >= 0.8 else "unstable"
        comparison = {
            "currentRunId": result.run_id,
            "previousRunId": latest_same_profile.get("runId"),
            "previousPath": latest_same_profile.get("_path"),
            "sameProfile": True,
            "overallMatches": overall_matches,
            **similarity,
        }
        comparisons.append(comparison)
        components.append(
            release_gates_repeatability_component(
                "same-profile-repeat",
                status,
                score,
                [str(latest_same_profile.get("_path"))],
                [f"Compared with previous same-profile run `{latest_same_profile.get('runId')}`."],
            )
        )
    else:
        components.append(
            release_gates_repeatability_component(
                "same-profile-repeat",
                "insufficient-history",
                0.0,
                [],
                ["No previous release-gates run with the same profile was found in .dev-bootstrap/runs."],
            )
        )

    gate_by_name = {gate.name: gate for gate in result.gates}
    managed_start_names = [name for name in ["managed_backend_start", "managed_frontend_start"] if name in gate_by_name]
    managed_stop_names = [name for name in ["managed_backend_stop", "managed_frontend_stop"] if name in gate_by_name]
    if result.dry_run:
        components.append(
            release_gates_repeatability_component(
                "start-stop-start",
                "planned-only",
                0.0,
                [],
                ["Dry-run cannot prove process lifecycle repeatability."],
            )
        )
    elif managed_start_names and managed_stop_names:
        start_ok = all(gate_by_name[name].status == "ok" for name in managed_start_names)
        stop_ok = all(gate_by_name[name].status == "ok" for name in managed_stop_names)
        components.append(
            release_gates_repeatability_component(
                "start-stop-start",
                "single-cycle-evidence" if start_ok and stop_ok else "failed-cycle-evidence",
                0.6 if start_ok and stop_ok else 0.0,
                [gate_by_name[name].log_path or name for name in managed_start_names + managed_stop_names],
                ["Current release-gates run contains one owned managed-runtime start/stop cycle; run the same profile again to prove start-stop-start."],
            )
        )
    else:
        components.append(
            release_gates_repeatability_component(
                "start-stop-start",
                "not-observed",
                0.0,
                [],
                ["Managed runtime was not enabled, so process lifecycle repeatability was not exercised."],
            )
        )

    previous_start_failures = [payload for payload in previous_runs if any(isinstance(g, dict) and str(g.get("name", "")).endswith("_start") and g.get("status") in {"failed", "infra_failed", "timeout"} for g in payload.get("gates", []) if isinstance(payload.get("gates"), list))]
    current_start_ok = any(name in gate_by_name and gate_by_name[name].status == "ok" for name in ["managed_backend_start", "managed_frontend_start"])
    if previous_start_failures and current_start_ok:
        components.append(
            release_gates_repeatability_component(
                "failed-start-retry",
                "verified",
                1.0,
                [str(previous_start_failures[0].get("_path"))],
                ["A previous managed start failure exists and the current run reached a managed start successfully."],
            )
        )
    else:
        components.append(
            release_gates_repeatability_component(
                "failed-start-retry",
                "not-observed",
                0.0,
                [],
                ["No failed-start-then-retry evidence was found; keep this as a scenario in manual/CI repeatability review."],
            )
        )

    smoke_gate_names = [name for name in ["backend_python_smoke_first", "backend_python_smoke_second"] if name in gate_by_name]
    if len(smoke_gate_names) == 2:
        smoke_ok = all(gate_by_name[name].status == "ok" for name in smoke_gate_names)
        components.append(
            release_gates_repeatability_component(
                "fresh-and-dirty-smoke",
                "verified" if smoke_ok else "known-classified",
                1.0 if smoke_ok else 0.4,
                [gate_by_name[name].log_path or name for name in smoke_gate_names],
                ["Both backend smoke passes are present; this is the current in-run fresh/dirty smoke proxy."],
            )
        )
    else:
        components.append(
            release_gates_repeatability_component(
                "fresh-and-dirty-smoke",
                "not-observed",
                0.0,
                [],
                ["The double backend smoke path requires a write-safe DB via managed-test-db or TEST_DATABASE_URL."],
            )
        )

    if latest_same_profile:
        ledger_score = comparisons[0]["gateStabilityRatio"] if comparisons else 0.0
        components.append(
            release_gates_repeatability_component(
                "ledger-compare",
                "verified" if ledger_score >= 0.8 else "unstable",
                ledger_score,
                [str(latest_same_profile.get("_path"))],
                ["Compared current gate ledger signature with the latest same-profile release-gates JSON."],
            )
        )
    else:
        components.append(
            release_gates_repeatability_component(
                "ledger-compare",
                "insufficient-history",
                0.0,
                [],
                ["Need at least one previous same-profile release-gates JSON to compare ledgers."],
            )
        )

    cleanup_ok = True
    cleanup_evidence: list[str] = []
    controlled = release_gates_controlled_mutators(project_root, result)
    cleanup_ok = controlled.get("cleanupCoverage") == "ok" and int(controlled.get("unsafeMutationCount") or 0) == 0
    cleanup_evidence.extend(["remediation/controlled-mutators.json", "remediation/controlled-mutators.md"])
    components.append(
        release_gates_repeatability_component(
            "cleanup-verification",
            "verified" if cleanup_ok else "incomplete",
            1.0 if cleanup_ok else 0.0,
            cleanup_evidence,
            ["Controlled mutators ledger reports cleanup coverage and unsafe mutation count for this run."],
        )
    )

    reproducibility_index = sum(float(item.get("score") or 0.0) for item in components) / len(components) if components else 0.0
    exit_criteria_met = reproducibility_index >= 0.8 and not result.dry_run
    recommended_commands = [
        f"python tools/devbootstrap.py release-gates --profile {current_profile or RELEASE_GATES_DEFAULT_PROFILE}",
        f"python tools/devbootstrap.py release-gates --profile {current_profile or RELEASE_GATES_DEFAULT_PROFILE}",
        "python tools/devbootstrap.py release-gates --managed-test-db --managed-runtime --test-db-retention=drop-always",
        "python tools/devbootstrap.py status && python tools/devbootstrap.py stop && python tools/devbootstrap.py up --dry-run --smoke-level quick",
    ]
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "phase": "phase-5-repeatability-loop",
        "purpose": "Show whether configured release-gates evidence is repeatable instead of accidental.",
        "profile": current_profile,
        "dryRun": result.dry_run,
        "reproducibilityIndex": round(reproducibility_index, 3),
        "exitCriteriaMet": exit_criteria_met,
        "threshold": 0.8,
        "previousRunsScanned": len(previous_runs),
        "sameProfilePreviousRuns": len(same_profile_runs),
        "comparisons": comparisons,
        "components": components,
        "recommendedCommands": recommended_commands,
        "notes": [
            "This artifact is evidence-only and does not change release-gates overall status.",
            "A dry-run can verify the contract shape but cannot prove runtime repeatability.",
        ],
    }


def render_release_gates_repeatability_loop_md(report: dict[str, Any]) -> str:
    lines = ["# release-gates repeatability loop", ""]
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Contract: `{report.get('contractVersion')}`")
    lines.append(f"- Profile: `{report.get('profile')}`")
    lines.append(f"- Dry run: `{report.get('dryRun')}`")
    lines.append(f"- Reproducibility Index: `{report.get('reproducibilityIndex')}` / threshold `{report.get('threshold')}`")
    lines.append(f"- Exit criteria met: `{report.get('exitCriteriaMet')}`")
    lines.append(f"- Previous runs scanned: `{report.get('previousRunsScanned')}`")
    lines.append(f"- Same-profile previous runs: `{report.get('sameProfilePreviousRuns')}`")
    lines.append("")
    lines.append("Phase 5 treats one successful run as insufficient. Review this artifact to see which repeatability scenarios are already evidenced and which still need another run or a managed-runtime profile.")
    lines.append("")
    lines.append("## Components")
    lines.append("")
    lines.append("| Component | Status | Score | Evidence |")
    lines.append("|---|---|---:|---|")
    for item in report.get("components", []):
        evidence = "; ".join(f"`{value}`" for value in item.get("evidence", [])) or "none"
        lines.append(f"| `{item.get('name')}` | `{item.get('status')}` | `{item.get('score')}` | {evidence} |")
    lines.append("")
    lines.append("## Comparisons")
    lines.append("")
    comparisons = report.get("comparisons") if isinstance(report.get("comparisons"), list) else []
    if comparisons:
        for item in comparisons:
            lines.append(f"- Current `{item.get('currentRunId')}` vs previous `{item.get('previousRunId')}` from `{item.get('previousPath')}`: gate stability `{item.get('gateStabilityRatio')}`, overall matches `{item.get('overallMatches')}`.")
    else:
        lines.append("- No same-profile historical run was available for ledger comparison.")
    lines.append("")
    lines.append("## Recommended repeatability commands")
    lines.append("")
    for command in report.get("recommendedCommands", []):
        lines.append(f"- `{command}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in report.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)



RELEASE_CONFIDENCE_SCORE_CLASSES = [
    (95, "stable_release_loop"),
    (85, "beta_candidate"),
    (70, "internal_candidate"),
    (50, "partial_signal"),
    (0, "diagnostic_chaos"),
]


def release_confidence_score_class(score: int) -> str:
    for threshold, class_name in RELEASE_CONFIDENCE_SCORE_CLASSES:
        if score >= threshold:
            return class_name
    return "diagnostic_chaos"


def release_confidence_class_rank(class_name: str) -> int:
    order = ["diagnostic_chaos", "partial_signal", "internal_candidate", "beta_candidate", "stable_release_loop"]
    try:
        return order.index(class_name)
    except ValueError:
        return 0


def release_confidence_min_class(current: str, cap: str) -> str:
    return current if release_confidence_class_rank(current) <= release_confidence_class_rank(cap) else cap


def release_confidence_gate_counts(result: ReleaseGatesResult) -> dict[str, Any]:
    required = [gate for gate in result.gates if gate.required]
    optional = [gate for gate in result.gates if not gate.required]
    statuses: dict[str, int] = {}
    for gate in result.gates:
        status = release_gates_normalized_status(gate)
        statuses[status] = statuses.get(status, 0) + 1
    ignored_covered = release_gates_critical_ignored_covered(result.gates)
    unknown_statuses = {"infra_failed", "skipped_prerequisite", "partial_pass", "planned", "unknown"}
    unknown_required = [
        gate
        for gate in required
        if release_gates_normalized_status(gate) in unknown_statuses
        and not (ignored_covered and gate.classification == "critical_tests_ignored")
    ]
    failed_required = [gate for gate in required if release_gates_normalized_status(gate) == "failed"]
    accepted_skips = [gate for gate in optional if release_gates_normalized_status(gate) in {"skipped_optional", "planned"}]
    return {
        "requiredGateCount": len(required),
        "optionalGateCount": len(optional),
        "passedRequiredGateCount": len([gate for gate in required if release_gates_normalized_status(gate) == "passed"]),
        "unknownRequiredGateCount": len(unknown_required),
        "failedRequiredGateCount": len(failed_required),
        "acceptedSkipCount": len(accepted_skips),
        "statuses": statuses,
        "unknownRequiredGates": [release_gates_gate_ledger_entry(gate) for gate in unknown_required],
        "failedRequiredGates": [release_gates_gate_ledger_entry(gate) for gate in failed_required],
        "acceptedSkips": [release_gates_gate_ledger_entry(gate) for gate in accepted_skips],
    }


def release_confidence_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def release_confidence_read_json_or_none(path: Path) -> dict[str, Any] | None:
    payload = read_json(path)
    return payload if payload else None


def release_confidence_artifact_quality(run_dir: Path) -> dict[str, Any]:
    redaction = release_confidence_read_json_or_none(run_dir / "redaction-report.json")
    completeness = release_confidence_read_json_or_none(run_dir / "artifact-completeness.json")
    manifest = release_confidence_read_json_or_none(run_dir / "bundle-manifest.json")
    redaction_ok = bool(redaction and redaction.get("status") == "ok")
    completeness_ok = bool(completeness and completeness.get("overallStatus") == "ok")
    manifest_ok = bool(manifest and manifest.get("contractVersion") == RELEASE_GATES_AUTOPSY_CONTRACT_VERSION)
    # During the first write pass, artifact-completeness and the final manifest may
    # not exist yet. Award partial credit for redaction and the currently present
    # required artifacts; the report is rewritten after completeness is generated.
    present_required = 0
    total_required = 0
    for spec in release_gates_required_bundle_artifacts():
        if not spec.get("required", True):
            continue
        total_required += 1
        relative = str(spec["path"])
        candidate = run_dir / relative.rstrip("/")
        if relative.endswith("/"):
            if candidate.is_dir() and any(item.is_file() for item in candidate.rglob("*")):
                present_required += 1
        elif candidate.is_file() or relative in {"artifact-completeness.json", "artifact-completeness.md"}:
            present_required += 1
    presence_ratio = release_confidence_ratio(present_required, total_required)
    if redaction_ok and completeness_ok and manifest_ok:
        score = 5
    elif redaction_ok and presence_ratio >= 0.9:
        score = 4
    elif redaction_ok:
        score = 3
    else:
        score = 1 if presence_ratio >= 0.75 else 0
    return {
        "score": score,
        "maxScore": 5,
        "redactionStatus": redaction.get("status") if redaction else "missing",
        "artifactCompletenessStatus": completeness.get("overallStatus") if completeness else "pending",
        "manifestContractVersion": manifest.get("contractVersion") if manifest else "pending",
        "requiredArtifactPresenceRatio": presence_ratio,
        "requiredArtifactsPresent": present_required,
        "requiredArtifactCount": total_required,
    }


def release_confidence_evidence_completeness(counts: dict[str, Any], artifact_quality: dict[str, Any], result: ReleaseGatesResult) -> dict[str, Any]:
    required_count = int(counts.get("requiredGateCount") or 0)
    unknown_count = int(counts.get("unknownRequiredGateCount") or 0)
    gate_signal_ratio = 1.0 - release_confidence_ratio(unknown_count, required_count) if required_count else 0.0
    artifact_ratio = float(artifact_quality.get("requiredArtifactPresenceRatio") or 0.0)
    base = round(15 * (0.6 * gate_signal_ratio + 0.4 * artifact_ratio))
    if result.dry_run:
        base = min(base, 7)
    return {
        "score": max(0, min(15, base)),
        "maxScore": 15,
        "gateSignalRatio": round(gate_signal_ratio, 3),
        "artifactPresenceRatio": artifact_ratio,
        "reason": "Reviewer can use bundle artifacts plus gate ledger to understand the run." if base >= 10 else "Evidence is still incomplete or mostly planned/skipped.",
    }


def release_confidence_gate_execution_signal(counts: dict[str, Any], result: ReleaseGatesResult) -> dict[str, Any]:
    required_count = int(counts.get("requiredGateCount") or 0)
    passed = int(counts.get("passedRequiredGateCount") or 0)
    failed = int(counts.get("failedRequiredGateCount") or 0)
    unknown = int(counts.get("unknownRequiredGateCount") or 0)
    executed = max(0, required_count - unknown)
    executed_ratio = release_confidence_ratio(executed, required_count)
    pass_ratio = release_confidence_ratio(passed, required_count)
    base = round(20 * (0.7 * pass_ratio + 0.3 * executed_ratio))
    if failed:
        base = min(base, 8)
    if result.dry_run:
        base = min(base, 4)
    return {
        "score": max(0, min(20, base)),
        "maxScore": 20,
        "requiredGateCount": required_count,
        "executedRequiredGateCount": executed,
        "passedRequiredGateCount": passed,
        "failedRequiredGateCount": failed,
        "unknownRequiredGateCount": unknown,
        "reason": "Required gates mostly executed and passed." if base >= 14 else "Required gates are still skipped, planned, infra-blocked or failing.",
    }


def release_confidence_repeatability(repeatability_loop: dict[str, Any] | None, result: ReleaseGatesResult) -> dict[str, Any]:
    index = float((repeatability_loop or {}).get("reproducibilityIndex") or 0.0)
    base = round(15 * index)
    if result.dry_run:
        base = min(base, 3)
    exit_met = bool((repeatability_loop or {}).get("exitCriteriaMet"))
    if not exit_met:
        base = min(base, 12)
    return {
        "score": max(0, min(15, base)),
        "maxScore": 15,
        "reproducibilityIndex": round(index, 3),
        "exitCriteriaMet": exit_met,
        "reason": "Repeatability threshold is met." if exit_met else "Repeatability is not fully proven by current history.",
    }


def release_confidence_isolation_safety(controlled_mutators: dict[str, Any] | None, result: ReleaseGatesResult) -> dict[str, Any]:
    unsafe_count = int((controlled_mutators or {}).get("unsafeMutationCount") or 0)
    cleanup_ok = (controlled_mutators or {}).get("cleanupCoverage") == "ok"
    enabled = [item for item in (controlled_mutators or {}).get("mutators", []) if isinstance(item, dict) and item.get("enabled")]
    score = 15
    if unsafe_count:
        score = 0
    elif not cleanup_ok:
        score = 8
    elif result.dry_run and enabled:
        score = 10
    elif not enabled:
        score = 12
    return {
        "score": max(0, min(15, score)),
        "maxScore": 15,
        "unsafeMutationCount": unsafe_count,
        "cleanupCoverage": (controlled_mutators or {}).get("cleanupCoverage", "missing"),
        "enabledMutatorCount": len(enabled),
        "reason": "Side effects are scoped and cleanup-covered." if score >= 12 else "Mutation safety is not fully covered.",
    }


def release_confidence_cross_platform(command_resolution: dict[str, Any] | None, provocation_matrix: dict[str, Any] | None, result: ReleaseGatesResult) -> dict[str, Any]:
    command_resolution_present = bool(command_resolution and command_resolution.get("gateCommands") is not None)
    launcher_probe = False
    for item in (provocation_matrix or {}).get("probes", []):
        if isinstance(item, dict) and "launcher" in str(item.get("probeId") or item.get("name") or ""):
            launcher_probe = True
            break
    score = 0
    if command_resolution_present:
        score += 5
    if launcher_probe:
        score += 3
    if platform.system().lower().startswith("win"):
        score += 1
    if result.dry_run:
        score = min(score, 8)
    return {
        "score": max(0, min(10, score)),
        "maxScore": 10,
        "commandResolutionPresent": command_resolution_present,
        "launcherProbePresent": launcher_probe,
        "currentPlatform": platform.system(),
        "reason": "Command resolution and launcher probes are present." if score >= 7 else "Cross-platform evidence is still partial.",
    }


def release_confidence_product_path(result: ReleaseGatesResult) -> dict[str, Any]:
    by_name = {gate.name: gate for gate in result.gates}

    def passed(name: str) -> bool:
        gate = by_name.get(name)
        return bool(gate and release_gates_normalized_status(gate) == "passed")

    backend_smoke = passed("backend_python_smoke_first") or passed("backend_python_smoke_second")
    frontend_build = passed("frontend_build")
    frontend_unit = passed("frontend_unit_integration")
    legacy_browser_mocked = passed("frontend_browser_smoke")
    uiux_mocked_core_flow = passed("frontend_uiux_mocked_core_flow")
    mocked_ui_path = legacy_browser_mocked or uiux_mocked_core_flow
    legacy_real_backend_browser = passed("browser_real_backend_path")
    uiux_real_backend_core_flow = passed("frontend_uiux_real_backend_core_flow")
    real_backend_product_path = legacy_real_backend_browser or uiux_real_backend_core_flow
    accepted_real_backend_gate = None
    if uiux_real_backend_core_flow:
        accepted_real_backend_gate = "frontend_uiux_real_backend_core_flow"
    elif legacy_real_backend_browser:
        accepted_real_backend_gate = "browser_real_backend_path"

    score = 0
    if backend_smoke:
        score += 5
    if frontend_build:
        score += 3
    if frontend_unit:
        score += 2
    if mocked_ui_path:
        score += 2
    if real_backend_product_path:
        score += 5
    if result.dry_run:
        score = min(score, 3)
    return {
        "score": max(0, min(15, score)),
        "maxScore": 15,
        "backendSmokePassed": backend_smoke,
        "frontendBuildPassed": frontend_build,
        "frontendUnitPassed": frontend_unit,
        "mockedBrowserSmokePassed": legacy_browser_mocked,
        "uiuxMockedCoreFlowPassed": uiux_mocked_core_flow,
        "mockedUiPathPassed": mocked_ui_path,
        "realBackendBrowserPassed": legacy_real_backend_browser,
        "uiuxRealBackendCoreFlowPassed": uiux_real_backend_core_flow,
        "realBackendProductPathPassed": real_backend_product_path,
        "acceptedRealBackendGate": accepted_real_backend_gate,
        "reason": (
            f"Real backend product path is covered by `{accepted_real_backend_gate}`."
            if accepted_real_backend_gate
            else "Real-backend product path is not proven in this run."
        ),
    }


def release_confidence_remediation_maturity(problem_ledger: dict[str, Any] | None, probe_ledger: dict[str, Any] | None, decision_template: dict[str, Any] | None) -> dict[str, Any]:
    problems = [item for item in (problem_ledger or {}).get("problems", []) if isinstance(item, dict)]
    probes = [item for item in (probe_ledger or {}).get("probes", []) if isinstance(item, dict)]
    unmapped = [item for item in problems if str(item.get("id") or "").startswith("REL-UNMAPPED-")]
    missing_links = int((probe_ledger or {}).get("missingProblemLinkCount") or 0)
    score = 0
    if problem_ledger:
        score += 2
    if probe_ledger:
        score += 1
    if decision_template:
        score += 1
    if not unmapped and missing_links == 0:
        score += 1
    return {
        "score": max(0, min(5, score)),
        "maxScore": 5,
        "problemCount": len(problems),
        "probeCount": len(probes),
        "unmappedProblemCount": len(unmapped),
        "missingProblemLinkCount": missing_links,
        "reason": "Problems, probes and decisions are linked." if score >= 4 else "Problem/probe linkage still needs curation.",
    }


def release_confidence_caps(
    *,
    counts: dict[str, Any],
    repeatability: dict[str, Any],
    product_path: dict[str, Any],
    artifact_quality: dict[str, Any],
    result: ReleaseGatesResult,
) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    if int(counts.get("unknownRequiredGateCount") or 0) > 0:
        caps.append({"id": "unknown-release-blockers", "maximumClass": "partial_signal", "active": True, "reason": "One or more required gates are infra-blocked, skipped, partial or planned."})
    if int(counts.get("failedRequiredGateCount") or 0) > 0:
        caps.append({"id": "required-gate-failed", "maximumClass": "partial_signal", "active": True, "reason": "A required gate failed."})
    if float(repeatability.get("reproducibilityIndex") or 0.0) < 0.8:
        caps.append({"id": "repeatability-not-proven", "maximumClass": "internal_candidate", "active": True, "reason": "No accepted two-run/repeatability evidence at threshold 0.8."})
    if not product_path.get("realBackendProductPathPassed"):
        caps.append({"id": "real-backend-product-path-missing", "maximumClass": "internal_candidate", "active": True, "reason": "Real-backend product path was not proven by UIX or legacy no-mock browser evidence."})
    if artifact_quality.get("redactionStatus") != "ok" or artifact_quality.get("artifactCompletenessStatus") not in {"ok", "pending"}:
        caps.append({"id": "artifact-not-shareable", "maximumClass": "partial_signal", "active": True, "reason": "Redaction or artifact completeness is not accepted."})
    if result.dry_run:
        caps.append({"id": "dry-run", "maximumClass": "partial_signal", "active": True, "reason": "Dry-run validates contract shape only; it is not release evidence."})
    return caps


def release_confidence_decision(score: int, raw_class: str, capped_class: str, caps: list[dict[str, Any]], result: ReleaseGatesResult) -> dict[str, Any]:
    beta_allowed = score >= 85 and capped_class in {"beta_candidate", "stable_release_loop"} and not caps and result.overall_status == "ok"
    if beta_allowed:
        decision = "beta_candidate_allowed"
        recommendation = "Proceed to limited beta review with known limitations documented."
    elif capped_class == "internal_candidate" and result.overall_status in {"ok", "incomplete", "partial_pass"}:
        decision = "internal_candidate_only"
        recommendation = "Use for internal testing only; lift active hard caps before external beta."
    elif capped_class == "partial_signal":
        decision = "release_blocked_partial_signal"
        recommendation = "Do not release; resolve unknown blockers, skipped prerequisites or failed required gates."
    else:
        decision = "release_forbidden_diagnostic_chaos"
        recommendation = "Do not release; improve diagnostic evidence before product judgement."
    return {
        "decision": decision,
        "betaAllowed": beta_allowed,
        "recommendation": recommendation,
    }


def release_gates_release_confidence_gate(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    counts = release_confidence_gate_counts(result)
    repeatability_loop = release_confidence_read_json_or_none(run_dir / "remediation" / "repeatability-loop.json")
    controlled_mutators = release_confidence_read_json_or_none(run_dir / "remediation" / "controlled-mutators.json")
    problem_ledger = release_confidence_read_json_or_none(run_dir / "remediation" / "problem-ledger.json")
    probe_ledger = release_confidence_read_json_or_none(run_dir / "remediation" / "probe-ledger.json")
    decision_template = release_confidence_read_json_or_none(run_dir / "remediation" / "decision-ledger-template.json")
    provocation_matrix = release_confidence_read_json_or_none(run_dir / "remediation" / "provocation-matrix.json")
    command_resolution = release_confidence_read_json_or_none(run_dir / "command-resolution.json")
    artifact_quality = release_confidence_artifact_quality(run_dir)

    blocks = {
        "evidenceCompleteness": release_confidence_evidence_completeness(counts, artifact_quality, result),
        "gateExecutionSignal": release_confidence_gate_execution_signal(counts, result),
        "repeatability": release_confidence_repeatability(repeatability_loop, result),
        "isolationSafety": release_confidence_isolation_safety(controlled_mutators, result),
        "crossPlatformConfidence": release_confidence_cross_platform(command_resolution, provocation_matrix, result),
        "productPathConfidence": release_confidence_product_path(result),
        "remediationMaturity": release_confidence_remediation_maturity(problem_ledger, probe_ledger, decision_template),
        "artifactQuality": artifact_quality,
    }
    score = int(sum(int(block.get("score") or 0) for block in blocks.values()))
    raw_class = release_confidence_score_class(score)
    caps = release_confidence_caps(
        counts=counts,
        repeatability=blocks["repeatability"],
        product_path=blocks["productPathConfidence"],
        artifact_quality=artifact_quality,
        result=result,
    )
    capped_class = raw_class
    for cap in caps:
        capped_class = release_confidence_min_class(capped_class, str(cap.get("maximumClass") or "diagnostic_chaos"))
    decision = release_confidence_decision(score, raw_class, capped_class, caps, result)
    required_count = int(counts.get("requiredGateCount") or 0)
    unknown_count = int(counts.get("unknownRequiredGateCount") or 0)
    report = {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "phase": "phase-6-release-confidence-gate",
        "toolVersion": TOOL_VERSION,
        "profile": result.profile_plan.profile if result.profile_plan else None,
        "dryRun": result.dry_run,
        "overallStatus": result.overall_status,
        "classification": result.classification,
        "score": score,
        "scoreClass": raw_class,
        "effectiveClass": capped_class,
        "unknownRatio": release_confidence_ratio(unknown_count, required_count),
        "classificationCoverage": release_confidence_ratio(
            len([gate for gate in result.gates if gate.classification and gate.classification != "unknown"]),
            len(result.gates),
        ),
        "blocks": blocks,
        "gateCounts": counts,
        "hardCaps": caps,
        "decision": decision,
        "acceptedSkipsDocumented": bool(counts.get("acceptedSkips") is not None),
        "evidencePaths": release_gates_autopsy_bundle_paths(result),
        "scorePolicy": {
            "betaCandidateThreshold": 85,
            "unknownBlockersCap": "partial_signal",
            "repeatabilityCapUntilThreshold": "internal_candidate",
            "realBackendPathCapUntilProven": "internal_candidate",
        },
    }
    return report


def render_release_gates_release_confidence_gate_md(report: dict[str, Any]) -> str:
    lines = ["# release-gates release confidence gate", ""]
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Contract: `{report.get('contractVersion')}`")
    lines.append(f"- Profile: `{report.get('profile')}`")
    lines.append(f"- Dry run: `{report.get('dryRun')}`")
    lines.append(f"- Overall: `{report.get('overallStatus')}` / `{report.get('classification')}`")
    lines.append(f"- Score: `{report.get('score')}`")
    lines.append(f"- Raw class: `{report.get('scoreClass')}`")
    lines.append(f"- Effective class: `{report.get('effectiveClass')}`")
    lines.append(f"- Unknown ratio: `{report.get('unknownRatio')}`")
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    lines.append(f"- Decision: `{decision.get('decision')}`")
    lines.append(f"- Recommendation: {decision.get('recommendation')}")
    lines.append("")
    lines.append("## Score blocks")
    lines.append("")
    lines.append("| Block | Score | Max | Reason |")
    lines.append("|---|---:|---:|---|")
    blocks = report.get("blocks") if isinstance(report.get("blocks"), dict) else {}
    for name, block in blocks.items():
        if not isinstance(block, dict):
            continue
        reason = str(block.get("reason") or "").replace("|", "\\|")
        lines.append(f"| `{name}` | {block.get('score')} | {block.get('maxScore')} | {reason} |")
    lines.append("")
    lines.append("## Hard caps")
    lines.append("")
    caps = report.get("hardCaps") if isinstance(report.get("hardCaps"), list) else []
    if caps:
        lines.append("| Cap | Maximum class | Reason |")
        lines.append("|---|---|---|")
        for cap in caps:
            reason = str(cap.get("reason") or "").replace("|", "\\|")
            lines.append(f"| `{cap.get('id')}` | `{cap.get('maximumClass')}` | {reason} |")
    else:
        lines.append("No hard caps are active.")
    lines.append("")
    lines.append("## Unknown required gates")
    lines.append("")
    gate_counts = report.get("gateCounts") if isinstance(report.get("gateCounts"), dict) else {}
    unknown = gate_counts.get("unknownRequiredGates") if isinstance(gate_counts.get("unknownRequiredGates"), list) else []
    if unknown:
        for gate in unknown:
            lines.append(f"- `{gate.get('name')}` — `{gate.get('status')}` / `{gate.get('classification')}`: {gate.get('message')}")
    else:
        lines.append("No unknown required gates were detected.")
    lines.append("")
    lines.append("## Accepted skips")
    lines.append("")
    skips = gate_counts.get("acceptedSkips") if isinstance(gate_counts.get("acceptedSkips"), list) else []
    if skips:
        for gate in skips:
            lines.append(f"- `{gate.get('name')}` — `{gate.get('status')}` / `{gate.get('classification')}`: {gate.get('message')}")
    else:
        lines.append("No optional skips were recorded.")
    lines.append("")
    return "\n".join(lines)


def render_v1_release_readiness_md(report: dict[str, Any]) -> str:
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    lines = ["# v1 release readiness", ""]
    lines.append(f"- Generated: `{report.get('generatedAt')}`")
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Profile: `{report.get('profile')}`")
    lines.append(f"- Overall: `{report.get('overallStatus')}`")
    lines.append(f"- Release Confidence Score: `{report.get('score')}` / `100`")
    lines.append(f"- Effective class: `{report.get('effectiveClass')}`")
    lines.append(f"- Unknown ratio: `{report.get('unknownRatio')}`")
    lines.append(f"- Decision: `{decision.get('decision')}`")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(str(decision.get("recommendation") or "No recommendation generated."))
    lines.append("")
    beta_allowed = bool(decision.get("betaAllowed"))
    if beta_allowed:
        lines.append("This run satisfies the automated beta-candidate gate. A human reviewer should still attach known limitations and release notes before publishing.")
    else:
        lines.append("This run is not sufficient for external beta release. Use the hard caps and unknown required gates below as the next stabilization checklist.")
    lines.append("")
    lines.append("## Blocking caps")
    lines.append("")
    caps = report.get("hardCaps") if isinstance(report.get("hardCaps"), list) else []
    if caps:
        for cap in caps:
            lines.append(f"- `{cap.get('id')}` caps the result at `{cap.get('maximumClass')}`: {cap.get('reason')}")
    else:
        lines.append("- No active hard caps.")
    lines.append("")
    lines.append("## Evidence summary")
    lines.append("")
    blocks = report.get("blocks") if isinstance(report.get("blocks"), dict) else {}
    for name, block in blocks.items():
        if isinstance(block, dict):
            lines.append(f"- `{name}`: `{block.get('score')}/{block.get('maxScore')}` — {block.get('reason', '')}")
    lines.append("")
    lines.append("## Required follow-up")
    lines.append("")
    if caps:
        lines.append("1. Resolve or explicitly accept every active hard cap.")
        lines.append("2. Rerun `python tools/devbootstrap.py release-gates` with the same profile to refresh repeatability evidence.")
        lines.append("3. Use `remediation/problem-ledger.md` and `release-confidence-gate.md` as the review checklist.")
    else:
        lines.append("1. Attach known limitations and release notes.")
        lines.append("2. Preserve this bundle as release evidence.")
    lines.append("")
    return "\n".join(lines)


def write_release_gates_release_confidence_artifacts(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    report = release_gates_release_confidence_gate(project_root, result, run_dir)
    write_json(run_dir / "release-confidence-gate.json", report)
    (run_dir / "release-confidence-gate.md").write_text(render_release_gates_release_confidence_gate_md(report), encoding="utf-8")
    (run_dir / "v1-release-readiness.md").write_text(render_v1_release_readiness_md(report), encoding="utf-8")
    return report

def release_gates_current_problem_families(problem_ledger: dict[str, Any] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    problems = problem_ledger.get("problems") if isinstance(problem_ledger, dict) and isinstance(problem_ledger.get("problems"), list) else []
    for problem in problems:
        if not isinstance(problem, dict):
            continue
        family = str(problem.get("family") or release_gates_problem_family(str(problem.get("id") or "REL-UNKNOWN")))
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def release_gates_previous_problem_family_observations(project_root: Path, result: ReleaseGatesResult, limit: int = 24) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for payload in release_gates_previous_run_payloads(project_root, result.report_dir, limit=limit):
        payload_path = payload.get("_path")
        if not payload_path:
            continue
        ledger_path = project_root / str(payload_path).replace("release-gates.json", "remediation/problem-ledger.json")
        ledger = release_confidence_read_json_or_none(ledger_path)
        if not ledger:
            continue
        observations.append(
            {
                "runId": ledger.get("runId") or payload.get("runId"),
                "path": rel(ledger_path, project_root),
                "overallStatus": ledger.get("overallStatus"),
                "unresolvedBlockerCount": ledger.get("unresolvedBlockerCount"),
                "familyCounts": release_gates_current_problem_families(ledger),
            }
        )
    return observations


def release_gates_recurring_family_counts(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    current_ledger = release_confidence_read_json_or_none(run_dir / "remediation" / "problem-ledger.json") or {}
    current_counts = release_gates_current_problem_families(current_ledger)
    previous = release_gates_previous_problem_family_observations(project_root, result)
    totals: dict[str, dict[str, Any]] = {}

    def add_family(family: str, count: int, *, run_id: str | None, path: str | None, current: bool) -> None:
        if not family:
            return
        item = totals.setdefault(
            family,
            {
                "family": family,
                "currentCount": 0,
                "historicalCount": 0,
                "runCount": 0,
                "runs": [],
                "recurrenceClass": "single_run",
                "processReviewRequired": False,
            },
        )
        if current:
            item["currentCount"] = int(item.get("currentCount") or 0) + count
        else:
            item["historicalCount"] = int(item.get("historicalCount") or 0) + count
        if run_id and run_id not in item["runs"]:
            item["runs"].append(run_id)
            item["runCount"] = len(item["runs"])
        if path:
            item.setdefault("evidencePaths", [])
            if path not in item["evidencePaths"]:
                item["evidencePaths"].append(path)

    for family, count in current_counts.items():
        add_family(family, int(count), run_id=result.run_id, path=rel(run_dir / "remediation" / "problem-ledger.json", project_root), current=True)
    for observation in previous:
        for family, count in (observation.get("familyCounts") or {}).items():
            add_family(str(family), int(count), run_id=str(observation.get("runId") or ""), path=str(observation.get("path") or ""), current=False)

    recurring: list[dict[str, Any]] = []
    for item in totals.values():
        current_count = int(item.get("currentCount") or 0)
        historical_count = int(item.get("historicalCount") or 0)
        run_count = int(item.get("runCount") or 0)
        if run_count >= 3:
            item["recurrenceClass"] = "recurring_process_risk"
            item["processReviewRequired"] = True
        elif run_count >= 2:
            item["recurrenceClass"] = "repeated_signal"
        elif current_count and historical_count:
            item["recurrenceClass"] = "repeated_signal"
        else:
            item["recurrenceClass"] = "single_run"
        item["totalCount"] = current_count + historical_count
        recurring.append(item)
    recurring.sort(key=lambda item: (not item.get("processReviewRequired"), -int(item.get("runCount") or 0), str(item.get("family"))))
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "phase": "phase-7-recurring-family-counts",
        "purpose": "Track repeated REL-* failure families across release-gates history so recurring families trigger process review instead of ad-hoc fixes.",
        "currentFamilyCounts": current_counts,
        "previousRunsScanned": len(previous),
        "families": recurring,
        "processReviewFamilies": [item for item in recurring if item.get("processReviewRequired")],
        "overallStatus": "review_required" if any(item.get("processReviewRequired") for item in recurring) else "ok",
        "policy": {
            "repeatedSignalRunThreshold": 2,
            "processReviewRunThreshold": 3,
            "currentRunAlwaysIncluded": True,
        },
    }


def render_release_gates_recurring_family_counts_md(report: dict[str, Any]) -> str:
    lines = ["# release-gates recurring family counts", ""]
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Contract: `{report.get('contractVersion')}`")
    lines.append(f"- Overall: `{report.get('overallStatus')}`")
    lines.append(f"- Previous runs scanned: `{report.get('previousRunsScanned')}`")
    lines.append("")
    families = report.get("families") if isinstance(report.get("families"), list) else []
    if not families:
        lines.append("No failure families were observed in the current or scanned release-gates history.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Family | Current | Historical | Runs | Class | Process review |")
    lines.append("|---|---:|---:|---:|---|---:|")
    for item in families:
        lines.append(
            f"| `{item.get('family')}` | {item.get('currentCount')} | {item.get('historicalCount')} | {item.get('runCount')} | `{item.get('recurrenceClass')}` | {bool(item.get('processReviewRequired'))} |"
        )
    lines.append("")
    review = report.get("processReviewFamilies") if isinstance(report.get("processReviewFamilies"), list) else []
    lines.append("## Process review triggers")
    lines.append("")
    if review:
        for item in review:
            lines.append(f"- `{item.get('family')}` appeared in `{item.get('runCount')}` scanned runs; stop patching symptoms and review the process/system boundary.")
    else:
        lines.append("No family reached the process-review threshold in the scanned history.")
    lines.append("")
    return "\n".join(lines)


def release_gates_regression_memory(project_root: Path, result: ReleaseGatesResult, run_dir: Path, recurring: dict[str, Any]) -> dict[str, Any]:
    problem_ledger = release_confidence_read_json_or_none(run_dir / "remediation" / "problem-ledger.json") or {}
    probe_ledger = release_confidence_read_json_or_none(run_dir / "remediation" / "probe-ledger.json") or {}
    repeatability_loop = release_confidence_read_json_or_none(run_dir / "remediation" / "repeatability-loop.json") or {}
    confidence = release_confidence_read_json_or_none(run_dir / "release-confidence-gate.json") or {}
    completeness = release_confidence_read_json_or_none(run_dir / "artifact-completeness.json") or {}
    manifest = release_confidence_read_json_or_none(run_dir / "bundle-manifest.json") or {}
    problems = [item for item in problem_ledger.get("problems", []) if isinstance(item, dict)]
    probes = [item for item in probe_ledger.get("probes", []) if isinstance(item, dict)]
    problem_ids = {str(problem.get("id")) for problem in problems if problem.get("id")}
    probe_problem_ids = {str(probe.get("problemId")) for probe in probes if probe.get("problemId")}
    unguarded = sorted(problem_ids - probe_problem_ids)
    phase7_doc = project_root / "docs" / "development" / "release-stabilization-phase-7-regression-memory.md"
    docs_checks = [
        {"path": "docs/development/release-stabilization-program-v1.md", "exists": (project_root / "docs" / "development" / "release-stabilization-program-v1.md").is_file()},
        {"path": "docs/development/release-stabilization-problem-ledger.md", "exists": (project_root / "docs" / "development" / "release-stabilization-problem-ledger.md").is_file()},
        {"path": "docs/development/release-stabilization-phase-7-regression-memory.md", "exists": phase7_doc.is_file()},
        {"path": "docs/README.md", "exists": (project_root / "docs" / "README.md").is_file()},
    ]
    missing_docs = [item for item in docs_checks if not item.get("exists")]
    memory_checks = [
        {
            "name": "failure-updates-ledger",
            "status": "ok" if problem_ledger.get("ledgerType") == "problem-ledger" else "missing",
            "evidence": "remediation/problem-ledger.json",
            "reason": "Every classified failure/skipped gate has a durable REL-* entry for this run.",
        },
        {
            "name": "remediation-updates-probes",
            "status": "ok" if probe_ledger.get("ledgerType") == "probe-ledger" and int(probe_ledger.get("missingProblemLinkCount") or 0) == 0 else "needs-curation",
            "evidence": "remediation/probe-ledger.json",
            "reason": "Failing/skipped probes should point to stable Problem Ledger IDs.",
            "missingProblemLinkCount": probe_ledger.get("missingProblemLinkCount"),
        },
        {
            "name": "run-history-comparison",
            "status": "ok" if int(repeatability_loop.get("previousRunsScanned") or 0) > 0 else "insufficient-history",
            "evidence": "remediation/repeatability-loop.json",
            "reason": "Run history comparison prevents a single lucky run from being treated as proof.",
        },
        {
            "name": "docs-synchronized",
            "status": "ok" if not missing_docs else "missing-docs",
            "evidence": "docs/development/release-stabilization-phase-7-regression-memory.md",
            "reason": "The operating docs name the current regression-memory contract.",
            "missingDocs": missing_docs,
        },
        {
            "name": "recurring-family-counts",
            "status": "review_required" if recurring.get("processReviewFamilies") else "ok",
            "evidence": "remediation/recurring-family-counts.json",
            "reason": "Recurring REL-* families are counted separately from one-off gate failures.",
        },
        {
            "name": "artifact-shareability-memory",
            "status": "ok" if completeness.get("overallStatus") in {"ok", "pending", None} and manifest.get("contractVersion") in {RELEASE_GATES_AUTOPSY_CONTRACT_VERSION, None} else "incomplete",
            "evidence": "artifact-completeness.json / bundle-manifest.json",
            "reason": "The current bundle should carry enough context for future reviewers without terminal scrollback.",
        },
    ]
    review_required = any(item.get("status") == "review_required" for item in memory_checks)
    needs_curation = any(item.get("status") in {"missing", "needs-curation", "missing-docs", "incomplete"} for item in memory_checks)
    next_actions: list[str] = []
    if unguarded:
        next_actions.append("Map unguarded problem IDs to probes or add an explicit accepted-skip rationale before behavior-changing remediation.")
    if recurring.get("processReviewFamilies"):
        next_actions.append("Open a process review for recurring families before adding another tactical patch.")
    if not next_actions:
        next_actions.append("Use this bundle as the baseline memory for the next release-gates run.")
    return {
        "schemaVersion": 1,
        "generatedAt": iso_now(),
        "runId": result.run_id,
        "contractVersion": RELEASE_GATES_AUTOPSY_CONTRACT_VERSION,
        "phase": "phase-7-continuous-memory-regression-protection",
        "purpose": "Close the stabilization program by making every run update durable memory, probe links, docs synchronization and recurring family counts.",
        "overallStatus": "review_required" if review_required else "needs_curation" if needs_curation else "ok",
        "dryRun": result.dry_run,
        "profile": result.profile_plan.profile if result.profile_plan else None,
        "releaseConfidence": {
            "score": confidence.get("score"),
            "effectiveClass": confidence.get("effectiveClass"),
            "decision": (confidence.get("decision") or {}).get("decision") if isinstance(confidence.get("decision"), dict) else None,
        },
        "problemIds": sorted(problem_ids),
        "unguardedProblemIds": unguarded,
        "memoryChecks": memory_checks,
        "recurringFamilySummary": {
            "overallStatus": recurring.get("overallStatus"),
            "familyCount": len(recurring.get("families") or []),
            "processReviewFamilyCount": len(recurring.get("processReviewFamilies") or []),
            "previousRunsScanned": recurring.get("previousRunsScanned"),
        },
        "evidencePaths": {
            "problemLedger": "remediation/problem-ledger.json",
            "probeLedger": "remediation/probe-ledger.json",
            "repeatabilityLoop": "remediation/repeatability-loop.json",
            "releaseConfidenceGate": "release-confidence-gate.json",
            "recurringFamilyCounts": "remediation/recurring-family-counts.json",
            "artifactCompleteness": "artifact-completeness.json",
            "bundleManifest": "bundle-manifest.json",
        },
        "nextActions": next_actions,
    }


def render_release_gates_regression_memory_md(report: dict[str, Any]) -> str:
    lines = ["# release-gates regression memory", ""]
    lines.append(f"- Run ID: `{report.get('runId')}`")
    lines.append(f"- Contract: `{report.get('contractVersion')}`")
    lines.append(f"- Overall: `{report.get('overallStatus')}`")
    lines.append(f"- Profile: `{report.get('profile')}`")
    lines.append(f"- Dry run: `{report.get('dryRun')}`")
    confidence = report.get("releaseConfidence") if isinstance(report.get("releaseConfidence"), dict) else {}
    lines.append(f"- Release confidence: `{confidence.get('score')}` / `{confidence.get('effectiveClass')}` / `{confidence.get('decision')}`")
    lines.append("")
    lines.append("## Memory checks")
    lines.append("")
    lines.append("| Check | Status | Evidence | Reason |")
    lines.append("|---|---|---|---|")
    for item in report.get("memoryChecks", []):
        reason = str(item.get("reason") or "").replace("|", "\\|")
        lines.append(f"| `{item.get('name')}` | `{item.get('status')}` | `{item.get('evidence')}` | {reason} |")
    lines.append("")
    lines.append("## Unguarded problem IDs")
    lines.append("")
    unguarded = report.get("unguardedProblemIds") if isinstance(report.get("unguardedProblemIds"), list) else []
    if unguarded:
        for problem_id in unguarded:
            lines.append(f"- `{problem_id}`")
    else:
        lines.append("All current problem IDs are linked from the probe ledger or no current problems were detected.")
    lines.append("")
    lines.append("## Recurring family summary")
    lines.append("")
    recurring = report.get("recurringFamilySummary") if isinstance(report.get("recurringFamilySummary"), dict) else {}
    lines.append(f"- Overall: `{recurring.get('overallStatus')}`")
    lines.append(f"- Families: `{recurring.get('familyCount')}`")
    lines.append(f"- Process-review families: `{recurring.get('processReviewFamilyCount')}`")
    lines.append(f"- Previous runs scanned: `{recurring.get('previousRunsScanned')}`")
    lines.append("")
    lines.append("## Next actions")
    lines.append("")
    for action in report.get("nextActions", []):
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_release_gates_phase7_artifacts(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> dict[str, Any]:
    remediation_dir = run_dir / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)
    recurring = release_gates_recurring_family_counts(project_root, result, run_dir)
    write_json(remediation_dir / "recurring-family-counts.json", recurring)
    (remediation_dir / "recurring-family-counts.md").write_text(render_release_gates_recurring_family_counts_md(recurring), encoding="utf-8")
    memory = release_gates_regression_memory(project_root, result, run_dir, recurring)
    write_json(remediation_dir / "regression-memory.json", memory)
    (remediation_dir / "regression-memory.md").write_text(render_release_gates_regression_memory_md(memory), encoding="utf-8")
    return memory


def write_release_gates_remediation_bundle(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> None:
    remediation_dir = run_dir / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)
    result.remediation_bundle_path = rel(remediation_dir, project_root)
    ledger = release_gates_build_ledger(result)
    blockers = release_gates_infrastructure_blockers(result)
    unverified = release_gates_unverified_areas(result)
    rerun_commands = release_gates_rerun_commands(result, blockers)
    fingerprint = release_gates_environment_fingerprint(project_root, result)
    problem_ledger = release_gates_problem_ledger(result, rerun_commands)
    probe_ledger = release_gates_probe_ledger(result)
    decision_template = release_gates_decision_ledger_template(result, problem_ledger)
    provocation_matrix = release_gates_provocation_matrix(project_root, result)
    controlled_mutators = release_gates_controlled_mutators(project_root, result)
    repeatability_loop = release_gates_repeatability_loop(project_root, result)

    write_json(remediation_dir / "gate-ledger.json", ledger)
    (remediation_dir / "gate-ledger.md").write_text(render_release_gates_gate_ledger_md(ledger), encoding="utf-8")
    write_json(remediation_dir / "problem-ledger.json", problem_ledger)
    (remediation_dir / "problem-ledger.md").write_text(render_release_gates_problem_ledger_md(problem_ledger), encoding="utf-8")
    write_json(remediation_dir / "probe-ledger.json", probe_ledger)
    (remediation_dir / "probe-ledger.md").write_text(render_release_gates_probe_ledger_md(probe_ledger), encoding="utf-8")
    write_json(remediation_dir / "decision-ledger-template.json", decision_template)
    (remediation_dir / "decision-ledger-template.md").write_text(render_release_gates_decision_ledger_template_md(decision_template), encoding="utf-8")
    write_json(remediation_dir / "provocation-matrix.json", provocation_matrix)
    (remediation_dir / "provocation-matrix.md").write_text(render_release_gates_provocation_matrix_md(provocation_matrix), encoding="utf-8")
    write_json(remediation_dir / "controlled-mutators.json", controlled_mutators)
    (remediation_dir / "controlled-mutators.md").write_text(render_release_gates_controlled_mutators_md(controlled_mutators), encoding="utf-8")
    write_json(remediation_dir / "repeatability-loop.json", repeatability_loop)
    (remediation_dir / "repeatability-loop.md").write_text(render_release_gates_repeatability_loop_md(repeatability_loop), encoding="utf-8")
    (remediation_dir / "prerequisites.md").write_text(render_release_gates_prerequisites_md(result, blockers), encoding="utf-8")
    (remediation_dir / "skipped-gates.md").write_text(render_release_gates_skipped_gates_md(unverified), encoding="utf-8")
    (remediation_dir / "next-actions.md").write_text(render_release_gates_next_actions_md(result), encoding="utf-8")
    (remediation_dir / "rerun-commands.md").write_text(render_release_gates_rerun_commands_md(rerun_commands), encoding="utf-8")
    write_json(remediation_dir / "environment-fingerprint.json", fingerprint)

def render_release_gates_summary(result: ReleaseGatesResult) -> str:
    lines: list[str] = []
    lines.append("# release-gates summary")
    lines.append("")
    lines.append(f"Overall: {result.overall_status}")
    lines.append(f"Classification: {result.classification}")
    lines.append(f"Generated: {result.generated_at}")
    lines.append(f"Dry run: {result.dry_run}")
    if result.profile_plan:
        lines.append(f"Profile: {result.profile_plan.profile} (explicit={result.profile_plan.explicit_profile})")
        lines.append(f"Consent plan: {result.profile_plan.consent_summary_path or '<not written>'}")
    lines.append(f"Project root: {result.project_root or 'not found'}")
    if result.managed_test_db and result.managed_test_db.enabled:
        lines.append(f"Managed test DB: {result.managed_test_db.status} / {result.managed_test_db.classification}")
        lines.append(f"Managed DB name: {result.managed_test_db.database_name or '<none>'}")
        lines.append(f"Managed DB URL: {result.managed_test_db.masked_database_url or '<none>'}")
        lines.append(f"Managed DB retention: {result.managed_test_db.retention}; retained={result.managed_test_db.retained}")
        lines.append(f"Managed DB cleanup: {result.managed_test_db.cleanup_command or '<none>'}")
    if result.managed_runtime and result.managed_runtime.enabled:
        lines.append(f"Managed runtime: {result.managed_runtime.status} / {result.managed_runtime.classification}")
        lines.append(f"Managed backend: {result.managed_runtime.backend_api_base_url or '<none>'}")
        lines.append(f"Managed frontend: {result.managed_runtime.frontend_url or '<none>'}")
        lines.append(f"Managed runtime state: {result.managed_runtime.runtime_state_path or '<none>'}")
    lines.append(f"Report dir: {result.report_dir or '<not written>'}")
    lines.append(f"Remediation bundle: {result.remediation_bundle_path or '<not written>'}")
    if result.archive_path:
        lines.append(f"Archive: {result.archive_path}")
    lines.append("")
    for gate in result.gates:
        lines.append(f"> {release_gate_command_display(gate.command) if gate.command else gate.name}")
        lines.append(f"status: {gate.status}")
        lines.append(f"classification: {gate.classification}")
        lines.append(f"reason: {gate.message}")
        if gate.log_path:
            lines.append(f"log: {gate.log_path}")
        lines.append("")
    return "\n".join(lines)


def render_release_gates_report(result: ReleaseGatesResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap release-gates report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Overall status: `{result.overall_status}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    if result.archive_path:
        lines.append(f"- Archive: `{result.archive_path}`")
    if getattr(result, "remediation_bundle_path", None):
        lines.append("- Remediation bundle: `" + result.remediation_bundle_path + "`")
    autopsy_paths = release_gates_autopsy_bundle_paths(result)
    if autopsy_paths:
        lines.append("- Bundle manifest: `" + autopsy_paths["manifestPath"] + "`")
        lines.append("- Artifact completeness: `" + autopsy_paths["artifactCompletenessPath"] + "`")
        lines.append("- Command resolution: `" + autopsy_paths["commandResolutionPath"] + "`")
        lines.append("- Redaction report: `" + autopsy_paths["redactionReportPath"] + "`")
    if result.profile_plan:
        lines.append("")
        lines.append("## Profile and consent")
        lines.append("")
        lines.append(f"- Profile: `{result.profile_plan.profile}`")
        lines.append(f"- Explicit profile: `{result.profile_plan.explicit_profile}`")
        lines.append(f"- Consent summary: `{result.profile_plan.consent_summary_path or '<none>'}`")
        lines.append(f"- Description: {result.profile_plan.description}")
        lines.append("- Allowed scoped side effects: " + (", ".join(f"`{item['category']}`" for item in result.profile_plan.allowed_side_effects) if result.profile_plan.allowed_side_effects else "none"))
        lines.append("- Denied unscoped side effects: " + ", ".join(f"`{item['category']}`" for item in result.profile_plan.denied_side_effects))
    if result.managed_test_db and result.managed_test_db.enabled:
        lines.append("")
        lines.append("## Managed test database")
        lines.append("")
        lines.append(f"- Status: `{result.managed_test_db.status}`")
        lines.append(f"- Classification: `{result.managed_test_db.classification}`")
        lines.append(f"- Database: `{result.managed_test_db.database_name or '<none>'}`")
        lines.append(f"- URL: `{result.managed_test_db.masked_database_url or '<none>'}`")
        lines.append(f"- Retention: `{result.managed_test_db.retention}`")
        lines.append(f"- Retained: `{result.managed_test_db.retained}`")
        lines.append(f"- Metadata: `{result.managed_test_db.metadata_path or '<none>'}`")
        lines.append(f"- Cleanup: `{result.managed_test_db.cleanup_command or '<none>'}`")
    if result.managed_runtime and result.managed_runtime.enabled:
        lines.append("")
        lines.append("## Managed runtime")
        lines.append("")
        lines.append(f"- Status: `{result.managed_runtime.status}`")
        lines.append(f"- Classification: `{result.managed_runtime.classification}`")
        lines.append(f"- Backend API: `{result.managed_runtime.backend_api_base_url or '<none>'}`")
        lines.append(f"- Backend health: `{result.managed_runtime.backend_health_url or '<none>'}`")
        lines.append(f"- Frontend: `{result.managed_runtime.frontend_url or '<none>'}`")
        lines.append(f"- Backend PID: `{result.managed_runtime.backend_pid or '<none>'}`")
        lines.append(f"- Frontend PID: `{result.managed_runtime.frontend_pid or '<none>'}`")
        lines.append(f"- Runtime state: `{result.managed_runtime.runtime_state_path or '<none>'}`")
        lines.append(f"- Env diff: `{result.managed_runtime.env_diff_path or '<none>'}`")
        lines.append(f"- Managed URLs: `{result.managed_runtime.managed_urls_path or '<none>'}`")
    lines.append("")
    lines.append("## Gates")
    lines.append("")
    lines.append("| Gate | Status | Classification | Command | Log |")
    lines.append("|---|---|---|---|---|")
    for gate in result.gates:
        command = release_gate_command_display(gate.command) if gate.command else gate.name
        log = f"`{gate.log_path}`" if gate.log_path else ""
        lines.append(f"| `{gate.name}` | {gate.status} | `{gate.classification}` | `{command}` | {log} |")
    lines.append("")
    if result.remediation_bundle_path:
        lines.append("## Diagnostic remediation bundle")
        lines.append("")
        lines.append(f"- Bundle directory: `{result.remediation_bundle_path}`")
        lines.append("- Gate ledger: `remediation/gate-ledger.md` / `remediation/gate-ledger.json`")
        lines.append("- Problem ledger: `remediation/problem-ledger.md` / `remediation/problem-ledger.json`")
        lines.append("- Probe ledger: `remediation/probe-ledger.md` / `remediation/probe-ledger.json`")
        lines.append("- Decision ledger template: `remediation/decision-ledger-template.md` / `remediation/decision-ledger-template.json`")
        lines.append("- Diagnostic provocation matrix: `remediation/provocation-matrix.md` / `remediation/provocation-matrix.json`")
        lines.append("- Controlled mutators ledger: `remediation/controlled-mutators.md` / `remediation/controlled-mutators.json`")
        lines.append("- Repeatability loop: `remediation/repeatability-loop.md` / `remediation/repeatability-loop.json`")
        lines.append("- Prerequisites: `remediation/prerequisites.md`")
        lines.append("- Skipped gates: `remediation/skipped-gates.md`")
        lines.append("- Next actions: `remediation/next-actions.md`")
        lines.append("- Rerun commands: `remediation/rerun-commands.md`")
        lines.append("- Environment fingerprint: `remediation/environment-fingerprint.json`")
        lines.append("")
    autopsy_paths = release_gates_autopsy_bundle_paths(result)
    if autopsy_paths:
        lines.append("## Release-gates autopsy bundle contract")
        lines.append("")
        lines.append("- Manifest: `bundle-manifest.json`")
        lines.append("- Artifact completeness: `artifact-completeness.json` / `artifact-completeness.md`")
        lines.append("- Environment fingerprint: `environment-fingerprint.json`")
        lines.append("- Command resolution: `command-resolution.json` / `command-resolution.md`")
        lines.append("- Redaction report: `redaction-report.json` / `redaction-report.md`")
        lines.append("- Ledgers: `remediation/problem-ledger.*`, `remediation/probe-ledger.*`, `remediation/decision-ledger-template.*`")
        lines.append("- Provocation matrix: `remediation/provocation-matrix.*`")
        lines.append("- Controlled mutators: `remediation/controlled-mutators.*`")
        lines.append("- Repeatability loop: `remediation/repeatability-loop.*`")
        lines.append("")
    lines.append("## Findings")
    lines.append("")
    if result.findings:
        for finding in result.findings:
            lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}` — {finding['message']}")
    else:
        lines.append("- No blocking findings from configured release-gates.")
    lines.append("")
    lines.append("## Next safe actions")
    lines.append("")
    for action in result.next_actions:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def release_gates_json_payload(result: ReleaseGatesResult) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "command": "release-gates",
        "toolVersion": result.tool_version,
        "generatedAt": result.generated_at,
        "projectRoot": result.project_root,
        "invokedFrom": result.invoked_from,
        "runId": result.run_id,
        "dryRun": result.dry_run,
        "timeoutSeconds": result.timeout_seconds,
        "overallStatus": result.overall_status,
        "classification": result.classification,
        "reportDir": result.report_dir,
        "archivePath": result.archive_path,
        "remediationBundlePath": result.remediation_bundle_path,
        "autopsyBundle": release_gates_autopsy_bundle_paths(result),
        "profilePlan": as_jsonable(result.profile_plan) if result.profile_plan else None,
        "managedTestDb": managed_test_db_public_payload(result.managed_test_db) if result.managed_test_db else None,
        "managedRuntime": managed_runtime_public_payload(result.managed_runtime) if result.managed_runtime else None,
        "gates": [as_jsonable(gate) for gate in result.gates],
        "findings": result.findings,
        "nextActions": result.next_actions,
    }


def release_gates_archive_excluded(path: Path, root: Path, archive_path: Path) -> bool:
    if path == archive_path:
        return True
    if path.suffix == ".zip" and path.name.startswith("release-gates_"):
        return True
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    if any(part in RELEASE_GATES_ARCHIVE_EXCLUDED_PARTS for part in relative.parts):
        return True
    if path.name in RELEASE_GATES_ARCHIVE_EXCLUDED_NAMES:
        return True
    if path.name.startswith(".env."):
        return True
    if path.suffix in RELEASE_GATES_ARCHIVE_EXCLUDED_SUFFIXES:
        return True
    return False


def create_release_gates_archive(run_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(run_dir.rglob("*")):
            if path.is_dir() or release_gates_archive_excluded(path, run_dir, archive_path):
                continue
            zf.write(path, path.relative_to(run_dir).as_posix())


def write_release_gates_reports(project_root: Path, result: ReleaseGatesResult, run_dir: Path) -> None:
    result.report_dir = rel(run_dir, project_root)
    timestamp = now_utc().strftime("%Y%m%d_%H%M%S")
    archive_path = run_dir / f"release-gates_{timestamp}.zip"
    result.archive_path = rel(archive_path, project_root)
    write_release_gates_remediation_bundle(project_root, result, run_dir)

    environment_fingerprint = release_gates_environment_fingerprint(project_root, result)
    write_json(run_dir / "environment-fingerprint.json", environment_fingerprint)

    command_resolution = release_gates_command_resolution_report(project_root, result)
    write_json(run_dir / "command-resolution.json", command_resolution)
    (run_dir / "command-resolution.md").write_text(render_release_gates_command_resolution_md(command_resolution), encoding="utf-8")

    (run_dir / "summary.txt").write_text(render_release_gates_summary(result), encoding="utf-8")
    (run_dir / "release-gates.md").write_text(render_release_gates_report(result), encoding="utf-8")
    write_json(run_dir / "release-gates.json", release_gates_json_payload(result))

    redaction = release_gates_redaction_report(project_root, result, run_dir)
    write_json(run_dir / "redaction-report.json", redaction)
    (run_dir / "redaction-report.md").write_text(render_release_gates_redaction_report_md(redaction), encoding="utf-8")

    # Phase 6/7 readiness is written before completeness so the completeness
    # check can require those artifacts, then rewritten after completeness and
    # manifest exist so the final archive carries the strongest available signal.
    write_release_gates_release_confidence_artifacts(project_root, result, run_dir)
    write_release_gates_phase7_artifacts(project_root, result, run_dir)
    manifest = release_gates_bundle_manifest(project_root, result, run_dir)
    write_json(run_dir / "bundle-manifest.json", manifest)
    completeness = release_gates_artifact_completeness(project_root, result, run_dir)
    write_json(run_dir / "artifact-completeness.json", completeness)
    (run_dir / "artifact-completeness.md").write_text(render_release_gates_artifact_completeness_md(completeness), encoding="utf-8")
    write_release_gates_release_confidence_artifacts(project_root, result, run_dir)
    write_release_gates_phase7_artifacts(project_root, result, run_dir)
    # Re-write the manifest after the completeness and Phase 7 artifacts exist,
    # so a bundle opened from the archive names every final artifact.
    manifest = release_gates_bundle_manifest(project_root, result, run_dir)
    write_json(run_dir / "bundle-manifest.json", manifest)

    create_release_gates_archive(run_dir, archive_path)
    append_report_to_state(project_root, run_dir, result.run_id)


def print_release_gates_summary(result: ReleaseGatesResult) -> None:
    print_header("devbootstrap release-gates")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Overall: {result.overall_status}")
    print(f"Classification: {result.classification}")
    print(f"Dry run: {result.dry_run}")
    if result.profile_plan:
        print(f"Profile: {result.profile_plan.profile} (explicit={result.profile_plan.explicit_profile})")
        print(f"Consent plan: {result.profile_plan.consent_summary_path or '<not written>'}")
    if result.remediation_bundle_path:
        print(f"Remediation: {result.remediation_bundle_path}")
    if result.managed_runtime and result.managed_runtime.enabled:
        print("\nManaged runtime:")
        print(f"  - backend: {result.managed_runtime.backend_api_base_url or '<none>'}")
        print(f"  - frontend: {result.managed_runtime.frontend_url or '<none>'}")
        print(f"  - state: {result.managed_runtime.runtime_state_path or '<not written>'}")
    print("\nGates:")
    for gate in result.gates:
        suffix = f" — {gate.log_path}" if gate.log_path else ""
        print(f"  - {gate.status.upper()} {gate.name}: {gate.message}{suffix}")
    if result.findings:
        print("\nFindings:")
        for finding in result.findings:
            print(f"  - {finding['severity'].upper()} {finding['code']}: {finding['message']}")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/release-gates.md")
    if result.archive_path:
        print(f"Archive: {result.archive_path}")


def command_release_gates(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    run_id_value = run_id("release-gates")
    result = ReleaseGatesResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        run_id=run_id_value,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
    )
    if project_root is None:
        result.overall_status = "failed"
        result.classification = "invalid_project_root"
        result.findings.append({"severity": "fail", "code": "invalid_project_root", "message": "Could not find project root."})
        result.next_actions.append("Run this command from the project root, tools/, backend/ or frontend/ directory.")
        print_release_gates_summary(result)
        if args.json:
            print("\nJSON:")
            print(json.dumps(release_gates_json_payload(result), ensure_ascii=False, indent=2))
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = project_root / output_dir
        run_dir = output_dir
        run_id_value = run_dir.name
        result.run_id = run_id_value
    else:
        run_dir = project_root / BOOTSTRAP_DIR_NAME / "runs" / run_id_value
    logs_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    profile_plan = resolve_release_gates_profile_args(args)
    result.profile_plan = profile_plan
    write_release_gates_profile_plan(project_root, run_dir, profile_plan)
    if args.dry_run or profile_plan.explicit_profile:
        print_release_gates_profile_consent(profile_plan)

    next_gate_index = 1
    managed_test_db_url: str | None = None
    if args.managed_test_db:
        managed_state = build_release_gates_managed_test_database(
            project_root,
            run_dir,
            run_id_value=run_id_value,
            retention=args.test_db_retention,
            dry_run=args.dry_run,
            start_db_if_needed=args.start_db_if_needed,
            test_db_admin_user=args.test_db_admin_user,
            test_db_admin_password=args.test_db_admin_password,
            test_db_admin_password_env=args.test_db_admin_password_env,
            test_db_maintenance_db=args.test_db_maintenance_db,
        )
        result.managed_test_db = managed_state
        result.gates.append(release_gates_managed_db_prepare_result(project_root, logs_dir, next_gate_index, managed_state))
        next_gate_index += 1
        if managed_state.database_url and managed_state.status in {"ok", "planned"}:
            managed_test_db_url = managed_state.database_url

    effective_managed_runtime = bool(args.managed_runtime or args.managed_test_db)
    managed_runtime_state: ManagedRuntimeState | None = None
    managed_runtime_db_url: str | None = None
    managed_runtime_db_reason: str | None = None
    if effective_managed_runtime:
        managed_runtime_state = build_managed_runtime_state(project_root, run_dir, run_id_value)
        result.managed_runtime = managed_runtime_state
        managed_runtime_db_url, managed_runtime_db_reason = release_gate_managed_runtime_database_url(
            project_root,
            managed_test_db_url=managed_test_db_url,
            allow_dev_db_write=args.allow_dev_db_write,
        )
        managed_runtime_state.database_source = managed_runtime_db_reason
        if managed_runtime_db_url:
            managed_runtime_state.masked_database_url = mask_database_url(managed_runtime_db_url)
        if args.dry_run:
            result.gates.append(release_gates_managed_runtime_plan_result(project_root, logs_dir, next_gate_index, managed_runtime_state))
            next_gate_index += 1
        elif not managed_runtime_db_url:
            result.gates.append(
                release_gates_managed_runtime_db_unavailable_result(
                    project_root,
                    logs_dir,
                    next_gate_index,
                    managed_runtime_state,
                    managed_runtime_db_reason or "managed runtime database target is unavailable",
                )
            )
            next_gate_index += 1

    frontend_prepare_blocker: GateResult | None = None
    if args.prepare_deps is not None:
        prepare_deps_mode = normalize_frontend_prepare_dep_mode(args.prepare_deps)
    elif args.prepare_frontend:
        prepare_deps_mode = DEFAULT_FRONTEND_PREPARE_DEP_MODE
    else:
        prepare_deps_mode = "never"
    if prepare_deps_mode != "never":
        prepare_spec = GateSpec(
            name="frontend_prepare_dependencies",
            cwd=".",
            command=[
                sys.executable,
                "tools/devbootstrap.py",
                "prepare-frontend",
                f"--install-mode={prepare_deps_mode}",
                "--no-write-report",
            ],
            description="Install or verify frontend npm dependencies before building release-gates frontend specs.",
            timeout_seconds=TIMEOUT_POLICY["npm_install"],
            details={"prepareDepsMode": prepare_deps_mode, "compatPrepareFrontendFlag": bool(args.prepare_frontend)},
        )
        effective_timeout = min(args.timeout_seconds, prepare_spec.timeout_seconds) if args.timeout_seconds > 0 else prepare_spec.timeout_seconds
        prepare_gate = run_gate_process_step(
            project_root=project_root,
            logs_dir=logs_dir,
            index=next_gate_index,
            spec=prepare_spec,
            timeout_seconds=effective_timeout,
            dry_run=args.dry_run,
        )
        result.gates.append(prepare_gate)
        if prepare_gate.status not in {"ok", "planned"}:
            frontend_prepare_blocker = prepare_gate
        next_gate_index += 1

        backend_warmup_spec = GateSpec(
            name="backend_dependency_warmup",
            cwd="backend",
            command=["cargo", "test", "--no-run"],
            description="Warm backend Cargo dependencies/build artifacts to separate dependency or compile failures from test failures.",
            timeout_seconds=900,
            details={"prepareDepsMode": prepare_deps_mode},
        )
        effective_timeout = min(args.timeout_seconds, backend_warmup_spec.timeout_seconds) if args.timeout_seconds > 0 else backend_warmup_spec.timeout_seconds
        result.gates.append(
            run_gate_process_step(
                project_root=project_root,
                logs_dir=logs_dir,
                index=next_gate_index,
                spec=backend_warmup_spec,
                timeout_seconds=effective_timeout,
                dry_run=args.dry_run,
            )
        )
        next_gate_index += 1

    specs = build_release_gate_specs(
        project_root,
        allow_dev_db_write=args.allow_dev_db_write,
        install_playwright_browsers=args.install_playwright_browsers,
        include_real_backend_browser=args.include_real_backend_browser,
        real_backend_browser_spec=args.real_backend_browser_spec,
        include_clean_machine=args.include_clean_machine,
        clean_machine_profile=args.clean_machine_profile,
        clean_machine_retention=args.clean_machine_retention,
        dry_run=args.dry_run,
        managed_test_db_url=managed_test_db_url,
        managed_test_db_requested=args.managed_test_db,
        managed_runtime_requested=effective_managed_runtime,
        managed_backend_api_base_url=managed_runtime_state.backend_api_base_url if managed_runtime_state else None,
        managed_frontend_url=managed_runtime_state.frontend_url if managed_runtime_state else None,
        managed_frontend_host=managed_runtime_state.frontend_host if managed_runtime_state else None,
        managed_frontend_port=managed_runtime_state.frontend_port if managed_runtime_state else None,
        smoke_run_id=run_id_value,
    )

    for spec in specs:
        if spec.internal_check == "clean_machine_sandbox":
            spec.details.setdefault("runId", run_id_value)

    managed_backend: ReleaseGatesManagedRuntimeProcess | None = None
    managed_frontend: ReleaseGatesManagedRuntimeProcess | None = None
    managed_backend_start_failed: str | None = None
    managed_frontend_start_failed: str | None = None
    managed_backend_gate_names = RELEASE_GATES_MANAGED_BACKEND_GATE_NAMES
    managed_frontend_gate_names = RELEASE_GATES_MANAGED_FRONTEND_GATE_NAMES
    frontend_prepare_downstream_gate_names = {
        "frontend_build",
        "frontend_unit_integration",
        "frontend_browser_smoke",
        "frontend_uiux_boot",
        "frontend_uiux_mocked_core_flow",
        "frontend_uiux_real_backend_core_flow",
        "playwright_install",
        "browser_real_backend_path",
    }

    for spec in specs:
        if (
            frontend_prepare_blocker is not None
            and spec.name in frontend_prepare_downstream_gate_names
            and not args.dry_run
            and not spec.not_implemented_reason
        ):
            result.gates.append(release_gates_skip_for_frontend_prepare_failed(project_root, logs_dir, next_gate_index, spec, frontend_prepare_blocker))
            next_gate_index += 1
            continue
        requires_managed_runtime = effective_managed_runtime and spec.name in managed_backend_gate_names and not args.dry_run and not spec.skip_reason and not spec.not_implemented_reason
        if requires_managed_runtime:
            if not managed_runtime_state or not managed_runtime_db_url:
                result.gates.append(
                    release_gates_skip_for_managed_runtime_unavailable(project_root, logs_dir, next_gate_index, spec, managed_runtime_db_reason or "managed runtime database target is unavailable")
                )
                next_gate_index += 1
                continue
            if managed_backend is None and managed_backend_start_failed is None:
                start_timeout = min(args.timeout_seconds, TIMEOUT_POLICY["backend_ready"]) if args.timeout_seconds > 0 else TIMEOUT_POLICY["backend_ready"]
                start_gate, managed_backend = start_release_gates_managed_backend(
                    project_root,
                    logs_dir,
                    next_gate_index,
                    managed_runtime_state,
                    managed_runtime_db_url,
                    start_timeout,
                )
                result.gates.append(start_gate)
                next_gate_index += 1
                if managed_backend is None:
                    managed_backend_start_failed = start_gate.classification
            if managed_backend_start_failed:
                result.gates.append(
                    release_gates_skip_for_managed_runtime_unavailable(project_root, logs_dir, next_gate_index, spec, managed_backend_start_failed)
                )
                next_gate_index += 1
                continue
            if spec.name in managed_frontend_gate_names and managed_frontend is None and managed_frontend_start_failed is None:
                frontend_timeout = min(args.timeout_seconds, TIMEOUT_POLICY["frontend_ready"]) if args.timeout_seconds > 0 else TIMEOUT_POLICY["frontend_ready"]
                start_gate, managed_frontend = start_release_gates_managed_frontend(
                    project_root,
                    logs_dir,
                    next_gate_index,
                    managed_runtime_state,
                    frontend_timeout,
                )
                result.gates.append(start_gate)
                next_gate_index += 1
                if managed_frontend is None:
                    managed_frontend_start_failed = start_gate.classification
            if spec.name in managed_frontend_gate_names and managed_frontend_start_failed:
                result.gates.append(
                    release_gates_skip_for_managed_runtime_unavailable(project_root, logs_dir, next_gate_index, spec, managed_frontend_start_failed)
                )
                next_gate_index += 1
                continue

        effective_timeout = min(args.timeout_seconds, spec.timeout_seconds) if args.timeout_seconds > 0 else spec.timeout_seconds
        result.gates.append(
            run_gate_process_step(
                project_root=project_root,
                logs_dir=logs_dir,
                index=next_gate_index,
                spec=spec,
                timeout_seconds=effective_timeout,
                dry_run=args.dry_run,
            )
        )
        next_gate_index += 1

    if managed_frontend is not None:
        result.gates.append(stop_release_gates_managed_process(project_root, logs_dir, next_gate_index, managed_frontend))
        next_gate_index += 1
    if managed_backend is not None:
        result.gates.append(stop_release_gates_managed_process(project_root, logs_dir, next_gate_index, managed_backend))
        next_gate_index += 1
    if managed_runtime_state is not None:
        if not args.dry_run:
            managed_runtime_state.stopped_at = iso_now()
            if managed_runtime_state.classification in {"managed_frontend_started", "managed_backend_started", "managed_frontend_stopped", "managed_backend_stopped"}:
                managed_runtime_state.status = "stopped"
                managed_runtime_state.classification = "managed_runtime_stopped"
                managed_runtime_state.message = "managed runtime was stopped after release-gates"
        write_release_gates_runtime_files(project_root, logs_dir, managed_runtime_state)

    finalize_release_gates_result(result)

    if result.managed_test_db is not None:
        retention_gate = finalize_release_gates_managed_test_database(
            project_root,
            logs_dir,
            next_gate_index,
            result.managed_test_db,
            release_succeeded=result.overall_status == "ok",
            dump_on_failure=args.dump_test_db_on_failure,
        )
        result.gates.append(retention_gate)
        finalize_release_gates_result(result)

    write_release_gates_reports(project_root, result, run_dir)
    print_release_gates_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(release_gates_json_payload(result), ensure_ascii=False, indent=2))
    return 1 if result.overall_status not in {"ok", "dry_run"} else 0


def stop_target_from_entry(project_root: Path, name: str, entry: dict[str, Any]) -> StopTarget:
    pid_value = entry.get("pid")
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        pid = None
    target = StopTarget(
        name=name,
        pid=pid,
        cwd=entry.get("cwd") if isinstance(entry.get("cwd"), str) else None,
        command=entry.get("command") if isinstance(entry.get("command"), str) else None,
        log_path=entry.get("logPath") if isinstance(entry.get("logPath"), str) else None,
        run_id=entry.get("runId") if isinstance(entry.get("runId"), str) else None,
        alive_before=pid_alive(pid or -1),
    )
    verify_stop_target(project_root, target)
    return target


def expected_process_cwd(project_root: Path, name: str) -> Path | None:
    if name == "backend":
        return (project_root / "backend").resolve()
    if name == "frontend":
        return (project_root / "frontend").resolve()
    return None


def verify_stop_target(project_root: Path, target: StopTarget) -> None:
    if target.name not in {"backend", "frontend"}:
        target.verification_status = "unsupported_process"
        target.verification_evidence = "devbootstrap only stops tracked backend/frontend processes"
        return
    if target.pid is None or target.pid <= 0:
        target.verification_status = "invalid_pid"
        target.verification_evidence = f"stored pid is invalid: {target.pid!r}"
        return
    if not target.alive_before:
        target.verification_status = "stale_pid"
        target.verification_evidence = "stored pid is not alive"
        return
    expected_cwd = expected_process_cwd(project_root, target.name)
    stored_cwd = ((project_root / target.cwd).resolve() if target.cwd else None)
    expected_word = "cargo" if target.name == "backend" else "npm"
    stored_command_ok = bool(target.command and expected_word in target.command.lower())
    stored_cwd_ok = bool(stored_cwd and expected_cwd and stored_cwd == expected_cwd)
    if os.name != "nt" and (Path("/proc") / str(target.pid)).exists():
        actual_cwd, actual_cmd, detail_error = procfs_process_details(target.pid)
        actual_cwd_ok = bool(actual_cwd and expected_cwd and Path(actual_cwd).resolve() == expected_cwd)
        actual_cmd_text = (actual_cmd or "").lower()
        command_hint_ok = expected_word in actual_cmd_text or stored_command_ok
        evidence_parts = [f"expected_cwd={expected_cwd}"]
        if actual_cwd:
            evidence_parts.append(f"actual_cwd={actual_cwd}")
        if actual_cmd:
            evidence_parts.append(f"actual_cmd={actual_cmd[:240]}")
        if detail_error:
            evidence_parts.append(detail_error)
        target.verification_evidence = "; ".join(evidence_parts)
        if actual_cwd_ok and command_hint_ok:
            target.verification_status = "owned"
        elif actual_cwd is None and command_hint_ok and stored_cwd_ok:
            target.verification_status = "owned_limited"
            target.verification_evidence += "; procfs cwd unavailable, fell back to state cwd plus process command hint"
        else:
            target.verification_status = "mismatch"
        return
    if stored_cwd_ok and stored_command_ok:
        target.verification_status = "owned_limited"
        target.verification_evidence = "procfs command/cwd verification is unavailable; using state cwd+command guard"
    else:
        target.verification_status = "mismatch"
        target.verification_evidence = f"stored cwd/command do not match expected {target.name} process"


def send_signal_to_owned_process(pid: int, sig: int) -> None:
    if os.name != "nt":
        try:
            os.killpg(pid, sig)
            return
        except ProcessLookupError:
            return
        except OSError:
            # Older devbootstrap runs did not necessarily create a process group.
            pass
    os.kill(pid, sig)


def wait_until_dead(pid: int, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + max(0, timeout_seconds)
    while time.monotonic() <= deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.25)
    return not pid_alive(pid)


def stop_owned_target(target: StopTarget, *, timeout_seconds: int, dry_run: bool, force: bool) -> None:
    if target.verification_status == "stale_pid":
        target.action = "stale_removed"
        target.alive_after = False
        return
    if target.verification_status not in {"owned", "owned_limited"}:
        target.action = "skipped"
        target.alive_after = target.alive_before
        target.error = "process did not pass ownership verification"
        return
    if target.pid is None:
        target.action = "skipped"
        target.error = "invalid pid"
        return
    if dry_run:
        target.action = "planned_stop"
        target.alive_after = target.alive_before
        return
    try:
        send_signal_to_owned_process(target.pid, signal.SIGTERM)
    except ProcessLookupError:
        target.action = "stale_removed"
        target.alive_after = False
        return
    except OSError as exc:
        target.action = "failed"
        target.error = f"SIGTERM failed: {exc}"
        target.alive_after = pid_alive(target.pid)
        return
    if wait_until_dead(target.pid, timeout_seconds):
        target.action = "stopped"
        target.alive_after = False
        return
    if not force:
        target.action = "timeout"
        target.alive_after = pid_alive(target.pid)
        target.error = "process did not exit before timeout; force kill disabled"
        return
    kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        send_signal_to_owned_process(target.pid, kill_signal)
    except ProcessLookupError:
        target.action = "stale_removed"
        target.alive_after = False
        return
    except OSError as exc:
        target.action = "failed"
        target.error = f"force kill failed: {exc}"
        target.alive_after = pid_alive(target.pid)
        return
    if wait_until_dead(target.pid, min(5, max(1, timeout_seconds))):
        target.action = "force_stopped"
        target.alive_after = False
    else:
        target.action = "failed"
        target.alive_after = pid_alive(target.pid)
        target.error = "process still alive after force kill"


def stop_compose_postgres(project_root: Path, *, include_db: bool, dry_run: bool, timeout_seconds: int) -> StopDbAction:
    if not include_db:
        return StopDbAction(status="skipped", message="PostgreSQL compose service is left running by default; pass --include-db to stop it.")
    compose_command, detection = detect_compose_command(project_root)
    if not process_probe_ok(detection):
        return StopDbAction(status="unavailable", message="Docker Compose is not available, so devbootstrap cannot stop postgres service.", evidence=first_output_line(detection))
    command = compose_base_command(compose_command, project_root) + ["stop", POSTGRES_SERVICE_NAME]
    if dry_run:
        return StopDbAction(status="planned", command=command_as_text(command), message="Would stop docker compose postgres service without removing volumes.")
    probe = run_process_probe("compose_stop_postgres", command, cwd=project_root, timeout=max(10, timeout_seconds))
    status = "stopped" if process_probe_ok(probe) else "failed"
    evidence = first_output_line(probe)
    message = "Stopped docker compose postgres service without removing volumes." if status == "stopped" else "Docker compose postgres stop failed."
    return StopDbAction(status=status, command=command_as_text(command), message=message, evidence=evidence)


def build_stop_result(project_root: Path | None, invoked_from: Path, args: argparse.Namespace) -> StopResult:
    run_id_value = run_id("stop")
    result = StopResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
        dry_run=args.dry_run,
        include_db=args.include_db,
        force=not args.no_force,
        timeout_seconds=args.timeout_seconds,
        run_id=run_id_value,
    )
    if project_root is None:
        result.classification = "invalid_project_root"
        result.failures.append({"code": "invalid_project_root", "message": "Could not find project root."})
        return result
    state_path, state, processes = process_table_state(project_root)
    if "_error" in state:
        result.classification = "state_invalid"
        result.failures.append({"code": "state_invalid", "message": f"Could not read state file {rel(state_path, project_root)}: {state.get('_error')}"})
        return result
    if not processes:
        result.warnings.append({"code": "no_tracked_processes", "message": "state.json does not contain tracked backend/frontend processes."})
    for name, entry in processes.items():
        target = stop_target_from_entry(project_root, name, entry)
        stop_owned_target(target, timeout_seconds=args.timeout_seconds, dry_run=args.dry_run, force=not args.no_force)
        result.targets.append(target)
        if target.action in {"skipped", "timeout", "failed"}:
            result.warnings.append({"code": f"{name}_{target.action}", "message": target.error or f"{name} was not stopped."})
    result.db_action = stop_compose_postgres(project_root, include_db=args.include_db, dry_run=args.dry_run, timeout_seconds=args.timeout_seconds)
    if result.db_action.status == "failed":
        result.warnings.append({"code": "postgres_stop_failed", "message": result.db_action.evidence or result.db_action.message})
    # Probe common runtime surfaces after requested stop attempt.
    backend_host, backend_port, _ = parse_backend_host_port(project_root)
    frontend_host, frontend_port, _ = parse_frontend_host_port(project_root)
    db_url = effective_env_values_for(project_root, "backend").get("DATABASE__URL") or effective_env_values_for(project_root, "backend").get("DATABASE_URL")
    db_probe = parse_database_url_probe(db_url)
    if db_probe.host and db_probe.port:
        result.ports_after.append(probe_port("postgres", db_probe.port, host=db_probe.host))
    result.ports_after.append(probe_port("backend", backend_port, host=http_probe_host(backend_host)))
    result.ports_after.append(probe_port("frontend", frontend_port, host=http_probe_host(frontend_host)))
    result.http_after.extend(probe_backend_health(backend_host, backend_port, timeout=0.6))
    result.http_after.append(probe_http("frontend_root", frontend_root_url(frontend_host, frontend_port), timeout=0.6))
    if any(t.action in {"failed", "timeout", "skipped"} for t in result.targets):
        result.classification = "partial"
    elif args.dry_run:
        result.classification = "planned"
    elif not result.targets and result.db_action and result.db_action.status in {"skipped", "unavailable"}:
        result.classification = "idle"
    else:
        result.classification = "stopped"
    if any(t.action == "skipped" and t.verification_status == "mismatch" for t in result.targets):
        result.next_actions.append("Inspect skipped tracked PIDs manually; devbootstrap refused to stop them because ownership verification failed.")
    if any(p.open for p in result.ports_after if p.name in {"backend", "frontend"}):
        result.next_actions.append("A backend/frontend port is still open after stop. If it is not a tracked process, inspect it manually before retrying up.")
    if result.db_action and result.db_action.status == "skipped":
        result.next_actions.append("Run `python tools/devbootstrap.py stop --include-db` only when you intentionally want to stop the compose postgres service.")
    if not result.next_actions:
        result.next_actions.append("Run `python tools/devbootstrap.py status` to confirm the environment is clean.")
    return result


def render_stop_report(result: StopResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap stop report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Run ID: `{result.run_id}`")
    lines.append(f"- Dry run: `{result.dry_run}`")
    lines.append(f"- Include DB: `{result.include_db}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append("")
    lines.append("## Tracked process actions")
    lines.append("")
    lines.append("| Name | PID | Alive before | Verification | Action | Alive after | Evidence |")
    lines.append("|---|---:|---|---|---|---|---|")
    if result.targets:
        for target in result.targets:
            lines.append(
                f"| `{target.name}` | {target.pid if target.pid is not None else ''} | {target.alive_before} | "
                f"{target.verification_status} | {target.action} | {target.alive_after} | `{target.verification_evidence or target.error or ''}` |"
            )
    else:
        lines.append("| | | | | no tracked processes | | |")
    lines.append("")
    lines.append("## PostgreSQL compose action")
    lines.append("")
    if result.db_action:
        lines.append(f"- Status: `{result.db_action.status}`")
        if result.db_action.command:
            lines.append(f"- Command: `{result.db_action.command}`")
        lines.append(f"- Message: {result.db_action.message}")
        if result.db_action.evidence:
            lines.append(f"- Evidence: `{result.db_action.evidence}`")
    else:
        lines.append("- Not evaluated.")
    lines.append("")
    lines.append("## Ports after stop")
    lines.append("")
    lines.append("| Name | Address | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for port in result.ports_after:
        status = "open" if port.open else "closed/unreachable"
        lines.append(f"| {port.name} | `{port.host}:{port.port}` | {status} | `{port.error or ''}` |")
    lines.append("")
    lines.append("## HTTP after stop")
    lines.append("")
    lines.append("| Name | URL | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for probe in result.http_after:
        status = f"HTTP {probe.status}" if probe.reachable and probe.status is not None else "unreachable"
        lines.append(f"| {probe.name} | `{probe.url}` | {status} | `{probe.error or f'{probe.duration_ms} ms'}` |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking findings from stop.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")
    lines.append("## Next safe actions")
    lines.append("")
    for action in result.next_actions:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_stop_reports(project_root: Path, result: StopResult, report_dir: Path) -> None:
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / "stop.json", result, command="stop")
    (report_dir / "report.md").write_text(render_stop_report(result), encoding="utf-8")


def update_state_after_stop(project_root: Path, result: StopResult, report_dir: Path) -> None:
    if result.dry_run:
        append_report_to_state(project_root, report_dir, result.run_id)
        return
    state_path, state, processes = process_table_state(project_root)
    if "_error" in state:
        return
    removable = {target.name for target in result.targets if target.action in {"stopped", "force_stopped", "stale_removed"}}
    for name in removable:
        processes.pop(name, None)
    state["version"] = STATE_VERSION
    state["processes"] = processes
    if not processes and state.get("activeRunId"):
        state["activeRunId"] = None
    last_reports = state.get("lastReports") if isinstance(state.get("lastReports"), list) else []
    last_reports.append(rel(report_dir, project_root))
    state["lastReports"] = last_reports[-20:]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)


def print_stop_summary(result: StopResult) -> None:
    print_header("devbootstrap stop")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Classification: {result.classification}")
    print(f"Dry run: {result.dry_run}")
    print(f"Include DB: {result.include_db}")
    if result.targets:
        print("\nTracked processes:")
        for target in result.targets:
            print(
                f"  - {target.name}: pid={target.pid} alive_before={target.alive_before} "
                f"verify={target.verification_status} action={target.action} alive_after={target.alive_after}"
            )
            if target.error:
                print(f"    error: {target.error}")
    else:
        print("\nTracked processes: none")
    if result.db_action:
        command = f" command={result.db_action.command}" if result.db_action.command else ""
        print(f"\nPostgres: {result.db_action.status} — {result.db_action.message}{command}")
    if result.ports_after:
        print("\nPorts after stop:")
        for port in result.ports_after:
            status = "open" if port.open else "closed"
            print(f"  - {port.name} {port.host}:{port.port}: {status}")
    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking findings from stop")
    if result.next_actions:
        print("\nNext safe actions:")
        for action in result.next_actions:
            print(f"  - {action}")
    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_stop(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_stop_result(project_root, invoked_from, args)
    report_dir: Path | None = None
    if project_root is not None and not args.no_write_report:
        report_dir = create_report_dir(project_root, "stop")
        write_stop_reports(project_root, result, report_dir)
        update_state_after_stop(project_root, result, report_dir)
    print_stop_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures or any(t.action in {"failed", "timeout"} for t in result.targets) else 0


def build_status_snapshot(project_root: Path) -> dict[str, Any]:
    state = summarize_state(project_root)
    backend_host, backend_port, backend_warning = parse_backend_host_port(project_root)
    frontend_host, frontend_port, frontend_warning = parse_frontend_host_port(project_root)
    backend_probe_host = http_probe_host(backend_host)
    frontend_probe_host = http_probe_host(frontend_host)
    db_env = effective_env_values_for(project_root, "backend")
    db_url = db_env.get("DATABASE__URL") or db_env.get("DATABASE_URL")
    db_probe = parse_database_url_probe(db_url)
    ports: list[PortProbe] = []
    if db_probe.host and db_probe.port:
        ports.append(probe_port("postgres", db_probe.port, host=db_probe.host))
    ports.append(probe_port("backend", backend_port, host=backend_probe_host))
    ports.append(probe_port("frontend", frontend_port, host=frontend_probe_host))
    http = probe_backend_health(backend_host, backend_port, timeout=0.8)
    http.append(probe_http("frontend_root", frontend_root_url(frontend_host, frontend_port), timeout=0.8))
    compose_command, compose_detection = detect_compose_command(project_root)
    compose_status = probe_compose_status(project_root, compose_command) if process_probe_ok(compose_detection) else compose_detection
    warnings = [warning for warning in [backend_warning, frontend_warning] if warning]
    return {
        "projectRoot": str(project_root),
        "state": state,
        "ports": as_jsonable(ports),
        "http": as_jsonable(http),
        "composeStatus": as_jsonable(compose_status),
        "warnings": warnings,
    }


def print_status_snapshot(snapshot: dict[str, Any]) -> None:
    print(f"Project root: {snapshot.get('projectRoot')}")
    state = snapshot.get("state", {})
    print(f"State file: {state.get('statePath')}")
    print(f"State exists: {state.get('exists')}")
    print(f"State valid: {state.get('valid')}")
    if state.get("error"):
        print(f"State error: {state.get('error')}")
    print(f"Active run: {state.get('activeRunId')}")
    processes = state.get("processes", {})
    if processes:
        print("\nRegistered processes:")
        for name, process in processes.items():
            print(
                f"  - {name}: pid={process.get('pid')} alive={process.get('alive')} "
                f"command={process.get('command')} cwd={process.get('cwd')}"
            )
    else:
        print("Registered processes: none")
    print("\nPorts:")
    for port in snapshot.get("ports", []):
        status = "open" if port.get("open") else "closed"
        print(f"  - {port.get('name')} {port.get('host')}:{port.get('port')}: {status}")
    print("\nHTTP:")
    for probe in snapshot.get("http", []):
        if probe.get("reachable"):
            print(f"  - {probe.get('name')}: HTTP {probe.get('status')} ({probe.get('duration_ms')} ms)")
        else:
            print(f"  - {probe.get('name')}: unreachable")
    compose = snapshot.get("composeStatus") or {}
    if compose:
        compose_state = "ok" if compose.get("returncode") == 0 else "unavailable" if not compose.get("available") else f"exit {compose.get('returncode')}"
        print(f"\nCompose postgres: {compose_state} — {first_output_line(ProcessProbe(**compose)) if isinstance(compose, dict) and {'name','command','available'}.issubset(compose.keys()) else compose.get('error', '')}")
    reports = state.get("lastReports") or []
    if reports:
        print("\nLast reports:")
        for report in reports[-5:]:
            print(f"  - {report}")
    warnings = snapshot.get("warnings") or []
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")

def print_diagnose_summary(result: DiagnoseResult) -> None:
    print_header("devbootstrap diagnose")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Platform: {result.platform.get('system')} {result.platform.get('release')} ({result.platform.get('machine')})")

    missing = [item.path for item in result.paths if item.required and not item.exists]
    if missing:
        print(f"Required files: MISSING ({len(missing)})")
        for path in missing:
            print(f"  - {path}")
    elif result.project_root:
        print("Required files: OK")

    print("\nTools:")
    for tool in result.tools:
        status = "OK" if tool.available else "MISSING"
        details = tool.version if tool.available else tool.error
        print(f"  - {tool.name}: {status}" + (f" — {details}" if details else ""))

    if result.ports:
        print("\nPorts:")
        for port in result.ports:
            status = "open" if port.open else "closed"
            print(f"  - {port.name} {port.host}:{port.port}: {status}")

    if result.http:
        print("\nHTTP:")
        for probe in result.http:
            if probe.reachable:
                print(f"  - {probe.name}: HTTP {probe.status} ({probe.duration_ms} ms)")
            else:
                print(f"  - {probe.name}: unreachable")

    if result.failures or result.warnings:
        print("\nFindings:")
        for failure in result.failures:
            print(f"  - FAIL {failure['code']}: {failure['message']}")
        for warning in result.warnings:
            print(f"  - WARN {warning['code']}: {warning['message']}")
    else:
        print("\nFindings: no blocking findings from phase 1 diagnostics")

    if result.report_dir:
        print(f"\nReport: {result.report_dir}/report.md")


def command_diagnose(args: argparse.Namespace) -> int:
    if getattr(args, "section", "all") == "postgres":
        return command_diagnose_postgres(args)
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_diagnose(project_root, invoked_from)
    if project_root is not None and not args.no_write_report:
        write_reports(project_root, result, "diagnose")
    print_diagnose_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if any(failure.get("code") == "invalid_project_root" for failure in result.failures) else 0


def command_status(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    print_header("devbootstrap status")
    if project_root is None:
        print("Project root: not found")
        print("State: unavailable")
        return 1
    snapshot = build_status_snapshot(project_root)
    print_status_snapshot(snapshot)
    if args.json:
        print("\nJSON:")
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0



@dataclass
class SelfCheckCase:
    name: str
    status: str
    message: str
    evidence: str | None = None


@dataclass
class SelfCheckResult:
    generated_at: str
    tool_version: str
    project_root: str | None
    invoked_from: str
    cases: list[SelfCheckCase] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    classification: str = "unknown"
    report_dir: str | None = None


def self_check_case(result: SelfCheckResult, name: str, func: Any) -> None:
    try:
        evidence = func()
    except AssertionError as exc:
        message = str(exc) or "assertion failed"
        result.cases.append(SelfCheckCase(name=name, status="fail", message=message))
        result.failures.append({"code": name, "message": message})
    except Exception as exc:
        message = f"unexpected error: {exc}"
        result.cases.append(SelfCheckCase(name=name, status="fail", message=message, evidence=exc.__class__.__name__))
        result.failures.append({"code": name, "message": message})
    else:
        result.cases.append(SelfCheckCase(name=name, status="ok", message="passed", evidence=evidence))


def case_self_check_version_and_timeout_policy() -> str:
    assert TOOL_VERSION == "2.0.1-draft", f"expected TOOL_VERSION 2.0.1-draft, got {TOOL_VERSION}"
    required = {
        "probe_command",
        "port_probe",
        "http_probe",
        "postgres_ready",
        "cargo_metadata",
        "cargo_check",
        "backend_ready",
        "npm_install",
        "frontend_ready",
        "smoke_step",
        "up_step",
        "stop_grace",
        "release_gate",
    }
    missing = sorted(required.difference(TIMEOUT_POLICY))
    assert not missing, "missing timeout policy keys: " + ", ".join(missing)
    for key, value in TIMEOUT_POLICY.items():
        assert isinstance(value, (int, float)) and value > 0, f"timeout {key} must be positive"
    return f"{len(TIMEOUT_POLICY)} timeout defaults checked"


def case_self_check_env_parser_and_masking() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-env-") as tmp:
        env_file = Path(tmp) / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "# comment",
                    "APP_NAME=p2p",
                    "export QUOTED='hello world'",
                    "SECRET_TOKEN=super-secret",
                    "DATABASE__URL=postgres://planner:pw@localhost:5432/p2p_planner",
                    "BROKEN_LINE",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        values, warnings = parse_env_file(env_file)
    assert values["APP_NAME"] == "p2p"
    assert values["QUOTED"] == "hello world"
    assert values["SECRET_TOKEN"] == "super-secret"
    assert warnings and "ignored non KEY=VALUE line" in warnings[0]
    assert mask_value("SECRET_TOKEN", values["SECRET_TOKEN"]) == "***"
    masked_db = mask_value("DATABASE__URL", values["DATABASE__URL"])
    assert "pw" not in masked_db and ":***@" in masked_db, masked_db
    return "env parser warnings and secret masking checked"


def case_self_check_database_url_parse() -> str:
    probe = parse_database_url_probe("postgres://planner:secret@127.0.0.1:15432/p2p_planner_dev?sslmode=disable")
    assert probe.raw_present is True
    assert probe.scheme == "postgres"
    assert probe.host == "127.0.0.1"
    assert probe.port == 15432
    assert probe.database == "p2p_planner_dev"
    assert probe.username == "planner"
    assert probe.has_password is True
    assert probe.masked_url and "secret" not in probe.masked_url
    return f"{probe.host}:{probe.port}/{probe.database}"


def case_self_check_failure_classifiers() -> str:
    assert classify_backend_failure("error: address already in use", "x") == "port_conflict"
    assert classify_backend_failure("migration 6 was previously applied but is missing in the resolved migrations", "x") == "migration_drift"
    assert classify_backend_failure("database foo does not exist", "x") == "database_missing"
    assert classify_frontend_failure("Error: Cannot find module '@vitejs/plugin-react'", "x") == "frontend_dependency_missing"
    assert classify_smoke_process_failure("quick", "NetworkError when attempting to fetch resource") == "runtime_unreachable"
    psql = ProcessProbe(name="psql", command=["psql"], available=True, returncode=2, stderr="password authentication failed for user planner")
    assert classify_psql_failure(psql, None) == "auth_failed"
    return "backend/frontend/postgres/smoke classifiers checked"


def case_self_check_project_discovery() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-root-") as tmp:
        root = Path(tmp) / "project"
        for relative in ["backend", "frontend", "docs", "tools"]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
        found_from_tools = find_project_root(root / "tools")
        found_from_nested = find_project_root(Path(tmp))
    assert found_from_tools == root.resolve()
    assert found_from_nested == root.resolve()
    return "root discovery from tools/ and parent workspace checked"


def case_self_check_env_diff() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-plan-") as tmp:
        root = Path(tmp)
        (root / "backend").mkdir()
        (root / "frontend").mkdir()
        (root / "docs").mkdir()
        (root / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
        (root / "backend" / ".env.example").write_text("DATABASE__URL=postgres://u:p@localhost:5432/a\nHTTP__HOST=127.0.0.1\n", encoding="utf-8")
        (root / "backend" / ".env").write_text("DATABASE__URL=postgres://u:p@localhost:5432/b\nEXTRA_KEY=yes\n", encoding="utf-8")
        (root / "frontend" / ".env.example").write_text("VITE_API_BASE_URL=http://127.0.0.1:18080/api/v1\n", encoding="utf-8")
        result = build_env_plan(root, root, mode="plan")
    backend = next(item for item in result.files if item.name == "backend")
    frontend = next(item for item in result.files if item.name == "frontend")
    assert "HTTP__HOST" in backend.missing_keys
    assert "EXTRA_KEY" in backend.extra_keys
    assert frontend.target_exists is False
    assert any(action.code == "create_env_file" and action.path == "frontend/.env.local" for action in result.actions)
    return "env diff detects missing, extra and absent target files"


def case_self_check_report_json_contract() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-report-") as tmp:
        path = Path(tmp) / "fixture.json"
        write_report_json(
            path,
            {
                "generated_at": iso_now(),
                "tool_version": TOOL_VERSION,
                "failures": [],
                "warnings": [],
            },
            command="self-check-fixture",
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == REPORT_SCHEMA_VERSION
    assert payload["command"] == "self-check-fixture"
    assert payload["toolVersion"] == TOOL_VERSION
    assert payload["status"] == "ok"
    assert payload.get("generatedAt")
    return "schemaVersion/command/toolVersion/status/generatedAt envelope checked"


def case_self_check_report_markdown_contract() -> str:
    result = DiagnoseResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=None,
        invoked_from="self-check",
        platform={"system": platform.system(), "python": sys.version.split()[0]},
    )
    rendered = render_report(result)
    required_sections = ["# devbootstrap diagnose report", "## Findings", "## Next safe actions"]
    for section in required_sections:
        assert section in rendered, f"missing report section {section}"
    return "minimal report.md sections checked"


def case_self_check_release_gates_json_envelope() -> str:
    result = ReleaseGatesResult(
        generated_at="2026-05-24T00:00:00+00:00",
        tool_version=TOOL_VERSION,
        project_root="/tmp/project",
        invoked_from="/tmp/project",
        run_id="selfcheck-release-gates",
        dry_run=False,
        timeout_seconds=123,
        report_dir=".dev-bootstrap/runs/selfcheck-release-gates",
        archive_path=".dev-bootstrap/runs/selfcheck-release-gates/release-gates_selfcheck.zip",
        overall_status="ok",
        classification="release_gates_ok",
        gates=[GateResult(name="fixture_gate", status="ok", classification="ok", message="gate completed", cwd=".", command=["true"], log_path="logs/01_fixture_gate.log")],
    )
    payload = release_gates_json_payload(result)
    assert payload["schemaVersion"] == 1
    assert payload["command"] == "release-gates"
    assert payload["toolVersion"] == TOOL_VERSION
    assert payload["overallStatus"] == "ok"
    assert payload["archivePath"].endswith(".zip")
    assert payload["gates"][0]["name"] == "fixture_gate"
    return "release-gates JSON envelope checked"


def case_self_check_release_gates_summary_rendering() -> str:
    result = ReleaseGatesResult(
        generated_at="2026-05-24T00:00:00+00:00",
        tool_version=TOOL_VERSION,
        project_root="/tmp/project",
        invoked_from="/tmp/project",
        run_id="selfcheck-release-gates",
        dry_run=True,
        timeout_seconds=123,
        overall_status="dry_run",
        classification="release_gates_dry_run",
        gates=[GateResult(name="frontend_build", status="planned", classification="dry_run", message="would run gate command", cwd="frontend", command=["npm", "run", "build"], log_path="logs/07_frontend_build.log")],
    )
    rendered = render_release_gates_summary(result)
    assert "# release-gates summary" in rendered
    assert "Overall: dry_run" in rendered
    assert "> npm run build" in rendered
    assert "logs/07_frontend_build.log" in rendered
    return "release-gates summary rendering checked"


def case_self_check_release_gates_archive_exclusions() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-archive-") as tmp:
        root = Path(tmp) / "run"
        (root / "logs").mkdir(parents=True)
        (root / "logs" / "01_ok.log").write_text("ok\n", encoding="utf-8")
        (root / "summary.txt").write_text("summary\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "bad.pyc").write_bytes(b"bad")
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache" / "bad").write_text("bad", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "bad.txt").write_text("bad", encoding="utf-8")
        (root / ".env").write_text("SECRET=bad", encoding="utf-8")
        (root / "frontend.tsbuildinfo").write_text("generated", encoding="utf-8")
        archive_path = root / "release-gates_selfcheck.zip"
        create_release_gates_archive(root, archive_path)
        with zipfile.ZipFile(archive_path) as zf:
            names = set(zf.namelist())
    assert "summary.txt" in names
    assert "logs/01_ok.log" in names
    forbidden = [
        name
        for name in names
        if "__pycache__" in name
        or ".pytest_cache" in name
        or "node_modules" in name
        or name == ".env"
        or name.endswith((".pyc", ".tsbuildinfo"))
    ]
    assert not forbidden, "forbidden archive entries: " + ", ".join(sorted(forbidden))
    return "release-gates archive exclusion rules checked"


def case_self_check_release_gates_ignored_classifier() -> str:
    stdout = "test result: ok. 12 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out"
    status, classification, message = classify_gate_output("backend_cargo_test_default", stdout, "", None, 0)
    assert status == "partial_pass"
    assert classification == "critical_tests_ignored"
    assert "ignored" in message
    return "ignored Rust tests classifier checked"


def case_self_check_release_gates_playwright_classifier() -> str:
    stderr = "Error: browserType.launch: Executable doesn't exist. Please run: npx playwright install"
    status, classification, message = classify_gate_output("frontend_browser_smoke", "", stderr, None, 1)
    assert status == "infra_failed"
    assert classification == "browser_smoke_prerequisite"
    assert "Playwright" in message
    return "Playwright missing-browser classifier checked"


def case_self_check_release_gates_playwright_assertion_classifier() -> str:
    stdout = """
> playwright test e2e/smoke/real-backend.smoke.spec.ts

Running 1 test using 1 worker
  ✘  1 e2e/smoke/real-backend.smoke.spec.ts › real backend core kanban path uses API without mocks

Error: expect(locator).toBeVisible() failed
Locator: getByRole('heading', { name: 'Workspace list / switcher' })
Expected: visible
"""
    status, classification, message = classify_gate_output("browser_real_backend_path", stdout, "", None, 1)
    assert status == "failed"
    assert classification == "browser_real_backend_path_failed"
    assert "gate failed" in message
    return "Playwright assertion classifier checked"


def case_self_check_release_gates_frontend_classifier_priority() -> str:
    missing_npm_log = """FAIL npm_version: npm availability check. — command not found
frontend/package-lock.json presence check; npm ci is preferred when it exists.
FAIL missing_npm: npm is not available on PATH.
"""
    status, classification, _ = classify_gate_output("frontend_prepare_dependencies", missing_npm_log, "", None, 1)
    assert status == "infra_failed"
    assert classification == "frontend_dependencies_missing", classification
    lockfile_log = """npm ERR! code EUSAGE
npm ERR! npm ci can only install packages when your package.json and package-lock.json are in sync.
npm ERR! Missing: vite@5.4.2 from lock file
"""
    status, classification, _ = classify_gate_output("frontend_prepare_dependencies", lockfile_log, "", None, 1)
    assert status == "infra_failed"
    assert classification == "frontend_lockfile_mismatch", classification
    return "frontend prepare classifier priority checked"


def case_self_check_windows_command_resolution() -> str:
    command = command_for_subprocess(
        ["npm", "--version"],
        resolved_path=r"C:\Program Files\nodejs\npm.CMD",
        platform_name="nt",
    )
    assert command[:4] == ["cmd.exe", "/d", "/c", "call"], command
    assert "/s" not in command, command
    assert command[4] == r"C:\Program Files\nodejs\npm.CMD", command
    assert command[5:] == ["--version"], command
    display = command_as_text(command)
    assert "/s" not in display, display
    assert r'cmd.exe /d /c call "C:\Program Files\nodejs\npm.CMD" --version' in display, display
    direct = command_for_subprocess(["node", "--version"], resolved_path=r"C:\Program Files\nodejs\node.exe", platform_name="nt")
    assert direct == [r"C:\Program Files\nodejs\node.exe", "--version"], direct
    return "Windows .cmd command resolution checked"


def case_self_check_frontend_prepare_blocker_converts_downstream_skip() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-frontend-blocker-") as tmp:
        root = Path(tmp)
        logs = root / "logs"
        logs.mkdir(parents=True)
        blocker = GateResult(
            name="frontend_prepare_dependencies",
            status="infra_failed",
            classification="frontend_dependencies_missing",
            message="npm unavailable",
            cwd=".",
            log_path="logs/01_frontend_prepare_dependencies.log",
        )
        spec = release_gate_frontend_dependency_skip_spec(
            name="frontend_build",
            command=["npm", "run", "build"],
            description="Run frontend build.",
            reason="npm is not available",
            details={},
        )
        converted = release_gates_skip_for_frontend_prepare_failed(root, logs, 2, spec, blocker)
    assert converted.status == "skipped_prerequisite"
    assert converted.classification == "frontend_prepare_dependencies_failed"
    assert converted.details["blockedBy"]["gate"] == "frontend_prepare_dependencies"
    return "failed frontend prepare converts downstream frontend failures to prerequisite skips"


def case_self_check_release_gates_ignored_covered_by_db_gate() -> str:
    gates = [
        GateResult(
            name="backend_cargo_test_default",
            status="partial_pass",
            classification="critical_tests_ignored",
            message="ignored DB tests",
            cwd="backend",
        ),
        GateResult(
            name="backend_cargo_test_db_ignored",
            status="ok",
            classification="ok",
            message="include-ignored passed",
            cwd="backend",
        ),
    ]
    overall, classification = release_gates_overall_status(gates, dry_run=False)
    assert overall == "ok", (overall, classification)
    return "covered ignored Rust tests are not release blockers"



def case_self_check_managed_test_db_url_derivation() -> str:
    source = "postgres://planner:secret@127.0.0.1:15432/p2p_planner_dev?sslmode=disable"
    managed = replace_database_name_in_url(source, "p2pkanban_rg_test")
    maintenance = replace_database_name_in_url(source, "postgres")
    admin_runtime = database_url_with_credentials(source, database_name="p2pkanban_rg_test", username="postgres", password="admin secret")
    admin_maintenance = database_url_with_credentials(source, database_name="postgres", username="postgres", password="admin secret")
    assert managed == "postgres://planner:secret@127.0.0.1:15432/p2pkanban_rg_test?sslmode=disable"
    assert maintenance == "postgres://planner:secret@127.0.0.1:15432/postgres?sslmode=disable"
    assert admin_runtime == "postgres://postgres:admin%20secret@127.0.0.1:15432/p2pkanban_rg_test?sslmode=disable"
    assert admin_maintenance == "postgres://postgres:admin%20secret@127.0.0.1:15432/postgres?sslmode=disable"
    env = release_gate_managed_db_env(managed)
    assert env["DATABASE__URL"] == managed
    assert env["DATABASE_URL"] == managed
    assert env["TEST_DATABASE_URL"] == managed
    assert "secret" not in mask_database_url(managed)
    return "managed test DB URL derivation and env override checked"


def case_self_check_managed_test_db_specs() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-managed-") as tmp:
        root = Path(tmp)
        (root / "backend").mkdir()
        (root / "frontend").mkdir()
        (root / "docs").mkdir()
        (root / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
        (root / "backend" / ".env.example").write_text("DATABASE__URL=postgres://u:p@127.0.0.1:5432/dev\n", encoding="utf-8")
        (root / "frontend" / "package.json").write_text(json.dumps({"scripts": {}, "devDependencies": {}}), encoding="utf-8")
        (root / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")
        managed_url = "postgres://u:p@127.0.0.1:5432/p2pkanban_rg_selfcheck"
        specs = build_release_gate_specs(root, managed_test_db_url=managed_url, managed_test_db_requested=True)
        by_name = {spec.name: spec for spec in specs}
    db_spec = by_name["backend_cargo_test_db_ignored"]
    smoke_spec = by_name["backend_python_smoke_first"]
    assert db_spec.env_extra["TEST_DATABASE_URL"] == managed_url
    assert db_spec.env_extra["DATABASE__URL"] == managed_url
    assert smoke_spec.env_extra["TEST_DATABASE_URL"] == managed_url
    assert smoke_spec.details["managedTestDb"] is True
    return "release-gates managed DB specs carry safe env overrides"


def case_self_check_managed_runtime_specs() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-runtime-") as tmp:
        root = Path(tmp)
        (root / "backend").mkdir()
        (root / "frontend").mkdir()
        (root / "docs").mkdir()
        (root / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
        (root / "backend" / ".env.example").write_text("DATABASE__URL=postgres://u:p@127.0.0.1:5432/dev\n", encoding="utf-8")
        (root / "frontend" / "package.json").write_text(json.dumps({"scripts": {"test:browser": "playwright test"}, "devDependencies": {"@playwright/test": "1.55.0"}}), encoding="utf-8")
        (root / "frontend" / "package-lock.json").write_text("{}", encoding="utf-8")
        api_base = "http://127.0.0.1:39001/api/v1"
        frontend_url = "http://127.0.0.1:39002/"
        specs = build_release_gate_specs(
            root,
            allow_dev_db_write=True,
            managed_runtime_requested=True,
            managed_backend_api_base_url=api_base,
            managed_frontend_url=frontend_url,
            managed_frontend_host="127.0.0.1",
            managed_frontend_port=39002,
            dry_run=True,
        )
        by_name = {spec.name: spec for spec in specs}
    smoke_spec = by_name["backend_python_smoke_first"]
    uiux_spec = by_name["frontend_uiux_real_backend_core_flow"]
    assert smoke_spec.env_extra["BASE_URL"] == api_base
    assert "--api-base-url" in uiux_spec.command
    assert api_base in uiux_spec.command
    assert "--base-url" in uiux_spec.command
    assert frontend_url in uiux_spec.command
    assert by_name["frontend_browser_smoke"].required is False
    return "release-gates managed runtime specs carry dynamic URL env overrides"


def case_self_check_managed_runtime_uiux_boot_starts_frontend() -> str:
    assert "frontend_uiux_boot" in RELEASE_GATES_MANAGED_BACKEND_GATE_NAMES
    assert "frontend_uiux_boot" in RELEASE_GATES_MANAGED_FRONTEND_GATE_NAMES
    assert "frontend_uiux_mocked_core_flow" not in RELEASE_GATES_MANAGED_FRONTEND_GATE_NAMES
    return "managed-runtime UIX boot gate starts managed backend/frontend before opening managed URL"


def case_self_check_managed_runtime_dynamic_cors_origin() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-cors-") as tmp:
        root = Path(tmp)
        (root / "backend").mkdir()
        (root / "backend" / ".env.example").write_text(
            "HTTP__CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173\n",
            encoding="utf-8",
        )
        state = build_managed_runtime_state(root, root / ".dev-bootstrap" / "runs" / "selfcheck", "selfcheck")
        state.frontend_url = "http://127.0.0.1:39002/"
        cors_env = release_gate_managed_backend_cors_env(root, state)
    origins = split_csv(cors_env["HTTP__CORS_ALLOWED_ORIGINS"])
    assert "http://127.0.0.1:5173" in origins, origins
    assert "http://localhost:5173" in origins, origins
    assert "http://127.0.0.1:39002" in origins, origins
    assert "http://localhost:39002" in origins, origins
    return "managed runtime backend CORS includes the dynamic frontend origin"


def case_self_check_release_confidence_accepts_uiux_real_backend_path() -> str:
    result = ReleaseGatesResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=None,
        invoked_from="self-check",
        run_id="selfcheck",
        dry_run=False,
        timeout_seconds=TIMEOUT_POLICY["release_gate"],
        gates=[
            GateResult("backend_python_smoke_first", "ok", "ok", "gate completed", "backend"),
            GateResult("frontend_build", "ok", "ok", "gate completed", "frontend"),
            GateResult("frontend_unit_integration", "ok", "ok", "gate completed", "frontend"),
            GateResult("frontend_uiux_mocked_core_flow", "ok", "ok", "gate completed", "."),
            GateResult("frontend_uiux_real_backend_core_flow", "ok", "ok", "gate completed", "."),
        ],
    )
    product_path = release_confidence_product_path(result)
    caps = release_confidence_caps(
        counts={"unknownRequiredGateCount": 0, "failedRequiredGateCount": 0},
        repeatability={"reproducibilityIndex": 1.0},
        product_path=product_path,
        artifact_quality={"redactionStatus": "ok", "artifactCompletenessStatus": "ok"},
        result=result,
    )
    assert product_path["realBackendProductPathPassed"] is True, product_path
    assert product_path["uiuxRealBackendCoreFlowPassed"] is True, product_path
    assert product_path["acceptedRealBackendGate"] == "frontend_uiux_real_backend_core_flow", product_path
    assert not any(cap["id"] == "real-backend-product-path-missing" for cap in caps), caps
    return "release confidence accepts UIX real-backend core flow as product-path evidence"


def case_self_check_release_gates_frontend_dependency_preflight() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-frontend-") as tmp:
        root = Path(tmp)
        frontend = root / "frontend"
        frontend.mkdir()
        (root / "backend").mkdir()
        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {
                        "build": "tsc -b && vite build",
                        "test:run": "vitest run",
                        "test:browser": "playwright test e2e/smoke/auth-and-workspaces.smoke.spec.ts",
                    },
                    "devDependencies": {"@playwright/test": "1.55.0"},
                }
            ),
            encoding="utf-8",
        )
        (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
        specs = build_release_gate_specs(root)
        by_name = {spec.name: spec for spec in specs}
    for name in ["frontend_build", "frontend_unit_integration", "frontend_uiux_boot", "frontend_uiux_mocked_core_flow", "frontend_browser_smoke"]:
        spec = by_name[name]
        assert spec.skip_status == "infra_failed", name
        assert spec.skip_classification == "frontend_dependencies_missing", name
        assert "--prepare-deps" in (spec.skip_reason or ""), name
    return "release-gates frontend dependency preflight checked"


def case_self_check_frontend_prepare_modes() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-frontend-modes-") as tmp:
        root = Path(tmp)
        frontend = root / "frontend"
        frontend.mkdir(parents=True)
        result = FrontendResult(
            generated_at=iso_now(),
            tool_version=TOOL_VERSION,
            project_root=str(root),
            invoked_from=str(root),
            mode="prepare-frontend",
            package_json_exists=True,
            package_lock_exists=True,
            node_modules_exists=False,
            install_marker_valid=False,
        )
        assert frontend_prepare_should_install(result, "missing")[0] is True
        result.node_modules_exists = True
        assert frontend_prepare_should_install(result, "missing")[0] is False
        assert frontend_prepare_should_install(result, "stale")[0] is True
        assert normalize_frontend_prepare_dep_mode("missing-or-stale") == "stale"
    return "frontend dependency preparation modes checked"



def case_self_check_release_gates_profiles_and_consent() -> str:
    args = argparse.Namespace(
        profile="full-local-release",
        dry_run=True,
        allow_dev_db_write=None,
        managed_runtime=None,
        managed_test_db=None,
        test_db_retention=None,
        keep_test_db=None,
        start_db_if_needed=None,
        dump_test_db_on_failure=None,
        prepare_frontend=False,
        prepare_deps=None,
        install_playwright_browsers=None,
        include_real_backend_browser=False,
        real_backend_browser_spec="e2e/smoke/real-backend.smoke.spec.ts",
        include_clean_machine=None,
        clean_machine_profile=None,
        clean_machine_retention=None,
    )
    plan = resolve_release_gates_profile_args(args)
    assert plan.profile == "full-local-release"
    assert args.managed_test_db is True
    assert args.managed_runtime is True
    assert args.prepare_deps == DEFAULT_FRONTEND_PREPARE_DEP_MODE
    assert args.install_playwright_browsers is False
    assert args.include_real_backend_browser is False
    assert plan.explicit_overrides["include_real_backend_browser"] is False
    allowed_categories = {item["category"] for item in plan.allowed_side_effects}
    assert {"create-database", "write-database", "start-process"}.issubset(allowed_categories)
    rendered = render_release_gates_profile_plan(plan)
    assert "Dry-run guarantee" in rendered
    assert "fallback npm install" in rendered
    assert parse_optional_bool_arg("false") is False
    assert parse_optional_bool_arg(None) is True
    return "release-gates profiles, explicit overrides and consent plan checked"


def case_self_check_clean_machine_profiles() -> str:
    dry = release_gate_clean_machine_commands("dry")
    deps = release_gate_clean_machine_commands("deps")
    runtime = release_gate_clean_machine_commands("runtime")
    assert any(command[:3] == [sys.executable, "tools/devbootstrap.py", "up"] and "--dry-run" in command for command in dry)
    assert not any(command[:3] == ["cargo", "test", "--no-run"] for command in dry)
    assert any(command[:3] == ["cargo", "test", "--no-run"] for command in deps)
    assert any("release-gates" in command and "--managed-runtime" in command for command in runtime)
    assert normalize_clean_machine_profile("clean-machine-dry") == "dry"
    return "clean-machine sandbox profiles and command plan checked"



def case_self_check_release_gates_remediation_bundle() -> str:
    result = ReleaseGatesResult(
        generated_at="2026-05-25T00:00:00+00:00",
        tool_version=TOOL_VERSION,
        project_root="/tmp/project",
        invoked_from="/tmp/project",
        run_id="selfcheck-release-gates-remediation",
        dry_run=False,
        timeout_seconds=60,
        overall_status="infra_failed",
        classification="release_gates_infra_failed",
    )
    result.gates.append(
        GateResult(
            name="frontend_build",
            status="infra_failed",
            classification="frontend_dependencies_missing",
            message="frontend/node_modules is missing",
            cwd="frontend",
            command=["npm", "run", "build"],
            required=True,
            log_path=".dev-bootstrap/runs/selfcheck/logs/frontend.log",
        )
    )
    result.gates.append(
        GateResult(
            name="docs_readme_startup_commands_present",
            status="ok",
            classification="ok",
            message="README contains startup commands",
            cwd=".",
            command=[],
            required=True,
        )
    )
    ledger = release_gates_build_ledger(result)
    blockers = release_gates_infrastructure_blockers(result)
    unverified = release_gates_unverified_areas(result)
    commands = release_gates_rerun_commands(result, blockers)
    problem_ledger = release_gates_problem_ledger(result, commands)
    probe_ledger = release_gates_probe_ledger(result)
    assert ledger["releaseConfidence"] == "incomplete"
    assert ledger["countsByStatus"]["infra_failed"] == 1
    assert ledger["countsByStatus"]["passed"] == 1
    assert ledger["productRegressionsProven"] == "none-proven-but-incomplete"
    assert blockers and blockers[0]["code"] == "frontend_dependencies_missing"
    assert any(item["gate"] == "frontend_build" for item in unverified)
    assert any("--prepare-deps" in command for command in commands)
    assert problem_ledger["problems"][0]["id"] == "REL-FE-001"
    assert any(probe["problemId"] == "REL-FE-001" for probe in probe_ledger["probes"])
    markdown = render_release_gates_gate_ledger_md(ledger)
    assert "Release confidence" in markdown
    assert "frontend_dependencies_missing" in markdown
    return "release-gates remediation ledger and targeted rerun commands checked"


def case_self_check_release_gates_targeted_next_actions() -> str:
    result = ReleaseGatesResult(
        generated_at="2026-05-24T00:00:00+00:00",
        tool_version=TOOL_VERSION,
        project_root="/tmp/project",
        invoked_from="/tmp/project",
        run_id="selfcheck-release-gates-actions",
        dry_run=False,
        timeout_seconds=123,
        gates=[
            GateResult(
                name="frontend_build",
                status="infra_failed",
                classification="frontend_dependencies_missing",
                message="frontend/node_modules is missing",
                cwd="frontend",
                command=["npm", "run", "build"],
            ),
            GateResult(
                name="backend_cargo_test_db_ignored",
                status="skipped_prerequisite",
                classification="db_test_prerequisite_missing",
                message="TEST_DATABASE_URL is absent",
                cwd="backend",
                command=["cargo", "test", "--", "--include-ignored"],
            ),
        ],
    )
    finalize_release_gates_result(result)
    joined = "\n".join(result.next_actions)
    assert result.overall_status == "infra_failed"
    assert "--prepare-deps" in joined
    assert "TEST_DATABASE_URL" in joined
    assert "release-gates-test-database.md" in joined
    return "targeted release-gates next actions checked"


def case_self_check_release_gates_keep_going_behavior() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-keepgoing-") as tmp:
        root = Path(tmp)
        logs = root / "logs"
        logs.mkdir()
        first = run_gate_process_step(
            project_root=root,
            logs_dir=logs,
            index=1,
            spec=GateSpec(name="first_missing_command", cwd=".", command=["definitely-missing-devbootstrap-command-xyz"]),
            timeout_seconds=5,
        )
        second = run_gate_process_step(
            project_root=root,
            logs_dir=logs,
            index=2,
            spec=GateSpec(name="second_still_runs", cwd=".", command=[sys.executable, "-c", "print('ok')"]),
            timeout_seconds=5,
        )
    assert first.status == "infra_failed"
    assert second.status == "ok"
    assert first.log_path and second.log_path
    overall, classification = release_gates_overall_status([first, second], dry_run=False)
    assert overall == "infra_failed"
    assert classification == "release_gates_infra_failed"
    return "keep-going execution after a failed prerequisite checked"



def case_self_check_release_gates_phase7_bundle_contract() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-phase7-") as tmp:
        root = Path(tmp)
        (root / "backend" / "migrations").mkdir(parents=True)
        (root / "frontend").mkdir(parents=True)
        (root / "tools").mkdir(parents=True)
        (root / "backend" / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.0.0'\n", encoding="utf-8")
        (root / "backend" / "Cargo.lock").write_text("# fixture\n", encoding="utf-8")
        (root / "backend" / "build.rs").write_text("fn main() {}\n", encoding="utf-8")
        (root / "backend" / "migrations" / "0001_fixture.sql").write_text("select 1;\n", encoding="utf-8")
        (root / "frontend" / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}}), encoding="utf-8")
        (root / "frontend" / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (root / "tools" / "devbootstrap.py").write_text("# fixture\n", encoding="utf-8")
        run_dir = root / BOOTSTRAP_DIR_NAME / "runs" / "selfcheck-release-gates-phase7"
        logs = run_dir / "logs"
        logs.mkdir(parents=True)
        (logs / "01_fixture_gate.log").write_text("status: ok\n", encoding="utf-8")
        result = ReleaseGatesResult(
            generated_at="2026-05-27T00:00:00+00:00",
            tool_version=TOOL_VERSION,
            project_root=str(root),
            invoked_from=str(root),
            run_id="selfcheck-release-gates-phase7",
            dry_run=False,
            timeout_seconds=123,
            overall_status="ok",
            classification="release_gates_ok",
            gates=[GateResult(name="fixture_gate", status="ok", classification="ok", message="gate completed", cwd=".", command=[sys.executable, "--version"], log_path="logs/01_fixture_gate.log")],
        )
        result.profile_plan = ReleaseGatesProfilePlan(
            profile=RELEASE_GATES_DEFAULT_PROFILE,
            explicit_profile=False,
            description=RELEASE_GATES_PROFILE_DESCRIPTIONS[RELEASE_GATES_DEFAULT_PROFILE],
            dry_run=False,
            effective_options=release_gates_profile_defaults(RELEASE_GATES_DEFAULT_PROFILE),
            allowed_side_effects=[],
            denied_side_effects=[{"category": "write-project-files", "description": "fixture denied side effect"}],
            planned_gates=["fixture_gate"],
        )
        write_release_gates_profile_plan(root, run_dir, result.profile_plan)
        write_release_gates_reports(root, result, run_dir)
        manifest = read_json(run_dir / "bundle-manifest.json")
        completeness = read_json(run_dir / "artifact-completeness.json")
        command_resolution = read_json(run_dir / "command-resolution.json")
        redaction = read_json(run_dir / "redaction-report.json")
        archive_path = Path(result.archive_path or "")
        archive_abs = root / archive_path
        with zipfile.ZipFile(archive_abs) as zf:
            names = set(zf.namelist())
    assert manifest["bundleType"] == "devbootstrap-release-gates-autopsy"
    assert manifest["contractVersion"] == RELEASE_GATES_AUTOPSY_CONTRACT_VERSION
    assert completeness["overallStatus"] == "ok", completeness
    assert command_resolution["gateCommands"][0]["command"]["resolvedExecutable"]
    assert redaction["status"] == "ok"
    for required_name in [
        "bundle-manifest.json",
        "artifact-completeness.json",
        "environment-fingerprint.json",
        "command-resolution.json",
        "redaction-report.json",
        "release-gates.json",
        "remediation/problem-ledger.json",
        "remediation/probe-ledger.json",
        "remediation/decision-ledger-template.json",
        "remediation/provocation-matrix.json",
        "remediation/controlled-mutators.json",
        "remediation/repeatability-loop.json",
        "release-confidence-gate.json",
        "release-confidence-gate.md",
        "v1-release-readiness.md",
        "remediation/regression-memory.json",
        "remediation/regression-memory.md",
        "remediation/recurring-family-counts.json",
        "remediation/recurring-family-counts.md",
        "release-gates-consent.json",
    ]:
        assert required_name in names, f"missing {required_name} from archive"
    return "release-gates phase 7 regression memory and autopsy bundle contract checked"



def case_self_check_frontend_direct_vite_launch_command() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-frontend-direct-vite-") as tmp:
        root = Path(tmp)
        frontend = root / "frontend"
        vite_bin = frontend / "node_modules" / "vite" / "bin"
        vite_bin.mkdir(parents=True)
        (frontend / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
        (vite_bin / "vite.js").write_text("console.log('vite')\n", encoding="utf-8")
        command, action_code, action_message = frontend_dev_launch_command(root, "127.0.0.1", 5173)
    assert command == ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173", "--strictPort"], command
    assert action_code == "vite_direct", action_code
    assert "directly" in action_message, action_message
    return "frontend direct Vite launch command checked"


def case_self_check_release_gates_playwright_install_force() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-rg-playwright-install-") as tmp:
        root = Path(tmp)
        frontend = root / "frontend"
        (root / "backend").mkdir()
        (root / "docs").mkdir()
        (frontend / "node_modules" / "@playwright" / "test").mkdir(parents=True)
        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"test:browser": "playwright test"},
                    "devDependencies": {"@playwright/test": "1.55.0"},
                }
            ),
            encoding="utf-8",
        )
        (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
        fake_cache = root / "fake-ms-playwright"
        fake_browser = fake_cache / "chromium-older" / "chrome-linux64" / "chrome"
        fake_browser.parent.mkdir(parents=True)
        fake_browser.write_text("stale browser placeholder\n", encoding="utf-8")
        old_browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(fake_cache)
        try:
            specs = build_release_gate_specs(root, dry_run=True, install_playwright_browsers=True)
        finally:
            if old_browsers_path is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_browsers_path
    names = [spec.name for spec in specs]
    assert "playwright_install" in names, names
    assert names.index("playwright_install") < names.index("frontend_browser_smoke"), names
    install_spec = next(spec for spec in specs if spec.name == "playwright_install")
    assert install_spec.command == ["npx", "playwright", "install", "chromium"], install_spec.command
    assert install_spec.details.get("chromiumExecutablePresent") is True, install_spec.details
    assert install_spec.details.get("playwrightInstallPolicy") == "explicit_ensure_current_revision", install_spec.details
    return "explicit Playwright install flag forces browser revision ensure even with stale cache evidence"

def build_self_check_result(project_root: Path | None, invoked_from: Path) -> SelfCheckResult:
    result = SelfCheckResult(
        generated_at=iso_now(),
        tool_version=TOOL_VERSION,
        project_root=str(project_root) if project_root else None,
        invoked_from=str(invoked_from),
    )
    self_check_case(result, "version_and_timeout_policy", case_self_check_version_and_timeout_policy)
    self_check_case(result, "env_parser_and_masking", case_self_check_env_parser_and_masking)
    self_check_case(result, "database_url_parse", case_self_check_database_url_parse)
    self_check_case(result, "failure_classifiers", case_self_check_failure_classifiers)
    self_check_case(result, "project_discovery", case_self_check_project_discovery)
    self_check_case(result, "stop_without_state_is_safe", case_self_check_stop_without_state_is_safe)
    self_check_case(result, "env_diff", case_self_check_env_diff)
    self_check_case(result, "report_json_contract", case_self_check_report_json_contract)
    self_check_case(result, "report_markdown_contract", case_self_check_report_markdown_contract)
    self_check_case(result, "release_gates_json_envelope", case_self_check_release_gates_json_envelope)
    self_check_case(result, "release_gates_summary_rendering", case_self_check_release_gates_summary_rendering)
    self_check_case(result, "release_gates_archive_exclusions", case_self_check_release_gates_archive_exclusions)
    self_check_case(result, "release_gates_ignored_classifier", case_self_check_release_gates_ignored_classifier)
    self_check_case(result, "release_gates_playwright_classifier", case_self_check_release_gates_playwright_classifier)
    self_check_case(result, "release_gates_playwright_assertion_classifier", case_self_check_release_gates_playwright_assertion_classifier)
    self_check_case(result, "release_gates_playwright_install_force", case_self_check_release_gates_playwright_install_force)
    self_check_case(result, "release_gates_frontend_classifier_priority", case_self_check_release_gates_frontend_classifier_priority)
    self_check_case(result, "windows_command_resolution", case_self_check_windows_command_resolution)
    self_check_case(result, "frontend_prepare_blocker_converts_downstream_skip", case_self_check_frontend_prepare_blocker_converts_downstream_skip)
    self_check_case(result, "release_gates_ignored_covered_by_db_gate", case_self_check_release_gates_ignored_covered_by_db_gate)
    self_check_case(result, "managed_test_db_url_derivation", case_self_check_managed_test_db_url_derivation)
    self_check_case(result, "managed_test_db_specs", case_self_check_managed_test_db_specs)
    self_check_case(result, "managed_runtime_specs", case_self_check_managed_runtime_specs)
    self_check_case(result, "managed_runtime_uiux_boot_starts_frontend", case_self_check_managed_runtime_uiux_boot_starts_frontend)
    self_check_case(result, "managed_runtime_dynamic_cors_origin", case_self_check_managed_runtime_dynamic_cors_origin)
    self_check_case(result, "release_confidence_accepts_uiux_real_backend_path", case_self_check_release_confidence_accepts_uiux_real_backend_path)
    self_check_case(result, "release_gates_frontend_dependency_preflight", case_self_check_release_gates_frontend_dependency_preflight)
    self_check_case(result, "frontend_prepare_modes", case_self_check_frontend_prepare_modes)
    self_check_case(result, "frontend_direct_vite_launch_command", case_self_check_frontend_direct_vite_launch_command)
    self_check_case(result, "clean_machine_profiles", case_self_check_clean_machine_profiles)
    self_check_case(result, "release_gates_profiles_and_consent", case_self_check_release_gates_profiles_and_consent)
    self_check_case(result, "release_gates_remediation_bundle", case_self_check_release_gates_remediation_bundle)
    self_check_case(result, "release_gates_targeted_next_actions", case_self_check_release_gates_targeted_next_actions)
    self_check_case(result, "release_gates_keep_going_behavior", case_self_check_release_gates_keep_going_behavior)
    self_check_case(result, "release_gates_phase7_bundle_contract", case_self_check_release_gates_phase7_bundle_contract)
    if result.failures:
        result.classification = "failed"
        result.next_actions.append("Fix failing self-check cases before using devbootstrap as the v1 routine entrypoint.")
    else:
        result.classification = "ok"
        result.next_actions.append("devbootstrap internal fixtures passed; run `python tools/devbootstrap.py diagnose` or `up --dry-run` next.")
    return result


def render_self_check_report(result: SelfCheckResult) -> str:
    lines: list[str] = []
    lines.append("# devbootstrap self-check report")
    lines.append("")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Tool version: `{result.tool_version}`")
    lines.append(f"- Project root: `{result.project_root or 'not found'}`")
    lines.append(f"- Invoked from: `{result.invoked_from}`")
    lines.append(f"- Classification: `{result.classification}`")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append("| Case | Status | Message | Evidence |")
    lines.append("|---|---|---|---|")
    for case in result.cases:
        lines.append(f"| `{case.name}` | {case.status} | {case.message} | `{case.evidence or ''}` |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not result.failures and not result.warnings:
        lines.append("- No blocking findings from self-check.")
    for failure in result.failures:
        lines.append(f"- **FAIL** `{failure['code']}` — {failure['message']}")
    for warning in result.warnings:
        lines.append(f"- **WARN** `{warning['code']}` — {warning['message']}")
    lines.append("")
    lines.append("## Next safe actions")
    lines.append("")
    for action in result.next_actions:
        lines.append(f"- {action}")
    lines.append("")
    return "\n".join(lines)


def write_self_check_reports(project_root: Path, result: SelfCheckResult) -> Path:
    report_dir = create_report_dir(project_root, "self-check")
    result.report_dir = rel(report_dir, project_root)
    write_report_json(report_dir / "self-check.json", result, command="self-check")
    (report_dir / "report.md").write_text(render_self_check_report(result), encoding="utf-8")
    append_report_to_state(project_root, report_dir, report_dir.name)
    return report_dir


def print_self_check_summary(result: SelfCheckResult) -> None:
    print_header("devbootstrap self-check")
    print(f"Tool version: {result.tool_version}")
    print(f"Project root: {result.project_root or 'not found'}")
    print(f"Classification: {result.classification}")
    print("\nCases:")
    for case in result.cases:
        evidence = f" ({case.evidence})" if case.evidence else ""
        print(f"  - {case.status.upper()} {case.name}: {case.message}{evidence}")
    if result.next_actions:
        print("\nNext actions:")
        for action in result.next_actions:
            print(f"  - {action}")


def case_self_check_stop_without_state_is_safe() -> str:
    with tempfile.TemporaryDirectory(prefix="devbootstrap-selfcheck-stop-") as tmp:
        root = Path(tmp)
        for relative in ["backend", "frontend", "docs", "tools"]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
        args = argparse.Namespace(dry_run=False, include_db=False, no_force=False, timeout_seconds=1)
        result = build_stop_result(root, root, args)
        rendered = render_stop_report(result)
    assert result.classification == "idle", result.classification
    assert result.targets == []
    assert result.db_action is not None
    assert result.db_action.status == "skipped"
    assert "no tracked processes" in rendered.lower()
    return "stop without state/procs reports idle instead of raising"


def command_self_check(args: argparse.Namespace) -> int:
    invoked_from = Path.cwd()
    project_root = find_project_root(invoked_from)
    result = build_self_check_result(project_root, invoked_from)
    if project_root is not None and not args.no_write_report:
        write_self_check_reports(project_root, result)
    print_self_check_summary(result)
    if args.json:
        print("\nJSON:")
        print(json.dumps(as_jsonable(result), ensure_ascii=False, indent=2))
    return 1 if result.failures else 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devbootstrap",
        description="Local development environment diagnostics for p2p_planner.",
    )
    parser.add_argument("--version", action="version", version=f"devbootstrap {TOOL_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose = subparsers.add_parser("diagnose", help="Run read-only environment diagnostics.")
    diagnose.add_argument("--section", choices=["all", "postgres"], default="all", help="Limit diagnostics to a specific subsystem.")
    diagnose.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    diagnose.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    diagnose.set_defaults(func=command_diagnose)

    start_db = subparsers.add_parser("start-db", help="Diagnose PostgreSQL and start docker compose postgres when the configured port is closed.")
    start_db.add_argument("--dry-run", action="store_true", help="Show the planned compose action without starting containers.")
    start_db.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["postgres_ready"], help="How long to wait for PostgreSQL readiness after compose start.")
    start_db.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    start_db.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    start_db.set_defaults(func=command_start_db)

    check_backend = subparsers.add_parser("check-backend", help="Run backend Rust preflight checks: cargo metadata and cargo check.")
    check_backend.add_argument("--dry-run", action="store_true", help="Show what would be checked without running cargo metadata/check.")
    check_backend.add_argument("--metadata-timeout-seconds", type=int, default=TIMEOUT_POLICY["cargo_metadata"], help="Timeout for cargo metadata.")
    check_backend.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["cargo_check"], help="Timeout for cargo check.")
    check_backend.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    check_backend.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    check_backend.set_defaults(func=command_check_backend)

    start_backend = subparsers.add_parser("start-backend", help="Start backend with cargo run, capture logs and wait for health.")
    start_backend.add_argument("--dry-run", action="store_true", help="Show what would be started without running cargo run.")
    start_backend.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["backend_ready"], help="How long to wait for backend health after cargo run.")
    start_backend.add_argument("--no-write-report", action="store_true", help="Skip report files when used with --dry-run; real start still writes logs/state.")
    start_backend.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    start_backend.set_defaults(func=command_start_backend)


    prepare_frontend = subparsers.add_parser("prepare-frontend", help="Install or verify frontend npm dependencies with a devbootstrap marker.")
    prepare_frontend.add_argument("--dry-run", action="store_true", help="Show whether npm ci/install would run without changing node_modules.")
    prepare_frontend.add_argument("--force-install", action="store_true", help="Compatibility alias for --install-mode=always.")
    prepare_frontend.add_argument("--install-mode", choices=["never", "missing", "stale", "missing-or-stale", "always"], default=DEFAULT_FRONTEND_PREPARE_DEP_MODE, help="Dependency preparation policy: never, missing, stale/missing-or-stale, or always.")
    prepare_frontend.add_argument("--allow-npm-install-without-lock", action="store_true", help="Allow fallback to npm install when frontend/package-lock.json is absent; disabled by default for reproducibility.")
    prepare_frontend.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["npm_install"], help="Timeout for npm ci/install.")
    prepare_frontend.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    prepare_frontend.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    prepare_frontend.set_defaults(func=command_prepare_frontend)

    start_frontend = subparsers.add_parser("start-frontend", help="Start frontend with npm run dev, capture logs and wait for Vite root.")
    start_frontend.add_argument("--dry-run", action="store_true", help="Show what would be started without running npm run dev.")
    start_frontend.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["frontend_ready"], help="How long to wait for frontend root after npm run dev.")
    start_frontend.add_argument("--no-write-report", action="store_true", help="Skip report files when used with --dry-run; real start still writes logs/state.")
    start_frontend.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    start_frontend.set_defaults(func=command_start_frontend)

    plan = subparsers.add_parser("plan", help="Build a safe env/bootstrap plan without changing files.")
    plan.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    plan.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    plan.set_defaults(func=command_plan)

    prepare_env = subparsers.add_parser("prepare-env", help="Create missing env files from examples without overwriting existing files.")
    prepare_env.add_argument("--add-missing-keys", action="store_true", help="Append missing keys from examples to existing env files after creating a timestamped backup.")
    prepare_env.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap report files.")
    prepare_env.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    prepare_env.set_defaults(func=command_prepare_env)

    up = subparsers.add_parser("up", help="Run the safe one-command dev environment pipeline.")
    up.add_argument("--dry-run", action="store_true", help="Show the up pipeline without changing env files or starting processes.")
    up.add_argument("--skip-install", action="store_true", help="Skip frontend dependency installation/preparation.")
    up.add_argument("--skip-cargo-check", action="store_true", help="Skip cargo metadata/check before backend start.")
    up.add_argument("--skip-db-start", action="store_true", help="Skip compose-assisted PostgreSQL start.")
    up.add_argument("--skip-backend-start", action="store_true", help="Skip backend process start; useful for clean-machine dry planning.")
    up.add_argument("--skip-frontend-start", action="store_true", help="Skip frontend process start; useful for clean-machine dry planning.")
    up.add_argument("--smoke-level", choices=["quick", "standard", "full", "none"], default="quick", help="Smoke level after startup. Phase 7 implements quick, standard and full smoke gates.")
    up.add_argument("--yes", action="store_true", help="Allow non-destructive automatic steps; this never permits DB reset or killing foreign processes.")
    up.add_argument("--step-timeout-seconds", type=int, default=TIMEOUT_POLICY["up_step"], help="Timeout for short diagnose/plan/prepare-env steps.")
    up.add_argument("--db-timeout-seconds", type=int, default=TIMEOUT_POLICY["postgres_ready"], help="Timeout for start-db readiness.")
    up.add_argument("--cargo-check-timeout-seconds", type=int, default=TIMEOUT_POLICY["cargo_check"], help="Timeout for cargo check.")
    up.add_argument("--backend-timeout-seconds", type=int, default=TIMEOUT_POLICY["backend_ready"], help="Timeout for backend health after cargo run.")
    up.add_argument("--npm-timeout-seconds", type=int, default=TIMEOUT_POLICY["npm_install"], help="Timeout for npm ci/install.")
    up.add_argument("--frontend-timeout-seconds", type=int, default=TIMEOUT_POLICY["frontend_ready"], help="Timeout for frontend readiness after npm run dev.")
    up.add_argument("--smoke-timeout-seconds", type=int, default=TIMEOUT_POLICY["smoke_step"], help="Timeout for smoke substeps launched by up.")
    up.add_argument("--allow-dev-db-write", action="store_true", help="Allow standard/full smoke to write through the live backend API to the configured dev database.")
    up.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    up.set_defaults(func=command_up)


    smoke = subparsers.add_parser("smoke", help="Run post-start smoke gates with clear failure classification.")
    smoke.add_argument("--level", choices=["quick", "standard", "full"], default="quick", help="quick probes HTTP; standard adds backend Python smoke and frontend tests; full adds browser smoke.")
    smoke.add_argument("--allow-dev-db-write", action="store_true", help="Allow backend smoke to write to the configured dev database when TEST_DATABASE_URL is not present.")
    smoke.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["smoke_step"], help="Timeout for each command-based smoke substep.")
    smoke.add_argument("--no-write-report", action="store_true", help="Do not create a standalone smoke report; step logs may still be temporary for command execution.")
    smoke.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    smoke.set_defaults(func=command_smoke)

    release_gates = subparsers.add_parser("release-gates", help="Run keep-going release-gates scaffold and create a shareable report bundle.")
    release_gates.add_argument("--dry-run", action="store_true", help="Create a planned release-gates bundle without executing gate commands.")
    release_gates.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["release_gate"], help="Maximum timeout for each implemented gate command.")
    release_gates.add_argument("--output-dir", help="Write the run directory to this path instead of .dev-bootstrap/runs/<run-id>.")
    release_gates.add_argument("--profile", choices=RELEASE_GATES_PROFILES, help="Release-gates consent/profile preset: diagnostic, prepared-local, isolated-db, managed-runtime or full-local-release.")
    release_gates.add_argument("--allow-dev-db-write", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Allow backend Python smoke to write through the configured live backend API when TEST_DATABASE_URL is not present. Use =false to override a profile.")
    release_gates.add_argument("--managed-runtime", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Start isolated backend/frontend processes on dynamic ports for write-capable release-gates instead of using live ports. Use =false to override a profile.")
    release_gates.add_argument("--managed-test-db", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Create a disposable PostgreSQL database for DB-writing release-gates and run managed gates against it. Use =false to override a profile.")
    release_gates.add_argument("--test-db-retention", choices=["drop-always", "keep-on-failure", "keep-always"], default=None, help="Retention policy for --managed-test-db. Default/profile setting keeps failed runs for investigation and drops successful runs.")
    release_gates.add_argument("--keep-test-db", choices=["on-failure", "always", "never"], help="Compatibility alias for --test-db-retention: on-failure, always or never.")
    release_gates.add_argument("--start-db-if-needed", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="With --managed-test-db, start the project docker compose PostgreSQL service if the configured PostgreSQL port is closed. Use =false to override a profile.")
    release_gates.add_argument("--test-db-admin-user", help="Optional PostgreSQL maintenance/admin role used to create/drop the managed test DB. When supplied, managed runtime also uses these known-good credentials for DATABASE__URL/TEST_DATABASE_URL.")
    release_gates.add_argument("--test-db-admin-password", help="Password for --test-db-admin-user. Prefer --test-db-admin-password-env to avoid exposing secrets in shell history/process listings.")
    release_gates.add_argument("--test-db-admin-password-env", help="Environment variable containing the password for --test-db-admin-user.")
    release_gates.add_argument("--test-db-maintenance-db", default="postgres", help="Maintenance database used for CREATE/DROP DATABASE when --managed-test-db is enabled. Default: postgres.")
    release_gates.add_argument("--dump-test-db-on-failure", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="With --managed-test-db, try pg_dump into the run directory when release-gates fail and the DB is retained. Use =false to override a profile.")
    release_gates.add_argument("--prepare-frontend", action="store_true", help="Compatibility alias for --prepare-deps=stale.")
    release_gates.add_argument("--prepare-deps", nargs="?", const=DEFAULT_FRONTEND_PREPARE_DEP_MODE, choices=["never", "missing", "stale", "missing-or-stale", "always"], help="Prepare frontend/backend dependencies before release gates. Bare --prepare-deps uses stale/missing-or-stale mode.")
    release_gates.add_argument("--install-playwright-browsers", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Run npx playwright install chromium when browser binaries are missing before browser smoke. Use =false to override a profile.")
    release_gates.add_argument("--include-real-backend-browser", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Run the dedicated write-capable real-backend Playwright path when its spec and prerequisites exist. Use =false to override a profile.")
    release_gates.add_argument("--real-backend-browser-spec", default="e2e/smoke/real-backend.smoke.spec.ts", help="Frontend-relative Playwright spec path for the real-backend browser gate.")
    release_gates.add_argument("--include-clean-machine", nargs="?", const="true", default=None, type=parse_optional_bool_arg, metavar="BOOL", help="Run the optional clean-machine sandbox gate in a temporary project copy. Use =false to override a profile.")
    release_gates.add_argument("--clean-machine-profile", choices=CLEAN_MACHINE_PROFILES, default=None, help="Clean-machine sandbox strictness: dry, deps or runtime. The clean-machine-* aliases are accepted too.")
    release_gates.add_argument("--clean-machine-retention", choices=CLEAN_MACHINE_RETENTION_POLICIES, default=None, help="Whether to delete or keep the clean-machine sandbox after the gate.")
    release_gates.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    release_gates.set_defaults(func=command_release_gates)

    status = subparsers.add_parser("status", help="Show devbootstrap runtime state, process liveness, ports and health probes.")
    status.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    status.set_defaults(func=command_status)

    stop = subparsers.add_parser("stop", help="Stop only devbootstrap-tracked backend/frontend processes, and optionally compose postgres.")
    stop.add_argument("--include-db", action="store_true", help="Also stop docker compose postgres service without removing volumes.")
    stop.add_argument("--dry-run", action="store_true", help="Show what would be stopped without terminating processes or compose services.")
    stop.add_argument("--timeout-seconds", type=int, default=TIMEOUT_POLICY["stop_grace"], help="Graceful stop timeout before force kill for owned processes.")
    stop.add_argument("--no-force", action="store_true", help="Do not force kill owned processes after the graceful timeout.")
    stop.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap stop report files.")
    stop.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    stop.set_defaults(func=command_stop)

    self_check = subparsers.add_parser("self-check", help="Run devbootstrap internal v1 hardening fixtures without external packages.")
    self_check.add_argument("--no-write-report", action="store_true", help="Do not create .dev-bootstrap self-check report files.")
    self_check.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout.")
    self_check.set_defaults(func=command_self_check)

    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "keep_test_db", None):
        args.test_db_retention = {"on-failure": "keep-on-failure", "always": "keep-always", "never": "drop-always"}[args.keep_test_db]
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
