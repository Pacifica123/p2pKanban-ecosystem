#!/usr/bin/env python3
"""A01b strict offline build/host acceptance harness.

No step silently skips missing toolchains or dependencies. `doctor` is informational;
`offline-build` is an acceptance command and fails closed.
"""
from __future__ import annotations

import argparse, json, os, platform, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "src-tauri" / "Cargo.toml"
LOCK = ROOT / "src-tauri" / "Cargo.lock"


def run(cmd, *, cwd=ROOT, env=None, capture=False):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, cwd=cwd, env=merged, text=True, check=True,
                          capture_output=capture)


def command(name):
    return shutil.which(name)


def pkg_version(name):
    if not command("pkg-config"):
        return None
    p = subprocess.run(["pkg-config", "--modversion", name], text=True,
                       capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else None


def os_release():
    data = {}
    p = Path("/etc/os-release")
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k] = v.strip().strip('"')
    return data


def doctor():
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "os_release": os_release(),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "wayland_display": bool(os.environ.get("WAYLAND_DISPLAY")),
        "display": bool(os.environ.get("DISPLAY")),
        "commands": {n: command(n) for n in ("node", "npm", "cargo", "rustc", "pkg-config")},
        "packages": {n: pkg_version(n) for n in ("webkit2gtk-4.1", "gtk+-3.0", "glib-2.0")},
        "cargo_lock": LOCK.is_file(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def require_environment():
    missing = [n for n in ("node", "npm", "cargo", "rustc", "pkg-config") if not command(n)]
    if missing:
        raise SystemExit("A01b acceptance unavailable: missing commands: " + ", ".join(missing))
    libs = [n for n in ("webkit2gtk-4.1", "gtk+-3.0", "glib-2.0") if not pkg_version(n)]
    if libs:
        raise SystemExit("A01b acceptance unavailable: missing pkg-config modules: " + ", ".join(libs))
    if not LOCK.is_file():
        raise SystemExit("A01b acceptance unavailable: src-tauri/Cargo.lock is missing; generate/review it on a provisioned host before offline verification")


def verify_dist():
    index = ROOT / "dist" / "index.html"
    if not index.is_file():
        raise SystemExit("A01b build failed: dist/index.html missing")
    text = index.read_text(encoding="utf-8", errors="replace")
    if re.search(r'''(?:src|href)=["']https?://''', text, re.I):
        raise SystemExit("A01b build failed: packaged index contains remote runtime asset")
    assets = ROOT / "dist" / "assets"
    if not assets.is_dir() or not any(p.is_file() for p in assets.rglob("*")):
        raise SystemExit("A01b build failed: packaged Vite assets missing")


def offline_build():
    require_environment()
    # npm and Cargo are explicitly offline. Frontend/Rust build commands must not resolve dependencies.
    run(["npm", "ci", "--offline", "--ignore-scripts", "--no-audit", "--no-fund"])
    run(["npm", "run", "typecheck"])
    run(["npm", "run", "build"])
    verify_dist()
    env = {"CARGO_NET_OFFLINE": "true"}
    run(["cargo", "test", "--manifest-path", str(CARGO), "--locked", "--offline"], env=env)
    run(["cargo", "build", "--manifest-path", str(CARGO), "--locked", "--offline"], env=env)
    binary = ROOT / "src-tauri" / "target" / "debug" / "p2pkanban-arch-native"
    if not binary.is_file():
        raise SystemExit(f"A01b build failed: expected binary missing: {binary}")
    print("A01b strict offline build: OK")
    print("Runtime launch/security evidence is a separate host step; do not infer it from compile success.")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("offline-build")
    args = p.parse_args()
    return doctor() if args.command == "doctor" else offline_build()

if __name__ == "__main__":
    raise SystemExit(main())
