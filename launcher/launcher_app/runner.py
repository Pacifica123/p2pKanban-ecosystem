"""Выполнение объявленных команд направлений (ступень L2).

Лаунчер запускает только то, что собрал entry.command: Python-скрипт
направления, своим интерпретатором, в каталоге направления, без оболочки.
Окно запускает те же argv через QProcess; здесь — общая часть и путь CLI.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import entry as entries, local

StatusRun = Callable[[list[str], Path, dict, float], tuple[int, str]]


def child_python() -> str:
    """Интерпретатор для команд направлений: базовый Python, а не venv с Qt."""
    base = getattr(sys, "_base_executable", None)
    return base if base and Path(base).is_file() else sys.executable


def child_env() -> dict:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "P2PKANBAN_LAUNCHER": "1"})
    env.pop("P2PKANBAN_LAUNCHER_REEXEC", None)
    return env


def resolve(root: Path, command: dict, python: str | None = None) -> dict:
    """Команда контракта → процесс этой машины: {python} заменён, каталог абсолютный."""
    python = python or child_python()
    argv = [python if index == 0 else part for index, part in enumerate(command["argv"])]
    return {**command, "argv": argv, "cwd": str((root / command["cwd"]).resolve())}


def display(argv: list[str]) -> str:
    """Командная строка для показа человеку (не для выполнения)."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    import shlex
    return " ".join(shlex.quote(part) for part in argv)


def capture(argv: list[str], cwd: Path, env: dict, timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as error:
        return 127, str(error)
    return done.returncode, done.stdout


def status(root: Path, entry: dict, given: dict | None = None, run: StatusRun = capture) -> dict:
    """Спросить направление, что установлено. Ничего не меняет."""
    try:
        command = resolve(root, entries.command(entry, "status", given))
    except entries.Rejected as error:
        return {**entries.parse_status(entry, 1, ""), "detail": f"настройки не по объявлению: {error}"}
    code, out = run(command["argv"], Path(command["cwd"]), child_env(), float(command["timeoutSeconds"]))
    parsed = entries.parse_status(entry, code, out)
    if parsed["state"] == "broken":
        parsed["detail"] = {124: "status не ответил вовремя", 127: f"status не запустился: {out.strip()[:200]}"}.get(
            code, "status ответил ошибкой" if parsed["reason"] == "exit-code" else "status ответил не по контракту")
    return parsed


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record(registry_file: Path, command: dict, exit_code: int, dry_run: bool, given: dict | None,
           parsed_status: dict | None = None) -> None:
    """Записать в реестр установок, что лаунчер сделал (пробный прогон не считается установкой)."""
    if dry_run or command["action"] == "status":
        return
    item = {"action": command["action"], "at": now_iso(), "exitCode": exit_code, "argv": command["argv"]}
    fields = {"lastAction": item, "values": dict(given or {}), "root": str(Path(command["cwd"]).parent)}
    if parsed_status and parsed_status.get("state") not in (None, "broken"):
        fields.update({"state": parsed_status["state"], "version": parsed_status.get("version"),
                       "revision": parsed_status.get("revision")})
    if command["action"] == "remove" and exit_code == 0:
        local.forget_install(registry_file, command["component"])
    else:
        local.record_install(registry_file, command["component"], fields)


def stream(command: dict, on_line: Callable[[str], None] = print) -> int:
    """Выполнить и печатать вывод построчно (CLI). Код выхода процесса."""
    env = child_env()
    if command.get("detached"):
        kwargs = {"start_new_session": True} if sys.platform != "win32" else \
            {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        subprocess.Popen(command["argv"], cwd=command["cwd"], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        on_line("запущено отдельно от лаунчера")
        return 0
    try:
        process = subprocess.Popen(command["argv"], cwd=command["cwd"], env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as error:
        on_line(f"не запустилось: {error}")
        return 127
    expired = threading.Event()

    def stop() -> None:
        expired.set()
        process.kill()
    watchdog = threading.Timer(command["timeoutSeconds"], stop)
    watchdog.daemon = True
    watchdog.start()
    try:
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                on_line(line.rstrip("\n"))
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return 130
    finally:
        watchdog.cancel()
    if expired.is_set():
        on_line(f"остановлено: дольше {command['timeoutSeconds']} с")
        return 124
    return code
