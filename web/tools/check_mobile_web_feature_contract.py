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
    if version != "1.0.0":
        raise SystemExit("FAIL: VERSION must be 1.0.0")

    frontend = json.loads(read("frontend/package.json"))
    if frontend.get("version") != version:
        raise SystemExit("FAIL: frontend package version is not aligned")

    require(
        "backend/src/modules/cards/dto.rs",
        "checklist_item_count",
        "checklist_completed_item_count",
    )
    require(
        "backend/src/modules/activity/mod.rs",
        "/boards/{boardId}/productivity",
    )
    require(
        "backend/src/transports/roaming.rs",
        '"checklists"',
        "apply_checklist_bundle",
        "'checklistItemCount'",
    )
    require(
        "backend/migrations/0010_mobile_checklists_productivity_wallpapers.sql",
        "'image'",
        "'checklist_item'",
        "enqueue_roaming_card_activity",
    )
    require(
        "frontend/src/features/boards/pages/BoardPage.tsx",
        "card-checklist-progress",
        "ProductivityGraph",
    )
    require(
        "frontend/src/shared/appearance/theme.ts",
        "backgroundImage",
        "backgroundSize",
    )
    require(
        "frontend/src/features/bootstrap/lib/projectRoadmapSeed.ts",
        "ROADMAP_CARDS",
        "v2: Rich text в карточках",
        "v2: Интеграция с devctl",
        "v2: Интеграция с GitHub",
        "v2: Интеграция с Obsidian",
        "v2: Пригласительные ссылки и права доступа",
        "updateCard",
    )
    require(
        "backend/migrations/0018_workspace_invitations_and_capability_epochs.sql",
        "workspace_invitations",
        "access_epoch",
        "roaming_board_authorizations",
        "capability_epoch",
    )
    require(
        "backend/src/modules/workspaces/repo.rs",
        "advance_workspace_access_epoch",
        "create_invitation",
        "accept_invitation",
        "revoke_invitation",
    )
    require(
        "frontend/src/features/workspaces/pages/WorkspaceAccessPage.tsx",
        "Новая пригласительная ссылка",
        "Срок жизни",
        "Отозвать",
    )
    require(
        "docs/api/openapi.yaml",
        "/boards/{boardId}/productivity:",
        "checklistItemCount:",
        "- image",
        "/workspaces/{workspaceId}/invitations:",
        "/invitations/{token}/accept:",
        "accessEpoch:",
        "authorPublicKey:",
        "writerPublicKeys:",
    )
    print("OK: mobile/web features, migration, roaming payload and OpenAPI are aligned")


if __name__ == "__main__":
    main()
