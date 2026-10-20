"""Сборка состояния для окна и `status --json`: каталог, платформа, сверка."""
from __future__ import annotations

import json
from pathlib import Path

from . import entry as entries, local, paths, probes, remote, runner as runs

STATE_SCHEMA = "p2p-kanban-launcher-state/1"
STAGE = "L2"

VERDICTS = {
    "current": "актуально",
    "outdated": "устарело",
    "modified": "изменено локально",
    "ahead": "впереди main",
    "absent": "нет в checkout",
    "unknown": "неизвестно",
}


def launcher_version() -> str:
    try:
        return (paths.LAUNCHER_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def load_ecosystem(root: Path | None) -> dict:
    if root is None:
        return {"components": []}
    return json.loads((root / "ecosystem.json").read_text(encoding="utf-8"))


def local_board(root: Path | None) -> dict | None:
    if root is None:
        return None
    try:
        origin = json.loads((root / "board" / "board.json").read_text(encoding="utf-8")).get("origin") or {}
    except (OSError, ValueError):
        return None
    return {"boardRevision": origin.get("boardRevision"), "lastPatchId": origin.get("lastPatchId")}


def checkout_verdict(root: Path | None, directory: str, local_entry: dict | None, remote_commit: dict | None) -> dict:
    """Вердикт по исходникам checkout относительно `main`."""
    if local_entry is None:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "состояние checkout неизвестно"}
    if not local_entry.get("present"):
        return {"id": "absent", "label": VERDICTS["absent"],
                "detail": f"каталога {directory}/ нет в checkout (sparse или удалён)"}
    mine = (local_entry.get("commit") or {}).get("sha")
    theirs = (remote_commit or {}).get("sha")
    if local_entry.get("dirty"):
        return {"id": "modified", "label": VERDICTS["modified"],
                "detail": f"незакоммиченных файлов: {local_entry['dirty']}"}
    if not theirs:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "нет данных о main"}
    if mine == theirs:
        return {"id": "current", "label": VERDICTS["current"], "detail": "как в main"}
    if local.is_ancestor(root, theirs, mine):
        return {"id": "ahead", "label": VERDICTS["ahead"], "detail": "в checkout есть коммиты, которых ещё нет в main"}
    behind = local.commits_behind(root, mine, theirs, directory)
    detail = f"в main новее: {remote_commit.get('subject') or theirs[:7]}"
    if behind:
        detail = f"отстаёт на {behind} коммит(ов); последний в main: {remote_commit.get('subject') or theirs[:7]}"
    return {"id": "outdated", "label": VERDICTS["outdated"], "detail": detail}


INSTALL_LABELS = {
    "absent": "не установлено",
    "installed": "установлено",
    "running": "работает",
    "stopped": "остановлено",
    "broken": "не работает",
}


def installed_state(component: dict, registry: dict, entry_info: dict | None = None,
                    status_value: dict | None = None) -> dict:
    """Что установлено: ответ status направления, иначе реестр лаунчера, иначе неизвестно."""
    if status_value is not None:
        state_id = status_value["state"]
        detail = status_value.get("detail") or ""
        if status_value.get("problems"):
            detail = "; ".join([detail] + status_value["problems"][:2]) if detail else "; ".join(status_value["problems"][:2])
        return {"id": state_id, "label": INSTALL_LABELS[state_id], "detail": detail}
    entry = registry.get("installs", {}).get(component["id"])
    if entry:
        last = entry.get("lastAction") or {}
        return {"id": "registered", "label": "ставил лаунчер",
                "detail": f"последнее действие: {last.get('action', '?')} {last.get('at', '')}".strip()}
    if component.get("distribution") == "apk":
        return {"id": "phone", "label": "на телефоне", "detail": "ставится на телефон из APK"}
    if component["id"] == "launcher":
        return {"id": "self", "label": "это окно", "detail": f"версия {launcher_version()}"}
    if component.get("audience") == "developer":
        return {"id": "developer", "label": "для разработки",
                "detail": f"ставится своей командой: {component.get('entry', '')}".strip()}
    if entry_info and entry_info.get("error"):
        return {"id": "unknown", "label": "неизвестно", "detail": entry_info["error"]}
    return {"id": "unknown", "label": "неизвестно", "detail": "направление ещё не объявило launcher.json"}


