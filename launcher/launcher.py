#!/usr/bin/env python3
"""Лаунчер экосистемы p2pKanban (ступень L1: витрина и сверка, только чтение).

    launcher/install.sh                         # один раз: окно на PySide6 (Windows: install.bat)
    python launcher/launcher.py                 # открыть окно
    python launcher/launcher.py status          # то же состояние в терминале
    python launcher/launcher.py status --json   # для UTS и агента
    python launcher/launcher.py status --offline

Ядро — только стандартная библиотека Python 3.11+; окну нужен PySide6 из venv
лаунчера (E-ADR-004 п.2). Ничего не устанавливает из направлений: их команды
появятся в ступени L2 (launcher/docs/ROADMAP.md).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Лаунчеру нужен Python 3.11 или новее")

sys.path.insert(0, str(Path(__file__).resolve().parent))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(errors="replace")  # консоль Windows в cp866 не должна ронять вывод
    except (AttributeError, ValueError):
        pass

from launcher_app import install, paths, state  # noqa: E402

REEXEC_MARK = "P2PKANBAN_LAUNCHER_REEXEC"


def print_status(value: dict) -> None:
    eco, glob = value["ecosystem"], value["global"]
    print(f"p2pKanban Launcher {value['launcher']['version']} ({value['launcher']['stage']}) · {value['host']['label']}")
    local_board, remote_board = eco.get("localBoard") or {}, eco.get("remoteBoard") or {}
    print(f"Доска: у вас патч {local_board.get('boardRevision', '?')} · {local_board.get('lastPatchId', '?')}; "
          f"main: {remote_board.get('boardRevision', '?')} · {remote_board.get('lastPatchId', '?')}")
    source = {"network": "сеть", "cache": "кеш", "none": "нет данных"}.get(glob["source"], glob["source"])
    print(f"Глобальное состояние: {source}" + (f", проверено {glob['checkedAt']}" if glob.get("checkedAt") else "")
          + (f" — {glob['error']}" if glob.get("error") else ""))
    if not value["checkout"]["available"]:
        print(f"Checkout: {value['checkout']['reason']}")
    print()
    for row in value["components"]:
        fit = row["fit"]
        mark = {"yes": "●", "phone": "◐", "no": "○"}[fit["fit"]]
        print(f"{mark} {row['id']:<9} {row['checkout']['label']:<18} {row['summary']}")
        if fit["reason"]:
            print(f"    {fit['reason']}")
        for item in row["requires"]:
            if item["ok"] is False:
                print(f"    ✗ {item['label']}: {item['detail']}" + (f" — {item['hint']}" if item.get("hint") else ""))
        if row["checkout"]["id"] not in ("current", "unknown"):
            print(f"    {row['checkout']['detail']}")
    print("\n«Актуально» — исходники как в main, а не «принято»: приёмку даёт tools/ecosystem/uts.py.")


def qt_problem() -> str | None:
    """None, если окно на PySide6 загрузится в этом интерпретаторе."""
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as error:
        return str(error)
    return None


def run_window(args: argparse.Namespace, argv: list[str]) -> int:
    problem = qt_problem()
    if problem:
        venv = paths.venv_python()
        if venv.is_file() and not os.environ.get(REEXEC_MARK):
            # Тот же лаунчер, но интерпретатором venv, где стоит PySide6.
            env = {**os.environ, REEXEC_MARK: "1"}
            return subprocess.call([str(venv), "-B", str(Path(__file__).resolve()), *argv], env=env)
        script = "launcher\\install.bat" if sys.platform == "win32" else "sh launcher/install.sh"
        if os.environ.get(REEXEC_MARK):
            print(f"Окно не загружается из venv лаунчера: {problem}")
            if ".so" in problem:
                print(install.QT_LIBS_HINT)
            print()
        else:
            print(f"Окна пока нет: PySide6 не установлен. Запустите один раз {script} — он поставит его\n"
                  f"в отдельный venv ({paths.venv_dir()}), системный Python не трогается.\n")
        print_status(state.build_state(offline=args.offline))
        return 3

    from launcher_app import qt_app

    def provider(force: bool) -> dict:
        return state.build_state(force=force, offline=args.offline)

    size = None
    if args.size:
        width, _, height = args.size.partition("x")
        size = (int(width), int(height))
    screenshot = Path(args.screenshot).resolve() if args.screenshot else None
    return qt_app.run(provider, paths.config_dir() / "settings.json", screenshot, args.theme, size)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=state.launcher_version())
    commands = parser.add_subparsers(dest="command")

    gui = commands.add_parser("gui", help="открыть окно (по умолчанию)")
    status = commands.add_parser("status", help="показать состояние в терминале")
    setup = commands.add_parser("install-gui", help="поставить PySide6 в venv лаунчера (это делают install.sh и install.bat)")
    setup.add_argument("--force", action="store_true", help="пересоздать venv")
    for sub in (parser, gui):
        sub.add_argument("--screenshot", help=argparse.SUPPRESS)  # снимок окна для агента и UTS, затем выход
        sub.add_argument("--theme", help=argparse.SUPPRESS)
        sub.add_argument("--size", help=argparse.SUPPRESS)
    for sub in (parser, gui, status):
        sub.add_argument("--offline", action="store_true", help="не ходить в сеть, только кеш")
    status.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    status.add_argument("--refresh", action="store_true", help="не брать кеш моложе 10 минут")

    args = parser.parse_args(argv)
    if args.command == "status":
        value = state.build_state(force=args.refresh, offline=args.offline)
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print_status(value)
        return 0
    if args.command == "install-gui":
        return install.install_gui(force=args.force)
    return run_window(args, argv)


if __name__ == "__main__":
    raise SystemExit(main())
