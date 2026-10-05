#!/usr/bin/env python3
"""Non-root A15 packaging acceptance that prepares immutable release inputs.

This probe deliberately does not create a chroot, install packages, alter pacman
configuration, or sign with a real release key. It proves release-source binding,
PKGBUILD/source verification and availability of the host packaging toolchain.
Clean-chroot package build/install/remove and real-key repository signing remain
explicit manual/multi-host evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit("A15 HOST PACKAGING PROBE FAILED: " + message)


def run(argv: list[str], cwd: Path) -> str:
    p = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode != 0:
        fail("command failed: " + " ".join(argv) + "\n" + (p.stdout or ""))
    return p.stdout or ""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    required = ("bash", "makepkg", "namcap", "desktop-file-validate", "makechrootpkg", "repo-add", "gpg")
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        fail("missing Arch packaging commands: " + ", ".join(missing) + "; install devtools/namcap/desktop-file-utils as appropriate")

    cargo_lock = ROOT / "src-tauri" / "Cargo.lock"
    if not cargo_lock.is_file():
        fail("canonical UTS Cargo.lock is missing before A15 package preparation")

    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    stage = report.parent / "a15-release-inputs"
    prep = run([
        "python3", "-B", str(ROOT / "tools" / "a15_prepare_release.py"),
        "--cargo-lock", str(cargo_lock), "--stage", str(stage),
    ], ROOT)

    pkgbuild = stage / "PKGBUILD"
    if "SKIP" in pkgbuild.read_text(encoding="utf-8") or "__P2PKANBAN_SOURCE_SHA256__" in pkgbuild.read_text(encoding="utf-8"):
        fail("staged PKGBUILD did not resolve exact source checksum")
    run(["bash", "-n", str(pkgbuild)], stage)
    srcinfo = run(["makepkg", "--printsrcinfo"], stage)
    (stage / ".SRCINFO").write_text(srcinfo, encoding="utf-8")
    run(["makepkg", "--verifysource"], stage)
    namcap_output = run(["namcap", "PKGBUILD"], stage)
    (stage / "namcap-pkgbuild.txt").write_text(namcap_output, encoding="utf-8")
    namcap_errors = [line for line in namcap_output.splitlines() if " E: " in f" {line} "]
    if namcap_errors:
        fail("namcap PKGBUILD errors:\n" + "\n".join(namcap_errors))
    run(["desktop-file-validate", "p2pkanban.desktop"], stage)

    # Arch devtools makechrootpkg prints valid help for -h but exits non-zero.
    # Binary presence is already proven by shutil.which above, so treat help as
    # a textual capability sanity-check instead of imposing GNU exit-code
    # semantics on the Arch shell script.
    help_probe = subprocess.run(
        ["makechrootpkg", "-h"],
        cwd=stage,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    help_output = help_probe.stdout or ""
    if "Usage: makechrootpkg" not in help_output or "Flags:" not in help_output:
        fail("makechrootpkg -h did not expose the expected Arch devtools help surface\n" + help_output)

    package_list = run(["makepkg", "--packagelist"], stage).strip().splitlines()
    if len(package_list) != 1 or not package_list[0].endswith("p2pkanban-0.1.0-1-x86_64.pkg.tar.zst"):
        fail("unexpected makepkg package filename: " + repr(package_list))

    manifest = json.loads((stage / "release-inputs.json").read_text(encoding="utf-8"))
    archive = stage / manifest["sourceArchive"]["filename"]
    if sha(archive) != manifest["sourceArchive"]["sha256"]:
        fail("release source archive hash drifted after preparation")
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    required_members = {
        "p2pkanban-0.1.0/src-tauri/Cargo.lock",
        "p2pkanban-0.1.0/package-lock.json",
        "p2pkanban-0.1.0/src-tauri/icons/icon.png",
        "p2pkanban-0.1.0/fixtures/protocol/lan-bridge-v1-golden.json",
    }
    if not required_members.issubset(names):
        fail("release source archive is missing required retained inputs")
    forbidden_parts = {"node_modules", "target", "dist", ".git", ".uts-reports"}
    if any(forbidden_parts.intersection(Path(name).parts) for name in names):
        fail("release source archive contains generated/private workspace state")
    for path in stage.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
            fail("release staging unexpectedly contains private-key-shaped material")

    result = {
        "format": "p2pkanban-a15-host-packaging-probe",
        "version": 1,
        "releaseInputs": manifest,
        "srcinfoSha256": sha(stage / ".SRCINFO"),
        "pkgbuildSha256": sha(pkgbuild),
        "expectedPackage": Path(package_list[0]).name,
        "tooling": {name: shutil.which(name) for name in required},
        "cleanChrootExecuted": False,
        "realSigningKeyUsed": False,
        "notes": [
            "makepkg source verification, fail-closed PKGBUILD namcap and desktop-file validation passed non-root.",
            "makechrootpkg availability was PATH-verified and its -h output matched the expected Arch devtools help surface without requiring a zero help exit code.",
            "Clean-chroot build, package namcap, pacman Qkk/remove preservation and real release-key signing remain manual A15 evidence.",
        ],
    }
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
