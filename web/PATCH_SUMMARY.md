# Replicate common activity and repair versioned checklist snapshots

Base: supplied snapshot `ab2d2a8`.

Adds encrypted common activity delivery via immutable board.activity events, retained original activity ids/timestamps, canonical mutation history deduplication, historical backfill and per-epoch delivery receipts. Android activity metadata is ingested from existing mutation events; retained common history can be republished once per node/epoch. HTTP history now also includes card.updated. History-only publication does not add unsupported comment/label state replication.

Adds migration 0023 (existing migrations untouched), which permits compacted field stamps before their original event arrives and merges checklist snapshots under original per-field versions, including explicit lifecycle deletion. No event is falsely marked applied merely to store a snapshot stamp. Adds PostgreSQL-engine regression probe and tests. Documentation includes all-node update order and a concrete stable-identity/catalog/RPC/Iroh reachability design; that future service is not implemented/deployed by this patch.

Backend build/unit tests and PostgreSQL-engine scenarios pass locally. Docker, physical Android/ISP/real relay retention acceptance remain separate. Upgrade every participating web node then Android. No profile reset/re-pairing. Source rollback after migration 0023 is not database rollback: use a forward fix or a verified matching database backup for a downgrade.