def freshness(root: Path | None, status_value: dict | None, remote_commit: dict | None) -> dict:
    """Установка рядом с main: актуальна, если последний коммит каталога в main — её предок."""
    if not status_value or status_value["state"] in ("absent", "broken"):
        return {"id": "none", "label": "", "detail": ""}
    revision = status_value.get("revision")
    theirs = (remote_commit or {}).get("sha")
    if not revision:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "установка не сообщает свой коммит"}
    if not theirs:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "нет данных о main"}
    if revision == theirs or local.is_ancestor(root, theirs, revision):
        return {"id": "current", "label": VERDICTS["current"], "detail": f"установлен {revision[:7]}, как в main"}
    return {"id": "outdated", "label": VERDICTS["outdated"],
            "detail": f"установлен {revision[:7]}; в main новее: {remote_commit.get('subject') or theirs[:7]}"}


def build_state(root: Path | None = None, global_state: remote.GlobalState | None = None,
                force: bool = False, offline: bool = False, runner: probes.Run = probes.run,
                host: dict | None = None, status_run: runs.StatusRun | None = runs.capture) -> dict:
    root = paths.ecosystem_root() if root is None else root
    ecosystem = load_ecosystem(root)
    components = ecosystem.get("components", [])
    directories = [item["dir"] for item in components]
    repository = ecosystem.get("repository")
    branch = ecosystem.get("branch", "main")

    host = probes.detect_platform() if host is None else host
    global_state = global_state or remote.GlobalState(paths.cache_dir() / "global.json")
    if repository:
        remote_data = global_state.get(repository, branch, directories, force=force, offline=offline)
    else:
        remote_data = {"source": "none", "checkedAt": None, "error": "в ecosystem.json нет repository",
                       "directories": {}, "board": None}
    checkout = local.checkout_state(root, directories)
    registry = local.read_registry(paths.registry_file())
    memo: dict = {}

    rows = []
    for component in components:
        directory = component["dir"]
        fit = probes.platform_fit(component.get("platforms", []), host)
        requires = probes.check_requires(component.get("requires", []), host, runner, memo) if fit["fit"] == "yes" else []
        local_entry = checkout["directories"].get(directory) if checkout["available"] else None
        remote_commit = remote_data.get("directories", {}).get(directory)
        docs = component.get("docs")
        entry_info = entries.load(root, directory)
        given = registry["settings"].get(component["id"]) or {}
        if entry_info["available"]:
            given = entries.clean_values(entry_info["entry"], given)
        status_value = None
        if entry_info["available"] and status_run is not None and fit["fit"] == "yes":
            status_value = runs.status(root, entry_info["entry"], given, status_run)
        rows.append({
            "id": component["id"],
            "dir": directory,
            "summary": component.get("summary") or component.get("role", ""),
            "role": component.get("role", ""),
            "audience": component.get("audience", "user"),
            "distribution": component.get("distribution"),
            "platforms": component.get("platforms", []),
            "fit": fit,
            "requires": requires,
            "ready": fit["fit"] == "yes" and all(item["ok"] is not False for item in requires),
            "install": component.get("install") or ([component["entry"]] if component.get("entry") else []),
            "docs": docs,
            "docsUrl": f"https://github.com/{repository}/blob/{branch}/{docs}" if repository and docs else None,
            "remote": remote_commit,
            "local": local_entry,
            "checkout": checkout_verdict(root, directory, local_entry, remote_commit) if checkout["available"]
            else {"id": "unknown", "label": VERDICTS["unknown"], "detail": checkout["reason"]},
            "installed": installed_state(component, registry, entry_info, status_value),
            "status": status_value,
            "freshness": freshness(root, status_value, remote_commit),
            "entry": entry_info["entry"],
            "entryError": entry_info["error"],
            "values": given,
        })

    return {
        "schema": STATE_SCHEMA,
        "launcher": {"version": launcher_version(), "stage": STAGE},
        "host": host,
        "ecosystem": {
            "name": ecosystem.get("name"),
            "repository": repository,
            "branch": branch,
            "root": str(root) if root else None,
            "localBoard": local_board(root),
            "remoteBoard": remote_data.get("board"),
        },
        "global": {"source": remote_data.get("source"), "checkedAt": remote_data.get("checkedAt"),
                   "error": remote_data.get("error")},
        "checkout": {key: checkout.get(key) for key in ("available", "reason", "head", "branch")},
        "components": rows,
    }
