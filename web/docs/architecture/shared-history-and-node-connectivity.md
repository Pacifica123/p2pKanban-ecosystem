# Shared activity and reachable nodes across networks

## This correction

Android Activity used HTTP-only `/boards/:id/activity` even after autonomous relay enrollment. A saved board key did not make that endpoint reachable. Both clients now share an encrypted activity feed: `board.activity` carries the same activity id, timestamp, action, entity, field mask and actor; Android mutations carry `payload.activity` inside their existing immutable mutation. Recovery snapshots and retries do not create feed entries.

The web worker backfills retained original `activity_entries`, freezes delivery per activity and access epoch, and publishes through the board's authenticated encrypted relay channel. This includes comments/labels/columns even where their state has no roaming operation. Receiving a history entry does not apply those unsupported state operations. Canonical history replaces duplicate node-generated mutation activity using `mutationEventId`. Imported common history may be republished once per node/epoch so the creator does not remain the sole historical source. Import does not create another original action.

Android reads the authenticated feed from all writers and keeps it in its durable journal, with a stale indicator when relays fail. HTTP remains the unenrolled-board fallback. Historic original web entries are recovered by backfill; old Android events lacking activity metadata cannot recover an actor/action record that was never retained on any node. This does not invent missing historical events. Relay retention remains a real dependency; this patch does not guarantee indefinite relay storage.

Checklist recovery now merges subsequent signed snapshots into an existing cached board, and merges web snapshot fields into existing PostgreSQL rows using their original field versions. Explicit lifecycle stamps apply deletion; absence alone does not delete. Old snapshot publication times never override newer local toggles. Migration 0023 permits field-version origin ids from compacted snapshots before their original event arrives, without marking those unseen events applied.

## Apply and accept

Apply this web devctl patch to every participating web node, rebuild/restart them, then apply/build/install the matching Android patch over the existing app. No profile reset or re-pairing is required. New migration 0023 preserves existing migration files/checksums. Backfill and peer discovery can require several polling rounds. Verify on different Wi-Fi/mobile networks: create a checklist and two items, toggle on both clients, rename/delete and reconnect; compare values, deleted items and progress. Open History on both clients and compare canonical action ids and ordering. Test comments as history-only replication; do not mistake a history entry for replicated comment content.

An older client ignores the new `board.activity` operation. All nodes must be upgraded for the common feed. Source rollback after migration 0023 is not a database rollback: SQLx records the new version, so use a forward correction or a verified matching database backup for a version downgrade.

Automated evidence: Android merge/history/replica tests, backend compilation/unit tests, and PostgreSQL-engine migration/snapshot tests. Docker/real devices/ISP relay retention are separate acceptance steps.

## Reachability decision and next patch

The repository contains an optional Iroh crate but the normal worker currently runs Nostr delivery only. `IrohTransport::bind` currently creates an endpoint without a supplied durable identity; it has static peers and no request/response service. It therefore does not make an existing private HTTP node reachable from Android or a browser. We must implement the missing node service and address distribution; changing the saved private IP or increasing HTTP timeouts cannot cross unrelated NATs.

Chosen next implementation: authenticated node RPC with stable node identity and a signed device-scoped endpoint catalog. The catalog advertises EndpointId, supported protocol versions, relay routes, optional LAN/HTTPS addresses and expiry. Address changes do not change identity; key rotation requires the existing trusted introduction/delegation flow. Native nodes attempt Iroh direct connections and retain encrypted relay fallback. The existing board journal remains the offline recovery path when the node is asleep or disconnected.

For immediate feature coverage across current React Native and web clients, add a bounded encrypted `node-rpc/1` request/response channel over existing WebSockets/Nostr. Requests have id, recipient node key, authenticated device grant, board/workspace scope, method from an allowlist, expiry and request nonce. Responses bind id, request digest, responder identity and scope. Start with paged activity read and sync status; enforce authorization on the responder, cursor/size/time bounds and replay/dedup handling. Never transfer HTTP bearer tokens or deployment secrets. Receiving a response does not grant new access. Persist only state-changing requests with explicit idempotency; read requests expire rather than silently retry forever.

Then add native Kotlin/React Native and Rust Iroh adapters behind the same RPC interface. Browser transport needs its own compatible gateway/adapter; do not expose the entire backend or promise browsers can use the native crate unchanged. An operator-owned HTTPS reverse tunnel is an alternative deployment path when immediate access to every HTTP endpoint is needed; its domain, TLS, access controls and always-on relay must be selected explicitly, not inserted into user deployments by this patch.

Acceptance matrix for that next patch: foreign Wi-Fi, cellular CGNAT, double NAT, blocked UDP, node restart (same identity), Wi-Fi/cellular switch, relay outage, both peers offline, expired/revoked grant, replayed response, and cursor pagination while new activity is created. UI must distinguish direct, relayed, cached and unreachable, and name the node which answered. A packet ACK alone is not a successfully authorized application response. No transport can make a powered-off node execute a query.

Primary references reviewed 2026-10-01:

- [Iroh endpoint/direct connection model](https://github.com/n0-computer/iroh/blob/main/README.md)
- [Iroh direct and relay fallback](https://www.iroh.computer/blog/iroh-0-91-0-the-last-relay-break)
- [Official language/platform bindings](https://www.iroh.computer/blog/iroh-language-support)
- [Browser gateway constraints](https://github.com/n0-computer/iroh-live/blob/main/docs/guide/browser-relay.md) — illustrative transport constraints, not a ready authenticated p2pKanban gateway.

This document is a concrete next-patch design. The reachability/RPC service is not shipped or deployed by this correction.
