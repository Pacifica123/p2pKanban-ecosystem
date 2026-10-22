"""Сборка состояния для окна и `status --json`: каталог, платформа, сверка."""
from __future__ import annotations

import json
from pathlib import Path

from . import apk, entry as entries, local, paths, probes, remote, runner as runs, source

STATE_SCHEMA = "p2p-kanban-launcher-state/1"
STAGE = "L5"

VERDICTS = {
    "current": "актуально",
    "outdated": "устарело",
    "modified": "изменено локально",
    "ahead": "впереди main",
    "absent": "не скачано",
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


def content_verdict(found: dict, directory: str) -> dict:
    """Вердикт сверки по содержимому (source.identify) — копия без git."""
    kind = found["id"]
    if kind == "absent":
        return {"id": "absent", "label": VERDICTS["absent"],
                "detail": f"каталога {directory}/ в этой копии нет — его можно скачать с GitHub"}
    if kind == "current":
        return {"id": "current", "label": VERDICTS["current"], "detail": "файлы как в main (сверка по содержимому)"}
    if kind == "outdated":
        commit = found["matched"]
        return {"id": "outdated", "label": VERDICTS["outdated"],
                "detail": f"как main {found['behind']} коммит(ов) каталога назад: {commit['sha'][:7]} {commit.get('subject') or ''}".rstrip()}
    if kind == "modified":
        text = source.describe(found.get("diff")) or "файлы отличаются от main"
        tail = found.get("error") or f"среди последних {found.get('searched', source.HISTORY_DEPTH)} версий main совпадения нет"
        return {"id": "modified", "label": "не как в main", "detail": f"{text}; {tail}"}
    return {"id": "unknown", "label": VERDICTS["unknown"], "detail": found.get("error") or "сверка не удалась"}


def offline_trees() -> source.Trees:
    def refuse(url: str) -> bytes:
        raise remote.RemoteError("без сети: дерева нет в кеше")
    return source.Trees(paths.cache_dir() / "trees", refuse)


def source_commit(root: Path | None, directory: str, trees: source.Trees | None = None) -> dict | None:
    """Коммит main, с которым совпадает каталог копии, — из кеша, без сети (для реестра установок)."""
    if root is None:
        return None
    checkout = local.checkout_state(root, [directory])
    if checkout["available"]:
        entry = checkout["directories"][directory]
        return None if entry["dirty"] else entry["commit"]
    ecosystem = load_ecosystem(root)
    data = remote.GlobalState(paths.cache_dir() / "global.json").get(
        ecosystem.get("repository") or "", ecosystem.get("branch", "main"),
        [item["dir"] for item in ecosystem.get("components", [])], offline=True)
    history = (data.get("history") or {}).get(directory) or []
    found = source.identify(root, directory, ecosystem.get("repository") or "", history,
                            (data.get("trees") or {}).get(directory), trees or offline_trees())
    return found["matched"]


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
    if status_value is not None and component["id"] == "launcher" and status_value["state"] == "running":
        return {"id": "self", "label": "это окно", "detail": status_value.get("detail") or ""}
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
    if entry_info and entry_info.get("available"):
        return {"id": "unknown", "label": "неизвестно", "detail": "на этой платформе не спрашивали"}
    if entry_info and entry_info.get("error"):
        return {"id": "unknown", "label": "неизвестно", "detail": entry_info["error"]}
    return {"id": "unknown", "label": "неизвестно", "detail": "направление ещё не объявило launcher.json"}


def freshness(root: Path | None, status_value: dict | None, remote_commit: dict | None,
              history: list[dict] | None = None, contains=None, recorded: dict | None = None) -> dict:
    """Установка рядом с main: актуальна, если последний коммит каталога в main — её предок.

    Предка спрашивает git копии; без git — история каталога из main и, если
    нужно, GitHub compare (`contains`). Если направление не сообщает коммит,
    берётся коммит исходников, из которых ставил лаунчер (`recorded`).
    """
    if not status_value or status_value["state"] in ("absent", "broken"):
        return {"id": "none", "label": "", "detail": ""}
    revision = status_value.get("revision")
    how = ""
    if not revision and recorded and recorded.get("sha"):
        revision, how = recorded["sha"], " (по копии, из которой ставил лаунчер)"
    theirs = (remote_commit or {}).get("sha")
    if not revision:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "установка не сообщает свой коммит"}
    if not theirs:
        return {"id": "unknown", "label": VERDICTS["unknown"], "detail": "нет данных о main"}
    newer = remote_commit.get("subject") or theirs[:7]
    shas = [item.get("sha") for item in history or []]
    if revision in shas[1:]:
        behind = shas.index(revision)
        return {"id": "outdated", "label": VERDICTS["outdated"],
                "detail": f"установлен {revision[:7]}{how}, отстаёт на {behind} коммит(ов) каталога; в main: {newer}"}
    ancestor = True if revision == theirs else local.is_ancestor(root, theirs, revision)
    if ancestor is None and contains is not None:
        ancestor = contains(theirs, revision)
    if ancestor:
        return {"id": "current", "label": VERDICTS["current"], "detail": f"установлен {revision[:7]}{how}, как в main"}
    if ancestor is None:
        return {"id": "unknown", "label": VERDICTS["unknown"],
                "detail": f"установлен {revision[:7]}{how}; новее ли он main, не проверить без git и GitHub"}
    return {"id": "outdated", "label": VERDICTS["outdated"], "detail": f"установлен {revision[:7]}{how}; в main новее: {newer}"}


