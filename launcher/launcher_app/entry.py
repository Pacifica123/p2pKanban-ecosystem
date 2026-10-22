"""Объявление направления `<dir>/launcher.json` (p2p-kanban-launcher-entry/1).

Своя реализация контракта, как у любого направления: эталон корня
(`tools/ecosystem/contract_ref.py`) лаунчер не импортирует, а сверяется с его
векторами в тестах. Здесь только правила файла, сборка argv и разбор ответа
status; запуск процессов — в runner.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ENTRY_SCHEMA = "p2p-kanban-launcher-entry/1"
STATUS_SCHEMA = "p2p-kanban-launcher-status/1"
PYTHON = "{python}"
VALUE = "{value}"
SETTING_TYPES = ("port", "choice", "bool")
KNOWN_ACTIONS = ("install", "start", "stop", "update", "status", "doctor", "logs", "remove", "launch")

_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ARG = re.compile(r"^[^\x00-\x1f]{1,200}$")
_SCRIPT = re.compile(r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]+\.py$")
_URL = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+(?:/[^\s]*)?$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


class Rejected(ValueError):
    """Не по контракту; `reason` — код из SPEC."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _text(value, limit: int = 400) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def value_ok(setting: dict, value) -> bool:
    kind = setting["type"]
    if value is None:
        return kind != "bool"
    if kind == "port":
        return _is_int(value) and setting.get("min", 1024) <= value <= setting.get("max", 65535)
    if kind == "choice":
        return value in [item["value"] for item in setting["choices"]]
    return isinstance(value, bool)


def _check_setting(setting, known: dict) -> None:
    if not isinstance(setting, dict) or not isinstance(setting.get("id"), str) or not _ID.match(setting["id"]):
        raise Rejected("bad-setting", "id")
    sid = setting["id"]
    if sid in known:
        raise Rejected("duplicate-id", sid)
    if setting.get("type") not in SETTING_TYPES or not _text(setting.get("label"), 80):
        raise Rejected("bad-setting", sid)
    if setting["type"] == "choice":
        choices = setting.get("choices")
        if not isinstance(choices, list) or not choices or any(
                not isinstance(item, dict) or not isinstance(item.get("value"), str) or not _text(item.get("label"), 80)
                for item in choices) or len({item["value"] for item in choices}) != len(choices):
            raise Rejected("bad-setting", sid)
    if setting["type"] == "port":
        low, high = setting.get("min", 1024), setting.get("max", 65535)
        if not (_is_int(low) and _is_int(high)) or not 1 <= low <= high <= 65535:
            raise Rejected("bad-setting", sid)
    if "default" in setting and not value_ok(setting, setting["default"]):
        raise Rejected("bad-setting", f"{sid}.default")
    known[sid] = setting


def _check_action(action, known: dict, seen: set) -> None:
    if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not _ID.match(action["id"]):
        raise Rejected("bad-action", "id")
    aid = action["id"]
    if aid in seen:
        raise Rejected("duplicate-id", aid)
    seen.add(aid)
    if not _text(action.get("label"), 80) or action.get("output", "text") not in ("text", "status"):
        raise Rejected("bad-action", aid)
    if action.get("confirm") is not None and not _text(action.get("confirm")):
        raise Rejected("bad-action", f"{aid}.confirm")
    for flag in ("privileged", "detached"):
        if flag in action and not isinstance(action[flag], bool):
            raise Rejected("bad-action", f"{aid}.{flag}")
    timeout = action.get("timeoutSeconds", 600)
    if not _is_int(timeout) or not 1 <= timeout <= 86400:
        raise Rejected("bad-action", f"{aid}.timeoutSeconds")
    argv = action.get("argv")
    if not isinstance(argv, list) or len(argv) < 2 or argv[0] != PYTHON \
            or not isinstance(argv[1], str) or not _SCRIPT.match(argv[1]):
        raise Rejected("bad-argv", aid)
    for arg in argv[1:] + list(action.get("dryRun", [])):
        if not isinstance(arg, str) or not _ARG.match(arg):
            raise Rejected("bad-argv", aid)
        if "{" in arg or "}" in arg:
            raise Rejected("bad-placeholder", aid)
    if not isinstance(action.get("dryRun", []), list):
        raise Rejected("bad-argv", f"{aid}.dryRun")
    options = action.get("options", [])
    if not isinstance(options, list):
        raise Rejected("bad-action", f"{aid}.options")
    for option in options:
        if not isinstance(option, dict) or option.get("setting") not in known:
            name = option.get("setting") if isinstance(option, dict) else option
            raise Rejected("unknown-setting", f"{aid}: {name}")
        setting = known[option["setting"]]
        parts = option.get("argv")
        if not isinstance(parts, list) or not parts:
            raise Rejected("bad-argv", f"{aid}.{setting['id']}")
        for part in parts:
            if not isinstance(part, str) or not _ARG.match(part):
                raise Rejected("bad-argv", f"{aid}.{setting['id']}")
            if part != VALUE and ("{" in part or "}" in part):
                raise Rejected("bad-placeholder", aid)
        if (VALUE in parts) == (setting["type"] == "bool"):
            raise Rejected("bad-placeholder", f"{aid}.{setting['id']}")


