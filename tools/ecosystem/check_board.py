#!/usr/bin/env python3
"""Проверка самоприменимой доски экосистемы и карты направлений.

Только стандартная библиотека. Правила повторяют импортёры, которые реально
читают доску: web (frontend/src/features/integrations/lib/boardBundle.ts) и
abl (src-tauri/src/domain/import.rs, parse_portable_bundle_v1), плюс правила
экосистемы из docs/ecosystem/development.md.

    python -B tools/ecosystem/check_board.py                    # доска и карта корректны
    python -B tools/ecosystem/check_board.py --require-changed  # и изменены относительно HEAD
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD = "board/board.json"
ECOSYSTEM = "ecosystem.json"
MAX_BYTES = 10 * 1024 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PRIORITIES = {None, "low", "medium", "high", "urgent"}
DIRECTION_LABELS = {"web", "mobile", "abl", "devctl", "экосистема"}
FORBIDDEN_KEYS = {
    "accesstoken", "refreshtoken", "sessiontoken", "passwordhash", "boardkey",
    "deviceprivatekey", "privatekey", "jwtsecret", "globalmasterkey",
    "nostrsigningsecret", "deploymentsecret",
}


class CheckError(Exception):
    pass


def fail(message: str) -> None:
    raise CheckError(message)


def text(row: dict, key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{label}.{key} должен быть непустой строкой")
    if "\x00" in value:
        fail(f"{label}.{key} содержит NUL")
    return value


def uuid(row: dict, key: str, label: str) -> str:
    value = text(row, key, label)
    if not UUID_RE.match(value):
        fail(f"{label}.{key} не UUID: {value}")
    return value


def position(row: dict, label: str) -> None:
    value = row.get("position")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{label}.position обязателен и должен быть конечным числом")


def timestamp(row: dict, key: str, label: str) -> None:
    value = row.get(key)
    if value is None:
        return
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        fail(f"{label}.{key} не дата ISO 8601: {value}")


def rows(payload: dict, key: str) -> list[dict]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        fail(f"payload.{key} должен быть массивом объектов")
    return value


def reject_secrets(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(ch for ch in key if ch.isascii() and ch.isalnum()).lower()
            if normalized in FORBIDDEN_KEYS:
                fail(f"секретное поле {path}.{key} недопустимо в доске")
            reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secrets(child, f"{path}[{index}]")


def validate_board(raw: bytes) -> dict:
    if len(raw) > MAX_BYTES:
        fail("доска больше 10 МБ: web её не импортирует")
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"доска не является корректным JSON: {error}")
    if not isinstance(bundle, dict):
        fail("корень доски должен быть объектом")
    reject_secrets(bundle)

    manifest = bundle.get("manifest.json")
    scope = bundle.get("scope")
    payload = bundle.get("payload")
    origin = bundle.get("origin")
    for name, value in (("manifest.json", manifest), ("scope", scope), ("payload", payload), ("origin", origin)):
        if not isinstance(value, dict):
            fail(f"раздел {name} обязателен и должен быть объектом")

    if manifest.get("format") != "p2p_planner_bundle" or manifest.get("formatVersion") != 1:
        fail("ожидается format=p2p_planner_bundle, formatVersion=1")
    if manifest.get("bundleKind") != "portable_export":
        fail("bundleKind должен быть portable_export: abl принимает только его")
    if manifest.get("scopeKind") != "board" or scope.get("scopeKind") != "board":
        fail("scopeKind должен быть board в manifest.json и scope")
    if manifest.get("includesLocalMetadata") is not False:
        fail("includesLocalMetadata должен быть false")
    workspace_id = uuid(manifest, "workspaceId", "manifest.json")
    board_id = uuid(manifest, "boardId", "manifest.json")
    if scope.get("workspaceId") != workspace_id or scope.get("boardId") != board_id:
        fail("scope не совпадает с manifest.json")

    revision = origin.get("boardRevision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        fail("origin.boardRevision должен быть целым числом ≥ 1")
    text(origin, "lastPatchId", "origin")
    timestamp(origin, "generatedAt", "origin")

    all_ids: set[str] = set()

    def register(identifier: str, label: str) -> None:
        if identifier in all_ids:
            fail(f"повторяющийся id {identifier} ({label})")
        all_ids.add(identifier)

    workspaces = rows(payload, "workspaces")
    if len(workspaces) != 1 or workspaces[0].get("id") != workspace_id:
        fail("payload.workspaces должен содержать ровно workspace из manifest")
    text(workspaces[0], "name", "workspace")
    register(workspace_id, "workspace")

    boards = rows(payload, "boards")
    if len(boards) != 1 or boards[0].get("id") != board_id or boards[0].get("workspaceId") != workspace_id:
        fail("payload.boards должен содержать ровно доску из manifest")
    text(boards[0], "name", "board")
    register(board_id, "board")

    columns = rows(payload, "columns")
    if not columns:
        fail("у доски нет колонок")
    column_ids = set()
    for column in columns:
        identifier = uuid(column, "id", "column")
        label = f"column {identifier}"
        if column.get("boardId") != board_id:
            fail(f"{label}: boardId не совпадает с доской")
        text(column, "name", label)
        position(column, label)
        wip = column.get("wipLimit")
        if wip is not None and (isinstance(wip, bool) or not isinstance(wip, int) or wip < 0):
            fail(f"{label}.wipLimit должен быть целым неотрицательным числом")
        register(identifier, label)
        column_ids.add(identifier)

    labels = rows(payload, "labels")
    label_names = {}
    for item in labels:
        identifier = uuid(item, "id", "label")
        if item.get("boardId") != board_id:
            fail(f"label {identifier}: boardId не совпадает с доской")
        label_names[identifier] = text(item, "name", f"label {identifier}")
        text(item, "color", f"label {identifier}")
        register(identifier, "label")

    cards = rows(payload, "cards")
    card_ids = set()
    parents = {}
    for card in cards:
        identifier = uuid(card, "id", "card")
        label = f"card {identifier}"
        if card.get("boardId") != board_id:
            fail(f"{label}: boardId не совпадает с доской")
        if card.get("columnId") not in column_ids:
            fail(f"{label}: columnId ссылается на отсутствующую колонку")
        text(card, "title", label)
        position(card, label)
        if card.get("priority") not in PRIORITIES:
            fail(f"{label}: неизвестный priority {card.get('priority')}")
        timestamp(card, "startAt", label)
        timestamp(card, "dueAt", label)
        register(identifier, label)
        card_ids.add(identifier)
        if card.get("parentCardId"):
            parents[identifier] = card["parentCardId"]
    for child, parent in parents.items():
        if parent not in card_ids:
            fail(f"card {child}: parentCardId ссылается на отсутствующую карточку")
        seen = {child}
        while parent:
            if parent in seen:
                fail(f"цикл в иерархии карточек около {child}")
            seen.add(parent)
            parent = parents.get(parent)

    labelled = {}
    pairs = set()
    for edge in rows(payload, "cardLabels"):
        card_id, label_id = edge.get("cardId"), edge.get("labelId")
        if card_id not in card_ids or label_id not in label_names:
            fail(f"cardLabels ссылается на отсутствующие {card_id} / {label_id}")
        if (card_id, label_id) in pairs:
            fail(f"повторяющаяся связь cardLabels {card_id} / {label_id}")
        pairs.add((card_id, label_id))
        labelled.setdefault(card_id, set()).add(label_names[label_id])

    checklist_ids = set()
    for checklist in rows(payload, "checklists"):
        identifier = uuid(checklist, "id", "checklist")
        if checklist.get("cardId") not in card_ids:
            fail(f"checklist {identifier}: cardId ссылается на отсутствующую карточку")
        text(checklist, "title", f"checklist {identifier}")
        position(checklist, f"checklist {identifier}")
        register(identifier, "checklist")
        checklist_ids.add(identifier)

    for item in rows(payload, "checklistItems"):
        identifier = uuid(item, "id", "checklist item")
        if item.get("checklistId") not in checklist_ids:
            fail(f"checklist item {identifier}: checklistId ссылается на отсутствующий чек-лист")
        text(item, "title", f"checklist item {identifier}")
        position(item, f"checklist item {identifier}")
        if not isinstance(item.get("isDone", False), bool):
            fail(f"checklist item {identifier}: isDone должен быть boolean")
        register(identifier, "checklist item")

    comment_ids = set()
    for comment in rows(payload, "comments"):
        identifier = uuid(comment, "id", "comment")
        if identifier in comment_ids:
            fail(f"повторяющийся id комментария {identifier}")
        comment_ids.add(identifier)
        if comment.get("cardId") not in card_ids:
            fail(f"comment {identifier}: cardId ссылается на отсутствующую карточку")
        text(comment, "body", f"comment {identifier}")
        timestamp(comment, "createdAt", f"comment {identifier}")

    summary = manifest.get("summary")
    counts = summary.get("entityCounts") if isinstance(summary, dict) else None
    if isinstance(counts, dict):
        actual = {
            "workspaces": 1, "boards": 1, "columns": len(columns), "cards": len(cards),
            "comments": len(comment_ids), "checklists": len(checklist_ids),
        }
        for key, value in actual.items():
            if key in counts and counts[key] != value:
                fail(f"manifest.summary.entityCounts.{key}={counts[key]}, в payload {value}")

    unlabelled = [card["title"] for card in cards if not (labelled.get(card["id"], set()) & DIRECTION_LABELS)]
    if unlabelled:
        fail("у карточек нет метки направления (web/mobile/abl/devctl/экосистема): " + "; ".join(unlabelled))

    return {"revision": revision, "lastPatchId": origin["lastPatchId"], "cards": len(cards), "columns": len(columns)}


def validate_ecosystem() -> int:
    try:
        data = json.loads((ROOT / ECOSYSTEM).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{ECOSYSTEM} не читается: {error}")
    components = data.get("components")
    if not isinstance(components, list) or not components:
        fail(f"{ECOSYSTEM}: components должен быть непустым списком")
    seen = set()
    for component in components:
        identifier = text(component, "id", "component")
        directory = text(component, "dir", f"component {identifier}")
        if identifier in seen:
            fail(f"{ECOSYSTEM}: повторяется направление {identifier}")
        seen.add(identifier)
        if not (ROOT / directory).is_dir():
            fail(f"{ECOSYSTEM}: каталог {directory} направления {identifier} не найден")
        docs = component.get("docs")
        if docs and not (ROOT / docs).is_file():
            fail(f"{ECOSYSTEM}: {docs} направления {identifier} не найден")
    return len(components)


def git(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, timeout=60)


def require_changed(current_raw: bytes, current: dict) -> str:
    if git("rev-parse", "--verify", "HEAD").returncode != 0:
        return "HEAD отсутствует: первый коммит, сравнивать не с чем"
    previous = git("show", f"HEAD:{BOARD}")
    if previous.returncode != 0:
        return f"{BOARD} отсутствует в HEAD: доска появляется этим патчем"
    if previous.stdout == current_raw:
        fail(f"{BOARD} не изменён. Каждый патч обновляет доску: docs/ecosystem/development.md")
    try:
        before = json.loads(previous.stdout.decode("utf-8")).get("origin", {})
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "доска в HEAD повреждена; текущая версия корректна"
    old_revision = before.get("boardRevision")
    if isinstance(old_revision, int) and current["revision"] != old_revision + 1:
        fail(f"origin.boardRevision должен быть {old_revision + 1}, сейчас {current['revision']}")
    if before.get("lastPatchId") == current["lastPatchId"]:
        fail("origin.lastPatchId не обновлён: впишите patchId этого патча")
    return f"ревизия {old_revision} → {current['revision']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--require-changed", action="store_true", help="требовать изменения доски относительно HEAD")
    args = parser.parse_args()
    try:
        raw = (ROOT / BOARD).read_bytes()
        result = validate_board(raw)
        components = validate_ecosystem()
        note = require_changed(raw, result) if args.require_changed else None
    except (OSError, CheckError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: доска ревизии {result['revision']} ({result['lastPatchId']}), "
          f"{result['columns']} колонок, {result['cards']} карточек; направлений в {ECOSYSTEM}: {components}")
    if note:
        print(f"OK: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
