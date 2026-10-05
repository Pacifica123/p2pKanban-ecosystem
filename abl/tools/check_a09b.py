#!/usr/bin/env python3
"""Deterministic/network-free A09b resolver correction gate."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def fail(msg: str) -> None: raise SystemExit("A09b CHECK FAILED: " + msg)
def read(rel: str) -> str:
    p=ROOT/rel
    if not p.is_file(): fail("missing " + rel)
    return p.read_text(encoding="utf-8")

cargo=read("src-tauri/Cargo.toml")
if 'chacha20poly1305 = "=0.10.1"' not in cargo:
    fail("stable chacha20poly1305 0.10.1 pin missing")
for forbidden in ('chacha20poly1305 = { version = "=0.11.0"', 'chacha20poly1305 = "=0.11.0"'):
    if forbidden in cargo: fail("A09 yanked-transitive AEAD line returned")
if 'argon2 = "=0.6.0"' not in cargo:
    fail("A09b unexpectedly changed the unrelated Argon2 pin")

impl=read("src-tauri/src/infrastructure/linux/secrets.rs")
for token in ('XChaCha20Poly1305','XNonce','aead::{Aead, KeyInit, Payload}'):
    if token not in impl: fail("vault AEAD API contract drifted: " + token)

plan=json.loads(read("tools/uts_plan.json"))
if plan.get("schemaVersion") != 1: fail("UTS plan schema drifted")
current_stage=plan.get("stage")
ids=[x.get("id") for x in plan.get("deterministic",[])]
for rid in ("a09","a09b"):
    if rid not in ids: fail("missing deterministic gate " + rid)
if ids.index("a09") >= ids.index("a09b"): fail("A09b gate must follow A09")
lock_offline=" ".join(plan.get("cargo",{}).get("lockOffline",[]))
if "generate-lockfile" not in lock_offline or "--offline" not in lock_offline:
    fail("A09b weakened offline Cargo lock acceptance")

status=read("docs/IMPLEMENTATION_STATUS.md")
if "A09b canonical UTS Cargo resolver correction" not in status: fail("status ledger missing A09b")
if "A10" not in read("docs/NEXT_PATCH_SEQUENCE.md"): fail("A10 next stage lost")

# Older A09 regression gate must not freeze the repository at A09.
a09=read("tools/check_a09.py")
if 'plan.get("stage") != "A09"' in a09: fail("A09 checker still freezes later stages")

# Evidence file must match its referenced source bytes.
ev=json.loads(read("evidence/a09b-resolver-correction.json"))
if ev.get("formatVersion") != 1 or ev.get("stage") != "A09b": fail("A09b evidence metadata mismatch")
for key in ("facts","inferences","proposals","unresolved","externalAnchors"):
    if not ev.get(key): fail("A09b evidence missing " + key)
evolving_after_a09b={"src-tauri/Cargo.toml", "tools/check_a09.py", "tools/uts_verify.py"}
for item in ev.get("sources",[]):
    rel=item.get("path"); expected=item.get("sha256")
    if not isinstance(rel,str) or rel.startswith("/") or ".." in Path(rel).parts: fail("unsafe evidence source path")
    p=ROOT/rel
    if not p.is_file(): fail("missing evidence source " + rel)
    if current_stage != "A09b" and rel in evolving_after_a09b:
        continue
    if hashlib.sha256(p.read_bytes()).hexdigest()!=expected: fail("evidence source digest drifted: " + rel)

print("A09b Cargo resolver correction: OK")
