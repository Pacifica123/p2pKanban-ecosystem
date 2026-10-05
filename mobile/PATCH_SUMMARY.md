# Read shared activity without HTTP and merge recovery checklist snapshots

Base: supplied snapshot `26b5007`.

Activity reads the shared authenticated relay history from all authorized writers and caches it durably instead of requiring HTTP after enrollment. Android mutations carry canonical activity metadata (id, timestamp, actor, action, entity and field mask); retries/snapshots do not create actions. Offline/relay failure retains common cached history with an explicit stale indicator. History-first journal initialization permits later cached board seeding.

Existing cached boards now consume checklist recovery snapshots, filling missing entities and applying original scalar field versions and lifecycle tombstones. Stale snapshots do not override newer checklist marks. Includes peer-history/offline/error and cached-snapshot/empty-journal regressions. Typecheck, 89 Jest tests and Android export pass. Real APK/phone/network acceptance remains required.

Apply matching web patch to all nodes first, then build/install this Android source over the current app. Do not clear application data or re-pair. Historical records never retained anywhere cannot be fabricated. Common history of comments/labels is not replication of their content. Reachable-node RPC/Iroh is documented as the next patch, not claimed here.
