#!/usr/bin/env python3
"""Дрейф якорей abl относительно web, mobile и devctl.

Только стандартная библиотека. `abl/evidence/source-anchors.json` заморозил
sha256 файлов соседей на 2026-09-12; abl на них основал совместимость.
Проверка сравнивает якоря с текущими файлами дерева и ничего не правит:
замороженные файлы abl остаются как есть (docs/ecosystem/boundaries.md,
«Известный дрейф»). Дрейф — не ошибка, поэтому код возврата 0; ненулевой —
только если сам файл якорей нечитаем или ссылается на неизвестный источник.

    python -B tools/ecosystem/anchor_drift.py          # отчёт: какие якоря разошлись
    python -B tools/ecosystem/anchor_drift.py --all    # и совпавшие
    python -B tools/ecosystem/anchor_drift.py --json   # то же в JSON
    python -B tools/ecosystem/anchor_drift.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = "abl/evidence/source-anchors.json"
ABL_CHECKS = "abl/tools"
# Источник в якорях → каталог направления. «android» — прежний kanban_mobile.
SOURCES = {"web": "web", "android": "mobile", "devctl": "devctl"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class AnchorsRejected(Exception):
    pass


def load_anchors(root: Path) -> dict:
    try:
        data = json.loads((root / ANCHORS).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AnchorsRejected(f"{ANCHORS} не прочитан: {error}") from error
    if not isinstance(data, dict) or data.get("formatVersion") != 1 or not isinstance(data.get("anchors"), list):
        raise AnchorsRejected(f"{ANCHORS}: ожидается formatVersion 1 и список anchors")
    for item in data["anchors"]:
        if not isinstance(item, dict):
            raise AnchorsRejected(f"{ANCHORS}: якорь не объект: {item!r}")
        source, path, digest = item.get("source"), item.get("path"), item.get("sha256")
        if source not in SOURCES:
            raise AnchorsRejected(f"{ANCHORS}: неизвестный источник {source!r}")
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ".." in path.split("/"):
            raise AnchorsRejected(f"{ANCHORS}: небезопасный путь {path!r}")
        if not isinstance(digest, str) or not SHA_RE.match(digest):
            raise AnchorsRejected(f"{ANCHORS}: плохой sha256 у {source}:{path}")
    return data


def abl_checks(root: Path) -> dict[str, str]:
    """Тексты проверок abl: по упоминанию пути якоря видно, какой этап abl на него опирается."""
    return {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in sorted((root / ABL_CHECKS).glob("check_*.py"))}


def users(path: str, checks: dict[str, str]) -> list[str]:
    # Имя без каталога (VERSION, README.md) встречается в проверках abl и про собственные файлы abl.
    if "/" not in path:
        return []
    return [name for name, text in checks.items() if f'"{path}"' in text or f"'{path}'" in text]


def measure(root: Path) -> dict:
    data = load_anchors(root)
    checks = abl_checks(root)
    rows = []
    for item in data["anchors"]:
        source, path = item["source"], item["path"]
        current = root / SOURCES[source] / path
        if current.is_file():
            actual = hashlib.sha256(current.read_bytes()).hexdigest()
            state = "same" if actual == item["sha256"] else "changed"
        else:
            actual, state = None, "missing"
        rows.append({
            "source": source,
            "direction": SOURCES[source],
            "path": path,
            "role": item.get("role", ""),
            "state": state,
            "frozen": item["sha256"],
            "actual": actual,
            "ablChecks": users(path, checks),
        })
    summary = {}
    for source, direction in SOURCES.items():
        mine = [row for row in rows if row["source"] == source]
        summary[direction] = {
            "anchors": len(mine),
            "changed": sum(row["state"] == "changed" for row in mine),
            "missing": sum(row["state"] == "missing" for row in mine),
        }
    return {
        "anchorsFile": ANCHORS,
        "capturedAt": data.get("capturedAt"),
        "anchors": len(rows),
        "drifted": sum(row["state"] != "same" for row in rows),
        "byDirection": summary,
        "rows": rows,
    }


STATE_TEXT = {"same": "совпадает", "changed": "изменён", "missing": "нет файла"}


def render(report: dict, show_all: bool) -> str:
    lines = [
        f"Якоря abl ({report['anchorsFile']}, заморожены {report['capturedAt']}): "
        f"разошлись {report['drifted']} из {report['anchors']}",
    ]
    for direction, counts in report["byDirection"].items():
        missing = f", нет файла {counts['missing']}" if counts["missing"] else ""
        lines.append(f"  {direction}: изменено {counts['changed']} из {counts['anchors']}{missing}")
    for row in report["rows"]:
        if row["state"] == "same" and not show_all:
            continue
        used = f" · проверки abl: {', '.join(row['ablChecks'])}" if row["ablChecks"] else ""
        lines.append(f"  [{STATE_TEXT[row['state']]}] {row['direction']}/{row['path']} — {row['role']}{used}")
    if report["drifted"]:
        lines.append("Дрейф не ошибка: якоря заморожены намеренно. Обновить их может только патч abl, "
                     "перепроверив совместимость с изменённым файлом.")
    return "\n".join(lines)


def self_test() -> None:
    import tempfile

    def tree(root: Path, anchors: list[dict]) -> None:
        for rel, body in {
            "web/VERSION": b"2.1.0\n",
            "mobile/src/a.ts": b"export {}\n",
            "abl/tools/check_a10.py": b'ANCHOR = "src/a.ts"\n',
            ANCHORS: json.dumps({"formatVersion": 1, "capturedAt": "2026-09-12", "anchors": anchors}).encode(),
        }.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(body)

    def anchor(source: str, path: str, body: bytes) -> dict:
        return {"source": source, "path": path, "sha256": hashlib.sha256(body).hexdigest(), "role": "test"}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tree(root, [anchor("web", "VERSION", b"2.1.0\n"), anchor("android", "src/a.ts", b"old\n"),
                    anchor("devctl", "devctl.py", b"")])
        report = measure(root)
        assert [row["state"] for row in report["rows"]] == ["same", "changed", "missing"], report
        assert report["drifted"] == 2 and report["byDirection"]["mobile"]["changed"] == 1, report
        assert report["rows"][1]["ablChecks"] == ["check_a10"], report
        assert "[изменён] mobile/src/a.ts" in render(report, False) and "web/VERSION" not in render(report, False)
        for bad in (anchor("ios", "x", b""), anchor("web", "../abl/x", b""), dict(anchor("web", "VERSION", b""), sha256="x")):
            tree(root, [bad])
            try:
                measure(root)
            except AnchorsRejected:
                continue
            raise AssertionError(f"не отклонён: {bad}")
    print("OK: anchor_drift self-test")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Дрейф якорей abl относительно соседей.")
    parser.add_argument("--all", action="store_true", help="показать и совпавшие якоря")
    parser.add_argument("--json", action="store_true", help="отчёт в JSON")
    parser.add_argument("--self-test", action="store_true", help="проверить саму проверку на временном дереве")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    try:
        report = measure(Path(args.root))
    except AnchorsRejected as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report, args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
