#!/bin/sh
# Ставит окно лаунчера: venv с PySide6 в каталоге данных пользователя.
# Системный Python не трогается. Повторный запуск безопасен.
#   launcher/install.sh            поставить или проверить
#   launcher/install.sh --force    пересоздать venv
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)

for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)' 2>/dev/null; then
        "$candidate" -B "$HERE/launcher.py" install-gui "$@"
        exit $?
    fi
done

echo "Не найден Python 3.11–3.14. На Arch: sudo pacman -S python; на Debian/Ubuntu: sudo apt install python3 python3-venv." >&2
exit 1
