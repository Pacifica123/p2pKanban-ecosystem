#!/usr/bin/env python3
"""Пользовательская установка abl из этого checkout: собрать пакет pacman и поставить его.

    python3 tools/user_install.py status --json     # для лаунчера (p2p-kanban-launcher-status/1)
    python3 tools/user_install.py install --dry-run # план без сборки
    python3 tools/user_install.py install           # собрать (makepkg) и поставить (pacman -U)
    python3 tools/user_install.py update            # то же, если checkout новее установленного
    python3 tools/user_install.py remove            # pacman -R p2pkanban; данные профиля остаются
    python3 tools/user_install.py launch            # запустить установленный p2pkanban

Это не релизный путь A15: пакет не подписывается и собирается на этой машине
обычным makepkg, без clean chroot. Входы сборки те же — их готовит
tools/a15_prepare_release.py из этого дерева. Права администратора нужны только
pacman: в терминале — sudo, без терминала (из лаунчера) — pkexec.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "p2pkanban"
BINARY = "/usr/bin/p2pkanban"
STATUS_SCHEMA = "p2p-kanban-launcher-status/1"
# Из packaging/arch/PKGBUILD: depends и makedepends, плюс сам makepkg.
DEPENDS = ["gcc-libs", "glib2", "glibc", "gtk3", "webkit2gtk-4.1"]
MAKEDEPENDS = ["cargo", "nodejs", "npm", "pkgconf", "base-devel"]


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def state_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "p2pkanban" / "abl-user-install.json"


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "p2pkanban" / "abl-build"


def read_state() -> dict:
    try:
        value = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write_state(value: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def is_arch() -> bool:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return False
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    ids = {fields.get("ID", "").strip('"')} | set(fields.get("ID_LIKE", "").strip('"').split())
    return "arch" in ids and shutil.which("pacman") is not None


def installed_version() -> str | None:
    if not shutil.which("pacman"):
        return None
    done = run(["pacman", "-Q", PACKAGE])
    if done.returncode != 0:
        return None
    parts = done.stdout.split()
    return parts[1] if len(parts) == 2 else None


def checkout_revision() -> tuple[str | None, bool]:
    """(HEAD монорепозитория, есть ли незакоммиченные правки abl/)."""
    if not shutil.which("git"):
        return None, False
    head = run(["git", "rev-parse", "HEAD"], cwd=ROOT)
    if head.returncode != 0:
        return None, False
    dirty = run(["git", "status", "--porcelain", "--", "."], cwd=ROOT)
    return head.stdout.strip(), bool(dirty.stdout.strip())


def missing_packages() -> list[str]:
    """Пакеты из DEPENDS и MAKEDEPENDS, которых нет (pacman -T для пакетов, -Sg для группы)."""
    missing = []
    names = [name for name in DEPENDS + MAKEDEPENDS if name != "base-devel"]
    done = run(["pacman", "-T", *names])
    missing += [line.strip() for line in done.stdout.splitlines() if line.strip()]
    if not shutil.which("makepkg") or not shutil.which("fakeroot"):
        missing.append("base-devel")
    return missing


def running() -> bool | None:
    if not shutil.which("pgrep"):
        return None
    return run(["pgrep", "-x", PACKAGE]).returncode == 0


def status_payload() -> dict:
    payload = {"schema": STATUS_SCHEMA, "component": "abl", "installed": False, "running": False,
               "version": None, "revision": None, "url": None, "values": {}, "detail": None, "problems": []}
    if not is_arch():
        payload["detail"] = "не Arch-based Linux: abl здесь не ставится"
        payload["running"] = None
        return payload
    version = installed_version()
    if version is None:
        payload["detail"] = "пакет p2pkanban не установлен"
        missing = missing_packages()
        if missing:
            payload["problems"].append("для сборки не хватает пакетов: " + " ".join(missing))
        return payload
    state = read_state()
    payload.update({"installed": True, "running": running(), "version": version})
    if state.get("version") == version and isinstance(state.get("revision"), str):
        payload["revision"] = state["revision"]
        payload["detail"] = f"собран из checkout {state['revision'][:7]} {state.get('installedAt', '')}".strip()
    else:
        payload["detail"] = "пакет p2pkanban установлен не этой командой: из какого коммита — неизвестно"
    return payload


def admin_prefix() -> list[str] | None:
    if sys.stdin.isatty() and shutil.which("sudo"):
        return ["sudo"]
    if shutil.which("pkexec"):
        return ["pkexec"]
    return None


def say(text: str) -> None:
    print(text, flush=True)


def stream(argv: list[str], cwd: Path, env: dict | None = None) -> int:
    say("$ " + " ".join(argv))
    return subprocess.call(argv, cwd=cwd, env=env)


def install(args: argparse.Namespace, only_if_changed: bool = False) -> int:
    if not is_arch():
        say("abl ставится только на Arch-based Linux (Arch, Manjaro, EndeavourOS).")
        return 2
    if os.geteuid() == 0:
        say("Запустите от обычного пользователя: makepkg не собирает от root; пароль спросит только pacman.")
        return 2
    revision, dirty = checkout_revision()
    version = installed_version()
    state = read_state()
    if only_if_changed and version and state.get("version") == version and state.get("revision") == revision and not dirty:
        say(f"Уже установлен пакет из этого checkout ({(revision or '?')[:7]}): обновлять нечего.")
        return 0
    missing = missing_packages()
    stage = cache_dir() / ((revision or "worktree")[:12] + ("-dirty" if dirty else ""))
    admin = admin_prefix()
    say("План установки abl:")
    say(f"- исходники: этот checkout, коммит {(revision or 'неизвестен')[:12]}" + (" + незакоммиченные правки abl/" if dirty else ""))
    say(f"- входы сборки: tools/a15_prepare_release.py → {stage}")
    say(f"- сборка: makepkg {'--check' if args.check else '--nocheck'} (cargo и npm скачают зависимости при первой сборке)")
    say(f"- установка: {' '.join(admin or ['<нет sudo/pkexec>'])} pacman -U --noconfirm <пакет>")
    say(f"- сейчас установлено: {version or 'ничего'}")
    if missing:
        say("Не хватает пакетов: " + " ".join(missing))
        say("Поставьте их: sudo pacman -S --needed " + " ".join(missing))
        return 2
    if admin is None:
        say("Нет ни sudo в терминале, ни pkexec: поставить пакет нечем. Запустите команду в терминале.")
        return 2
    if args.dry_run:
        say("Пробный прогон: ничего не собрано и не установлено.")
        return 0

    code = stream([sys.executable, "-B", str(ROOT / "tools" / "a15_prepare_release.py"),
                   "--cargo-lock", str(ROOT / "src-tauri" / "Cargo.lock"), "--stage", str(stage)], ROOT)
    if code != 0:
        say("Входы сборки не подготовлены.")
        return code
    env = {**os.environ, "PKGDEST": str(stage), "BUILDDIR": str(stage / "build")}
    code = stream(["makepkg", "--force", "--noconfirm", "--check" if args.check else "--nocheck"], stage, env)
    if code != 0:
        say("makepkg не собрал пакет. Вывод выше; повторный запуск начнёт сборку заново.")
        return code
    packages = sorted(stage.glob(f"{PACKAGE}-*.pkg.tar.*"), key=lambda p: p.stat().st_mtime)
    packages = [p for p in packages if not p.name.endswith(".sig")]
    if not packages:
        say(f"Пакет не найден в {stage}.")
        return 1
    code = stream([*admin, "pacman", "-U", "--noconfirm", str(packages[-1])], stage)
    if code != 0:
        say("pacman не установил пакет.")
        return code
    new_version = installed_version()
    write_state({"version": new_version, "revision": None if dirty else revision, "dirty": dirty,
                 "package": packages[-1].name,
                 "installedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")})
    say(f"Готово: p2pkanban {new_version}. Запуск — из меню приложений или командой p2pkanban.")
    return 0


def remove(args: argparse.Namespace) -> int:
    if installed_version() is None:
        say("Пакет p2pkanban не установлен.")
        return 0
    admin = admin_prefix()
    say(f"$ {' '.join(admin or ['sudo'])} pacman -R --noconfirm {PACKAGE}")
    say("Данные профиля (~/.local/share, ~/.config) и секреты в хранилище остаются: pacman их не трогает.")
    if args.dry_run:
        return 0
    if admin is None:
        say("Нет ни sudo в терминале, ни pkexec.")
        return 2
    code = subprocess.call([*admin, "pacman", "-R", "--noconfirm", PACKAGE])
    if code == 0:
        try:
            state_file().unlink()
        except FileNotFoundError:
            pass
    return code


def launch(_args: argparse.Namespace) -> int:
    binary = shutil.which(PACKAGE) or (BINARY if Path(BINARY).is_file() else None)
    if binary is None:
        say("p2pkanban не установлен.")
        return 2
    subprocess.Popen([binary], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    say("p2pkanban запущен.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")
    for name in ("install", "update"):
        sub = commands.add_parser(name)
        sub.add_argument("--dry-run", action="store_true")
        sub.add_argument("--check", action="store_true", help="прогнать cargo test в makepkg (дольше)")
    rm = commands.add_parser("remove")
    rm.add_argument("--dry-run", action="store_true")
    commands.add_parser("launch")
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = status_payload()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"abl: {'установлен ' + payload['version'] if payload['installed'] else 'не установлен'} — {payload['detail']}")
            for problem in payload["problems"]:
                print(f"  {problem}")
        return 0
    if args.command == "install":
        return install(args)
    if args.command == "update":
        return install(args, only_if_changed=True)
    if args.command == "remove":
        return remove(args)
    return launch(args)


if __name__ == "__main__":
    raise SystemExit(main())
