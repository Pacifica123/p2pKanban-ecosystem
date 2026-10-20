"""`launcher.py doctor`: всё, что нужно, чтобы понять, почему что-то не ставится (ступень L5).

Ничего не меняет. Отчёт — JSON в каталоге кеша лаунчера и короткая сводка в
терминале; его можно приложить к вопросу. Секретов в отчёте нет: токены
только отмечаются как «задан / не задан».
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import apk, entry as entries, local, paths, probes, remote, runner, selfupdate, state

SCHEMA = "p2p-kanban-launcher-doctor/1"
ALL_REQUIRES = ("python3.11", "docker", "git", "pacman", "webkit2gtk-4.1")


def _gui() -> dict:
    venv = paths.venv_python()
    result = {"venv": str(paths.venv_dir()), "exists": venv.is_file(), "pyside6": None, "error": None}
    if not venv.is_file():
        result["error"] = "venv лаунчера ещё нет: install.sh / install.bat"
        return result
    try:
        done = subprocess.run([str(venv), "-c", "import PySide6, PySide6.QtWidgets; print(PySide6.__version__)"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        result["error"] = str(error)
        return result
    if done.returncode == 0:
        result["pyside6"] = done.stdout.strip()
    else:
        result["error"] = (done.stderr.strip().splitlines() or ["PySide6 не загружается"])[-1]
    return result


def _reach(url: str, fetch: remote.Fetch, missing_ok: str | None = None) -> dict:
    try:
        fetch(url)
    except remote.RemoteError as error:
        if missing_ok and " 404 " in str(error):
            return {"url": url, "ok": None, "detail": missing_ok}
        return {"url": url, "ok": False, "detail": str(error)}
    return {"url": url, "ok": True, "detail": "отвечает"}


def collect(root: Path | None = None, fetch: remote.Fetch = remote.http_get, offline: bool = False,
            status_run: runner.StatusRun | None = runner.capture) -> dict:
    root = paths.ecosystem_root() if root is None else root
    host = probes.detect_platform()
    ecosystem = state.load_ecosystem(root)
    repository, branch = ecosystem.get("repository"), ecosystem.get("branch", "main")
    memo: dict = {}
    requires = probes.check_requires(list(ALL_REQUIRES), host, probes.run, memo)
    problems: list[str] = []
    for item in requires:
        if item["ok"] is False and item["id"] in ("python3.11", "git"):
            problems.append(f"{item['label']}: {item['detail']}")

    directions = []
    registry = local.read_registry(paths.registry_file())
    for component in ecosystem.get("components", []):
        info = entries.load(root, component["dir"])
        fit = probes.platform_fit(component.get("platforms", []), host)
        row = {"id": component["id"], "fit": fit["fit"], "entry": info["available"], "entryError": info["error"],
               "status": None, "savedValues": registry["settings"].get(component["id"]) or {}}
        if info["error"]:
            problems.append(info["error"])
        if info["available"] and fit["fit"] == "yes" and status_run is not None:
            value = runner.status(root, info["entry"], entries.clean_values(info["entry"], row["savedValues"]), status_run)
            row["status"] = {key: value.get(key) for key in ("state", "version", "revision", "url", "detail", "problems")}
            if value["state"] == "broken":
                problems.append(f"{component['id']}: status — {value['detail']}")
        directions.append(row)

    network = []
    if repository and not offline:
        network = [_reach(remote.commits_url(repository, branch, "launcher"), fetch),
                   _reach(remote.raw_url(repository, branch, "ecosystem.json"), fetch),
                   _reach(apk.feed_url(repository), fetch, "ленты APK ещё нет: Action launcher-apk-feed не запускался")]
        for item in network[:2]:
            if not item["ok"]:
                problems.append(f"сеть: {item['detail']}")

    data = paths.data_dir()
    usage_root = data if data.exists() else Path.home()
    free = shutil.disk_usage(usage_root).free
    if free < 2 * 1024 ** 3:
        problems.append(f"свободно меньше 2 ГБ ({free // 1024 ** 2} МБ): сборка web и abl может не влезть")
    return {
        "schema": SCHEMA,
        "launcher": {"version": state.launcher_version(), "stage": state.STAGE, "dir": str(paths.LAUNCHER_DIR)},
        "python": {"version": platform.python_version(), "executable": sys.executable,
                   "childPython": runner.child_python()},
        "host": host,
        "gui": _gui(),
        "checkout": {"root": str(root) if root else None, "mode": selfupdate.mode(root),
                     "revision": selfupdate.revision(root)},
        "paths": {"config": str(paths.config_dir()), "cache": str(paths.cache_dir()), "data": str(data),
                  "freeBytes": free},
        "tokens": {"GITHUB_TOKEN": bool(os.environ.get("GITHUB_TOKEN")), "EXPO_TOKEN": bool(os.environ.get("EXPO_TOKEN"))},
        "requires": requires,
        "directions": directions,
        "network": network,
        "problems": problems,
    }


def save(report: dict) -> Path:
    folder = paths.cache_dir() / "doctor"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = runner.now_iso().replace(":", "").replace("-", "")
    path = folder / f"doctor-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def summary(report: dict) -> list[str]:
    gui = report["gui"]
    lines = [f"Лаунчер {report['launcher']['version']} · Python {report['python']['version']} · {report['host']['label']}",
             f"Окно: {'PySide6 ' + gui['pyside6'] if gui['pyside6'] else gui['error']}",
             f"Checkout: {report['checkout']['mode']} {(report['checkout']['revision'] or '')[:12]} ({report['checkout']['root']})"]
    for item in report["requires"]:
        mark = "✓" if item["ok"] else "✗" if item["ok"] is False else "?"
        lines.append(f"  {mark} {item['label']}: {item['detail']}")
    for row in report["directions"]:
        status = row["status"] or {}
        text = status.get("state") or ("нет launcher.json" if not row["entry"] else
                                        "не для этой платформы" if row["fit"] == "no" else "на телефоне")
        lines.append(f"  {row['id']:<9} {text}" + (f" — {status.get('detail')}" if status.get("detail") else ""))
    for item in report["network"]:
        mark = "✓" if item["ok"] else "✗" if item["ok"] is False else "·"
        lines.append(f"  {mark} {item['url']}: {item['detail']}")
    lines.append("Проблемы: " + ("нет" if not report["problems"] else ""))
    lines += [f"  • {problem}" for problem in report["problems"]]
    return lines
