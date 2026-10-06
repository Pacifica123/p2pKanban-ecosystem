#!/usr/bin/env python3
"""A18 rolling-release canary for the WebKitGTK/GTK/glib/glibc/OpenSSL line (EX-ARCH-011).

    a18_rolling_canary.py snapshot [--profile debug|release]
    a18_rolling_canary.py check    [--profile ...] [--in-uts --report R]

Arch moves these libraries under an already built binary. The canary keeps a
fingerprint of the last system on which a whole UTS run passed and tells, after
any `pacman -Syu`, whether that is still the system the binary was proven on:

    ok               same library line as the last green UTS
    uts              patch/pkgrel drift: rerun the UTS before trusting the build
    rebuild-and-uts  minor/major/epoch transition or changed soname set: rebuild and rerun the UTS
    broken           a linked library or a WebKit helper process is missing: the binary
                     cannot start; see the printed diagnosis (no repair is attempted)

Baseline handling is automatic and needs no flag: `check --in-uts` stores the
current fingerprint as a candidate bound to that UTS report directory, and the
next `check` promotes it to the baseline only if that run's results.json says
overall pass. Files live in ${XDG_STATE_HOME:-~/.local/state}/p2pkanban-dev/,
outside the project tree, so a UTS run from a fresh UserTestSpace copy still
sees the baseline. This is developer-tool state, never the app's own profile.
Read-only towards the system: pacman/pkg-config/ldd queries only, no sudo,
no network, no hooks installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from a18_common import binary_path, write_report

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "p2pkanban-dev"
BASELINE = STATE / "a18-rolling-baseline.json"
CANDIDATE = STATE / "a18-rolling-candidate.json"
HISTORY = STATE / "a18-rolling-history.jsonl"
FORMAT = "p2pkanban-a18-rolling-fingerprint"
# Arch package -> pkg-config module used when pacman is unavailable (non-Arch dev hosts).
WATCHED = {
    "webkit2gtk-4.1": "webkit2gtk-4.1",
    "gtk3": "gtk+-3.0",
    "glib2": "glib-2.0",
    "libsoup3": "libsoup-3.0",
    "openssl": "openssl",
    "glibc": None,
}
HELPERS = ("WebKitWebProcess", "WebKitNetworkProcess")
HELPER_DIRS = ("/usr/lib/webkit2gtk-4.1", "/usr/lib64/webkit2gtk-4.1", "/usr/libexec/webkit2gtk-4.1")
SEVERITY = ["ok", "uts", "rebuild-and-uts", "broken"]


# ---------------------------------------------------------------- pure parsing (tested by check_a18)

def parse_ldd(text: str) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        match = re.match(r"^(\S+)\s+=>\s+(not found|\S+)", line)
        if match:
            if match.group(2) == "not found":
                missing.append(match.group(1))
            else:
                resolved[match.group(1)] = match.group(2)
    return resolved, sorted(missing)


def split_version(version: str) -> tuple[int, list[int], str]:
    """'1:2.48.3-1' -> (1, [2, 48, 3], '1'); '2.40+r16+gaa5-2' -> (0, [2, 40, 16], '2')."""
    epoch = 0
    if ":" in version:
        head, version = version.split(":", 1)
        epoch = int(head) if head.isdigit() else 0
    pkgrel = ""
    if "-" in version:
        version, pkgrel = version.rsplit("-", 1)
    numbers = [int(part) for part in re.findall(r"\d+", version)]
    return epoch, numbers, pkgrel


def classify_version(old: str | None, new: str | None) -> str:
    if old == new:
        return "same"
    if old is None or new is None:
        return "transition"
    old_epoch, old_nums, old_rel = split_version(old)
    new_epoch, new_nums, new_rel = split_version(new)
    if old_epoch != new_epoch or old_nums[:2] != new_nums[:2]:
        return "transition"
    if old_nums != new_nums:
        return "update"
    return "pkgrel" if old_rel != new_rel else "update"


def compare(baseline: dict | None, current: dict) -> dict[str, object]:
    reasons: list[str] = []
    verdict = "ok"

    def raise_to(level: str, reason: str) -> None:
        nonlocal verdict
        reasons.append(reason)
        if SEVERITY.index(level) > SEVERITY.index(verdict):
            verdict = level

    for soname in current.get("missing", []):
        raise_to("broken", f"linked library not found: {soname}")
    for name, path in current.get("helpers", {}).items():
        if not path:
            raise_to("broken", f"WebKit helper process not found: {name}")
    for name, missing in current.get("helperMissing", {}).items():
        for soname in missing:
            raise_to("broken", f"{name} cannot load {soname}")
    changes: dict[str, str] = {}
    if baseline is None:
        reasons.append("no baseline yet: the first green UTS run becomes the baseline")
        return {"verdict": verdict, "reasons": reasons, "packageChanges": changes}
    for name in sorted(set(baseline.get("packages", {})) | set(current.get("packages", {}))):
        old = baseline.get("packages", {}).get(name)
        new = current.get("packages", {}).get(name)
        kind = classify_version(old, new)
        if kind == "same":
            continue
        changes[name] = f"{old} -> {new} ({kind})"
        raise_to("rebuild-and-uts" if kind == "transition" else "uts", f"{name}: {old} -> {new} ({kind})")
    old_sonames, new_sonames = set(baseline.get("sonames", {})), set(current.get("sonames", {}))
    if old_sonames != new_sonames:
        delta = sorted(new_sonames - old_sonames) + ["-" + s for s in sorted(old_sonames - new_sonames)]
        raise_to("rebuild-and-uts", "linked soname set changed: " + ", ".join(delta))
    if baseline.get("binarySha256") != current.get("binarySha256"):
        reasons.append("binary differs from the baseline build (expected after a rebuild)")
    return {"verdict": verdict, "reasons": reasons, "packageChanges": changes}


# ---------------------------------------------------------------- host queries

def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    if not shutil.which(argv[0]):
        return None
    return subprocess.run(argv, text=True, capture_output=True, timeout=60)


def package_versions() -> tuple[str, dict[str, str | None], dict[str, str]]:
    versions: dict[str, str | None] = {}
    pending: dict[str, str] = {}
    pacman = _run(["pacman", "-Q", *WATCHED])
    if pacman is not None:
        for line in pacman.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2:
                versions[parts[0]] = parts[1]
        for name in WATCHED:
            versions.setdefault(name, None)
        upgrades = _run(["pacman", "-Qu"])  # local sync DB only, no network
        for line in (upgrades.stdout if upgrades else "").splitlines():
            parts = line.split()
            if parts and parts[0] in WATCHED:
                pending[parts[0]] = " ".join(parts[1:])
        return "pacman", versions, pending
    for name, module in WATCHED.items():
        result = _run(["pkg-config", "--modversion", module]) if module else None
        versions[name] = result.stdout.strip() if result and result.returncode == 0 else None
    libc = _run(["ldd", "--version"])
    if libc and libc.stdout:
        match = re.search(r"(\d+\.\d+)\s*$", libc.stdout.splitlines()[0])
        versions["glibc"] = match.group(1) if match else None
    return "pkg-config", versions, pending


def find_helpers() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    candidates = [Path(d) for d in HELPER_DIRS] + sorted(Path("/usr/lib").glob("*/webkit2gtk-4.1"))
    for name in HELPERS:
        found[name] = next((str(d / name) for d in candidates if (d / name).is_file()), None)
    return found


def ldd(path: Path) -> tuple[dict[str, str], list[str]]:
    result = _run(["ldd", str(path)])
    if result is None:
        raise SystemExit("ldd is required for the A18 rolling canary")
    return parse_ldd(result.stdout + result.stderr)


def fingerprint(binary: Path) -> dict[str, object]:
    if not binary.is_file():
        raise SystemExit(f"built executable missing: {binary}")
    source, versions, pending = package_versions()
    resolved, missing = ldd(binary)
    helpers = find_helpers()
    helper_missing = {}
    for name, path in helpers.items():
        if path:
            _, gone = ldd(Path(path))
            if gone:
                helper_missing[name] = gone
    os_release = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key in {"ID", "VERSION_ID", "BUILD_ID"}:
                    os_release[key] = value.strip('"')
    except OSError:
        pass
    return {
        "format": FORMAT,
        "formatVersion": 1,
        "takenAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "os": os_release,
        "packages": versions,
        "pendingUpgrades": pending,
        "sonames": resolved,
        "missing": missing,
        "helpers": helpers,
        "helperMissing": helper_missing,
        "binary": str(binary),
        "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }


def diagnosis(verdict: str) -> list[str]:
    if verdict == "broken":
        return [
            "The binary or a WebKit helper cannot load a system library; the app (and its doctor) cannot start.",
            "Do not copy libraries in or downgrade single packages: finish the upgrade with a full `pacman -Syu`.",
            "Then rebuild and rerun the UTS: python3 -B tools/uts_verify.py",
            "Your profile is untouched; if you need the planner before that, use the A17 offline kit (AppImage).",
        ]
    if verdict == "rebuild-and-uts":
        return ["The WebKitGTK/GTK/glib/glibc/OpenSSL line moved since the last green UTS: rebuild and rerun python3 -B tools/uts_verify.py"]
    if verdict == "uts":
        return ["Library patch/pkgrel drift since the last green UTS: rerun python3 -B tools/uts_verify.py"]
    return []


# ---------------------------------------------------------------- baseline lifecycle

def promote_candidate() -> str:
    if not CANDIDATE.is_file():
        return "none"
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    results = Path(candidate.get("reportDir", "")) / "results.json"
    outcome = "discarded (UTS run did not finish)"
    if results.is_file():
        overall = json.loads(results.read_text(encoding="utf-8")).get("overall")
        if overall == "pass":
            BASELINE.write_text(json.dumps(candidate["fingerprint"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with HISTORY.open("a", encoding="utf-8") as history:
                history.write(json.dumps({"promotedFrom": str(results.parent),
                                          "packages": candidate["fingerprint"].get("packages")}, sort_keys=True) + "\n")
            outcome = "promoted (UTS overall pass)"
        else:
            outcome = f"discarded (UTS overall {overall})"
    CANDIDATE.unlink()
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["snapshot", "check"])
    parser.add_argument("--profile", choices=["debug", "release"], default="debug")
    parser.add_argument("--in-uts", action="store_true", help="running inside uts_verify: drift is what this run verifies")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    binary = binary_path(args.profile)
    current = fingerprint(binary)
    if args.command == "snapshot":
        write_report(args.report, current)
        return 1 if current["missing"] or current["helperMissing"] or not all(current["helpers"].values()) else 0

    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    promotion = promote_candidate()
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else None
    result = compare(baseline, current)
    verdict = result["verdict"]
    if args.in_uts:
        if args.report is None:
            raise SystemExit("--in-uts needs --report inside the UTS report directory")
        CANDIDATE.write_text(json.dumps({"reportDir": str(args.report.parent.resolve()), "fingerprint": current},
                                        indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "format": "p2pkanban-a18-rolling-canary",
        "verdict": verdict,
        "inUts": args.in_uts,
        "baselinePromotion": promotion,
        "baselineTakenAt": baseline.get("takenAt") if baseline else None,
        **result,
        "diagnosis": diagnosis(verdict),
        "current": current,
    }
    if args.report:
        write_report(args.report, report)
    print(f"A18 rolling canary: {verdict}")
    for line in result["reasons"] + diagnosis(verdict):
        print("  " + line)
    if verdict == "broken":
        return 1
    if args.in_uts or verdict == "ok":
        if args.in_uts and verdict != "ok":
            print("  this UTS run is the rebuild/retest; a green run makes this system the new baseline")
        return 0
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
