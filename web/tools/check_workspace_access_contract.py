#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(relative: str, *needles: str) -> None:
    content = (ROOT / relative).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in content]
    if missing:
        raise SystemExit(f"FAIL: {relative} is missing: {', '.join(missing)}")


def main() -> None:
    require(
        "backend/src/modules/common.rs",
        '"owner" | "member"',
        "require_workspace_owner",
        "workspace_access_epoch",
    )
    require(
        "backend/src/modules/workspaces/service.rs",
        "URL_SAFE_NO_PAD",
        "Sha256",
        "expires_in_hours",
    )
    require(
        "backend/src/modules/workspaces/repo.rs",
        "set access_epoch = access_epoch + 1",
        "set revoked_at = now()",
        "'linked_node', $4",
        "advance_workspace_access_epoch",
        ".bind(workspace_id)\n    .bind(&role)\n    .fetch_optional",
    )
    require(
        "backend/src/modules/sync/service.rs",
        "payload.access_epoch != Some(current_epoch)",
        "author_public_key",
        "writer_public_keys",
        "can_write",
        "(board_tag, board_key, _capability_epoch)",
    )
    require(
        "backend/src/transports/roaming.rs",
        "event.capability_epoch != current_epoch",
        "author_public_key = $3",
        "actor_user_id",
    )
    require(
        "docs/product/v1-execution-roadmap.md",
        "Пригласительные ссылки и права доступа",
        "Готово",
    )
    print("OK: workspace access, invitation and capability-rotation contracts are present")


if __name__ == "__main__":
    main()
