from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class BrowserCandidate:
    name: str
    path: str
    source: str
    exists: bool
    executable: bool
    version: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrowserDiscoveryResult:
    status: str
    classification: str
    message: str
    platform: str
    chosen: BrowserCandidate | None
    candidates: list[BrowserCandidate]
    install_hints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "tool": "uiux_evidence",
            "kind": "browser-discovery",
            "status": self.status,
            "classification": self.classification,
            "message": self.message,
            "platform": self.platform,
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "installHints": self.install_hints,
        }


PATH_NAMES = [
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "microsoft-edge",
    "msedge",
    "chrome",
]

WINDOWS_PATHS = [
    r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    r"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    r"C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
]

MACOS_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

LINUX_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/brave-browser",
    "/usr/bin/microsoft-edge",
    "/snap/bin/chromium",
]


def _candidate_paths() -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []

    for name in PATH_NAMES:
        found = shutil.which(name)
        if found and found not in seen:
            seen.add(found)
            result.append((name, found, "PATH"))

    system = platform.system().lower()
    explicit = WINDOWS_PATHS if system.startswith("win") else MACOS_PATHS if system == "darwin" else LINUX_PATHS
    for raw in explicit:
        expanded = os.path.expandvars(raw)
        if expanded not in seen:
            seen.add(expanded)
            result.append((Path(expanded).name, expanded, "known-location"))
    return result


def _probe_version(path: str, timeout: float = 4.0) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            [path, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic evidence should keep exact class
        return None, f"{exc.__class__.__name__}: {exc}"
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0 and not output:
        return None, f"version command exited {completed.returncode}"
    return output or None, None


def discover_browsers() -> BrowserDiscoveryResult:
    candidates: list[BrowserCandidate] = []
    for name, path, source in _candidate_paths():
        p = Path(path)
        exists = p.is_file()
        executable = os.access(path, os.X_OK) if exists else False
        version = None
        error = None
        if executable:
            version, error = _probe_version(path)
        candidates.append(
            BrowserCandidate(
                name=name,
                path=path,
                source=source,
                exists=exists,
                executable=executable,
                version=version,
                error=error,
            )
        )
    chosen = next((candidate for candidate in candidates if candidate.exists and candidate.executable), None)
    hints = [
        "Install a Chromium-compatible browser such as Chromium, Google Chrome, Microsoft Edge or Brave.",
        "The UIX runner never downloads browser binaries; rerun discovery after installing a system browser.",
    ]
    if chosen:
        return BrowserDiscoveryResult(
            status="ok",
            classification="ok",
            message=f"selected browser executable: {chosen.path}",
            platform=platform.platform(),
            chosen=chosen,
            candidates=candidates,
            install_hints=hints,
        )
    return BrowserDiscoveryResult(
        status="skipped_prerequisite",
        classification="REL-ENV",
        message="no supported Chromium-compatible browser executable was found",
        platform=platform.platform(),
        chosen=None,
        candidates=candidates,
        install_hints=hints,
    )
