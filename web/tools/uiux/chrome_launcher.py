from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .browser_discovery import BrowserCandidate, discover_browsers


@dataclass
class BrowserProcess:
    executable: str
    port: int
    user_data_dir: tempfile.TemporaryDirectory[str]
    process: subprocess.Popen[Any]
    websocket_url: str
    version: dict[str, Any]

    def stop(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.user_data_dir.cleanup()


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def read_json_url(url: str, timeout: float = 1.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "uiux-evidence/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - local CDP HTTP endpoint only
        return json.loads(response.read().decode("utf-8"))


def wait_for_version(port: int, process: subprocess.Popen[Any], timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr_tail = ""
            try:
                stderr_tail = (process.stderr.read() if process.stderr else "")[-600:]
            except Exception:
                stderr_tail = ""
            detail = f"; stderr tail: {stderr_tail.strip()}" if stderr_tail.strip() else ""
            raise RuntimeError(f"browser exited before CDP opened with code {process.returncode}{detail}")
        try:
            return read_json_url(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            time.sleep(0.15)
    raise RuntimeError(f"CDP endpoint did not open on port {port}: {last_error}")


def launch_browser(executable: str | None = None, *, headless: bool = True, extra_args: list[str] | None = None) -> BrowserProcess:
    if executable is None:
        discovery = discover_browsers()
        if not discovery.chosen:
            raise RuntimeError(discovery.message)
        executable = discovery.chosen.path
    port = find_free_port()
    profile = tempfile.TemporaryDirectory(prefix="uiux-browser-profile-")
    args = [
        executable,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile.name}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-sync",
        "--metrics-recording-only",
    ]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    if headless:
        args.append("--headless=new")
    args.extend(extra_args or [])
    args.append("about:blank")
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        version = wait_for_version(port, process)
        tabs = read_json_url(f"http://127.0.0.1:{port}/json/list", timeout=1.0)
        page_tabs = [tab for tab in tabs if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl")]
        if not page_tabs:
            target = read_json_url(f"http://127.0.0.1:{port}/json/new?about:blank", timeout=1.0)
            websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        else:
            websocket_url = str(page_tabs[0]["webSocketDebuggerUrl"])
        if not websocket_url:
            raise RuntimeError("CDP page websocket URL is unavailable")
        return BrowserProcess(executable=executable, port=port, user_data_dir=profile, process=process, websocket_url=websocket_url, version=version)
    except Exception:
        try:
            if process.poll() is None:
                process.terminate()
        finally:
            profile.cleanup()
        raise


def browser_public_payload(candidate: BrowserCandidate | None, process: BrowserProcess | None = None) -> dict[str, Any]:
    if process:
        return {
            "name": Path(process.executable).name,
            "executable": process.executable,
            "version": process.version.get("Browser"),
            "webSocketDebuggerUrl": "<redacted-local-cdp>",
        }
    if candidate:
        return {"name": candidate.name, "executable": candidate.path, "version": candidate.version}
    return {"name": None, "executable": None, "version": None}
