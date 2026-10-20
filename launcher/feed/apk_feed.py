#!/usr/bin/env python3
"""Лента APK для лаунчера (p2p-kanban-launcher-apk-feed/1), E-ADR-004 п.6.

Запускает GitHub Action `.github/workflows/launcher-apk-feed.yml` с секретом
репозитория EXPO_TOKEN; результат — apk.json в ветке `launcher-feed`, его
лаунчеры читают без токена. Тот же код лаунчер может выполнить сам, если на
машине задан EXPO_TOKEN.

    EXPO_TOKEN=… python -B launcher/feed/apk_feed.py --root . --out apk.json

Только стандартная библиотека. Токен уходит только в api.expo.dev и никуда не
пишется: ни в ленту, ни в вывод.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA = "p2p-kanban-launcher-apk-feed/1"
ENDPOINT = "https://api.expo.dev/graphql"
LIMIT = 30
ACTIVE = ("NEW", "IN_QUEUE", "IN_PROGRESS")
FIELDS = """
  id status platform distribution buildProfile appVersion appBuildVersion
  gitCommitHash createdAt completedAt expirationDate
  artifacts { buildUrl }
"""
QUERY = """
query Builds($appId: String!, $offset: Int!, $limit: Int!) {
  app { byId(appId: $appId) { id builds(offset: $offset, limit: $limit) { %s } } }
}
"""

Post = Callable[[str, dict], dict]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def graphql_post(token: str) -> Post:
    def post(query: str, variables: dict) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}",
            "User-Agent": "p2pkanban-launcher-apk-feed"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except ValueError:
                return {"errors": [{"message": f"HTTP {error.code}"}]}
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {"errors": [{"message": f"нет связи с api.expo.dev: {getattr(error, 'reason', error)}"}]}
    return post


def fetch_builds(post: Post, project_id: str) -> tuple[list[dict] | None, str | None]:
    """Последние сборки проекта. Поля, которых сервер не знает, выкидываются (как в пробнике eas_probe)."""
    fields = FIELDS
    for _ in range(5):
        answer = post(QUERY % fields, {"appId": project_id, "offset": 0, "limit": LIMIT})
        app = ((answer.get("data") or {}).get("app") or {}).get("byId")
        if app is not None:
            return list(app.get("builds") or []), None
        problems = [str(item.get("message", item)) for item in answer.get("errors") or []]
        rejected = sorted({name for p in problems for name in re.findall(r'Cannot query field "(\w+)"', p)})
        if not rejected:
            return None, "; ".join(problems) or "пустой ответ EAS"
        for name in rejected:
            fields = re.sub(rf"\b{name}\b(\s*\{{[^}}]*\}})?", "", fields)
    return None, "EAS не принял запрос сборок"


def slim(build: dict | None, owner: str, slug: str) -> dict | None:
    if not build:
        return None
    return {
        "id": build.get("id"),
        "status": build.get("status"),
        "profile": build.get("buildProfile"),
        "appVersion": build.get("appVersion"),
        "versionCode": build.get("appBuildVersion"),
        "gitCommit": build.get("gitCommitHash"),
        "createdAt": build.get("createdAt"),
        "completedAt": build.get("completedAt"),
        "expiresAt": build.get("expirationDate"),
        "apkUrl": (build.get("artifacts") or {}).get("buildUrl"),
        "page": f"https://expo.dev/accounts/{owner}/projects/{slug}/builds/{build.get('id')}",
    }


def pick(builds: list[dict], profile: str) -> dict:
    """latest — последняя завершённая APK профиля; building — идущая; lastFailed — упавшая новее latest."""
    mine = [b for b in builds if b.get("platform") == "ANDROID" and (b.get("buildProfile") in (profile, None))]
    newest = lambda items: max(items, key=lambda b: b.get("createdAt") or "", default=None)  # noqa: E731
    finished = [b for b in mine if b.get("status") == "FINISHED"
                and ((b.get("artifacts") or {}).get("buildUrl") or "").lower().endswith(".apk")]
    latest = newest(finished)
    after = (latest or {}).get("createdAt") or ""
    return {
        "latest": latest,
        "building": newest([b for b in mine if b.get("status") in ACTIVE]),
        "lastFailed": newest([b for b in mine if b.get("status") == "ERRORED" and (b.get("createdAt") or "") > after]),
    }


def git(root: Path, *arguments: str) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return done.returncode, done.stdout.strip()


def mobile_head(root: Path, directory: str = "mobile") -> dict | None:
    code, out = git(root, "log", "-1", "--format=%H%x00%cI%x00%s", "--", directory)
    if code != 0 or not out:
        return None
    sha, date, subject = (out.split("\x00") + ["", ""])[:3]
    return {"sha": sha, "date": date, "subject": subject}


def includes(root: Path, older: str, newer: str | None) -> bool | None:
    """Входит ли older в историю newer; None — newer этому репозиторию не известен."""
    if not newer:
        return None
    if git(root, "cat-file", "-e", f"{newer}^{{commit}}")[0] != 0:
        return None
    return git(root, "merge-base", "--is-ancestor", older, newer)[0] == 0


def build_feed(ecosystem: dict, root: Path, token: str | None, post: Post | None = None) -> dict:
    mobile = next((c for c in ecosystem.get("components", []) if c.get("distribution") == "apk"), {})
    eas = mobile.get("eas") or {}
    owner, slug, profile = eas.get("owner", ""), eas.get("slug", ""), eas.get("profile", "preview")
    feed = {
        "schema": SCHEMA,
        "generatedAt": now_iso(),
        "repository": ecosystem.get("repository"),
        "project": {key: eas.get(key) for key in ("owner", "slug", "projectId", "profile")},
        "buildsPage": f"https://expo.dev/accounts/{owner}/projects/{slug}/builds" if owner and slug else None,
        "mobileHead": mobile_head(root, mobile.get("dir", "mobile")),
        "latest": None,
        "building": None,
        "lastFailed": None,
        "fresh": None,
        "error": None,
    }
    if not eas.get("projectId"):
        feed["error"] = "в ecosystem.json нет mobile.eas.projectId"
        return feed
    if not token and post is None:
        feed["error"] = "нет токена Expo (секрет репозитория EXPO_TOKEN)"
        return feed
    builds, error = fetch_builds(post or graphql_post(token or ""), eas["projectId"])
    if builds is None:
        feed["error"] = error
        return feed
    chosen = pick(builds, profile)
    for key, build in chosen.items():
        feed[key] = slim(build, owner, slug)
    if feed["mobileHead"] and feed["latest"]:
        feed["fresh"] = includes(root, feed["mobileHead"]["sha"], feed["latest"]["gitCommit"])
    return feed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="корень checkout экосистемы (с полной историей git)")
    parser.add_argument("--out", required=True, help="куда записать apk.json")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    ecosystem = json.loads((root / "ecosystem.json").read_text(encoding="utf-8"))
    feed = build_feed(ecosystem, root, os.environ.get("EXPO_TOKEN") or None)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = feed["latest"] or {}
    print(f"apk.json: последняя APK {latest.get('appVersion') or '—'} ({(latest.get('gitCommit') or '')[:7]}), "
          f"идёт сборка: {'да' if feed['building'] else 'нет'}, свежая: {feed['fresh']}"
          + (f"; ошибка: {feed['error']}" if feed["error"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
