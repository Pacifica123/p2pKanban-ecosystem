#!/usr/bin/env python3
"""Deterministic/network-free A15 pacman packaging and signed-repo gate."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A15 CHECK FAILED: " + message)


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        fail("missing " + rel)
    return p.read_text(encoding="utf-8")


def load(rel: str):
    try:
        return json.loads(read(rel))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON {rel}: {exc}")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


required = [
    "packaging/arch/PKGBUILD",
    "packaging/arch/p2pkanban.desktop",
    "packaging/arch/LICENSE",
    "packaging/arch/pacman-repo.conf.example",
    "tools/a15_prepare_release.py",
    "tools/a15_stage_signed_repo.py",
    "tools/a15_host_packaging_probe.py",
    "docs/A15_ARCH_RELEASE.md",
    "docs/evidence/A15_PACMAN_PACKAGING.md",
    "evidence/a15-pacman-packaging.json",
]
for rel in required:
    read(rel)

pkgbuild = read("packaging/arch/PKGBUILD")
for token in (
    "pkgname=p2pkanban",
    "pkgver=0.1.0",
    "pkgrel=1",
    "url=\'https://example.invalid/p2pkanban\'",
    "arch=('x86_64')",
    "'webkit2gtk-4.1'",
    "'gtk3'",
    "'glib2'",
    "'cargo'",
    "'nodejs'",
    "'npm'",
    "'__P2PKANBAN_SOURCE_SHA256__'",
    "npm ci --cache",
    "--ignore-scripts --no-audit --no-fund",
    "cargo fetch --locked",
    "cargo build --frozen --release",
    "cargo test --frozen --release",
    '"$pkgdir/usr/bin/p2pkanban"',
    '"$pkgdir/usr/share/applications/org.p2pkanban.archnative.desktop"',
    '"$pkgdir/usr/share/icons/hicolor/64x64/apps/p2pkanban.png"',
    '"$pkgdir/usr/share/licenses/$pkgname/LICENSE"',
):
    if token not in pkgbuild:
        fail("PKGBUILD missing " + token)
if pkgbuild.count("__P2PKANBAN_SOURCE_SHA256__") != 1:
    fail("PKGBUILD source checksum marker must appear exactly once")
for forbidden in ("sha256sums=('SKIP'", "sudo ", "pacman -S", "pacman -Sy", "pkexec", "systemctl", "/usr/local", "$HOME", "curl ", "wget "):
    if forbidden in pkgbuild:
        fail("PKGBUILD contains forbidden bootstrap/update behavior: " + forbidden)
if re.search(r"\binstall\s*=", pkgbuild):
    fail("A15 package must not add install/remove scriptlets")

# Version agreement is a release invariant.
package = load("package.json")
cargo_text = read("src-tauri/Cargo.toml")
tauri = load("src-tauri/tauri.conf.json")
if package.get("version") != "0.1.0" or 'version = "0.1.0"' not in cargo_text or tauri.get("version") != "0.1.0":
    fail("package/Cargo/Tauri version drifted from A15 PKGBUILD")

# Runtime/schema/protocol remain untouched by packaging.
migration = read("src-tauri/src/infrastructure/sqlite/migration.rs")
if "CURRENT_SCHEMA_VERSION: u32 = 6" not in migration:
    fail("A15 must not advance persistent schema")
conf = load("src-tauri/tauri.conf.json")
if "connect-src 'none'" not in conf.get("app", {}).get("security", {}).get("csp", ""):
    fail("A15 must not widen WebView CSP")
cap = load("src-tauri/capabilities/main-minimal.json")
if cap.get("permissions") != []:
    fail("A15 must not add WebView permissions")

# Package-owned deep-link registration delegates to A13 parser.
desktop = read("packaging/arch/p2pkanban.desktop")
for line in (
    "Type=Application",
    "Exec=p2pkanban %u",
    "Icon=p2pkanban",
    "Terminal=false",
    "MimeType=x-scheme-handler/p2pkanban;",
    "DBusActivatable=false",
):
    if line not in desktop:
        fail("desktop entry missing " + line)
for forbidden in ("sh -c", "bash -c", "%F", "%f", "http://", "https://"):
    if forbidden in desktop:
        fail("desktop entry contains unsafe/unowned dispatch: " + forbidden)
integration = read("src-tauri/src/domain/integration.rs")
if '"p2pkanban://activate"' not in integration or '.strip_prefix("p2pkanban://")' not in integration or "MAX_DEEP_LINK_BYTES" not in integration:
    fail("A15 scheme registration is not backed by A13 bounded parser")

repo_conf = read("packaging/arch/pacman-repo.conf.example")
if "SigLevel = Required TrustedOnly" not in repo_conf:
    fail("repository example must require trusted signatures")
if len(re.findall(r"^Server = https://", repo_conf, flags=re.M)) < 2:
    fail("repository example must document at least two HTTPS mirror slots")
for forbidden in ("TrustAll", "SigLevel = Never", "SigLevel = Optional", "http://"):
    if forbidden in repo_conf:
        fail("repository trust policy weakened by " + forbidden)

license_notice = read("packaging/arch/LICENSE")
if "does not yet declare a public redistribution license" not in license_notice or "do not grant redistribution rights" not in license_notice.lower():
    fail("A15 must not invent a software license")

prep = read("tools/a15_prepare_release.py")
for token in (
    "SOURCE_MARKER",
    "Cargo.lock",
    "package-lock.json",
    "migrationSetSha256",
    "protocolFixtureSetSha256",
    "signingMaterialIncluded",
    "mtime = 0",
    "SKIP",
):
    if token not in prep:
        fail("release preparation missing " + token)
for forbidden in ("subprocess.run", "curl", "wget", "requests", "private_key", "passphrase"):
    if forbidden in prep:
        fail("release preparation unexpectedly performs network/signing/secret behavior: " + forbidden)

signer = read("tools/a15_stage_signed_repo.py")
for token in (
    "--signing-key",
    "--detach-sign",
    "repo-add",
    "--prevent-downgrade",
    "--include-sigs",
    "--sign",
    "--key",
    "release-manifest.json",
    "privateSigningMaterialIncluded",
):
    if token not in signer:
        fail("signed repository tool missing " + token)
for forbidden in ("--passphrase", "secret-key", "export-secret", "sudo", "pacman -S", "TrustAll"):
    if forbidden in signer:
        fail("signed repository tool contains forbidden secret/privilege behavior: " + forbidden)

host_probe = read("tools/a15_host_packaging_probe.py")
for token in (
    '"makepkg"',
    '"namcap"',
    '"desktop-file-validate"',
    '"makechrootpkg"',
    '"repo-add"',
    '"gpg"',
    '"--verifysource"',
    "cleanChrootExecuted",
    "realSigningKeyUsed",
    '["makechrootpkg", "-h"]',
    '" E: "',
    '"Usage: makechrootpkg"',
    '"Flags:"',
    'help_probe = subprocess.run',
):
    if token not in host_probe:
        fail("A15 host packaging probe missing " + token)
for forbidden in ("sudo", "pacman -S", "mkarchroot", "--detach-sign", '["makechrootpkg", "--help"]', 'run(["makechrootpkg", "-h"]'):
    if forbidden in host_probe:
        fail("A15 canonical UTS probe must remain non-root/non-signing: " + forbidden)

# Prove source staging deterministic without Cargo/network by supplying a synthetic
# structurally valid lock graph. This tests archive ordering/metadata/hash binding,
# not dependency resolution itself (canonical UTS owns the real graph).
def fake_lock() -> str:
    names = ["tauri", "rusqlite", "serde", "serde_json", "zbus"] + [f"a15-dummy-{i}" for i in range(20)]
    out = ["# synthetic deterministic A15 checker lock", "version = 4", ""]
    for i, name in enumerate(names):
        out += ["[[package]]", f'name = "{name}"', f'version = "0.0.{i+1}"', ""]
    return "\n".join(out)

with tempfile.TemporaryDirectory(prefix="p2pkanban-a15-") as td:
    tmp = Path(td)
    lock = tmp / "Cargo.lock"
    lock.write_text(fake_lock(), encoding="utf-8")
    digests = []
    for n in (1, 2):
        stage = tmp / f"stage-{n}"
        p = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools" / "a15_prepare_release.py"), "--cargo-lock", str(lock), "--stage", str(stage)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if p.returncode != 0:
            fail("deterministic release prep failed: " + p.stdout)
        meta = json.loads((stage / "release-inputs.json").read_text(encoding="utf-8"))
        archive = stage / meta["sourceArchive"]["filename"]
        resolved = (stage / "PKGBUILD").read_text(encoding="utf-8")
        if "SKIP" in resolved or "__P2PKANBAN_SOURCE_SHA256__" in resolved:
            fail("release prep left checksum bypass/marker")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != meta["sourceArchive"]["sha256"]:
            fail("release archive hash metadata mismatch")
        digests.append((meta["sourceArchive"]["sha256"], hashlib.sha256(resolved.encode()).hexdigest()))
    if digests[0] != digests[1]:
        fail("release source/PKGBUILD staging is not deterministic")

plan = load("tools/uts_plan.json")
stage = plan.get("stage")
try:
    stage_number = int(str(stage).removeprefix("A"))
except ValueError:
    stage_number = -1
if plan.get("schemaVersion") != 1 or not str(stage).startswith("A") or stage_number < 15:
    fail("UTS plan regressed before A15")
ids = [item.get("id") for item in plan.get("deterministic", [])]
if not {"a14", "a15"}.issubset(ids) or ids.index("a14") >= ids.index("a15"):
    fail("A15 deterministic gate missing/not ordered after A14")
post = {item.get("id"): item.get("command") for item in plan.get("host", {}).get("postBuildProbes", [])}
if post.get("a15-package-prep") != [
    "python3", "-B", "tools/a15_host_packaging_probe.py", "--report", "{report_dir}/a15-packaging.json"
]:
    fail("A15 host packaging probe missing from canonical UTS")
manual = "\n".join(plan.get("manualEvidence", []))
for token in ("A15 clean-chroot", "pacman -Qkk", "A15 uninstall preservation", "A15 signing/repository", "A15 licensing"):
    if token not in manual:
        fail("A15 manual/release acceptance missing " + token)

status = read("docs/IMPLEMENTATION_STATUS.md")
if "A15 PKGBUILD + signed-repo packaging" not in status or "canonical packaging UTS + clean-chroot/release evidence pending" not in status:
    fail("A15 implementation ledger missing/premature")
sequence = read("docs/NEXT_PATCH_SEQUENCE.md")
if "A16" not in sequence or "backup/doctor/safe-mode/recovery" not in sequence:
    fail("next stage after A15 is not A16 recovery")
debt = read("docs/architecture/08-implementation-corrections-and-debt.md")
for token in ("DEBT-A15-001", "DEBT-A15-002", "DEBT-A15-003"):
    if token not in debt:
        fail("A15 debt ledger missing " + token)

# Evidence binds A15-owned packaging/release files. Shared status/UTS docs may evolve.
evidence = load("evidence/a15-pacman-packaging.json")
if evidence.get("formatVersion") != 1 or evidence.get("stage") != "A15":
    fail("A15 evidence metadata mismatch")
for key in ("facts", "inferences", "proposals", "unresolved", "externalReferences", "sources"):
    if not evidence.get(key):
        fail("A15 evidence missing " + key)
for item in evidence.get("sources", []):
    rel = item.get("path", "")
    expected = item.get("sha256", "")
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        fail("unsafe A15 evidence source path " + rel)
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("invalid A15 evidence digest " + rel)
    if not (ROOT / rel).is_file() or sha(rel) != expected:
        fail("A15 evidence source digest drifted: " + rel)

print("A15 pacman package + signed repository boundary: OK")
