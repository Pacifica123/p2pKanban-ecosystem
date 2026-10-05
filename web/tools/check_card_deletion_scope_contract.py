#!/usr/bin/env python3
"""Проверяет разделение локального скрытия и глобального tombstone удаления."""

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
        "backend/migrations/0014_card_deletion_scope_and_tombstones.sql",
        "local_card_hides",
        "tombstone-backfill:",
        "scope', 'all_devices'",
    )
    require(
        "backend/src/modules/cards/repo.rs",
        "hide_card_locally",
        "unhide_card_locally",
        "insert into tombstones",
        '"__lifecycle"',
    )
    require(
        "backend/src/transports/roaming.rs",
        "card.delete",
        "apply_remote_card_delete",
        "tombstone_wins",
        "left join tombstones",
    )
    require(
        "backend/src/auth/dto.rs",
        "NodeLinkCardTombstoneSnapshot",
        "card_tombstones",
    )
    require(
        "frontend/src/features/cards/components/CardDetailsDrawer.tsx",
        "Скрыть здесь",
        "Удалить везде",
        "старые копии карточки больше не смогут её воскресить",
    )
    require(
        "docs/api/openapi.yaml",
        "/cards/{cardId}/hide-local:",
        "localVisibility",
        "cardTombstones",
    )
    print("OK: local hide is node-only; global delete is tombstone-aware and roaming-visible")


if __name__ == "__main__":
    main()
