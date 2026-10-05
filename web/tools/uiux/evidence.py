from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SECRET_KEY_RE = re.compile(r"(authorization|cookie|set-cookie|token|password|secret|session|refresh)", re.IGNORECASE)
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@(?!local\.test\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
COOKIE_RE = re.compile(r"(?i)(cookie|set-cookie):\s*[^\n\r]+")
TOKEN_FIELD_RE = re.compile(r'(?i)("(?:accessToken|refreshToken|token|password|sessionId|deviceId)"\s*:\s*")[^"]+(")')


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        text = BEARER_RE.sub("Bearer <redacted>", value)
        text = COOKIE_RE.sub(lambda m: f"{m.group(1)}: <redacted>", text)
        text = TOKEN_FIELD_RE.sub(r"\1<redacted>\2", text)
        text = EMAIL_RE.sub("<redacted-email>", text)
        return text
    return value


def truncate_text(text: str, limit: int = 16000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n<!-- truncated {len(text) - limit} chars -->"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(content), encoding="utf-8")


def dom_excerpt(html: str, needle: str | None = None, limit: int = 4000) -> str:
    if not needle:
        return truncate_text(html, limit)
    index = html.find(needle)
    if index == -1:
        return truncate_text(html, limit)
    start = max(0, index - limit // 2)
    end = min(len(html), index + limit // 2)
    return html[start:end]


def json_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
