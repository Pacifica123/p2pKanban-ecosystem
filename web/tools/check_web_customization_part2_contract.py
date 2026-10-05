#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(relative: str, *needles: str) -> None:
    content = read(relative)
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {', '.join(missing)}")


def main() -> None:
    version = read("VERSION").strip()
    frontend = json.loads(read("frontend/package.json"))
    if version != "1.0.0" or frontend.get("version") != version:
        raise SystemExit("FAIL: v1 versions are not aligned")

    require(
        "backend/migrations/0011_account_workflow_and_accent_customization.sql",
        "checklist_item_submit_mode",
        "card_details_mode",
        "'accent'",
    )
    require(
        "backend/src/modules/appearance/service.rs",
        "CHECKLIST_ITEM_SUBMIT_MODES",
        "CARD_DETAILS_MODES",
        '"none" | "accent"',
        "accentColor must be a #RRGGBB color",
    )
    require(
        "frontend/src/features/cards/components/CardDetailsDrawer.tsx",
        "shouldSubmitChecklistItem",
        "drawer--",
        "cardDetailsMode",
    )
    require(
        "frontend/src/shared/appearance/theme.ts",
        "getBoardAccentColor",
        "getAccentPalette",
        "--board-info-scrim",
        "backgroundImage",
    )
    require(
        "frontend/src/features/appearance/pages/BoardAppearancePage.tsx",
        "Акцентный цвет",
        "От акцента",
        "Wallpaper при смене акцента сохраняется",
    )
    require(
        "docs/api/openapi.yaml",
        "checklistItemSubmitMode:",
        "cardDetailsMode:",
        "- accent",
    )
    print("OK: account workflow modes, accent palette, wallpaper overlay and card dialog are aligned")


if __name__ == "__main__":
    main()
