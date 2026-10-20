"""Платформа этой машины и предпосылки из `requires` в ecosystem.json.

Лаунчер ничего не ставит: он только узнаёт, есть ли нужное, и говорит, что
поставить. Каждая проба короткая и не меняет систему.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

Run = Callable[[list[str], float], "tuple[int, str]"]


def run(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


def detect_platform(system: str | None = None, release: dict[str, str] | None = None) -> dict:
    """Ярлыки платформы в словаре `platforms` из ecosystem.json."""
    system = system or platform.system()
    if system == "Windows":
        return {"id": "windows", "tags": ["windows"], "label": "Windows"}
    if system == "Darwin":
        return {"id": "macos", "tags": ["macos"], "label": "macOS"}
    release = os_release() if release is None else release
    family = {release.get("ID", "")} | set(release.get("ID_LIKE", "").split())
    tags = ["linux"]
    if "arch" in family:
        tags.append("arch-linux")
    label = release.get("PRETTY_NAME") or release.get("NAME") or "Linux"
    return {"id": tags[-1], "tags": tags, "label": label}


PLATFORM_NAMES = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
    "arch-linux": "Arch-based Linux",
    "android": "Android",
}


def platform_fit(component_platforms: list[str], host: dict) -> dict:
    """Подходит ли направление этой машине и почему нет."""
    if component_platforms == ["android"]:
        return {"fit": "phone", "reason": "ставится на телефон: APK"}
    if any(tag in component_platforms for tag in host["tags"]):
        return {"fit": "yes", "reason": None}
    names = ", ".join(PLATFORM_NAMES.get(item, item) for item in component_platforms)
    return {"fit": "no", "reason": f"только для {names}" if len(component_platforms) == 1 else f"только для: {names}"}


# --- предпосылки ---------------------------------------------------------

def _python(_run: Run, host: dict) -> dict:
    ok = sys.version_info >= (3, 11)
    return {"ok": ok, "detail": f"Python {platform.python_version()}",
            "hint": None if ok else "нужен Python 3.11 или новее"}


def _docker(_run: Run, host: dict) -> dict:
    desktop = "Docker Desktop (режим Linux containers)" if host["id"] in ("windows", "macos") else "Docker Engine с Compose v2"
    if not shutil.which("docker"):
        return {"ok": False, "detail": "Docker не найден", "hint": f"нужен {desktop}",
                "link": "https://docs.docker.com/get-docker/"}
    code, out = _run(["docker", "info", "--format", "{{.OSType}}"], 10.0)
    if code != 0:
        return {"ok": False, "detail": "Docker установлен, но не запущен",
                "hint": "запустите Docker Desktop" if host["id"] in ("windows", "macos") else "запустите службу docker"}
    os_type = out.strip().splitlines()[-1] if out.strip() else ""
    if os_type and os_type != "linux":
        return {"ok": False, "detail": f"Docker в режиме {os_type} containers",
                "hint": "переключите Docker Desktop на Linux containers"}
    code, out = _run(["docker", "compose", "version", "--short"], 10.0)
    if code != 0:
        return {"ok": False, "detail": "нет Docker Compose v2", "hint": f"нужен {desktop}"}
    return {"ok": True, "detail": f"Docker запущен, Compose {out.strip()}", "hint": None}


def _which(name: str, hint: str) -> Callable[[Run, dict], dict]:
    def probe(_run: Run, host: dict) -> dict:
        found = shutil.which(name)
        return {"ok": bool(found), "detail": f"{name}: {found}" if found else f"{name} не найден",
                "hint": None if found else hint}
    return probe


def _pacman_package(name: str) -> Callable[[Run, dict], dict]:
    def probe(_run: Run, host: dict) -> dict:
        if not shutil.which("pacman"):
            return {"ok": False, "detail": "pacman не найден", "hint": "нужен Arch-based Linux"}
        code, out = _run(["pacman", "-Q", name], 8.0)
        if code == 0:
            return {"ok": True, "detail": out.strip(), "hint": None}
        return {"ok": False, "detail": f"пакет {name} не установлен", "hint": f"sudo pacman -S {name}"}
    return probe


PROBES: dict[str, Callable[[Run, dict], dict]] = {
    "python3.11": _python,
    "docker": _docker,
    "git": _which("git", "нужен git"),
    "pacman": _which("pacman", "нужен Arch-based Linux"),
    "webkit2gtk-4.1": _pacman_package("webkit2gtk-4.1"),
}

LABELS = {
    "python3.11": "Python 3.11+",
    "docker": "Docker",
    "git": "git",
    "pacman": "pacman",
    "webkit2gtk-4.1": "WebKitGTK 4.1",
}


def check_requires(requires: list[str], host: dict, runner: Run = run, memo: dict | None = None) -> list[dict]:
    memo = {} if memo is None else memo
    results = []
    for item in requires:
        if item not in memo:
            probe = PROBES.get(item)
            memo[item] = probe(runner, host) if probe else {"ok": None, "detail": "лаунчер не умеет это проверять", "hint": None}
        results.append({"id": item, "label": LABELS.get(item, item), **memo[item]})
    return results
