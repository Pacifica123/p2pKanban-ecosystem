#!/usr/bin/env python3
"""Кнопка «Проверка приёмки» на месте: маршрут, пункт меню, шаги и их тест.

    python -B tools/check_acceptance_button.py

Только стандартная библиотека; запускать из web/. Описание:
docs/architecture/acceptance-check-v1.md.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
SRC = WEB / "frontend" / "src"


def read(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    if "acceptance: '/settings/acceptance'" not in read("app/router/paths.ts"):
        errors.append("paths.ts: нет paths.acceptance")
    if 'path="/settings/acceptance" element={<AcceptancePage />}' not in read("app/router/index.tsx"):
        errors.append("router: нет маршрута /settings/acceptance")
    if "paths.acceptance" not in read("app/layouts/MainLayout.tsx"):
        errors.append("MainLayout: нет пункта меню «Проверка приёмки»")
    steps = read("features/acceptance/webSteps.ts")
    ids = re.findall(r"\bid: '([a-z.-]+)'", steps)
    if len(ids) != len(set(ids)):
        errors.append("webSteps.ts: повторяются id шагов")
    for required in ("auth.poll-limit", "crud.card", "cross.client", "io.export", "error.report", "ui.themes", "cleanup"):
        if required not in ids:
            errors.append(f"webSteps.ts: нет шага {required}")
    if ids and ids[-1] != "cleanup":
        errors.append("webSteps.ts: уборка должна идти последней")
    for forbidden in ("signOutAll", "/ring/genesis", "/ring/migrate", "startSourceUpdate"):
        if forbidden in steps:
            errors.append(f"webSteps.ts: необратимое действие {forbidden} кнопке запрещено")
    if "p2p-kanban-acceptance-report/1" not in read("features/acceptance/report.ts"):
        errors.append("report.ts: нет имени протокола отчёта")
    if not (SRC / "test/unit/features/acceptance/acceptance.test.ts").is_file():
        errors.append("нет теста src/test/unit/features/acceptance/acceptance.test.ts")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: кнопка «Проверка приёмки»: шагов {len(ids)}, маршрут и меню на месте")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
