"""Лента APK (L4): сборка ленты из ответа EAS и вердикт для карточки Android. Без сети и токена.

    cd launcher && python -B -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feed import apk_feed  # noqa: E402
from launcher_app import apk, remote  # noqa: E402

EAS = {"owner": "me", "slug": "app", "projectId": "p-1", "profile": "preview"}
ECOSYSTEM = {"repository": "o/r", "components": [{"id": "mobile", "dir": "mobile", "distribution": "apk", "eas": EAS}]}
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def build(bid: str, status: str, created: str, commit: str | None = None, url: str | None = None, profile: str = "preview",
          platform: str = "ANDROID", expires: str = "2026-11-19T00:00:00Z") -> dict:
    return {"id": bid, "status": status, "platform": platform, "buildProfile": profile, "appVersion": "2.1.0",
            "appBuildVersion": "26", "gitCommitHash": commit, "createdAt": created, "completedAt": created,
            "expirationDate": expires, "artifacts": {"buildUrl": url}}


@unittest.skipUnless(shutil.which("git"), "нужен git")
class FeedBuildTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.root / "mobile").mkdir()
        (self.root / "mobile" / "a.txt").write_text("1", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", "mobile: первый")
        self.first = self.git("rev-parse", "HEAD").strip()
        (self.root / "mobile" / "a.txt").write_text("2", encoding="utf-8")
        self.git("commit", "-qam", "mobile: второй")
        self.second = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def git(self, *arguments: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *arguments], cwd=self.root, check=True, capture_output=True, text=True, env=env).stdout

    def feed(self, builds: list[dict], rejected_first: bool = False) -> dict:
        calls = []

        def post(query: str, variables: dict) -> dict:
            calls.append(query)
            if rejected_first and len(calls) == 1:
                return {"errors": [{"message": 'Cannot query field "expirationDate" on type "Build".'}]}
            return {"data": {"app": {"byId": {"id": "p-1", "builds": builds}}}}
        value = apk_feed.build_feed(ECOSYSTEM, self.root, None, post)
        self.calls = calls
        return value

    def test_latest_apk_building_and_fresh(self):
        value = self.feed([
            build("old", "FINISHED", "2026-10-18T10:00:00Z", self.first, "https://x/old.apk"),
            build("new", "FINISHED", "2026-10-19T10:00:00Z", self.second, "https://x/new.apk"),
            build("aab", "FINISHED", "2026-10-19T11:00:00Z", self.second, "https://x/app.aab"),
            build("prod", "FINISHED", "2026-10-19T12:00:00Z", self.second, "https://x/p.apk", profile="production"),
            build("ios", "FINISHED", "2026-10-19T12:00:00Z", self.second, "https://x/i.ipa", platform="IOS"),
            build("run", "IN_PROGRESS", "2026-10-20T09:00:00Z", self.second),
        ])
        self.assertEqual(value["schema"], apk_feed.SCHEMA)
        self.assertEqual(value["latest"]["id"], "new")
        self.assertEqual(value["latest"]["page"], "https://expo.dev/accounts/me/projects/app/builds/new")
        self.assertEqual(value["building"]["id"], "run")
        self.assertEqual(value["mobileHead"]["sha"], self.second)
        self.assertIs(value["fresh"], True)
        self.assertIsNone(value["error"])

    def test_commit_newer_than_build_is_not_fresh(self):
        value = self.feed([build("old", "FINISHED", "2026-10-18T10:00:00Z", self.first, "https://x/old.apk")])
        self.assertIs(value["fresh"], False)

    def test_unknown_field_is_dropped_and_retried(self):
        value = self.feed([build("old", "FINISHED", "2026-10-18T10:00:00Z", self.first, "https://x/old.apk")], rejected_first=True)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("expirationDate", self.calls[1])
        self.assertEqual(value["latest"]["id"], "old")

    def test_no_token_is_said_not_crashed(self):
        value = apk_feed.build_feed(ECOSYSTEM, self.root, None)
        self.assertIn("EXPO_TOKEN", value["error"])
        self.assertEqual(value["mobileHead"]["sha"], self.second)

    def test_feed_never_contains_the_token(self):
        def post(query, variables):
            return {"errors": [{"message": "Unauthorized"}]}
        value = apk_feed.build_feed(ECOSYSTEM, self.root, "secret-token-value", post)
        self.assertNotIn("secret-token-value", json.dumps(value))


class VerdictTest(unittest.TestCase):
    HEAD = {"sha": "b" * 40, "subject": "mobile: второй"}

    def feed(self, fresh, building=False, head=None, expires="2026-11-19T00:00:00Z", latest=True) -> dict:
        return {"feed": {
            "schema": apk.FEED_SCHEMA, "buildsPage": "https://expo.dev/accounts/me/projects/app/builds",
            "mobileHead": head or self.HEAD, "fresh": fresh, "error": None,
            "latest": {"apkUrl": "https://x/new.apk", "page": "https://expo.dev/b/new", "appVersion": "2.1.0",
                       "versionCode": "26", "gitCommit": "a" * 40, "expiresAt": expires} if latest else None,
            "building": {"page": "https://expo.dev/b/run", "createdAt": "x", "gitCommit": "b" * 40} if building else None,
        }, "source": "network", "error": None}

    def kind(self, got, main=None) -> str:
        return apk.verdict(got, main or self.HEAD, EAS, NOW)["id"]

    def test_matrix(self):
        self.assertEqual(self.kind(self.feed(True)), "current")
        self.assertEqual(self.kind(self.feed(False)), "awaiting")
        self.assertEqual(self.kind(self.feed(False, building=True)), "building")
        self.assertEqual(self.kind(self.feed(True, expires="2026-10-01T00:00:00Z")), "expired")
        self.assertEqual(self.kind(self.feed(None)), "unknown")
        self.assertEqual(self.kind(self.feed(None, latest=False)), "none")
        self.assertEqual(self.kind(self.feed(None, latest=False, building=True)), "building")

    def test_feed_behind_main_means_awaiting(self):
        newer = {"sha": "c" * 40, "subject": "mobile: третий"}
        value = apk.verdict(self.feed(True), newer, EAS, NOW)
        self.assertEqual(value["id"], "awaiting")
        self.assertIn("mobile: третий", value["detail"])

    def test_link_and_version(self):
        value = apk.verdict(self.feed(True), self.HEAD, EAS, NOW)
        self.assertEqual((value["apkUrl"], value["version"]), ("https://x/new.apk", "2.1.0 · 26"))

    def test_without_feed_links_to_builds_page(self):
        value = apk.verdict({"feed": None, "error": "ленты APK ещё нет"}, self.HEAD, EAS, NOW)
        self.assertEqual(value["id"], "unknown")
        self.assertEqual(value["page"], "https://expo.dev/accounts/me/projects/app/builds")
        self.assertIsNone(value["apkUrl"])


class FeedCacheTest(unittest.TestCase):
    def test_missing_branch_then_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            def missing(url):
                raise remote.RemoteError(f"GitHub ответил 404 на {url}")
            got = apk.Feed(Path(tmp) / "f.json", missing).get("o/r")
            self.assertIn("не запускался", got["error"])
            body = json.dumps({"schema": apk.FEED_SCHEMA, "latest": None}).encode()
            urls = []
            ok = apk.Feed(Path(tmp) / "f.json", lambda url: urls.append(url) or body).get("o/r")
            self.assertEqual(ok["source"], "network")
            self.assertEqual(urls, ["https://raw.githubusercontent.com/o/r/launcher-feed/apk.json"])
            again = apk.Feed(Path(tmp) / "f.json", missing).get("o/r", force=True)
            self.assertEqual((again["source"], again["feed"]["schema"]), ("cache", apk.FEED_SCHEMA))


if __name__ == "__main__":
    unittest.main()
