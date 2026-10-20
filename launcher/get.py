#!/usr/bin/env python3
"""Новая машина: скачать экосистему p2pKanban и поставить лаунчер одной командой (ступень L5).

Linux, macOS:
    curl -fsSL https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/launcher/get.py | python3 -
Windows (PowerShell или cmd):
    py -c "import urllib.request as u; exec(u.urlopen('https://raw.githubusercontent.com/Pacifica123/p2pKanban-ecosystem/main/launcher/get.py').read())"

Аргументы после `python3 -` (в Windows-строке их нет — берутся умолчания):
    --dir ПУТЬ        куда положить (по умолчанию ~/p2pkanban-ecosystem)
    --only web,abl    sparse: только эти направления (лаунчер и файлы корня — всегда)
    --archive         без git: zip последнего коммита main
    --no-gui          не ставить окно (PySide6, около 80 МБ)

Только стандартная библиотека Python 3.11+. Ничего не ставит в систему: git
clone (или архив) в выбранный каталог и venv лаунчера в каталоге данных
пользователя. Повторный запуск на готовом каталоге обновляет его.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPOSITORY = "Pacifica123/p2pKanban-ecosystem"
BRANCH = "main"
DIRECTIONS = ("web", "mobile", "abl", "devctl", "launcher")
ARCHIVE_MARKER = ".launcher-archive.json"
USER_AGENT = "p2pkanban-launcher-get"


def say(text: str) -> None:
    print(text, flush=True)


def default_dir() -> Path:
    return Path.home() / "p2pkanban-ecosystem"


def http(url: str, timeout: float = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def run(argv: list[str], cwd: Path | None = None) -> int:
    say("$ " + " ".join(argv))
    return subprocess.call(argv, cwd=cwd)


def is_our_checkout(target: Path) -> bool:
    return (target / "ecosystem.json").is_file() and (target / "launcher" / "launcher.py").is_file()


def git_get(target: Path, repository: str, branch: str, only: list[str]) -> int:
    url = f"https://github.com/{repository}.git"
    if (target / ".git").is_dir():
        say(f"{target} уже checkout: обновляю (git pull --ff-only).")
        return run(["git", "-C", str(target), "pull", "--ff-only", "origin", branch])
    argv = ["git", "clone", "--branch", branch, "--filter=blob:none"]
    if only:
        argv.append("--sparse")
    code = run([*argv, url, str(target)])
    if code != 0 or not only:
        return code
    return run(["git", "-C", str(target), "sparse-checkout", "set", "launcher", *only])


def archive_commit(repository: str, branch: str) -> str | None:
    try:
        payload = json.loads(http(f"https://api.github.com/repos/{repository}/commits/{branch}", 30).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    sha = payload.get("sha") if isinstance(payload, dict) else None
    return sha if isinstance(sha, str) and len(sha) == 40 else None


def extract_archive(data: bytes, target: Path, only: list[str] | None) -> int:
    """Распаковать zip GitHub поверх target: файлы перезаписываются, лишние локальные не удаляются."""
    count = 0
    keep = None if not only else {"launcher", *only}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            parts = Path(info.filename).parts[1:]  # первый уровень — <repo>-<branch>/
            if not parts or info.is_dir():
                continue
            if keep is not None and len(parts) > 1 and parts[0] in DIRECTIONS and parts[0] not in keep:
                continue
            if any(part in ("..", "") for part in parts) or Path(*parts).is_absolute():
                continue
            destination = target.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(destination, "wb") as sink:
                shutil.copyfileobj(source, sink)
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111 and os.name != "nt":
                destination.chmod(0o755)
            count += 1
    return count


def archive_get(target: Path, repository: str, branch: str, only: list[str]) -> int:
    commit = archive_commit(repository, branch)
    ref = commit or f"refs/heads/{branch}"
    url = f"https://codeload.github.com/{repository}/zip/{ref}"
    say(f"Скачиваю архив {repository}@{(commit or branch)[:12]}…")
    try:
        data = http(url, 300)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        say(f"Не скачалось: {getattr(error, 'reason', error)}")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    count = extract_archive(data, target, only or None)
    marker = {"repository": repository, "branch": branch, "commit": commit, "only": only or None}
    (target / ARCHIVE_MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"Распаковано файлов: {count}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        say("Нужен Python 3.11 или новее.")
        return 2
    parser = argparse.ArgumentParser(prog="get.py", description="Скачать экосистему p2pKanban и поставить лаунчер.")
    parser.add_argument("--dir", type=Path, default=default_dir())
    parser.add_argument("--only", default="", help="через запятую: web, mobile, abl, devctl")
    parser.add_argument("--archive", action="store_true", help="без git: zip последнего коммита main")
    parser.add_argument("--no-gui", action="store_true", help="не ставить окно на PySide6")
    parser.add_argument("--repo", default=REPOSITORY)
    parser.add_argument("--branch", default=BRANCH)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    only = [item.strip() for item in args.only.split(",") if item.strip()]
    unknown = [item for item in only if item not in DIRECTIONS]
    if unknown:
        say(f"Неизвестные направления: {', '.join(unknown)}; есть {', '.join(DIRECTIONS)}.")
        return 2
    only = [item for item in only if item != "launcher"]
    target = args.dir.expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not is_our_checkout(target):
        say(f"{target} не пуст и это не экосистема p2pKanban: выберите другой --dir.")
        return 2
    use_git = not args.archive and shutil.which("git") is not None and not (target / ARCHIVE_MARKER).is_file()
    if not args.archive and not use_git and not (target / ARCHIVE_MARKER).is_file():
        say("git не найден: беру архив main (обновлять — тоже архивом, launcher.py self-update).")
    say(f"Экосистема → {target}" + (f" (только launcher, {', '.join(only)})" if only else ""))
    code = git_get(target, args.repo, args.branch, only) if use_git else archive_get(target, args.repo, args.branch, only)
    if code != 0:
        return code
    launcher = target / "launcher" / "launcher.py"
    if not args.no_gui:
        code = run([sys.executable, "-B", str(launcher), "install-gui"])
        if code != 0:
            say("Окно не поставилось; лаунчер работает и в терминале: status, run, apk.")
    python = "py" if os.name == "nt" else "python3"
    say("\nГотово. Запуск лаунчера:")
    say(f"  {python} {launcher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