def _check_profile(profile, known: dict, actions: set, pids: set) -> None:
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), str) or not _ID.match(profile["id"]) \
            or profile["id"] in pids or not _text(profile.get("label"), 80) or not isinstance(profile.get("supported"), bool):
        raise Rejected("bad-profile", str(profile.get("id") if isinstance(profile, dict) else profile))
    pids.add(profile["id"])
    if not profile["supported"]:
        if not _text(profile.get("reason")):
            raise Rejected("bad-profile", f"{profile['id']}: нужна reason")
        return
    if profile.get("action") not in actions:
        raise Rejected("bad-profile", f"{profile['id']}: action")
    for sid in profile.get("ask", []):
        if sid not in known:
            raise Rejected("bad-profile", f"{profile['id']}: ask {sid}")
    for sid, value in (profile.get("values") or {}).items():
        if sid not in known or not value_ok(known[sid], value):
            raise Rejected("bad-profile", f"{profile['id']}: values.{sid}")


def check(entry, component: str | None = None) -> dict:
    """Принять объявление целиком или Rejected."""
    if not isinstance(entry, dict) or entry.get("schema") != ENTRY_SCHEMA:
        raise Rejected("wrong-schema")
    name = entry.get("component")
    if not isinstance(name, str) or not _ID.match(name) or (component is not None and name != component):
        raise Rejected("bad-component", str(name))
    settings = entry.get("settings", [])
    if not isinstance(settings, list):
        raise Rejected("bad-setting", "settings — список")
    known: dict[str, dict] = {}
    for setting in settings:
        _check_setting(setting, known)
    actions = entry.get("actions")
    if not isinstance(actions, list) or not actions:
        raise Rejected("no-actions")
    seen: set[str] = set()
    for action in actions:
        _check_action(action, known, seen)
    status = next((a for a in actions if a["id"] == "status"), None)
    if status is None or status.get("output") != "status" or status.get("privileged") or status.get("confirm"):
        raise Rejected("no-status")
    if any(a.get("output") == "status" for a in actions if a["id"] != "status"):
        raise Rejected("bad-action", "output=status только у status")
    profiles = entry.get("profiles", [])
    if not isinstance(profiles, list):
        raise Rejected("bad-profile")
    pids: set[str] = set()
    for profile in profiles:
        _check_profile(profile, known, seen, pids)
    return entry


def values(entry: dict, given: dict | None) -> dict:
    """Значения настроек: умолчания объявления, поверх — выбор пользователя."""
    out = {}
    given = given or {}
    for setting in entry.get("settings", []):
        sid = setting["id"]
        value = given.get(sid, setting.get("default", False if setting["type"] == "bool" else None))
        if not value_ok(setting, value):
            raise Rejected("bad-value", sid)
        out[sid] = value
    unknown = sorted(set(given) - set(out))
    if unknown:
        raise Rejected("bad-value", ", ".join(unknown))
    return out


def clean_values(entry: dict, given: dict | None) -> dict:
    """Сохранённые значения, которые ещё подходят объявлению (оно могло измениться)."""
    kinds = {s["id"]: s for s in entry.get("settings", [])}
    return {k: v for k, v in (given or {}).items() if k in kinds and value_ok(kinds[k], v)}


