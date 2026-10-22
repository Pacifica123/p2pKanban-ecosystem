#!/usr/bin/env python3
"""Лаунчер экосистемы p2pKanban.

    launcher/install.sh                         # один раз: окно на PySide6 (Windows: install.bat)
    python launcher/launcher.py                 # открыть окно
    python launcher/launcher.py status          # то же состояние в терминале
    python launcher/launcher.py status --json   # для UTS и агента
    python launcher/launcher.py actions web     # что объявило направление
    python launcher/launcher.py run web install --set port=8091 --dry-run
    python launcher/launcher.py settings web --set listen=lan
    python launcher/launcher.py apk             # ссылка на свежий APK и «ожидайте APK»
    python launcher/launcher.py get abl         # скачать направление с GitHub в эту копию (или в новую)
    python launcher/launcher.py self-update     # обновить эту копию из main (--dry-run — план)
    python launcher/launcher.py doctor          # диагностика: окно, предпосылки, направления, сеть

Новая машина — одной командой, см. launcher/get.py.

Ядро — только стандартная библиотека Python 3.11+; окну нужен PySide6 из venv
лаунчера (E-ADR-004 п.2). Лаунчер выполняет только команды, которые
направление объявило в своём launcher.json (contracts/launcher-entry/1).
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

from launcher_app import doctor, entry as entries, install, local, paths, runner, selfupdate, state  # noqa: E402

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
    alone = eco.get("standalone")
    method = value["checkout"].get("method")
    if alone is not None:
        print(f"Рядом с лаунчером экосистемы нет: направления из main ({alone['source']}). "
              f"Скачать: launcher.py get <направление> → {alone['downloadDir']}")
    elif method == "content":
        print("Копия без git: сверка с main по содержимому файлов.")
    elif method is None:
        print(f"Копия: {value['checkout']['reason']}")
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
        if row.get("status"):
            installed = row["installed"]
            line = f"    установка: {installed['label']}"
            if row["status"].get("url"):
                line += f" · {row['status']['url']}"
            if row["freshness"]["label"]:
                line += f" · {row['freshness']['label']}"
            print(line)
            if installed["detail"]:
                print(f"      {installed['detail']}")
        elif row.get("entryError"):
            print(f"    {row['entryError']}")
        if row.get("apk"):
            value = row["apk"]
            print(f"    APK: {value['label']}" + (f" · {value['version']}" if value.get("version") else "") + f" — {value['detail']}")
            if value.get("apkUrl"):
                print(f"    скачать: {value['apkUrl']}")
            elif value.get("page"):
                print(f"    сборки: {value['page']}")
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


def parse_sets(pairs: list[str], entry: dict) -> dict:
    """--set port=8091 → значения нужного типа по объявлению; пустое значение — «как решит направление»."""
    kinds = {s["id"]: s for s in entry.get("settings", [])}
    out: dict = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or key not in kinds:
            raise entries.Rejected("bad-value", f"{pair}: известны {', '.join(kinds) or 'никакие'}")
        kind = kinds[key]["type"]
        if raw == "":
            out[key] = False if kind == "bool" else None
        elif kind == "port":
            if not raw.isdigit():
                raise entries.Rejected("bad-value", f"{key}: нужен номер порта")
            out[key] = int(raw)
        elif kind == "bool":
            out[key] = raw.lower() in ("1", "true", "yes", "да", "on")
        else:
            out[key] = raw
    return out


def load_entry(component: str) -> tuple[Path, dict] | None:
    root = paths.ecosystem_root()
    info = entries.load(root, component)
    if not info["available"]:
        print(info["error"] or f"{component}: направление не объявило launcher.json — только инструкция в README",
              file=sys.stderr)
        return None
    return root, info["entry"]


def cmd_actions(args: argparse.Namespace) -> int:
    loaded = load_entry(args.component)
    if not loaded:
        return 2
    root, entry = loaded
    saved = entries.clean_values(entry, local.saved_values(paths.registry_file(), args.component))
    if args.json:
        print(json.dumps({"entry": entry, "values": saved}, ensure_ascii=False, indent=2))
        return 0
    print(f"{args.component}: действия")
    for action in entry["actions"]:
        marks = "".join([" [пробный прогон]" if action.get("dryRun") else "", " [спросит пароль]" if action.get("privileged") else "",
                         " [с подтверждением]" if action.get("confirm") else ""])
        print(f"  {action['id']:<10} {action['label']}{marks}")
    if entry.get("settings"):
        print("настройки (сохранено → по умолчанию):")
        for setting in entry["settings"]:
            print(f"  {setting['id']:<10} {setting['label']}: {saved.get(setting['id'], setting.get('default'))!r}"
                  + (f" — {setting['help']}" if setting.get("help") else ""))
    for profile in entry.get("profiles", []):
        mark = "✓" if profile["supported"] else "✗"
        print(f"  {mark} вариант {profile['id']}: {profile['label']}" + ("" if profile["supported"] else f" — {profile['reason']}"))
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    loaded = load_entry(args.component)
    if not loaded:
        return 2
    _, entry = loaded
    registry = paths.registry_file()
    try:
        merged = {**entries.clean_values(entry, local.saved_values(registry, args.component)), **parse_sets(args.set, entry)}
        entries.values(entry, merged)
    except entries.Rejected as error:
        print(f"Настройка не принята: {error}", file=sys.stderr)
        return 2
    if args.set:
        local.save_values(registry, args.component, merged)
    print(json.dumps(merged, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    loaded = load_entry(args.component)
    if not loaded:
        return 2
    root, entry = loaded
    registry = paths.registry_file()
    action_id = args.action
    try:
        given = {**entries.clean_values(entry, local.saved_values(registry, args.component)), **parse_sets(args.set, entry)}
        if args.profile:
            profile = next((p for p in entry.get("profiles", []) if p["id"] == args.profile), None)
            if profile is None:
                raise entries.Rejected("bad-profile", args.profile)
            if not profile["supported"]:
                print(f"Вариант «{profile['label']}» направление пока не умеет: {profile['reason']}", file=sys.stderr)
                return 2
            given.update(profile.get("values") or {})
            missing = [sid for sid in profile.get("ask", []) if given.get(sid) in (None, "")]
            if missing:
                raise entries.Rejected("bad-value", f"для варианта нужно задать {', '.join(missing)} (--set)")
            action_id = profile["action"]
        command = runner.resolve(root, entries.command(entry, action_id, given, args.dry_run))
    except entries.Rejected as error:
        print(f"Не запущено: {error}", file=sys.stderr)
        return 2
    action = entries.find_action(entry, action_id)
    print(f"{action['label']} ({args.component}){' — пробный прогон' if args.dry_run else ''}")
    print(f"$ {runner.display(command['argv'])}")
    print(f"  в {command['cwd']}")
    if command["privileged"]:
        print("  команда сама попросит пароль администратора")
    if action.get("confirm") and not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            print(f"Нужно подтверждение: {action['confirm']} Повторите с --yes.", file=sys.stderr)
            return 2
        if input(f"{action['confirm']} [да/нет] ").strip().lower() not in ("да", "y", "yes", "д"):
            print("Отменено.")
            return 1
    print()
    code = runner.stream(command)
    parsed = runner.status(root, entry, given) if not args.dry_run and action_id != "status" else None
    source_commit = state.source_commit(root, args.component) \
        if not args.dry_run and code == 0 and action_id in runner.SOURCE_ACTIONS else None
    runner.record(registry, command, code, args.dry_run, given, parsed, source_commit)
    print(f"\nКод выхода: {code}" + (f"; теперь: {state.INSTALL_LABELS[parsed['state']]}" if parsed else ""))
    return code


def cmd_get(args: argparse.Namespace) -> int:
    root = paths.ecosystem_root()
    target = Path(args.dir).expanduser().resolve() if args.dir else root or paths.default_download_dir()
    command = runner.get_command(target, ",".join(args.components) or None, args.dry_run)
    print(f"$ {runner.display(command['argv'])}")
    code = runner.stream(command)
    if code == 0 and not args.dry_run and root is None:
        paths.save_root(target)
        print(f"Лаунчер запомнил копию: {target}")
    return code


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

    actions = commands.add_parser("actions", help="что направление объявило лаунчеру: действия, настройки, варианты")
    actions.add_argument("component")
    actions.add_argument("--json", action="store_true")
    configure = commands.add_parser("settings", help="показать или сохранить настройки направления")
    configure.add_argument("component")
    configure.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ")
    run = commands.add_parser("run", help="выполнить объявленное действие направления")
    run.add_argument("component")
    run.add_argument("action", nargs="?", default="status")
    run.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ", help="значение настройки на этот запуск")
    run.add_argument("--profile", help="вариант установки из launcher.json (например, same-node-port)")
    run.add_argument("--dry-run", action="store_true", help="пробный прогон, если направление его объявило")
    run.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")

    apk_cmd = commands.add_parser("apk", help="ссылка на последнюю APK из ленты и её свежесть")
    apk_cmd.add_argument("--json", action="store_true")
    apk_cmd.add_argument("--offline", action="store_true")

    get_cmd = commands.add_parser("get", help="скачать направления с GitHub в эту копию (или в новую, если её нет)")
    get_cmd.add_argument("components", nargs="*", help="web, abl, mobile, devctl; пусто — все")
    get_cmd.add_argument("--dir", help="куда (по умолчанию эта копия или ~/p2pkanban-ecosystem)")
    get_cmd.add_argument("--dry-run", action="store_true")

    update = commands.add_parser("self-update", help="обновить копию лаунчера из main (git, архив или копия без git)")
    update.add_argument("--dry-run", action="store_true")
    self_status = commands.add_parser("self-status", help="ответ status лаунчера о себе (launcher-entry/1)")
    self_status.add_argument("--json", action="store_true")
    check = commands.add_parser("doctor", help="диагностика: ничего не меняет, отчёт JSON в кеше")
    check.add_argument("--json", action="store_true")
    check.add_argument("--offline", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "get":
        return cmd_get(args)
    if args.command == "self-update":
        root = paths.ecosystem_root()
        branch = state.load_ecosystem(root).get("branch", "main") if root else "main"
        return selfupdate.update(root, branch, args.dry_run)
    if args.command == "self-status":
        payload = selfupdate.status_payload(paths.ecosystem_root(), state.launcher_version())
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
              f"лаунчер {payload['version']}: {payload['detail']} {(payload['revision'] or '')[:12]}")
        return 0
    if args.command == "doctor":
        report = doctor.collect(offline=args.offline)
        path = doctor.save(report)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("\n".join(doctor.summary(report)))
            print(f"\nОтчёт: {path}")
        return 0
    if args.command == "apk":
        value = state.build_state(offline=args.offline)
        rows = [row for row in value["components"] if row.get("apk")]
        if args.json:
            print(json.dumps({row["id"]: row["apk"] for row in rows}, ensure_ascii=False, indent=2))
        for row in rows if not args.json else []:
            item = row["apk"]
            print(f"{row['id']}: {item['label']}" + (f" · {item['version']}" if item.get("version") else ""))
            print(f"  {item['detail']}")
            print(f"  {item.get('apkUrl') or item.get('page') or 'ссылки нет'}")
        return 0
    if args.command == "actions":
        return cmd_actions(args)
    if args.command == "settings":
        return cmd_settings(args)
    if args.command == "run":
        return cmd_run(args)
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
