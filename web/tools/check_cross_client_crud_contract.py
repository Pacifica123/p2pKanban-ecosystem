#!/usr/bin/env python3
"""Проверяет статический контракт Android -> coordinator -> web для v1."""

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


def forbid(relative: str, *needles: str) -> None:
    content = read(relative)
    present = [needle for needle in needles if needle in content]
    if present:
        raise SystemExit(f"FAIL: {relative} still contains: {', '.join(present)}")


def main() -> None:
    version = read("VERSION").strip()
    frontend = json.loads(read("frontend/package.json"))
    if frontend.get("version") != version:  # с 2.1.0 проверяется согласованность, а не номер 1.0.0
        raise SystemExit("FAIL: VERSION and frontend/package.json versions are not aligned")

    # С журнала реплик (миграция 0020) события board.appearance.put собирает триггер в SQL.
    require("backend/migrations/0020_replica_event_journal.sql", "op := 'board.appearance.put'")
    forbid("backend/src/modules/cards/dto.rs", "pub status:", "pub completed_at:")
    forbid("docs/api/openapi.yaml", "      - name: completed\n        in: query")
    require(
        "backend/src/transports/roaming.rs",
        "tokio::join!(",
        "tokio::task::JoinSet::new()",
        "publish_pending_board_settings",
        "insert into checklists",
        "insert into checklist_items",
        "Legacy v1 snapshots only fill missing rows",
        "insert into activity_entries",
        '"source": "roaming"',
    )
    require(
        "backend/migrations/0016_column_is_card_status.sql",
        "drop constraint if exists chk_cards_status",
        "drop column status",
        "drop column completed_at",
        "Card state is represented only by board column membership",
    )
    forbid(
        "backend/src/modules/cards/repo.rs",
        "c.status",
        "c.completed_at",
        "status = case",
        "completed_at = case",
    )
    require(
        "backend/migrations/0017_roaming_board_appearance.sql",
        "roaming_board_settings_outbox",
        "board.appearance.updated",
    )
    require(
        "backend/migrations/0012_roaming_activity_echo_guard.sql",
        "payload_jsonb ->> 'source'",
        "= 'roaming'",
        "return new",
    )
    require(
        "frontend/src/features/cards/hooks/useCards.ts",
        "refetchInterval: 3_000",
        "refetchInterval: 4_000",
    )
    require(
        "frontend/src/shared/api/client.ts",
        "refreshInFlight",
        "sessionRequestsBlocked",
        "expireSession()",
    )
    require(
        "frontend/src/features/cards/components/CardDetailsDrawer.tsx",
        "getBoardThemeStyle",
        "Колонка · это статус карточки",
    )
    forbid(
        "frontend/src/features/cards/components/CardDetailsDrawer.tsx",
        "setStatus(",
        "STATUS_OPTIONS",
    )
    require(
        "frontend/src/features/appearance/hooks/useAppearance.ts",
        "refetchInterval: 5_000",
    )
    require(
        "frontend/src/features/checklists/hooks/useChecklists.ts",
        "refetchInterval: 4_000",
    )
    require(
        "frontend/src/features/comments/hooks/useComments.ts",
        "refetchInterval: 5_000",
    )
    require(
        "frontend/src/features/labels/hooks/useLabels.ts",
        "refetchInterval: 5_000",
    )
    require(
        "docs/product/github-devctl-project-integration-concept-v1.md",
        "```mermaid",
        ".p2pkanban/project.json",
        "EvidenceReceipt",
        "receiptId",
    )
    require(
        "docs/product/stable-v1-readiness-2026-07-29.md",
        "Android → web",
        "full-local-release",
        "Вердикт: функционально близко, релизно ещё не готово",
    )
    print("OK: column-state cards, roaming convergence, auth recovery and appearance are aligned")


if __name__ == "__main__":
    main()
