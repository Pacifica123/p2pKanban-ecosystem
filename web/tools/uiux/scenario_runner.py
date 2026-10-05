from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .browser_discovery import BrowserDiscoveryResult, discover_browsers
from .chrome_launcher import BrowserProcess, browser_public_payload, launch_browser
from .cdp_client import CdpError, CdpSession
from .evidence import dom_excerpt, redact, truncate_text, write_json, write_text
from .mock_api import MockApiRuntime, start_mock_api

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

REQUIRED_MARKERS = [
    "app-root",
    "app-shell",
    "main-nav",
    "route-outlet",
    "auth-page",
    "auth-mode-sign-in",
    "auth-mode-sign-up",
    "auth-email",
    "auth-password",
    "auth-display-name",
    "auth-submit",
    "auth-error",
    "workspace-list-page",
    "workspace-create-form",
    "workspace-name-input",
    "workspace-description-input",
    "workspace-create-submit",
    "workspace-card",
    "workspace-open-boards",
    "workspace-boards-page",
    "board-create-form",
    "board-name-input",
    "board-description-input",
    "board-create-submit",
    "board-card",
    "board-open",
    "board-page",
    "board-title",
    "column-create-form",
    "column-name-input",
    "column-create-submit",
    "board-column",
    "card-create-input",
    "card-create-submit",
    "card-tile",
    "local-first-status",
    "sync-baseline-status",
    "activity-feed",
    "error-state",
    "loading-state",
]


