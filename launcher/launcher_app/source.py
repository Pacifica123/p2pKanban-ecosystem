"""Сверка копии с `main` по содержимому файлов: без git и без метки архива.

Git хранит файл как blob, его имя — sha1(b"blob <размер>\\0" + содержимое).
GitHub отдаёт дерево каталога с sha каждого файла (`git/trees`), а лаунчер
считает те же sha у файлов на диске. Поэтому одинаково сверяются git-checkout,
архив `main`, «Download ZIP» с GitHub, копия UTS и zip, присланный другом.

Сверяется только то, что есть в `main`: лишние файлы копии (кеши, сборки,
локальное состояние направлений, файлы, удалённые в `main` после архива) не
считаются. Деревья по sha неизменны, поэтому кешируются навсегда: повторная
проверка стоит один запрос корня `main` на всё окно.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from pathlib import Path

from . import remote
from .remote import compare_url, top_trees, trees_url

HISTORY_DEPTH = 10  # сколько последних версий каталога в main искать при несовпадении
FILE_MODES = ("100644", "100755")  # симлинки и подмодули не сверяются
MAX_LISTED = 5


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def file_shas(path: Path) -> set[str]:
    """sha файла как есть и, если в нём CRLF, — как его хранит git (core.autocrlf в Windows)."""
    data = path.read_bytes()
    shas = {blob_sha(data)}
    if b"\r\n" in data:
        shas.add(blob_sha(data.replace(b"\r\n", b"\n")))
    return shas


class Trees:
    """Деревья GitHub по sha с кешем на диске: они не меняются, их можно не перепрашивать."""

    def __init__(self, cache_dir: Path, fetch: remote.Fetch = remote.http_get):
        self.cache_dir, self.fetch = cache_dir, fetch

    def _cached(self, name: str, url: str, parse):
        path = self.cache_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        value = parse(json.loads(self.fetch(url).decode("utf-8")))
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            pass
        return value

    def dir_tree(self, repository: str, commit: str, directory: str) -> str | None:
        """sha дерева каталога на коммите (корень коммита кешируется по его sha)."""
        tops = self._cached(f"root-{commit}.json", trees_url(repository, commit), top_trees)
        return tops.get(directory)

    def listing(self, repository: str, tree: str) -> dict[str, str]:
        """{путь внутри каталога: sha blob} для обычных файлов дерева."""
        def parse(payload: object) -> dict[str, str]:
            if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
                raise ValueError("ответ git/trees не по формату")
            if payload.get("truncated"):
                raise ValueError("GitHub обрезал дерево каталога: слишком много файлов")
            return {item["path"]: item["sha"] for item in payload["tree"]
                    if isinstance(item, dict) and item.get("type") == "blob" and item.get("mode") in FILE_MODES}
        return self._cached(f"tree-{tree}.json", trees_url(repository, tree, recursive=True), parse)

    def contains(self, repository: str, older: str, newer: str) -> bool | None:
        """Есть ли коммит older в истории newer — как `git merge-base --is-ancestor`, но через GitHub."""
        if older == newer:
            return True

        def parse(payload: object) -> dict:
            status = payload.get("status") if isinstance(payload, dict) else None
            if status not in ("identical", "ahead", "behind", "diverged"):
                raise ValueError("ответ compare не по формату")
            return {"status": status, "behindBy": payload.get("behind_by")}
        try:
            value = self._cached(f"compare-{older}-{newer}.json", compare_url(repository, older, newer), parse)
        except (remote.RemoteError, ValueError):
            return None
        return value["status"] in ("identical", "ahead")


class Hashes:
    """sha файлов копии, посчитанные один раз на проверку."""

    def __init__(self, base: Path):
        self.base = base
        self.memo: dict[str, set[str] | None] = {}

    def get(self, relative: str) -> set[str] | None:
        if relative not in self.memo:
            path = self.base.joinpath(*relative.split("/"))
            try:
                self.memo[relative] = file_shas(path) if path.is_file() and not path.is_symlink() else None
            except OSError:
                self.memo[relative] = None
        return self.memo[relative]


def compare(hashes: Hashes, listing: dict[str, str]) -> dict:
    """Файлы каталога main против копии: {same, changed, missing}."""
    changed, missing = [], []
    for relative, sha in sorted(listing.items()):
        mine = hashes.get(relative)
        if mine is None:
            missing.append(relative)
        elif sha not in mine:
            changed.append(relative)
    return {"same": len(listing) - len(changed) - len(missing), "changed": changed, "missing": missing}


def identify(root: Path, directory: str, repository: str, history: list[dict], head_tree: str | None,
             trees: Trees, depth: int = HISTORY_DEPTH) -> dict:
    """С какой версией каталога в main совпадает копия.

    {id: current|outdated|modified|unknown, matched: коммит|None, behind: k, diff: {...} против main, error}
    history — последние коммиты main, менявшие каталог, новые первыми.
    """
    if not (root / directory).is_dir():
        return {"id": "absent", "matched": None, "behind": None, "diff": None, "error": None}
    if not history:
        return {"id": "unknown", "matched": None, "behind": None, "diff": None, "error": "нет истории каталога в main"}
    hashes = Hashes(root / directory)
    head_diff = None
    for index, commit in enumerate(history[:depth]):
        try:
            tree = head_tree if index == 0 and head_tree else trees.dir_tree(repository, commit["sha"], directory)
            if tree is None:
                continue
            diff = compare(hashes, trees.listing(repository, tree))
        except (remote.RemoteError, ValueError, KeyError) as error:
            if index == 0:
                return {"id": "unknown", "matched": None, "behind": None, "diff": None, "error": str(error)}
            return {"id": "modified", "matched": None, "behind": None, "diff": head_diff,
                    "error": f"старые версии не проверены: {error}"}
        if index == 0:
            head_diff = diff
        if not diff["changed"] and not diff["missing"]:
            return {"id": "current" if index == 0 else "outdated", "matched": commit, "behind": index,
                    "diff": head_diff, "error": None}
    return {"id": "modified", "matched": None, "behind": None, "diff": head_diff, "error": None,
            "searched": min(depth, len(history))}


def describe(diff: dict | None) -> str:
    """«изменено файлов: 2 (a.py, b.py); нет: 1 (c.py)» для подсказки."""
    if not diff:
        return ""
    parts = []
    for key, word in (("changed", "изменено"), ("missing", "нет")):
        items = diff[key]
        if items:
            shown = ", ".join(items[:MAX_LISTED]) + (" …" if len(items) > MAX_LISTED else "")
            parts.append(f"{word} файлов: {len(items)} ({shown})")
    return "; ".join(parts)
