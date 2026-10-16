#!/usr/bin/env python3
"""Аудит актуальности документации экосистемы: отчёт, а не барьер.

Только стандартная библиотека. Читает Markdown всех направлений и корня и
печатает признаки, по которым документ стоит перечитать глазами:

- нет даты: ни в имени файла, ни в первых строках нет даты вида 2026-10-16;
- битые ссылки: относительная Markdown-ссылка ведёт в несуществующий файл;
- пропавшие пути: путь в обратных кавычках не найден ни от каталога документа,
  ни от корня направления, ни от корня репозитория, ни как хвост любого пути;
  рабочие каталоги вида `.devctl/…` не проверяются;
- ADR: статус и дата каждого ADR; ADR, который другой ADR объявил заменённым,
  но в своём статусе об этом молчит.

Направления суверенны: аудит ничего не правит и не падает. Код возврата 0,
если отчёт построен. Решение о судьбе документа принимает патч направления.

    python -B tools/ecosystem/docs_audit.py              # сводка и списки
    python -B tools/ecosystem/docs_audit.py --json       # то же для машин
    python -B tools/ecosystem/docs_audit.py --only web   # одно направление
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", "target", "dist", "build", ".gradle", ".expo", ".dev-bootstrap", ".uts-reports", ".devctl"}
DATE_RE = re.compile(r"20\d\d-[01]\d-[0-3]\d|20\d\d[01]\d[0-3]\d")
HEAD_LINES = 15
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
TICK_PATH_RE = re.compile(r"`([A-Za-z0-9_.\-/]+/[A-Za-z0-9_.\-]+\.[A-Za-z0-9]{1,5})`")
SUPERSEDES_RE = re.compile(r"[Зз]аменяет[^.\n]*?(ADR-\d{3})")
STATUS_RE = re.compile(r"^\s*(?:[-*]\s*)?\**(?:Статус|Status|Decision status)\**\s*[:：]\s*(.+)$", re.I | re.M)


def directions() -> list[str]:
    data = json.loads((ROOT / "ecosystem.json").read_text(encoding="utf-8"))
    names = []
    for item in data.get("components", []):
        path = item.get("path") or item.get("dir") or item.get("id")
        if isinstance(path, str):
            names.append(path.strip("/"))
    return names


def owner(rel: Path, dirs: list[str]) -> str:
    first = rel.parts[0] if len(rel.parts) > 1 else ""
    return first if first in dirs else "корень"


def markdown_files(dirs: list[str]):
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield rel, owner(rel, dirs)


def file_index() -> set[str]:
    """Все пути репозитория с ведущим «/», чтобы искать короткий путь как хвост."""
    paths = set()
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        paths.add("/" + rel.as_posix())
    return paths


def exists_any(token: str, doc_dir: Path, direction_root: Path, index: set[str]) -> bool:
    for base in (doc_dir, direction_root, ROOT):
        if (base / token).exists():
            return True
    tail = "/" + token
    return any(path.endswith(tail) for path in index)


def audit(only: str | None) -> dict:
    dirs = directions()
    report: dict = {"directions": {}, "undated": [], "brokenLinks": [], "missingPaths": [], "adrs": [], "supersededSilently": []}
    index = file_index()
    supersedes: list[tuple[Path, str]] = []
    adr_rows: dict[str, list[dict]] = {}
    for rel, who in markdown_files(dirs):
        if only and who != only:
            continue
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        stats = report["directions"].setdefault(who, {"files": 0, "bytes": 0, "undated": 0})
        stats["files"] += 1
        stats["bytes"] += len(text.encode("utf-8"))
        head = "\n".join(text.splitlines()[:HEAD_LINES])
        if not DATE_RE.search(rel.name) and not DATE_RE.search(head):
            stats["undated"] += 1
            report["undated"].append(str(rel))
        direction_root = ROOT / who if who != "корень" else ROOT
        for target in LINK_RE.findall(text):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (path.parent / clean).exists():
                report["brokenLinks"].append({"doc": str(rel), "target": target})
        for token in set(TICK_PATH_RE.findall(text)):
            if token.startswith(("http", "~", "/", ".")) or "*" in token or "<" in token or ".." in token:
                continue
            if not exists_any(token, path.parent, direction_root, index):
                report["missingPaths"].append({"doc": str(rel), "path": token})
        if rel.name.startswith("ADR-") and "adr" in [p.lower() for p in rel.parts]:
            status = STATUS_RE.search(text)
            date = DATE_RE.search(head)
            row = {"doc": str(rel), "status": status.group(1).strip(" *") if status else None, "date": date.group(0) if date else None}
            report["adrs"].append(row)
            adr_rows.setdefault(rel.name[:7], []).append({"row": row, "text": text, "dir": rel.parent})
            for target in SUPERSEDES_RE.findall(text):
                supersedes.append((rel, target))
    for source, target in supersedes:
        for candidate in adr_rows.get(target, []):
            if candidate["dir"] != source.parent:
                continue
            head = "\n".join(candidate["text"].splitlines()[:HEAD_LINES])
            if not re.search(r"[Зз]аменён|superseded|частично заменён", head, re.I):
                report["supersededSilently"].append({"adr": candidate["row"]["doc"], "by": str(source)})
    return report


def print_report(report: dict, limit: int) -> None:
    print("== аудит документации ==")
    total = sum(s["files"] for s in report["directions"].values())
    size = sum(s["bytes"] for s in report["directions"].values())
    print(f"Markdown: {total} файлов, {size / 1024:.0f} KiB")
    for name, s in sorted(report["directions"].items()):
        print(f"  {name:10} {s['files']:4} файлов {s['bytes'] / 1024:7.0f} KiB, без даты {s['undated']}")

    def section(title: str, rows: list, fmt) -> None:
        print(f"\n{title} ({len(rows)})")
        for row in rows[:limit]:
            print("  - " + fmt(row))
        if len(rows) > limit:
            print(f"  … ещё {len(rows) - limit}; полный список: --json или --limit 0")

    section("ADR, заменённые молча", report["supersededSilently"], lambda r: f"{r['adr']} ← {r['by']}")
    section("ADR", report["adrs"], lambda r: f"{r['doc']}: {r['status'] or 'статус не найден'}; {r['date'] or 'без даты'}")
    section("Битые ссылки", report["brokenLinks"], lambda r: f"{r['doc']} → {r['target']}")
    section("Пропавшие пути в `…`", report["missingPaths"], lambda r: f"{r['doc']}: {r['path']}")
    section("Без даты", report["undated"], str)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="печатать JSON")
    parser.add_argument("--only", help="одно направление: web, mobile, abl, devctl или корень")
    parser.add_argument("--limit", type=int, default=25, help="строк на список (0 — все)")
    args = parser.parse_args()
    report = audit(args.only)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print_report(report, args.limit or 10**9)
    return 0


if __name__ == "__main__":
    sys.exit(main())
