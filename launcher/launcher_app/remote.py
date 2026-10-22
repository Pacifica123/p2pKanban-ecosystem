"""Глобальное состояние: `main` репозитория экосистемы на GitHub.

Для каждого направления — последний коммит `main`, менявший его каталог (так
же считает обновления updater web), и `origin` доски. Ответ кешируется; без
сети отдаётся кеш с пометкой, когда его проверяли (E-ADR-004 п.5).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

TTL_SECONDS = 600
TIMEOUT_SECONDS = 10
USER_AGENT = "p2pkanban-launcher"

Fetch = Callable[[str], bytes]


class RemoteError(Exception):
    pass


def http_get(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (403, 429) and error.headers.get("X-RateLimit-Remaining") == "0":
            raise RemoteError("GitHub ограничил запросы без токена (60 в час); задайте GITHUB_TOKEN или подождите") from error
        raise RemoteError(f"GitHub ответил {error.code} на {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RemoteError(f"нет связи с GitHub: {getattr(error, 'reason', error)}") from error


HISTORY = 10  # последние коммиты каталога: по ним копия без git находит свою версию


def commits_url(repository: str, branch: str, path: str, per_page: int = HISTORY) -> str:
    query = urllib.parse.urlencode({"sha": branch, "path": path, "per_page": per_page})
    return f"https://api.github.com/repos/{repository}/commits?{query}"


def raw_url(repository: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{path}"


def trees_url(repository: str, ref: str, recursive: bool = False) -> str:
    query = "?recursive=1" if recursive else ""
    return f"https://api.github.com/repos/{repository}/git/trees/{urllib.parse.quote(ref, safe='')}{query}"


def compare_url(repository: str, base: str, head: str) -> str:
    return f"https://api.github.com/repos/{repository}/compare/{base}...{head}"


def top_trees(payload: object) -> dict[str, str]:
    """Ответ git/trees корня → {каталог: sha его дерева}."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
        raise ValueError("ответ git/trees не по формату")
    return {item["path"]: item["sha"] for item in payload["tree"]
            if isinstance(item, dict) and item.get("type") == "tree" and isinstance(item.get("path"), str)
            and isinstance(item.get("sha"), str)}


def _one(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    commit = item.get("commit") or {}
    when = (commit.get("committer") or {}).get("date") or (commit.get("author") or {}).get("date")
    message = (commit.get("message") or "").splitlines()
    return {"sha": item.get("sha"), "date": when, "subject": message[0] if message else ""}


def _history(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        return []
    return [commit for commit in (_one(item) for item in payload) if commit and isinstance(commit.get("sha"), str)]


def _commit(payload: object) -> dict | None:
    history = _history(payload)
    return history[0] if history else None


def fetch_global(repository: str, branch: str, directories: list[str], fetch: Fetch = http_get) -> dict:
    """Один запрос на каталог, корень дерева main и доска; ошибка коммитов — RemoteError.

    `trees` — sha дерева каждого каталога в main: по нему копия без git
    сверяется по содержимому (source.py). Без него сверка остаётся git-only.
    """
    result: dict = {"repository": repository, "branch": branch, "directories": {}, "history": {},
                    "trees": None, "board": None}
    for directory in directories:
        payload = json.loads(fetch(commits_url(repository, branch, directory)).decode("utf-8"))
        result["history"][directory] = _history(payload)
        result["directories"][directory] = _commit(payload)
    try:
        result["trees"] = top_trees(json.loads(fetch(trees_url(repository, branch)).decode("utf-8")))
    except (RemoteError, ValueError):
        result["trees"] = None
    try:
        board = json.loads(fetch(raw_url(repository, branch, "board/board.json")).decode("utf-8"))
        origin = board.get("origin") or {}
        result["board"] = {"boardRevision": origin.get("boardRevision"), "lastPatchId": origin.get("lastPatchId")}
    except (RemoteError, ValueError):
        result["board"] = None
    return result


DEFAULT_REPOSITORY = "Pacifica123/p2pKanban-ecosystem"


def remote_ecosystem(cache_file: Path, fetch: Fetch = http_get, offline: bool = False,
                     repository: str = DEFAULT_REPOSITORY, branch: str = "main") -> dict:
    """ecosystem.json из main — для лаунчера, рядом с которым экосистемы ещё нет.

    {ecosystem, source: network|cache|none, error}; кеш — последний удачный ответ.
    """
    def cached() -> dict | None:
        try:
            value = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and isinstance(value.get("components"), list) else None
    if offline:
        value = cached()
        return {"ecosystem": value, "source": "cache" if value else "none", "error": None if value else "без сети, кеша нет"}
    try:
        value = json.loads(fetch(raw_url(repository, branch, "ecosystem.json")).decode("utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("components"), list):
            raise ValueError("ecosystem.json не по формату")
    except (RemoteError, ValueError) as error:
        value = cached()
        return {"ecosystem": value, "source": "cache" if value else "none", "error": str(error)}
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return {"ecosystem": value, "source": "network", "error": None}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GlobalState:
    """Кеш поверх fetch_global: свежий ответ, иначе кеш, иначе ошибка."""

    def __init__(self, cache_file: Path, fetch: Fetch = http_get, clock: Callable[[], float] = time.time):
        self.cache_file = cache_file
        self.fetch = fetch
        self.clock = clock

    def _read_cache(self) -> dict | None:
        try:
            value = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and "data" in value else None

    def _write_cache(self, value: dict) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_file.with_suffix(".tmp")
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.cache_file)
        except OSError:
            pass

    def get(self, repository: str, branch: str, directories: list[str], force: bool = False, offline: bool = False) -> dict:
        cached = self._read_cache()
        same_key = cached and cached.get("key") == [repository, branch, sorted(directories)]
        fresh = same_key and self.clock() - cached.get("checkedEpoch", 0) < TTL_SECONDS
        if same_key and (offline or (fresh and not force)):
            return {**cached["data"], "source": "cache", "checkedAt": cached.get("checkedAt"), "error": None}
        if offline:
            return {"source": "none", "checkedAt": None, "error": "без сети, кеша ещё нет", "directories": {}, "board": None}
        try:
            data = fetch_global(repository, branch, directories, self.fetch)
        except (RemoteError, ValueError) as error:
            if same_key:
                return {**cached["data"], "source": "cache", "checkedAt": cached.get("checkedAt"), "error": str(error)}
            return {"source": "none", "checkedAt": None, "error": str(error), "directories": {}, "board": None}
        checked = now_iso()
        self._write_cache({"key": [repository, branch, sorted(directories)], "checkedEpoch": self.clock(),
                           "checkedAt": checked, "data": data})
        return {**data, "source": "network", "checkedAt": checked, "error": None}