@dataclass
class EventLog:
    console: list[dict[str, Any]] = field(default_factory=list)
    runtime_errors: list[dict[str, Any]] = field(default_factory=list)
    network: list[dict[str, Any]] = field(default_factory=list)
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def on_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Runtime.consoleAPICalled":
            args = []
            for item in params.get("args", []):
                args.append(item.get("value", item.get("description", "")))
            self.console.append({"type": params.get("type"), "text": " ".join(str(arg) for arg in args), "timestamp": params.get("timestamp")})
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails") or {}
            self.runtime_errors.append({"text": details.get("text"), "url": details.get("url"), "line": details.get("lineNumber"), "column": details.get("columnNumber")})
        elif method == "Log.entryAdded":
            entry = params.get("entry") or {}
            level = entry.get("level")
            text = str(entry.get("text") or "")
            payload = {"type": f"browser-log-{level or 'unknown'}", "text": text, "url": entry.get("url"), "timestamp": entry.get("timestamp")}
            self.console.append(payload)
            # Chromium reports HTTP 4xx/5xx and blocked resource loads through Log.entryAdded
            # as level=error. Those are already captured in the network artifact and are not
            # JavaScript crashes. Fatal UI evidence should stay focused on explicit
            # console.error/assert and Runtime.exceptionThrown signals.
            if level == "fatal":
                self.runtime_errors.append({"text": text, "url": entry.get("url"), "level": level})
        elif method == "Network.requestWillBeSent":
            request = params.get("request") or {}
            request_id = params.get("requestId")
            if request_id:
                self.requests[request_id] = {"method": request.get("method"), "url": request.get("url"), "timestamp": params.get("timestamp")}
        elif method == "Network.responseReceived":
            response = params.get("response") or {}
            request_id = params.get("requestId")
            if request_id:
                self.responses[request_id] = {"status": response.get("status"), "url": response.get("url"), "mimeType": response.get("mimeType")}
        elif method == "Network.loadingFailed":
            request_id = params.get("requestId")
            if request_id:
                self.responses[request_id] = {"failed": True, "errorText": params.get("errorText")}

    def network_summary(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for request_id, request in self.requests.items():
            response = self.responses.get(request_id, {})
            items.append({**request, **response})
        return redact(items)

    def fatal_console_count(self) -> int:
        fatal_console = [item for item in self.console if item.get("type") in {"error", "assert"}]
        return len(fatal_console) + len(self.runtime_errors)


class FrontendStartupPrerequisiteError(RuntimeError):
    classification = "REL-ENV"


@dataclass
class FrontendRuntime:
    process: subprocess.Popen[Any]
    url: str
    log_path: Path

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def free_port(host: str = "127.0.0.1") -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - user configured local/dev URL
            return 200 <= response.status < 500
    except Exception:
        return False


def read_text_tail(path: Path | None, *, max_lines: int = 80, max_chars: int = 12_000) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"<failed to read {path}: {exc.__class__.__name__}: {exc}>"
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        return "<truncated>\n" + tail[-max_chars:]
    return tail


def frontend_startup_failure_message(reason: str, *, url: str, log_path: Path | None = None) -> str:
    message = f"{reason} while waiting for frontend URL {url}"
    if log_path is not None:
        message += f"; frontend log: {log_path.as_posix()}"
    tail = read_text_tail(log_path)
    if tail:
        message += f"; frontend log tail:\n{tail}"
    return message


def wait_for_url(url: str, process: subprocess.Popen[Any] | None = None, timeout: float = 60.0, *, log_path: Path | None = None) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not reachable"
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(frontend_startup_failure_message(f"frontend process exited early with code {process.returncode}", url=url, log_path=log_path))
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:  # noqa: S310 - user configured local/dev URL
                if 200 <= response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
        time.sleep(0.2)
    raise RuntimeError(frontend_startup_failure_message(f"frontend URL did not become reachable ({last_error})", url=url, log_path=log_path))


def resolve_executable_path(executable: str) -> str | None:
    if not executable:
        return None
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
    if effective_platform == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        # Windows package-manager launchers such as npm.cmd are batch files.
        # CreateProcess cannot execute them directly when shell=False, so run
        # them through cmd.exe while keeping args separate for Python quoting.
        return ["cmd.exe", "/d", "/c", "call", resolved, *command[1:]]
    return [resolved, *command[1:]]


def frontend_vite_entry(project_root: Path) -> Path:
    return project_root / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"


def frontend_startup_prerequisite_issue(project_root: Path) -> str | None:
    frontend_dir = project_root / "frontend"
    if not frontend_dir.is_dir():
        return "frontend directory is missing; restore frontend/ before running UIX evidence."
    if not (frontend_dir / "package.json").is_file():
        return "frontend/package.json is missing; restore the frontend manifest before running UIX evidence."
    if not (frontend_dir / "node_modules").is_dir():
        return (
            "frontend/node_modules is missing; run `python tools/devbootstrap.py prepare-frontend --install-mode=stale` "
            "before standalone UIX `--start-frontend`, or run release-gates with dependency preparation enabled."
        )
    if not frontend_vite_entry(project_root).is_file():
        return (
            "frontend dependencies are incomplete: Vite is not installed at frontend/node_modules/vite/bin/vite.js; "
            "run `python tools/devbootstrap.py prepare-frontend --install-mode=stale` to repair node_modules before standalone UIX."
        )
    return None


def frontend_dev_launch_command(project_root: Path, host: str, port: int) -> tuple[list[str], str]:
    vite_entry = frontend_vite_entry(project_root)
    if vite_entry.is_file():
        return ["node", "node_modules/vite/bin/vite.js", "--host", host, "--port", str(port), "--strictPort"], "vite_direct"
    return ["npm", "run", "dev", "--", "--host", host, "--port", str(port), "--strictPort"], "npm_run_dev"


def start_frontend(project_root: Path, report_dir: Path, *, api_base_url: str, host: str = "127.0.0.1") -> FrontendRuntime:
    port = free_port(host)
    url = f"http://{host}:{port}/"
    log_path = report_dir / "frontend.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"VITE_API_BASE_URL": api_base_url.rstrip("/"), "VITE_ENABLE_PROJECT_ROADMAP_SEED": "false"})
    requested_command, launch_mode = frontend_dev_launch_command(project_root, host, port)
    launch_command = command_for_subprocess(requested_command)
    with log_path.open("w", encoding="utf-8") as log_handle:
        log_handle.write(f"dependency preflight: frontend={str((project_root / 'frontend').as_posix())}\n")
        prerequisite_issue = frontend_startup_prerequisite_issue(project_root)
        if prerequisite_issue:
            log_handle.write(f"prerequisite failed: {prerequisite_issue}\n")
            log_handle.flush()
            raise FrontendStartupPrerequisiteError(frontend_startup_failure_message(prerequisite_issue, url=url, log_path=log_path))
        log_handle.write(f"launch mode: {launch_mode}\n")
        log_handle.write(f"requested: {requested_command!r}\n")
        log_handle.write(f"launch: {launch_command!r}\n")
        log_handle.flush()
        try:
            process = subprocess.Popen(launch_command, cwd=project_root / "frontend", env=env, stdout=log_handle, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError as exc:
            log_handle.write(f"launch failed: {exc.__class__.__name__}: {exc}\n")
            raise RuntimeError(f"frontend launch command not found: {launch_command[0]!r} (requested {requested_command[0]!r})") from exc
        except OSError as exc:
            log_handle.write(f"launch failed: {exc.__class__.__name__}: {exc}\n")
            raise
    try:
        wait_for_url(url, process, timeout=80.0, log_path=log_path)
        return FrontendRuntime(process=process, url=url, log_path=log_path)
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise


def load_scenario(name: str) -> dict[str, Any]:
    path = SCENARIOS_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"scenario not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_scenario_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(data.get("name"), str) or not data.get("name"):
        errors.append("name must be a non-empty string")
    if not isinstance(data.get("steps"), list) or not data.get("steps"):
        errors.append("steps must be a non-empty array")
    for index, step in enumerate(data.get("steps", []), start=1):
        if not isinstance(step, dict):
            errors.append(f"step {index} must be an object")
            continue
        keys = set(step)
        allowed = {
            "goto",
            "assertVisible",
            "click",
            "fill",
            "value",
            "valueFrom",
            "assertVisibleText",
            "selector",
            "text",
            "textFrom",
            "assertNetworkSeen",
            "assertNoFatalConsole",
            "waitForVisible",
            "waitForText",
        }
        unknown = keys.difference(allowed)
        if unknown:
            errors.append(f"step {index} has unknown keys: {sorted(unknown)}")
    return errors


def validate_all_scenarios(project_root: Path = ROOT) -> dict[str, Any]:
    scenario_results = []
    errors: list[str] = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scenario_errors = validate_scenario_data(data)
        except Exception as exc:  # noqa: BLE001 - validation report should include class
            data = {"name": path.stem}
            scenario_errors = [f"{exc.__class__.__name__}: {exc}"]
        scenario_results.append({"path": path.relative_to(project_root).as_posix(), "name": data.get("name", path.stem), "errors": scenario_errors})
        errors.extend(f"{path.name}: {item}" for item in scenario_errors)

    source_text = "\n".join(path.read_text(encoding="utf-8") for path in (project_root / "frontend" / "src").rglob("*.tsx")) if (project_root / "frontend" / "src").exists() else ""
    missing_markers = [marker for marker in REQUIRED_MARKERS if f'data-testid="{marker}"' not in source_text and f"data-testid='{marker}'" not in source_text]
    if missing_markers:
        errors.append("missing frontend test markers: " + ", ".join(missing_markers))
    return {
        "schemaVersion": 1,
        "tool": "uiux_evidence",
        "kind": "scenario-validation",
        "status": "ok" if not errors else "failed",
        "classification": "ok" if not errors else "REL-UIUX",
        "message": "scenario and marker contract valid" if not errors else "scenario or marker contract validation failed",
        "scenarios": scenario_results,
        "requiredMarkers": REQUIRED_MARKERS,
        "missingMarkers": missing_markers,
        "errors": errors,
    }


def resolve_value(token: str, generated: dict[str, str]) -> str:
    if token.startswith("generated."):
        return generated[token.split(".", 1)[1]]
    return token


def js_string(value: str) -> str:
    return json.dumps(value)


def selector_exists_expression(selector: str) -> str:
    return f"""
(() => {{
  const el = document.querySelector({js_string(selector)});
  if (!el) return {{ exists: false, visible: false, enabled: false, text: null }};
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const visible = style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  const enabled = !('disabled' in el) || !el.disabled;
  return {{ exists: true, visible, enabled, text: el.textContent || '', tag: el.tagName, id: el.id || null, className: String(el.className || '') }};
}})()
"""


def fill_expression(selector: str, value: str) -> str:
    return f"""
(() => {{
  const el = document.querySelector({js_string(selector)});
  if (!el) throw new Error('selector not found: ' + {js_string(selector)});

  const value = {js_string(value)};
  const prototype = Object.getPrototypeOf(el);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
  const fallbackDescriptor = el instanceof HTMLTextAreaElement
    ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')
    : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  const setter = descriptor && descriptor.set ? descriptor.set : fallbackDescriptor && fallbackDescriptor.set;

  el.focus();
  if (setter) {{
    setter.call(el, value);
  }} else {{
    el.value = value;
  }}
  el.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return true;
}})()
"""


def click_expression(selector: str) -> str:
    return f"""
(() => {{
  const el = document.querySelector({js_string(selector)});
  if (!el) throw new Error('selector not found: ' + {js_string(selector)});
  if ('disabled' in el && el.disabled) throw new Error('selector disabled: ' + {js_string(selector)});
  el.scrollIntoView({{ block: 'center', inline: 'center' }});
  el.click();
  return true;
}})()
"""


def visible_text_expression(selector: str, text: str) -> str:
    return f"""
(() => {{
  const items = [...document.querySelectorAll({js_string(selector)})];
  return items.some((el) => {{
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0 && (el.textContent || '').includes({js_string(text)});
  }});
}})()
"""


def storage_expression() -> str:
    return """
(() => {
  const read = (storage) => {
    const out = {};
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      out[key] = storage.getItem(key);
    }
    return out;
  };
  return { localStorage: read(window.localStorage), sessionStorage: read(window.sessionStorage) };
})()
"""


def wait_until(session: CdpSession, expression: str, *, timeout: float = 12.0, interval: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        session.drain_events(0.05)
        last = session.evaluate(expression, timeout=5.0)
        if last:
            return last
        time.sleep(interval)
    return last


def network_pattern_seen(network: list[dict[str, Any]], pattern: str) -> bool:
    method, _, path_pattern = pattern.partition(" ")
    regex = "^" + re_escape_path(path_pattern).replace("\\*", "[^/]+") + "$"
    for item in network:
        url = item.get("url") or ""
        parsed = urlparse(url)
        path = parsed.path
        if item.get("method") == method and __import__("re").match(regex, path):
            return True
    return False


def re_escape_path(value: str) -> str:
    import re

    return re.escape(value)


def generated_values(scenario_name: str) -> dict[str, str]:
    suffix = f"{int(time.time() * 1000)}-{os.getpid()}"
    return {
        "email": f"uiux-{scenario_name}-{suffix}@local.test",
        "password": f"Password-{suffix}!",
        "displayName": "UIX Evidence User",
        "workspaceName": f"UIX Workspace {suffix}",
        "boardName": f"UIX Board {suffix}",
        "columnName": f"Todo {suffix}",
        "cardTitle": f"UIX Card {suffix}",
    }


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# UI/UX evidence report: {report['scenario']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Classification: `{report['classification']}`",
        f"- Message: {report['message']}",
        f"- Base URL: `{report.get('baseUrl') or '<none>'}`",
        f"- API base URL: `{report.get('apiBaseUrl') or '<none>'}`",
        f"- Browser: `{(report.get('browser') or {}).get('name') or '<none>'}` / `{(report.get('browser') or {}).get('version') or '<unknown>'}`",
        "",
        "## Steps",
        "",
    ]
    for step in report.get("steps", []):
        lines.append(f"- `{step['status']}` {step['name']} — {step.get('message', '')}")
    lines.extend(
        [
            "",
            "## Console/network/storage",
            "",
            f"- Fatal console/runtime count: `{report.get('console', {}).get('fatalCount', 0)}`",
            f"- Warning count: `{report.get('console', {}).get('warningCount', 0)}`",
            f"- API request count: `{report.get('network', {}).get('apiRequestCount', 0)}`",
            f"- Failed API request count: `{report.get('network', {}).get('failedApiRequestCount', 0)}`",
            f"- localStorage changed: `{report.get('storage', {}).get('localStorageChanged')}`",
            f"- sessionStorage changed: `{report.get('storage', {}).get('sessionStorageChanged')}`",
            "",
        ]
    )
    diagnostics = report.get("diagnostics") or {}
    if diagnostics.get("frontendLogTail"):
        lines.extend(["## Frontend startup log tail", "", "```text", str(diagnostics["frontendLogTail"]), "```", ""])
    lines.extend(["## Artifacts", ""])
    for key, value in (report.get("artifacts") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


class ScenarioExecutionError(RuntimeError):
    def __init__(self, message: str, classification: str = "REL-UIUX") -> None:
        super().__init__(message)
        self.classification = classification


def execute_scenario(
    *,
    scenario_name: str,
    report_dir: Path,
    base_url: str | None = None,
    api_base_url: str | None = None,
    browser_executable: str | None = None,
    start_frontend_server: bool = False,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    scenario = load_scenario(scenario_name)
    validation_errors = validate_scenario_data(scenario)
    if validation_errors:
        raise ScenarioExecutionError("invalid scenario: " + "; ".join(validation_errors), "REL-UIUX")

    report_dir.mkdir(parents=True, exist_ok=True)
    mock_runtime: MockApiRuntime | None = None
    frontend_runtime: FrontendRuntime | None = None
    browser: BrowserProcess | None = None
    events = EventLog()
    steps: list[dict[str, Any]] = []
    status = "ok"
    classification = "ok"
    message = "scenario completed"
    generated = generated_values(scenario_name)
    requested_backend = bool((scenario.get("requires") or {}).get("backend"))
    requested_mock = scenario_name.startswith("mocked")
    boot_needs_owned_mock_api = scenario_name == "boot" and start_frontend_server and api_base_url is None

    try:
        if (requested_mock or boot_needs_owned_mock_api) and api_base_url is None:
            mock_runtime = start_mock_api()
            api_base_url = mock_runtime.url
        if start_frontend_server:
            if api_base_url is None:
                raise ScenarioExecutionError("--start-frontend requires --api-base-url or mocked scenario mock API", "REL-PROC")
            frontend_runtime = start_frontend(project_root, report_dir, api_base_url=api_base_url)
            base_url = frontend_runtime.url
        if not base_url:
            raise ScenarioExecutionError("base URL is required when runner does not start frontend", "REL-FE")
        if not http_ok(base_url):
            raise ScenarioExecutionError(f"frontend URL is unreachable: {base_url}", "REL-FE")
        discovery = discover_browsers()
        if not discovery.chosen and not browser_executable:
            write_browser_discovery(report_dir, discovery)
            status = "skipped_prerequisite"
            classification = "REL-ENV"
            message = discovery.message
            return finalize_report(
                scenario_name=scenario_name,
                report_dir=report_dir,
                status=status,
                classification=classification,
                message=message,
                base_url=base_url,
                api_base_url=api_base_url,
                browser_payload=browser_public_payload(None),
                steps=steps,
                generated=generated,
                events=events,
                storage_before={},
                storage_after={},
                final_html="",
            )
        browser = launch_browser(browser_executable or discovery.chosen.path)
        session = CdpSession(browser.websocket_url, on_event=events.on_event)
        try:
            session.command("Page.enable")
            session.command("Runtime.enable")
            session.command("Network.enable")
            session.command("Log.enable")
            storage_before: dict[str, Any] = {}
            storage_after: dict[str, Any] = {}
            final_html = ""
            for index, step in enumerate(scenario["steps"], start=1):
                name = step_name(step)
                started = time.monotonic()
                try:
                    execute_step(session, base_url, step, generated, events)
                    step_status = "ok"
                    step_message = "ok"
                except Exception as exc:  # noqa: BLE001 - evidence should preserve diagnostic text
                    step_status = "failed"
                    step_message = f"{exc.__class__.__name__}: {exc}"
                    final_html = str(session.evaluate("document.documentElement ? document.documentElement.outerHTML : \"\"", timeout=5.0) or "")
                    write_text(report_dir / "dom-excerpt.txt", dom_excerpt(final_html, step.get("assertVisible") or step.get("selector") or None))
                    raise ScenarioExecutionError(f"step {index} failed: {name}: {step_message}", getattr(exc, "classification", "REL-UIUX")) from exc
                finally:
                    duration_ms = int((time.monotonic() - started) * 1000)
                    steps.append({"name": name, "status": step_status, "message": step_message, "durationMs": duration_ms, "step": redact(step)})
                if index == 1:
                    storage_before = session.evaluate(storage_expression(), timeout=5.0) or {}
            session.drain_events(0.3)
            storage_after = session.evaluate(storage_expression(), timeout=5.0) or {}
            final_html = str(session.evaluate("document.documentElement ? document.documentElement.outerHTML : \"\"", timeout=5.0) or "")
            if events.fatal_console_count() > 0:
                raise ScenarioExecutionError("fatal console/runtime errors were captured", "REL-FE")
            return finalize_report(
                scenario_name=scenario_name,
                report_dir=report_dir,
                status=status,
                classification=classification,
                message=message,
                base_url=base_url,
                api_base_url=api_base_url,
                browser_payload=browser_public_payload(None, browser),
                steps=steps,
                generated=generated,
                events=events,
                storage_before=storage_before,
                storage_after=storage_after,
                final_html=final_html,
            )
        finally:
            try:
                session.close()
            except Exception:
                pass
    except ScenarioExecutionError as exc:
        status = "failed" if exc.classification not in {"REL-ENV", "REL-DB"} else "skipped_prerequisite"
        classification = exc.classification
        message = str(exc)
        return finalize_report(
            scenario_name=scenario_name,
            report_dir=report_dir,
            status=status,
            classification=classification,
            message=message,
            base_url=base_url,
            api_base_url=api_base_url,
            browser_payload=browser_public_payload(None, browser),
            steps=steps,
            generated=generated,
            events=events,
            storage_before={},
            storage_after={},
            final_html="",
        )
    except Exception as exc:  # noqa: BLE001
        classification = str(getattr(exc, "classification", "REL-PROC"))
        status = "skipped_prerequisite" if classification in {"REL-ENV", "REL-DB"} else "infra_failed"
        message = f"{exc.__class__.__name__}: {exc}"
        return finalize_report(
            scenario_name=scenario_name,
            report_dir=report_dir,
            status=status,
            classification=classification,
            message=message,
            base_url=base_url,
            api_base_url=api_base_url,
            browser_payload=browser_public_payload(None, browser),
            steps=steps,
            generated=generated,
            events=events,
            storage_before={},
            storage_after={},
            final_html="",
        )
    finally:
        if browser:
            browser.stop()
        if frontend_runtime:
            frontend_runtime.stop()
        if mock_runtime:
            write_json(report_dir / "mock-api-requests.json", mock_runtime.state.request_log)
            mock_runtime.stop()


def write_browser_discovery(report_dir: Path, discovery: BrowserDiscoveryResult) -> None:
    write_json(report_dir / "browser-discovery.json", discovery.to_dict())
    lines = ["# UIX browser discovery", "", f"- Status: `{discovery.status}`", f"- Classification: `{discovery.classification}`", f"- Message: {discovery.message}", "", "## Candidates", ""]
    for item in discovery.candidates:
        lines.append(f"- `{item.path}` — exists={item.exists}, executable={item.executable}, version={item.version or item.error or '<unknown>'}")
    write_text(report_dir / "browser-discovery.md", "\n".join(lines) + "\n")


def step_name(step: dict[str, Any]) -> str:
    for key in ["goto", "assertVisible", "waitForVisible", "click", "fill", "assertVisibleText", "waitForText", "assertNetworkSeen", "assertNoFatalConsole"]:
        if key in step:
            return f"{key} {step[key] if not isinstance(step[key], dict) else ''}".strip()
    return "unknown step"


def execute_step(session: CdpSession, base_url: str, step: dict[str, Any], generated: dict[str, str], events: EventLog) -> None:
    if "goto" in step:
        target = urljoin(base_url.rstrip("/") + "/", str(step["goto"]).lstrip("/"))
        navigation = session.command("Page.navigate", {"url": target})
        error_text = str(navigation.get("errorText") or "")
        if error_text:
            classification = "REL-ENV" if "ERR_BLOCKED_BY_ADMINISTRATOR" in error_text else "REL-FE"
            raise ScenarioExecutionError(f"browser navigation failed for {target}: {error_text}", classification)
        ready = wait_until(session, "document.readyState === 'complete' || document.readyState === 'interactive'", timeout=20.0)
        if not ready:
            current_url = session.evaluate("location.href", timeout=5.0)
            raise ScenarioExecutionError(f"page did not finish loading: {target}; current={current_url}", "REL-FE")
        return
    if "assertVisible" in step or "waitForVisible" in step:
        selector = str(step.get("assertVisible") or step.get("waitForVisible"))
        result = wait_until(session, selector_exists_expression(selector) + ".visible", timeout=15.0)
        if not result:
            state = session.evaluate(selector_exists_expression(selector), timeout=5.0)
            raise ScenarioExecutionError(f"selector not visible: {selector}; state={state}", "REL-UIUX")
        return
    if "fill" in step:
        selector = str(step["fill"])
        value = str(step.get("value") if "value" in step else resolve_value(str(step.get("valueFrom")), generated))
        visible = wait_until(session, selector_exists_expression(selector) + ".visible", timeout=15.0)
        if not visible:
            raise ScenarioExecutionError(f"cannot fill hidden selector: {selector}", "REL-UIUX")
        session.evaluate(fill_expression(selector, value), timeout=8.0)
        return
    if "click" in step:
        selector = str(step["click"])
        state = wait_until(session, selector_exists_expression(selector), timeout=15.0)
        if not state or not state.get("visible") or not state.get("enabled"):
            raise ScenarioExecutionError(f"cannot click selector: {selector}; state={state}", "REL-UIUX")
        session.evaluate(click_expression(selector), timeout=8.0)
        time.sleep(0.15)
        session.drain_events(0.2)
        return
    if "assertVisibleText" in step or "waitForText" in step:
        value = step.get("assertVisibleText") or step.get("waitForText")
        if isinstance(value, dict):
            selector = str(value["selector"])
            text = str(value.get("text") if "text" in value else resolve_value(str(value.get("textFrom")), generated))
        else:
            selector = str(step["selector"])
            text = str(step.get("text") if "text" in step else resolve_value(str(step.get("textFrom")), generated))
        result = wait_until(session, visible_text_expression(selector, text), timeout=20.0)
        if not result:
            raise ScenarioExecutionError(f"text not visible under {selector}: {text}", "REL-UIUX")
        return
    if "assertNetworkSeen" in step:
        pattern = str(step["assertNetworkSeen"])
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            session.drain_events(0.1)
            if network_pattern_seen(events.network_summary(), pattern):
                return
            time.sleep(0.1)
        raise ScenarioExecutionError(f"network pattern not seen: {pattern}", "REL-UIUX")
    if step.get("assertNoFatalConsole") is True:
        session.drain_events(0.2)
        if events.fatal_console_count():
            raise ScenarioExecutionError("fatal console/runtime errors captured", "REL-FE")
        return
    raise ScenarioExecutionError(f"unsupported step: {step}", "REL-UIUX")


def finalize_report(
    *,
    scenario_name: str,
    report_dir: Path,
    status: str,
    classification: str,
    message: str,
    base_url: str | None,
    api_base_url: str | None,
    browser_payload: dict[str, Any],
    steps: list[dict[str, Any]],
    generated: dict[str, str],
    events: EventLog,
    storage_before: dict[str, Any],
    storage_after: dict[str, Any],
    final_html: str,
) -> dict[str, Any]:
    network = events.network_summary()
    api_count = sum(1 for item in network if "/api/v1" in str(item.get("url")))
    failed_api_count = sum(1 for item in network if "/api/v1" in str(item.get("url")) and (item.get("failed") or int(item.get("status") or 0) >= 400))
    artifacts = {
        "domFinal": "dom-final.html",
        "domExcerpt": "dom-excerpt.txt",
        "console": "console.json",
        "runtimeErrors": "runtime-errors.json",
        "network": "network.json",
        "storageBefore": "storage-before.json",
        "storageAfter": "storage-after.json",
        "frontendLog": "frontend.log",
    }
    frontend_log_tail = read_text_tail(report_dir / "frontend.log")
    diagnostics = {"frontendLogTail": frontend_log_tail} if frontend_log_tail else {}
    report = {
        "schemaVersion": 1,
        "tool": "uiux_evidence",
        "scenario": scenario_name,
        "status": status,
        "classification": classification,
        "message": message,
        "baseUrl": base_url,
        "apiBaseUrl": api_base_url,
        "browser": browser_payload,
        "generated": {key: ("<redacted>" if key == "password" else value) for key, value in generated.items()},
        "steps": steps,
        "console": {"fatalCount": events.fatal_console_count(), "warningCount": sum(1 for item in events.console if item.get("type") == "warning")},
        "network": {"apiRequestCount": api_count, "failedApiRequestCount": failed_api_count},
        "storage": {"localStorageChanged": storage_before.get("localStorage") != storage_after.get("localStorage"), "sessionStorageChanged": storage_before.get("sessionStorage") != storage_after.get("sessionStorage")},
        "artifacts": artifacts,
        "diagnostics": diagnostics,
    }
    write_json(report_dir / "report.json", report)
    write_text(report_dir / "report.md", report_markdown(report))
    write_text(report_dir / "dom-final.html", truncate_text(final_html or ""))
    write_text(report_dir / "dom-excerpt.txt", dom_excerpt(final_html or ""))
    write_json(report_dir / "console.json", events.console)
    write_json(report_dir / "runtime-errors.json", events.runtime_errors)
    write_json(report_dir / "network.json", network)
    write_json(report_dir / "storage-before.json", storage_before)
    write_json(report_dir / "storage-after.json", storage_after)
    return report
