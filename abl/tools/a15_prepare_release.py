#!/usr/bin/env python3
"""Create deterministic A15 Arch release inputs without mutating the source tree.

The canonical UTS materializes Cargo.lock in its project copy. This tool binds that
exact lock into a deterministic source archive, resolves the PKGBUILD source hash,
and emits a release-input manifest. It never signs artifacts and never reads a
private key.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PKGBUILD = ROOT / "packaging" / "arch" / "PKGBUILD"
DESKTOP = ROOT / "packaging" / "arch" / "p2pkanban.desktop"
LICENSE = ROOT / "packaging" / "arch" / "LICENSE"
SOURCE_MARKER = "__P2PKANBAN_SOURCE_SHA256__"


def fail(message: str) -> None:
    raise SystemExit("A15 RELEASE PREP FAILED: " + message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_versions() -> str:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    versions = {str(package.get("version")), str(cargo.get("package", {}).get("version")), str(tauri.get("version"))}
    if len(versions) != 1 or "None" in versions:
        fail(f"package/Cargo/Tauri versions disagree: {sorted(versions)}")
    version = versions.pop()
    if version != "0.1.0":
        fail(f"A15 PKGBUILD is currently bound to 0.1.0, got {version}")
    return version


def validate_lock(path: Path) -> dict[str, str | int]:
    if not path.is_file():
        fail(f"Cargo.lock missing: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Cargo.lock is not valid TOML: {exc}")
    version = data.get("version")
    if version not in (3, 4):
        fail(f"unsupported Cargo.lock version: {version!r}")
    packages = data.get("package")
    if not isinstance(packages, list) or len(packages) < 20:
        fail("Cargo.lock package graph is unexpectedly small")
    names = {str(item.get("name")) for item in packages if isinstance(item, dict)}
    for expected in ("tauri", "rusqlite", "serde", "serde_json", "zbus"):
        if expected not in names:
            fail(f"Cargo.lock missing expected package {expected}")
    return {"version": int(version), "packages": len(packages), "sha256": sha256(path)}


def source_files() -> list[Path]:
    explicit = [
        ROOT / "ARCH_NATIVE_REPO",
        ROOT / "index.html",
        ROOT / "package.json",
        ROOT / "package-lock.json",
        ROOT / "tsconfig.json",
        ROOT / "vite.config.mjs",
    ]
    roots = [ROOT / "src", ROOT / "src-tauri", ROOT / "fixtures"]
    files: list[Path] = []
    for p in explicit:
        if not p.is_file():
            fail(f"missing source input {p.relative_to(ROOT)}")
        files.append(p)
    for base in roots:
        if not base.is_dir():
            fail(f"missing source directory {base.relative_to(ROOT)}")
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if "target" in rel.parts or p.name == "Cargo.lock":
                continue
            files.append(p)
    return sorted(set(files), key=lambda p: p.relative_to(ROOT).as_posix())


def tar_add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def build_source_archive(version: str, cargo_lock: Path, destination: Path) -> dict[str, object]:
    prefix = f"p2pkanban-{version}"
    source = source_files()
    lock_bytes = cargo_lock.read_bytes()
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in source:
                    rel = path.relative_to(ROOT).as_posix()
                    tar_add_bytes(tar, f"{prefix}/{rel}", path.read_bytes())
                tar_add_bytes(tar, f"{prefix}/src-tauri/Cargo.lock", lock_bytes)
    return {
        "filename": destination.name,
        "sha256": sha256(destination),
        "bytes": destination.stat().st_size,
        "sourceFiles": len(source) + 1,
    }


def aggregate_digest(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(ROOT).as_posix()):
        rel = path.relative_to(ROOT).as_posix().encode()
        h.update(rel + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cargo-lock", type=Path, required=True, help="Cargo.lock accepted by canonical UTS")
    ap.add_argument("--stage", type=Path, required=True, help="empty/output release staging directory")
    args = ap.parse_args()

    version = read_versions()
    lock = args.cargo_lock.resolve()
    lock_info = validate_lock(lock)
    stage = args.stage.resolve()
    if stage == ROOT or ROOT in stage.parents:
        # A staging path inside .uts-reports is allowed; source-owned packaging dirs are not.
        try:
            rel = stage.relative_to(ROOT)
        except ValueError:
            rel = None
        if rel is not None and (not rel.parts or rel.parts[0] != ".uts-reports"):
            fail("stage inside repository must be under ignored .uts-reports/")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    archive = stage / f"p2pkanban-{version}.tar.gz"
    archive_info = build_source_archive(version, lock, archive)

    for src in (DESKTOP, LICENSE):
        shutil.copy2(src, stage / src.name)

    template = BOOTSTRAP_PKGBUILD.read_text(encoding="utf-8")
    if template.count(SOURCE_MARKER) != 1:
        fail("bootstrap PKGBUILD must contain exactly one source checksum marker")
    resolved = template.replace(SOURCE_MARKER, str(archive_info["sha256"]))
    if "SKIP" in resolved or SOURCE_MARKER in resolved:
        fail("resolved PKGBUILD contains a checksum bypass/unresolved marker")
    (stage / "PKGBUILD").write_text(resolved, encoding="utf-8")

    fixtures = [p for p in (ROOT / "fixtures").rglob("*") if p.is_file()]
    migrations = [p for p in (ROOT / "src-tauri" / "migrations").glob("*.sql") if p.is_file()]
    manifest = {
        "format": "p2pkanban-arch-release-inputs",
        "version": 1,
        "appVersion": version,
        "architecture": "x86_64",
        "sourceArchive": archive_info,
        "cargoLock": lock_info,
        "packageLockSha256": sha256(ROOT / "package-lock.json"),
        "migrationSetSha256": aggregate_digest(migrations),
        "protocolFixtureSetSha256": aggregate_digest(fixtures),
        "desktopEntrySha256": sha256(DESKTOP),
        "licenseNoticeSha256": sha256(LICENSE),
        "signingMaterialIncluded": False,
        "notes": [
            "The generated source archive, not the mutable workspace, is the release build input.",
            "Cargo.lock is copied from the canonical UTS-resolved graph and becomes part of the retained release source archive.",
            "The staged PKGBUILD has an exact SHA-256 for that archive; checksum bypasses are rejected.",
        ],
    }
    (stage / "release-inputs.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