def build_state(root: Path | None = None, global_state: remote.GlobalState | None = None,
                force: bool = False, offline: bool = False, runner: probes.Run = probes.run,
                host: dict | None = None, status_run: runs.StatusRun | None = runs.capture,
                apk_feed: apk.Feed | None = None, trees: source.Trees | None = None) -> dict:
    root = paths.ecosystem_root() if root is None else root
    global_state = global_state or remote.GlobalState(paths.cache_dir() / "global.json")
    standalone = None
    if root is None:
        # Лаунчер без экосистемы рядом: каталог направлений — из main, скачать — кнопкой.
        standalone = remote.remote_ecosystem(paths.cache_dir() / "ecosystem.json", global_state.fetch, offline)
        ecosystem = standalone["ecosystem"] or {"components": []}
    else:
        ecosystem = load_ecosystem(root)
    components = ecosystem.get("components", [])
    directories = [item["dir"] for item in components]
    repository = ecosystem.get("repository")
    branch = ecosystem.get("branch", "main")

    host = probes.detect_platform() if host is None else host
    if repository:
        remote_data = global_state.get(repository, branch, directories, force=force, offline=offline)
    else:
        remote_data = {"source": "none", "checkedAt": None, "error": "в ecosystem.json нет repository",
                       "directories": {}, "board": None}
    checkout = local.checkout_state(root, directories)
    if trees is None:
        trees = offline_trees() if offline else source.Trees(paths.cache_dir() / "trees", global_state.fetch)
    head_trees = remote_data.get("trees") or {}
    histories = remote_data.get("history") or {}
    method = "git" if checkout["available"] else "content" if root is not None and repository and histories else None
    contains = (lambda older, newer: trees.contains(repository, older, newer)) if repository else None
    feed_value = None
    if repository and any(item.get("distribution") == "apk" for item in components):
        apk_feed = apk_feed or apk.Feed(paths.cache_dir() / "apk-feed.json")
        feed_value = apk_feed.get(repository, force=force, offline=offline)
        if feed_value["feed"] is None and not offline and root is not None:
            feed_value = apk.local_feed(root, ecosystem) or feed_value
    registry = local.read_registry(paths.registry_file())
    memo: dict = {}

    rows = []
    for component in components:
        directory = component["dir"]
        fit = probes.platform_fit(component.get("platforms", []), host)
        requires = probes.check_requires(component.get("requires", []), host, runner, memo) if fit["fit"] == "yes" else []
        local_entry = checkout["directories"].get(directory) if checkout["available"] else None
        remote_commit = remote_data.get("directories", {}).get(directory)
        if method == "git":
            verdict = checkout_verdict(root, directory, local_entry, remote_commit)
        elif method == "content":
            found = source.identify(root, directory, repository, histories.get(directory) or [],
                                    head_trees.get(directory), trees)
            verdict = content_verdict(found, directory)
            local_entry = {"present": found["id"] != "absent", "commit": found["matched"], "dirty": 0,
                           "method": "content", "diff": found.get("diff")}
        elif root is None:
            verdict = {"id": "absent", "label": VERDICTS["absent"], "detail": "экосистема ещё не скачана на эту машину"}
        else:
            verdict = {"id": "unknown", "label": VERDICTS["unknown"], "detail": checkout["reason"]
                       + ("; сверка по содержимому ждёт ответа GitHub" if repository else "")}
        if verdict["id"] == "absent" and component.get("distribution") == "apk":
            verdict = {"id": "notneeded", "label": "не нужны", "detail": "ставится на телефон из APK, исходники не нужны"}
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
            "checkout": verdict,
            "canGet": verdict["id"] == "absent" and fit["fit"] == "yes" and component.get("distribution") != "apk"
            and component["id"] != "launcher",
            "installed": {"id": "unknown", "label": "не скачано", "detail": "сначала «Скачать с GitHub»"}
            if verdict["id"] == "absent" and component.get("distribution") != "apk" and component["id"] != "launcher"
            else installed_state(component, registry, entry_info, status_value),
            "status": status_value,
            "apk": apk.verdict(feed_value or {}, remote_commit, component.get("eas"))
            if component.get("distribution") == "apk" else None,
            "freshness": freshness(root, status_value, remote_commit, histories.get(directory), contains,
                                   (registry["installs"].get(component["id"]) or {}).get("sourceCommit")),
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
            "standalone": None if standalone is None else {
                "source": standalone["source"], "error": standalone["error"],
                "downloadDir": str(paths.default_download_dir())},
            "localBoard": local_board(root),
            "remoteBoard": remote_data.get("board"),
        },
        "global": {"source": remote_data.get("source"), "checkedAt": remote_data.get("checkedAt"),
                   "error": remote_data.get("error")},
        "checkout": {**{key: checkout.get(key) for key in ("available", "reason", "head", "branch")}, "method": method},
        "components": rows,
    }