def command(entry: dict, action_id: str, given: dict | None = None, dry_run: bool = False) -> dict:
    """argv (с `{python}` на месте интерпретатора) и каталог направления."""
    action = find_action(entry, action_id)
    if action is None:
        raise Rejected("unknown-action", action_id)
    if dry_run and not action.get("dryRun"):
        raise Rejected("no-dry-run", action_id)
    chosen = values(entry, given)
    kinds = {s["id"]: s["type"] for s in entry.get("settings", [])}
    argv = list(action["argv"])
    for option in action.get("options", []):
        value = chosen[option["setting"]]
        if kinds[option["setting"]] == "bool":
            if value:
                argv += option["argv"]
        elif value is not None:
            argv += [str(value) if part == VALUE else part for part in option["argv"]]
    if dry_run:
        argv += action["dryRun"]
    return {"component": entry["component"], "action": action_id, "argv": argv, "cwd": entry["component"],
            "privileged": bool(action.get("privileged")), "detached": bool(action.get("detached")),
            "timeoutSeconds": action.get("timeoutSeconds", 600)}


def find_action(entry: dict, action_id: str) -> dict | None:
    return next((a for a in entry.get("actions", []) if a["id"] == action_id), None)


def parse_status(entry: dict, exit_code: int, stdout: str) -> dict:
    """Код выхода и stdout status → {state, version, revision, url, values, detail, problems}."""
    def broken(reason: str) -> dict:
        return {"protocol": STATUS_SCHEMA, "state": "broken", "reason": reason, "version": None,
                "revision": None, "url": None, "values": {}, "detail": None, "problems": []}
    if exit_code != 0:
        return broken("exit-code")
    try:
        value = json.loads(stdout)
    except (TypeError, ValueError):
        return broken("bad-output")
    if not isinstance(value, dict) or value.get("schema") != STATUS_SCHEMA or value.get("component") != entry["component"]:
        return broken("bad-output")
    installed, running = value.get("installed"), value.get("running")
    if not isinstance(installed, bool) or running not in (True, False, None):
        return broken("bad-output")
    revision, url, version = value.get("revision"), value.get("url"), value.get("version")
    if (revision is not None and not (isinstance(revision, str) and _HEX40.match(revision))) \
            or (url is not None and not (isinstance(url, str) and _URL.match(url))) \
            or (version is not None and not _text(version, 80)):
        return broken("bad-output")
    problems = value.get("problems", [])
    if not isinstance(problems, list) or not all(isinstance(item, str) for item in problems):
        return broken("bad-output")
    kinds = {s["id"]: s for s in entry.get("settings", [])}
    raw_values = value.get("values")
    clean = {k: v for k, v in raw_values.items() if k in kinds and value_ok(kinds[k], v)} \
        if isinstance(raw_values, dict) else {}
    detail = value.get("detail") if isinstance(value.get("detail"), str) else None
    state = "absent" if not installed else {True: "running", False: "stopped", None: "installed"}[running]
    return {"protocol": STATUS_SCHEMA, "state": state, "reason": None, "version": version if installed else None,
            "revision": revision if installed else None, "url": url if installed else None,
            "values": clean, "detail": detail, "problems": problems[:20]}


def load(root: Path | None, component: str) -> dict:
    """{available, entry, error}: launcher.json направления, если оно его положило."""
    if root is None:
        return {"available": False, "entry": None, "error": "направление ещё не скачано: «Скачать с GitHub»"}
    path = root / component / "launcher.json"
    if not path.is_file():
        return {"available": False, "entry": None, "error": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entry = check(raw, component)
    except (OSError, ValueError) as error:
        reason = error.reason if isinstance(error, Rejected) else "не читается как JSON"
        return {"available": False, "entry": None, "error": f"{component}/launcher.json не принят: {reason}"}
    for action in entry["actions"]:
        if not (root / component / action["argv"][1]).is_file():
            return {"available": False, "entry": None,
                    "error": f"{component}/launcher.json: нет скрипта {action['argv'][1]} для «{action['label']}»"}
    return {"available": True, "entry": entry, "error": None}
