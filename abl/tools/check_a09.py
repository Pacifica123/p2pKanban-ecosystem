#!/usr/bin/env python3
"""Deterministic/network-free A09 Linux secret persistence gate."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def fail(msg: str) -> None:
    raise SystemExit("A09 CHECK FAILED: " + msg)

def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file(): fail("missing " + rel)
    return p.read_text(encoding="utf-8")

required = (
    "src-tauri/src/infrastructure/linux/secrets.rs",
    "docs/evidence/A09_SECRET_PERSISTENCE.md",
    "evidence/a09-secret-persistence.json",
    "tools/a09_host_secret_service_probe.py",
)
for rel in required: read(rel)

cargo = read("src-tauri/Cargo.toml")
for token in (
    'secret-service = { version = "=5.2.0", default-features = false, features = ["rt-tokio-crypto-rust"] }', 'argon2 = "=0.6.0"',
    'chacha20poly1305 = "=0.10.1"',
    'getrandom = "=0.4.2"',
):
    if token not in cargo: fail("missing exact-pinned A09 dependency: " + token)

app = read("src-tauri/src/application/vault.rs")
for forbidden in ("secret_service", "argon2", "chacha20", "rusqlite", "tauri::", "std::fs", "std::process"):
    if forbidden in app.lower(): fail("platform/storage dependency escaped into application vault boundary: " + forbidden)
for token in ("SecretKind", "SecretRecordKey", "SecretValue", "trait SecretVault", "VaultState", "ProviderUnavailable", "ProviderLocked", "ProviderCorrupt", "PassphraseRequired"):
    if token not in app: fail("application vault contract missing " + token)

impl = read("src-tauri/src/infrastructure/linux/secrets.rs")
for token in (
    "SecretService::connect(EncryptionType::Dh)", "get_default_collection", "is_locked()",
    "p2pKanban vault root", "EncryptedFileVault", "XChaCha20Poly1305", "VAULT_AAD",
    "PassphraseVault", "Algorithm::Argon2id", "Version::V0x13", "PassphraseKdfParams",
    "ARGON2_MIN_M_KIB", "ARGON2_MAX_M_KIB", "create_new(true)", "libc::O_NOFOLLOW",
    "VaultState::ProviderUnavailable", "VaultState::ProviderLocked", "VaultState::ProviderCorrupt",
    "VaultState::PassphraseRequired", "a09_wrong_passphrase_and_corruption_fail_closed",
    "a09_passphrase_vault_round_trip_is_encrypted_at_rest",
):
    if token not in impl: fail("A09 provider/storage contract missing " + token)
for forbidden in ("println!(", "dbg!(", "tracing::", "log::", "env::var(\"PASSWORD", "env::var(\"TOKEN"):
    if forbidden in impl: fail("secret implementation contains forbidden diagnostic/input shortcut: " + forbidden)

profile = read("src-tauri/src/infrastructure/profile.rs")
for token in ('root.join("secrets.vault")', 'root.join("vault-root.passphrase")'):
    if token not in profile: fail("A09 profile path missing " + token)

main = read("src-tauri/src/main.rs")
if "bootstrap_vault(&prepared.paths.profile, \"default\")" not in main:
    fail("main does not bootstrap A09 vault behind the existing profile boundary")
api = read("src-tauri/src/desktop_api.rs")
transport = read("src/shared/transport/desktop.ts")
frontend = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "src").rglob("*.ts*")))
for forbidden in (
    "desktop_api_put_secret", "desktop_api_get_secret", "desktop_api_delete_secret",
    "desktop_api_set_refresh_token", "desktop_api_set_device_private_key",
):
    if forbidden in main + api + transport + frontend: fail("raw secret IPC introduced: " + forbidden)
for forbidden in ("localStorage", "sessionStorage"):
    if forbidden in frontend: fail("frontend secret/persistence bypass introduced: " + forbidden)
for token in ("passphraseFallbackAvailable", "provider-unavailable", "provider-locked", "provider-corrupt", "passphrase-required"):
    if token not in api + frontend: fail("safe vault-status capability missing " + token)

schema = "\n".join(p.read_text(encoding="utf-8").lower() for p in sorted((ROOT / "src-tauri/migrations").glob("*.sql")))
for forbidden in ("refresh_token", "access_token", "board_key", "private_key", "vault_root", "secret_key", "password_hash"):
    if forbidden in schema: fail("secret-bearing column leaked into SQLite migrations: " + forbidden)

probe = read("tools/a09_host_secret_service_probe.py")
for forbidden in ("subprocess.run([\"sudo\"", "subprocess.run([\"systemctl\"", ".unlock(", "create_item(", ".delete("):
    if forbidden in probe.lower(): fail("A09 host probe is not read-only/capability-only: " + forbidden)
if "org.freedesktop.secrets" not in probe or "--user" not in probe:
    fail("A09 host probe does not observe the user Secret Service capability")

verifier = read("tools/uts_verify.py")
for token in ("P2PKANBAN_UTS_SECRET_CANARY", "security.secret-canary-logs"):
    if token not in verifier: fail("UTS secret-canary contract missing " + token)
plan = json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1: fail("UTS plan schema mismatch")
current_stage = plan.get("stage")
# A09 remains a regression gate after later stages; it must not freeze the canonical plan at A09.
ids = [x.get("id") for x in plan.get("deterministic", [])]
for required_id in ("a08", "a09"):
    if required_id not in ids: fail("missing deterministic gate " + required_id)
if ids.index("a08") >= ids.index("a09"): fail("A09 deterministic gate must follow A08")
probes = {x.get("id"): x for x in plan.get("host", {}).get("postBuildProbes", [])}
for pid, marker in (("a09-vault-crypto", "a09_"), ("a09-secret-service-state", "a09_host_secret_service_probe.py")):
    item = probes.get(pid)
    if not item or marker not in " ".join(item.get("command", [])): fail("missing A09 UTS probe " + pid)

status = read("docs/IMPLEMENTATION_STATUS.md")
line = next((x for x in status.splitlines() if "A09 production Linux secret persistence matrix" in x), "")
if "implemented" not in line.lower() or "A10" not in line: fail("implementation ledger did not advance A09 toward A10")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A10" not in sequence: fail("next-patch sequence lost A10")
adr = read("docs/architecture/adr/ADR-004-secrets.md")
if "implemented through A09" not in adr or "full planner database encryption is still not claimed" not in adr.lower():
    fail("ADR-004 not synchronized with A09 boundary/non-claim")

# A08 checker must keep validating A08 without freezing the repository at stage A08/A09.
a08 = read("tools/check_a08.py")
if 'plan.get("stage") != "A08"' in a08 or 'exact next architecture patch is **A09' in a08:
    fail("A08 checker still freezes later architecture progression")

# Evidence classifications and source digests.
ev = json.loads(read("evidence/a09-secret-persistence.json"))
if ev.get("formatVersion") != 1 or ev.get("stage") != "A09": fail("A09 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalAnchors"):
    if not ev.get(key): fail("A09 evidence classification missing " + key)
# A09 evidence freezes the bytes that proved A09 itself. Later architecture stages may
# legitimately evolve composition roots such as main.rs while the A09 vault contract
# continues to be checked structurally above. Keep immutable A09 implementation bytes
# pinned, but do not make the historical evidence digest an architecture freeze.
evolving_after_a09={"src-tauri/src/main.rs"}
for item in ev.get("sources", []):
    rel=item.get("path"); digest=item.get("sha256")
    if not isinstance(rel,str) or rel.startswith("/") or ".." in Path(rel).parts: fail("unsafe A09 evidence source path")
    p=ROOT/rel
    if not p.is_file(): fail("missing A09 evidence source " + rel)
    if current_stage != "A09" and rel in evolving_after_a09:
        continue
    if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: fail("A09 evidence source digest drifted: " + rel)

print("A09 Linux secret persistence matrix: OK")
