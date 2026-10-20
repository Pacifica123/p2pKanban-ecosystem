"""Установка окна: venv лаунчера с PySide6 (E-ADR-004 п.2).

Вызывается из launcher/install.sh и launcher/install.bat. venv живёт в каталоге
данных пользователя, а не в checkout (его не захватят снимки devctl) и не в
системном Python (на Arch `pip install` в систему запрещён, PEP 668).
Повторный запуск безопасен: если PySide6 нужной версии уже стоит, ничего не
скачивается.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

REQUIREMENTS = paths.LAUNCHER_DIR / "requirements-gui.txt"
PYTHON_RANGE = ((3, 11), (3, 15))  # ядро — от 3.11; PySide6 6.11 — до 3.14 включительно


def pinned() -> str:
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    raise RuntimeError(f"в {REQUIREMENTS} нет пакета")


QT_LIBS_HINT = ("Qt нужны системные библиотеки графики. На Arch: sudo pacman -S --needed libglvnd libxkbcommon "
                "fontconfig xcb-util-cursor; на Debian/Ubuntu: sudo apt install libegl1 libgl1 libxkbcommon0 "
                "libfontconfig1 libxcb-cursor0.")


def venv_check(requirement: str) -> tuple[bool, str]:
    """Стоит ли нужная версия и импортируется ли окно; иначе — почему нет."""
    python = paths.venv_python()
    if not python.is_file():
        return False, "venv нет"
    name, _, version = requirement.partition("==")
    code = ("import importlib.metadata as m, PySide6.QtWidgets; "
            f"raise SystemExit(0 if m.version({name!r}) == {version!r} else 3)")
    done = subprocess.run([str(python), "-c", code], capture_output=True, text=True, errors="replace")
    if done.returncode == 0:
        return True, ""
    if done.returncode == 3:
        return False, "в venv другая версия PySide6"
    return False, (done.stderr.strip().splitlines() or ["неизвестная ошибка"])[-1]


def step(text: str) -> None:
    print(f"• {text}", flush=True)


def install_gui(force: bool = False) -> int:
    low, high = PYTHON_RANGE
    if not (low <= sys.version_info[:2] < high):
        print(f"Нужен Python {low[0]}.{low[1]}–{high[0]}.{high[1] - 1}, сейчас {sys.version.split()[0]}. "
              "install-скрипт сам ищет подходящий; поставьте его и запустите снова.")
        return 2
    requirement = pinned()
    venv = paths.venv_dir()
    if not force and venv_check(requirement)[0]:
        print(f"Окно уже установлено: {requirement} в {venv}.\nЗапуск: python launcher/launcher.py")
        return 0

    if force and venv.exists():
        step(f"удаляю прежний venv {venv}")
        shutil.rmtree(venv)
    if not paths.venv_python().is_file():
        step(f"создаю venv {venv} (Python {sys.version.split()[0]})")
        venv.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run([sys.executable, "-m", "venv", str(venv)])
        if done.returncode != 0 or not paths.venv_python().is_file():
            print("venv не создался. На Debian и Ubuntu нужен пакет python3-venv "
                  "(sudo apt install python3-venv); на Arch модуль venv входит в python.")
            return 1

    step(f"ставлю {requirement} (одна загрузка около 70 МБ)")
    done = subprocess.run([str(paths.venv_python()), "-m", "pip", "install", "--disable-pip-version-check",
                           "--no-input", "-r", str(REQUIREMENTS)])
    if done.returncode != 0:
        print("pip не справился: проверьте сеть (или прокси) и запустите install-скрипт снова. "
              "Без окна лаунчер работает в терминале: python launcher/launcher.py status")
        return 1
    ok, why = venv_check(requirement)
    if not ok:
        print(f"PySide6 поставился, но окно не загружается: {why}")
        if "lib" in why and ".so" in why:
            print(QT_LIBS_HINT)
        print("Поставьте недостающее и запустите install-скрипт снова: скачанное уже в venv.")
        return 1
    print(f"\nГотово: окно лаунчера установлено ({venv}).\nЗапуск: python launcher/launcher.py")
    if sys.platform.startswith("linux"):
        print("Если окно не откроется с ошибкой про платформу xcb: " + QT_LIBS_HINT)
    return 0
