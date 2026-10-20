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


def commits_url(repository: str, branch: str, path: str) -> str:
    query = urllib.parse.urlencode({"sha": branch, "path": path, "per_page": 1})
    return f"https://api.github.com/repos/{repository}/commits?{query}"


def raw_url(repository: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repository}/{branch}/{path}"


def _commit(payload: object) -> dict | None:
    if not isinstance(payload, list) or not payload:
        return None
    item = payload[0]
    commit = item.get("commit") or {}
    when = (commit.get("committer") or {}).get("date") or (commit.get("author") or {}).get("date")
    message = (commit.get("message") or "").splitlines()
    return {"sha": item.get("sha"), "date": when, "subject": message[0] if message else ""}


def fetch_global(repository: str, branch: str, directories: list[str], fetch: Fetch = http_get) -> dict:
    """Один запрос на каталог и один за доской; ошибка любого — RemoteError."""
    result: dict = {"repository": repository, "branch": branch, "directories": {}, "board": None}
    for directory in directories:
        payload = json.loads(fetch(commits_url(repository, branch, directory)).decode("utf-8"))
        result["directories"][directory] = _commit(payload)
    try:
        board = json.loads(fetch(raw_url(repository, branch, "board/board.json")).decode("utf-8"))
        origin = board.get("origin") or {}
        result["board"] = {"boardRevision": origin.get("boardRevision"), "lastPatchId": origin.get("lastPatchId")}
    except (RemoteError, ValueError):
        result["board"] = None
    return result


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
