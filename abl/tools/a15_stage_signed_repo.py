#!/usr/bin/env python3
"""Stage a signed p2pKanban pacman repository using an external GPG key.

No private key, passphrase, GNUPGHOME or exported secret material is accepted as
an input. Signing is delegated to the caller's configured gpg-agent/keyring.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PACKAGE_RE = re.compile(r"^p2pkanban-[0-9][A-Za-z0-9._+:-]*-[0-9]+-x86_64\.pkg\.tar\.zst$")
KEY_RE = re.compile(r"^[A-Fa-f0-9]{16,64}$")


def fail(message: str) -> None:
    raise SystemExit("A15 SIGNED REPO FAILED: " + message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv: list[str], cwd: Path) -> None:
    p = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        fail("command failed: " + " ".join(argv) + "\n" + (p.stdout or ""))


def key_fingerprint(key: str) -> str:
    p = subprocess.run(
        ["gpg", "--batch", "--with-colons", "--fingerprint", "--list-keys", key],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.returncode != 0:
        fail("signing public key is not available in GPG keyring")
    for line in p.stdout.splitlines():
        fields = line.split(":")
        if fields and fields[0] == "fpr" and len(fields) > 9 and fields[9]:
            return fields[9]
    fail("could not resolve signing key fingerprint")
    raise AssertionError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--signing-key", required=True, help="GPG fingerprint/key id already present in the caller keyring")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--repo-name", default="p2pkanban")
    args = ap.parse_args()

    package = args.package.resolve()
    if not package.is_file() or not PACKAGE_RE.fullmatch(package.name):
        fail("package must be p2pkanban-<version>-<rel>-x86_64.pkg.tar.zst")
    if not KEY_RE.fullmatch(args.signing_key):
        fail("signing key must be a hex key id/fingerprint, never a key file or passphrase")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", args.repo_name):
        fail("unsafe repository name")
    for cmd in ("gpg", "repo-add"):
        if shutil.which(cmd) is None:
            fail(f"required command not found: {cmd}")

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dst = out / package.name
    shutil.copy2(package, dst)
    sig = out / (package.name + ".sig")
    if sig.exists():
        sig.unlink()

    fingerprint = key_fingerprint(args.signing_key)
    run([
        "gpg", "--batch", "--yes", "--local-user", fingerprint,
        "--output", str(sig), "--detach-sign", str(dst),
    ], out)
    run(["gpg", "--batch", "--verify", str(sig), str(dst)], out)

    db = out / f"{args.repo_name}.db.tar.zst"
    run([
        "repo-add", "--prevent-downgrade", "--include-sigs", "--sign", "--key", fingerprint,
        str(db), str(dst),
    ], out)
    db_sig = Path(str(db) + ".sig")
    if not db.is_file() or not db_sig.is_file():
        fail("repo-add did not produce signed repository database")
    run(["gpg", "--batch", "--verify", str(db_sig), str(db)], out)

    manifest = {
        "format": "p2pkanban-signed-pacman-repo",
        "version": 1,
        "repository": args.repo_name,
        "architecture": "x86_64",
        "signingKeyFingerprint": fingerprint,
        "package": {"file": dst.name, "sha256": sha256(dst), "bytes": dst.stat().st_size},
        "packageSignature": {"file": sig.name, "sha256": sha256(sig), "bytes": sig.stat().st_size},
        "database": {"file": db.name, "sha256": sha256(db), "bytes": db.stat().st_size},
        "databaseSignature": {"file": db_sig.name, "sha256": sha256(db_sig), "bytes": db_sig.stat().st_size},
        "privateSigningMaterialIncluded": False,
    }
    (out / "release-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
