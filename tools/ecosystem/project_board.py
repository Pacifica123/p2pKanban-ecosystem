#!/usr/bin/env python3
"""Копии доски проекта в сборках направлений (`p2p-kanban-project-board/1`).

Только стандартная библиотека. Путь копии каждого направления — поле
`projectBoard` в ecosystem.json.

    python -B tools/ecosystem/project_board.py check          # копии — доска проекта, не новее корня
    python -B tools/ecosystem/project_board.py status         # то же и сводка корневой доски
    python -B tools/ecosystem/project_board.py vendor web     # положить board/board.json в копию web

Отставание копии — не ошибка: web-узел догоняет main репозитория, телефон и
abl получают доску с узла (contracts/project-board/1/SPEC.md). Патч
направления по умолчанию обновляет свою копию командой vendor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import contract_ref as c  # noqa: E402

ROOT = c.ROOT
BOARD = ROOT / "board" / "board.json"


def copies() -> dict[str, Path]:
    data = json.loads((ROOT / "ecosystem.json").read_text(encoding="utf-8"))
    out = {}
    for component in data.get("components", []):
        rel = component.get("projectBoard")
        if rel:
            out[component["id"]] = ROOT / rel
    return out


def summary(path: Path) -> dict:
    return c.project_board_summary(path.read_bytes())


def check(verbose: bool) -> int:
    try:
        root = summary(BOARD)
    except c.ProjectBoardRejected as error:
        print(f"FAIL: board/board.json не доска проекта: {error.reason}", file=sys.stderr)
        return 1
    if verbose:
        print(f"корень: ревизия {root['revision']} ({root['lastPatchId']}), {root['bytes']} байт, sha256 {root['sha256'][:12]}")
    failed = False
    for direction, path in copies().items():
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            print(f"{direction}: копии {rel} ещё нет")
            continue
        try:
            got = summary(path)
        except c.ProjectBoardRejected as error:
            print(f"FAIL: {direction}: {rel} не доска проекта: {error.reason}", file=sys.stderr)
            failed = True
            continue
        if got["revision"] > root["revision"]:
            print(f"FAIL: {direction}: копия ревизии {got['revision']} новее корня {root['revision']}", file=sys.stderr)
            failed = True
        elif got["sha256"] == root["sha256"]:
            print(f"{direction}: копия совпадает с корнем (ревизия {got['revision']})")
        elif got["revision"] == root["revision"]:
            print(f"FAIL: {direction}: копия ревизии {got['revision']} отличается от корня той же ревизии", file=sys.stderr)
            failed = True
        else:
            print(f"{direction}: копия ревизии {got['revision']}, отстаёт на {root['revision'] - got['revision']}")
    return 1 if failed else 0


def vendor(direction: str) -> int:
    known = copies()
    if direction not in known:
        print(f"FAIL: у направления {direction} нет поля projectBoard в ecosystem.json", file=sys.stderr)
        return 1
    raw = BOARD.read_bytes()
    try:
        root = c.project_board_summary(raw)
    except c.ProjectBoardRejected as error:
        print(f"FAIL: board/board.json не доска проекта: {error.reason}", file=sys.stderr)
        return 1
    target = known[direction]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    print(f"{direction}: {target.relative_to(ROOT).as_posix()} ← ревизия {root['revision']} ({root['lastPatchId']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("status")
    vend = sub.add_parser("vendor")
    vend.add_argument("direction")
    args = parser.parse_args()
    if args.command == "vendor":
        return vendor(args.direction)
    return check(verbose=args.command == "status")


if __name__ == "__main__":
    raise SystemExit(main())
