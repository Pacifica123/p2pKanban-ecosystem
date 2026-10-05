#!/usr/bin/env python3
"""Deterministic/network-free A10 sync-core + roaming compatibility gate."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def fail(msg:str)->None: raise SystemExit('A10 CHECK FAILED: '+msg)
def read(rel:str)->str:
    p=ROOT/rel
    if not p.is_file(): fail('missing '+rel)
    return p.read_text(encoding='utf-8')
def load(rel:str): return json.loads(read(rel))
def sha(rel:str)->str: return hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()

required=[
 'src-tauri/migrations/0004_sync_core.sql','src-tauri/src/domain/sync.rs',
 'src-tauri/src/application/sync.rs','src-tauri/src/infrastructure/sqlite/sync.rs',
 'fixtures/protocol/roaming-crypto-vector-v1.json','fixtures/protocol/roaming-board-snapshot-v1.json',
 'docs/evidence/A10_SYNC_ROAMING_COMPATIBILITY.md','evidence/a10-sync-compatibility.json',
]
for rel in required:
    if not (ROOT/rel).is_file(): fail('missing '+rel)

plan=load('tools/uts_plan.json')
current_stage=plan.get('stage')
cargo=read('src-tauri/Cargo.toml')
serde_pin = 'serde = { version = "=1.0.229"' if current_stage == 'A10' else 'serde = { version = "=1.0.228"'
for token in [serde_pin,'serde_json = "=1.0.151"','base64 = "=0.22.1"','hmac = "=0.12.1"','sha2 = "=0.10.9"','time = { version = "=0.3.55"','chacha20poly1305 = "=0.10.1"','getrandom = "=0.4.2"']:
    if token not in cargo: fail('missing exact A10 dependency: '+token)
for forbidden in ['sqlx','postgres','axum']:
    if forbidden in cargo.lower(): fail('forbidden backend dependency leaked into native Cargo.toml: '+forbidden)

domain=read('src-tauri/src/domain/sync.rs')
for token in ['p2p-kanban-sync/1','p2p-kanban-roaming/1','XChaCha20Poly1305','derive_board_tag','validate_sync_envelope','validate_roaming_event','RoamingMergeState','a10_android_roaming_crypto_vector_matches_exactly']:
    if token not in domain: fail('domain sync contract missing '+token)
for forbidden in ['rusqlite','tauri::','std::fs','std::net','reqwest','TcpStream','UdpSocket']:
    if forbidden in domain: fail('domain sync leaked infrastructure capability: '+forbidden)

app=read('src-tauri/src/application/sync.rs')
for token in ['pub trait SyncRepository','pub struct SyncService','SecretKind::BoardCapability','persist_board_capability_secret','load_board_capability_secret']:
    if token not in app: fail('application sync boundary missing '+token)
for forbidden in ['rusqlite','tauri::','secret_service','std::fs','std::net']:
    if forbidden in app: fail('application sync leaked adapter detail: '+forbidden)

sql=read('src-tauri/migrations/0004_sync_core.sql')
for token in ['CREATE TABLE sync_outbox','CREATE TABLE sync_seen_events','CREATE TABLE sync_field_versions','CREATE TABLE sync_entity_extensions','schema_version = 4','min_reader = 4','min_writer = 4','PRAGMA user_version = 4']:
    if token not in sql: fail('schema v4 missing '+token)
for secret in ['refresh_token','access_token','board_key','private_key','vault_root','password']:
    if secret in sql.lower(): fail('secret-bearing column/token forbidden in sync schema: '+secret)
if sha('src-tauri/migrations/0004_sync_core.sql')!='d975a65e66c6f4208d97e1a9d8e8c07b3dd6fe1070ebe32e894da3bfc0b0999a':
    fail('migration 0004 checksum drifted without migration-id correction')
migration=read('src-tauri/src/infrastructure/sqlite/migration.rs')
for token in ['MIGRATION_V3_TO_V4_ID','MIGRATION_V3_TO_V4_SHA256','apply_v3_to_v4']:
    if token not in migration: fail('migration engine v4 contract missing '+token)
match=re.search(r'CURRENT_SCHEMA_VERSION: u32 = (\d+)', migration)
if not match or int(match.group(1)) < 4: fail('migration engine regressed below schema v4')

adapter=read('src-tauri/src/infrastructure/sqlite/sync.rs')
for token in ['materialize_pending','sync_outbox','sync_seen_events','canonical_event_digest','ReplayConflict','record_local_event_versions','observe_remote_clock','apply_board_snapshot','blocked_markers','UnsupportedPendingKind','a10_materialized_local_version_beats_older_remote_event','a10_android_board_snapshot_fixture_seeds_empty_native_board_once','a10_relay_drop_reorder_replay_harness_converges']:
    if token not in adapter: fail('SQLite sync adapter missing '+token)
if 'board.snapshot"=>(apply_board_snapshot' not in adapter.replace(' ',''):
    fail('board.snapshot must be applied through bounded seed semantics')
repo=read('src-tauri/src/infrastructure/sqlite/repository.rs')
for token in ['struct PendingDescriptor','version: Option<VersionStamp>','Some(version.clone())','kind: "card.move"','card_pending_descriptors']:
    if token not in repo: fail('A10 local mutation identity correction missing '+token)
if '"card.reorder"' in repo[repo.find('fn card_pending_descriptors'):repo.find('impl PlannerRepository for SqlitePlannerRepository')]:
    fail('future reorder must not emit the legacy aggregate marker')

sync_fixture=load('fixtures/protocol/sync-envelope-v1.json')
if sync_fixture.get('protocolVersion')!='p2p-kanban-sync/1' or sync_fixture.get('event',{}).get('operation')!='update':
    fail('corrected sync/1 fixture mismatch')
put=load('fixtures/protocol/roaming-card-put-v1.json')
if put.get('operation')!='card.put' or not isinstance(put.get('payload',{}).get('card'),dict):
    fail('roaming card.put fixture must use Android payload.card shape')
delete=load('fixtures/protocol/roaming-card-delete-v1.json')
if delete.get('operation')!='card.delete' or 'deletedAt' not in delete.get('payload',{}):
    fail('roaming card.delete fixture missing Android deletedAt payload')
snapshot=load('fixtures/protocol/roaming-board-snapshot-v1.json')
if snapshot.get('operation')!='board.snapshot' or snapshot.get('payload',{}).get('snapshot',{}).get('schemaVersion')!=6:
    fail('Android snapshot fixture mismatch')
crypto=load('fixtures/protocol/roaming-crypto-vector-v1.json')
if crypto.get('formatVersion')!=1 or len(crypto.get('expectedBoardTag',''))<40 or len(crypto.get('expectedCiphertext',''))<100:
    fail('crypto compatibility vector malformed')
if crypto.get('syntheticBoardKey')!='BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc':
    fail('crypto vector must stay explicitly synthetic/reproducible')

if plan.get('schemaVersion')!=1: fail('UTS plan schema drifted')
ids=[x.get('id') for x in plan.get('deterministic',[])]
if 'a10' not in ids: fail('A10 deterministic gate missing')
if current_stage == 'A10' and ids[-1] != 'a10': fail('A10 must be last while stage A10 is current')
if current_stage != 'A10' and ids.index('a10') >= len(ids)-1: fail('later stage must follow A10')
probes={x.get('id'):' '.join(x.get('command',[])) for x in plan.get('host',{}).get('postBuildProbes',[])}
if 'a10-sync-compatibility' not in probes or 'a10_' not in probes['a10-sync-compatibility']:
    fail('A10 host Cargo compatibility probe missing')
if 'plan.get("stage") != "A09b"' in read('tools/check_a09b.py'):
    fail('A09b checker still freezes later stages')

status=read('docs/IMPLEMENTATION_STATUS.md')
if 'A10 sync-core + Nostr roaming compatibility' not in status or 'A11' not in read('docs/NEXT_PATCH_SEQUENCE.md'):
    fail('SSOT status/next-stage mapping missing')
correction=read('docs/architecture/08-implementation-corrections-and-debt.md')
for token in ['A00 `sync-envelope-v1` used operation `put`','payload.card','post-snapshot column mutation','getrandom 0.4.3']:
    if token not in correction: fail('explicit A10 correction/debt missing '+token)

ev=load('evidence/a10-sync-compatibility.json')
if ev.get('formatVersion')!=1 or ev.get('stage')!='A10': fail('A10 evidence metadata mismatch')
for key in ['facts','inferences','proposals','unresolved','externalAnchors','sources']:
    if not ev.get(key): fail('A10 evidence missing '+key)
anchor=load('evidence/source-anchors.json')
anchors={(x['source'],x['path']):x['sha256'] for x in anchor.get('anchors',[])}
expected={
 ('web','backend/crates/sync-core/src/envelope.rs'):'94fb11808a0a25a96792521f4919b7afa0db7506af179c8652eacf6467ef6dbd',
 ('web','backend/crates/sync-core/src/merge.rs'):'635f5ad23ecadc184697aa56c4e209a185729e1a076bdb4b186de386f1eee179',
 ('web','backend/crates/sync-core/src/validation.rs'):'dc14c98e41e134d9251a548fc8efc606fd46da20d19819db7e212acc45fd2be3',
 ('android','src/features/roaming/codec.ts'):'6093d9857622c375d83403f467a2ed6e68854603af3bcbb1ea9716ba438cc0fd',
 ('android','src/features/roaming/merge.ts'):'4eb262cc3558421f3f86f40d01753a222adb3af6726bca9ffd641eaef1487a14',
 ('android','src/features/roaming/service.ts'):'282b00bdc89965d8734ce5f697102d10170f3fca6b748ead1b18435ffda9a223',
}
for key,value in expected.items():
    if anchors.get(key)!=value: fail('legacy/Android source anchor drifted: '+str(key))
evolving_after_a10={
    'src-tauri/Cargo.toml',
    'src-tauri/src/infrastructure/sqlite/migration.rs',
    # Later stages may make compile-only compatibility edits in the A10 adapter
    # while the semantic contract above remains the authoritative regression gate.
    'src-tauri/src/infrastructure/sqlite/sync.rs',
    'tools/check_a10.py',
    'tools/uts_plan.json',
}
for item in ev['sources']:
    rel=item.get('path',''); expected_sha=item.get('sha256')
    if rel.startswith('/') or '..' in Path(rel).parts or not (ROOT/rel).is_file(): fail('unsafe/missing evidence source '+rel)
    if current_stage != 'A10' and rel in evolving_after_a10:
        continue
    if sha(rel)!=expected_sha: fail('evidence source digest drifted: '+rel)

print('A10 sync-core + roaming compatibility: OK')
