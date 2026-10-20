"""Ссылка на APK и «ожидайте APK» (ступень L4, E-ADR-004 п.6).

Лента `apk.json` лежит в ветке `launcher-feed`: её пишет GitHub Action с
секретом EXPO_TOKEN, лаунчер читает без токена. Если на машине задан
EXPO_TOKEN, лаунчер может собрать ту же ленту сам (`feed/apk_feed.py`).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import paths, remote

FEED_SCHEMA = "p2p-kanban-launcher-apk-feed/1"
FEED_BRANCH = "launcher-feed"
TTL_SECONDS = 300

VERDICTS = {
    "current": "свежий APK",
    "awaiting": "ожидайте APK",
    "building": "собирается",
    "expired": "ссылка истекла",
    "none": "сборок ещё нет",
    "unknown": "свежесть неизвестна",
}


def feed_url(repository: str) -> str:
    return remote.raw_url(repository, FEED_BRANCH, "apk.json")


def builds_page(eas: dict | None) -> str | None:
    eas = eas or {}
    if eas.get("owner") and eas.get("slug"):
        return f"https://expo.dev/accounts/{eas['owner']}/projects/{eas['slug']}/builds"
    return None


def _valid(feed: object) -> bool:
    return isinstance(feed, dict) and feed.get("schema") == FEED_SCHEMA


class Feed:
    """Лента с кешем: свежая, иначе кеш, иначе ошибка (как глобальное состояние)."""

    def __init__(self, cache_file: Path, fetch: remote.Fetch = remote.http_get, clock: Callable[[], float] = time.time):
        self.cache_file, self.fetch, self.clock = cache_file, fetch, clock

    def _cache(self) -> dict | None:
        try:
            value = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and _valid(value.get("feed")) else None

    def get(self, repository: str, force: bool = False, offline: bool = False) -> dict:
        cached = self._cache()
        same = cached and cached.get("repository") == repository
        fresh = same and self.clock() - cached.get("checkedEpoch", 0) < TTL_SECONDS
        if same and (offline or (fresh and not force)):
            return {"feed": cached["feed"], "source": "cache", "error": None}
        if offline:
            return {"feed": None, "source": "none", "error": "без сети, ленты в кеше нет"}
        try:
            feed = json.loads(self.fetch(feed_url(repository)).decode("utf-8"))
            if not _valid(feed):
                raise ValueError("лента не по формату")
        except remote.RemoteError as error:
            message = str(error)
            if " 404 " in message:
                message = "ленты APK ещё нет: GitHub Action launcher-apk-feed не запускался"
            if same:
                return {"feed": cached["feed"], "source": "cache", "error": message}
            return {"feed": None, "source": "none", "error": message}
        except ValueError as error:
            return {"feed": cached["feed"] if same else None, "source": "cache" if same else "none",
                    "error": f"лента APK не читается: {error}"}
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_file.with_suffix(".tmp")
            temp.write_text(json.dumps({"repository": repository, "checkedEpoch": self.clock(), "feed": feed},
                                       ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self.cache_file)
        except OSError:
            pass
        return {"feed": feed, "source": "network", "error": None}


def local_feed(root: Path, ecosystem: dict) -> dict | None:
    """Своя лента по EXPO_TOKEN этой машины, если он задан (запасной путь)."""
    token = os.environ.get("EXPO_TOKEN")
    if not token:
        return None
    import sys
    sys.path.insert(0, str(paths.LAUNCHER_DIR))
    from feed import apk_feed  # noqa: WPS433 — тот же код, что в GitHub Action

    return {"feed": apk_feed.build_feed(ecosystem, root, token), "source": "local", "error": None}


def _expired(build: dict, now: datetime) -> bool:
    value = build.get("expiresAt")
    if not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) < now
    except ValueError:
        return False


def verdict(got: dict, main_commit: dict | None, eas: dict | None, now: datetime | None = None) -> dict:
    """{id, label, detail, apkUrl, page, version, building} для карточки Android."""
    now = now or datetime.now(timezone.utc)
    feed = got.get("feed")
    out = {"apkUrl": None, "page": builds_page(eas), "version": None, "building": None,
           "source": got.get("source"), "generatedAt": (feed or {}).get("generatedAt")}

    def say(kind: str, detail: str) -> dict:
        return {**out, "id": kind, "label": VERDICTS[kind], "detail": detail}

    if not feed:
        return say("unknown", got.get("error") or "ленты APK нет")
    out["page"] = feed.get("buildsPage") or out["page"]
    latest, building = feed.get("latest"), feed.get("building")
    if building:
        out["building"] = {"page": building.get("page"), "createdAt": building.get("createdAt"),
                           "gitCommit": building.get("gitCommit")}
    if latest:
        out.update({"apkUrl": latest.get("apkUrl"), "page": latest.get("page") or out["page"],
                    "version": " · ".join(str(v) for v in (latest.get("appVersion"), latest.get("versionCode")) if v)})
    elif building:
        return say("building", "первая сборка идёт")
    else:
        return say("none", feed.get("error") or "в EAS нет завершённых Android-сборок профиля")
    head = feed.get("mobileHead") or {}
    theirs = (main_commit or {}).get("sha")
    built = (latest.get("gitCommit") or "")[:7]
    if theirs and head.get("sha") and theirs != head["sha"]:
        if building:
            return say("building", "идёт сборка; лента ещё не видела последний коммит mobile/ в main")
        return say("awaiting", f"в main новый коммит mobile/: {main_commit.get('subject') or theirs[:7]}; "
                               "лента обновится в течение 20 минут после push")
    if _expired(latest, now):
        return say("building" if building else "expired",
                   "срок хранения APK в EAS истёк" + ("; идёт новая сборка" if building else "; нужна новая сборка"))
    fresh = feed.get("fresh")
    if fresh is True:
        return say("current", f"сборка {built} включает последний коммит mobile/ в main")
    if fresh is False:
        if building:
            return say("building", f"идёт сборка; последняя готовая {built} старше коммита mobile/: {head.get('subject', '')}")
        return say("awaiting", f"в mobile/ есть коммит новее сборки {built}: {head.get('subject', '')}")
    return say("unknown", "коммит сборки неизвестен истории main (собрано из локальных правок?)"
               + (f"; ошибка ленты: {feed['error']}" if feed.get("error") else ""))
