#!/usr/bin/env python3
"""Single-entry UserTestSpace verifier for host-dependent evidence.

Default behavior is network-free. With --allow-network the verifier may populate
npm/Cargo caches, then it re-runs the acceptance build steps offline. It never
uses sudo, pacman, systemctl, Docker, or modifies devctl/workspace policy.

All steps are attempted when dependencies permit. Failures are summarized in
.uts-reports/<timestamp>/summary.txt and machine-readable results.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets as pysecrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "tools" / "uts_plan.json"
REPORT_ROOT = ROOT / ".uts-reports"
SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:token|password|passwd|secret)\s*[=:]\s*)[^\s]+"),
    re.compile(r"(?i)(//[^/:\s]+:)[^@/\s]+(@)"),
]


@dataclass
class Result:
    id: str
    status: str
    command: list[str] | None
    exit_code: int | None
    seconds: float
    log: str | None
    note: str = ""


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(r"\1<redacted>\2", text)
        else:
            text = pattern.sub(r"\1<redacted>", text)
    return text


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "step"


def load_plan() -> dict[str, Any]:
    data = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        raise SystemExit("Unsupported tools/uts_plan.json schemaVersion")
    return data


def command_available(argv: list[str]) -> bool:
    return bool(argv) and shutil.which(argv[0]) is not None


def expand(argv: list[str], report_dir: Path) -> list[str]:
    return [part.replace("{report_dir}", str(report_dir)) for part in argv]


def run_command(step_id: str, argv: list[str], report_dir: Path, *, env: dict[str, str] | None = None) -> Result:
    import time
    start = time.monotonic()
    log_rel = f"logs/{safe_id(step_id)}.log"
    log_path = report_dir / log_rel
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not command_available(argv):
        note = f"missing command: {argv[0] if argv else '<empty>'}"
        log_path.write_text(note + "\n", encoding="utf-8")
        return Result(step_id, "BLOCKED", argv, None, time.monotonic() - start, log_rel, note)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    p = subprocess.run(argv, cwd=ROOT, env=merged, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = redact(p.stdout or "")
    header = "$ " + " ".join(argv) + "\n"
    log_path.write_text(header + output, encoding="utf-8")
    return Result(step_id, "PASS" if p.returncode == 0 else "FAIL", argv, p.returncode, time.monotonic() - start, log_rel)


def synthetic(step_id: str, status: str, note: str) -> Result:
    return Result(step_id, status, None, None, 0.0, None, note)


def last_ok(results: list[Result], step_id: str) -> bool:
    for result in reversed(results):
        if result.id == step_id:
            return result.status == "PASS"
    return False


def offline_then_optional_network(
    step_id: str,
    offline: list[str],
    network: list[str],
    report_dir: Path,
    results: list[Result],
    allow_network: bool,
) -> bool:
    first = run_command(step_id + ".offline", offline, report_dir)
    if first.status == "PASS":
        results.append(first)
        return True
    if not allow_network:
        if step_id == "cargo.fetch" and first.log and any(token in (report_dir / first.log).read_text() for token in
            ("no matching package named", "attempting to make an HTTP request", "failed to download")):
            first.status = "BLOCKED"
            first.note = "Cargo cache incomplete; run python3 -B tools/uts_verify.py --allow-network once, then rerun offline"
        results.append(first)
        results.append(synthetic(step_id, "BLOCKED", "offline preparation failed; rerun with --allow-network to populate cache explicitly"))
        return False
    first.status = "RETRY"
    first.note = "offline cache incomplete; explicit network preparation requested"
    results.append(first)
    prep = run_command(step_id + ".network-prepare", network, report_dir)
    results.append(prep)
    if prep.status != "PASS":
        results.append(synthetic(step_id, "FAIL", "explicit network preparation failed"))
        return False
    second = run_command(step_id + ".offline-recheck", offline, report_dir)
    results.append(second)
    ok = second.status == "PASS"
    results.append(synthetic(step_id, "PASS" if ok else "FAIL", "network preparation used; final acceptance rechecked offline"))
    return ok



def prepare_cargo_lock(
    cargo: dict[str, Any],
    lock_path: Path,
    report_dir: Path,
    results: list[Result],
    allow_network: bool,
) -> bool:
    """Create Cargo.lock with a mandatory offline acceptance pass.

    On a fresh/partial cache, online `generate-lockfile` updates the index but does
    not download the selected crate archives. Rechecking resolution offline before
    `cargo fetch` therefore makes the result depend on whatever crate versions
    happened to be cached on the host. Explicit network preparation must populate
    the exact lock graph first, then remove the online lock and regenerate it
    offline. Byte equality proves that offline resolution selected the same graph.
    """
    first = run_command("cargo.lock.offline", cargo["lockOffline"], report_dir)
    if first.status == "PASS":
        results.append(first)
        if not lock_path.is_file():
            results.append(synthetic("cargo.lock", "FAIL", "offline lock command returned success but Cargo.lock is missing"))
            return False
        results.append(synthetic("cargo.lock", "PASS", "lockfile generated without network"))
        return True

    if not allow_network:
        # A missing offline cache is an unmet host prerequisite. Preserve the
        # failing command and log, but distinguish it from a Rust/test defect.
        if first.log and any(token in (report_dir / first.log).read_text() for token in
            ("no matching package named", "attempting to make an HTTP request", "failed to download")):
            first.status = "BLOCKED"
            first.note = "Cargo cache incomplete; run python3 -B tools/uts_verify.py --allow-network once, then rerun offline"
        results.append(first)
        results.append(synthetic(
            "cargo.lock",
            "BLOCKED",
            "offline lock resolution failed; rerun with --allow-network to populate the exact Cargo cache explicitly",
        ))
        return False

    first.status = "RETRY"
    first.note = "offline cache incomplete; explicit network lock+fetch preparation requested"
    results.append(first)

    prep = run_command("cargo.lock.network-prepare", cargo["lockNetwork"], report_dir)
    results.append(prep)
    if prep.status != "PASS" or not lock_path.is_file():
        results.append(synthetic("cargo.lock", "FAIL", "network lock generation failed or did not create Cargo.lock"))
        return False

    online_lock = lock_path.read_bytes()

    cache = run_command("cargo.lock.network-fetch", cargo["fetchNetwork"], report_dir)
    results.append(cache)
    if cache.status != "PASS":
        results.append(synthetic("cargo.lock", "FAIL", "network cache population for the generated lock failed"))
        return False

    # Prove resolver independence from the online-created lockfile itself. The
    # selected archives/index metadata are now cached; the next lock is generated
    # from scratch with Cargo offline.
    try:
        lock_path.unlink()
    except FileNotFoundError:
        results.append(synthetic("cargo.lock", "FAIL", "Cargo.lock disappeared before offline re-resolution"))
        return False

    second = run_command("cargo.lock.offline-recheck", cargo["lockOffline"], report_dir)
    results.append(second)
    if second.status != "PASS" or not lock_path.is_file():
        results.append(synthetic("cargo.lock", "FAIL", "network preparation used; final lock re-resolution failed offline"))
        return False

    same = lock_path.read_bytes() == online_lock
    results.append(synthetic(
        "cargo.lock.offline-equivalence",
        "PASS" if same else "FAIL",
        "offline-regenerated Cargo.lock is byte-identical to the network-prepared lock"
        if same else
        "offline-regenerated Cargo.lock differs from the network-prepared lock",
    ))
    results.append(synthetic(
        "cargo.lock",
        "PASS" if same else "FAIL",
        "network preparation used only to populate cache; final lock was regenerated and accepted offline",
    ))
    return same

def verify_artifact(step_id: str, rel: str, results: list[Result]) -> bool:
    path = ROOT / rel
    ok = path.is_file()
    results.append(synthetic(step_id, "PASS" if ok else "FAIL", f"artifact {'present' if ok else 'missing'}: {rel}"))
    return ok


def run_deterministic_phase(plan: dict[str, Any], report_dir: Path, results: list[Result], prefix: str) -> None:
    for item in plan.get("deterministic", []):
        result = run_command(prefix + item["id"], item["command"], report_dir)
        results.append(result)
        print(f"[{result.status}] {result.id}")


def write_summary(plan: dict[str, Any], report_dir: Path, results: list[Result], allow_network: bool) -> int:
    failures = [r for r in results if r.status in {"FAIL", "BLOCKED"}]
    lines = [
        f"p2pKanban Arch-native UTS verification — stage {plan.get('stage')}",
        f"report: {report_dir}",
        f"network preparation allowed: {str(allow_network).lower()}",
        "",
    ]
    for r in results:
        detail = f" — {r.note}" if r.note else ""
        log = f" — {r.log}" if r.log else ""
        lines.append(f"[{r.status}] {r.id}{detail}{log}")
    cache_blocked = any(r.status in {"FAIL","BLOCKED"} and r.id in {"cargo.lock","cargo.fetch.offline","cargo.lock.offline"} for r in results)
    if cache_blocked and not allow_network:
        lines += ["", "Cargo preparation required:",
          "python3 -B tools/uts_verify.py --allow-network",
          "After one successful cache preparation, rerun: python3 -B tools/uts_verify.py",
          "Dependent host probes are blocked by preparation; they were not executed."]
    lines += ["", "Manual evidence still required:"]
    for item in plan.get("manualEvidence", []):
        lines.append(f"- {item}")
    lines += ["", f"overall: {'FAIL' if failures else 'PASS'}"]
    if failures:
        lines.append("failed/blocked ids: " + ", ".join(r.id for r in failures))
    summary = "\n".join(lines) + "\n"
    (report_dir / "summary.txt").write_text(summary, encoding="utf-8")
    payload = {
        "schemaVersion": 1,
        "stage": plan.get("stage"),
        "allowNetwork": allow_network,
        "root": str(ROOT),
        "results": [asdict(r) for r in results],
        "manualEvidence": plan.get("manualEvidence", []),
        "overall": "fail" if failures else "pass",
    }
    (report_dir / "results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_ROOT.mkdir(exist_ok=True)
    (REPORT_ROOT / "latest-summary.txt").write_text(summary, encoding="utf-8")
    (REPORT_ROOT / "latest-results.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary, end="")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the canonical UserTestSpace verification plan and keep all logs.")
    parser.add_argument("--allow-network", action="store_true", help="allow explicit npm/Cargo cache preparation; acceptance is rechecked offline")
    parser.add_argument("--no-runtime", action="store_true", help="skip GUI runtime launch probe but keep build/doctor checks")
    parser.add_argument("--deterministic-only", action="store_true", help="run only deterministic A00..current-stage gates; skip host/frontend/Cargo/runtime phases")
    parser.add_argument("--report-dir", type=Path, help="override report directory (default: .uts-reports/<UTC timestamp>)")
    args = parser.parse_args()

    plan = load_plan()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = (args.report_dir or (REPORT_ROOT / stamp)).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    results: list[Result] = []
    secret_canary = "P2PK_A09_UTS_" + pysecrets.token_hex(24)

    print(f"UTS plan {plan.get('stage')} -> {report_dir}")

    # Deterministic gates are independent and all run even if one fails.
    run_deterministic_phase(plan, report_dir, results, "deterministic.")
    if args.deterministic_only:
        return write_summary(plan, report_dir, results, args.allow_network)

    host = plan["host"]
    for step_id, key in (("host.build-doctor", "buildDoctor"), ("host.runtime-doctor", "runtimeDoctor")):
        result = run_command(step_id, expand(host[key], report_dir), report_dir)
        results.append(result)
        print(f"[{result.status}] {result.id}")

    frontend = plan["frontend"]
    frontend_ready = offline_then_optional_network(
        "frontend.dependencies",
        frontend["offlineInstall"], frontend["networkPrepare"], report_dir, results, args.allow_network,
    )
    if frontend_ready:
        for step_id, key in (("frontend.typecheck", "typecheck"), ("frontend.build", "build")):
            result = run_command(step_id, frontend[key], report_dir)
            results.append(result)
            print(f"[{result.status}] {result.id}")
        if last_ok(results, "frontend.build"):
            verify_artifact("frontend.dist", frontend["requiredArtifact"], results)
    else:
        results.append(synthetic("frontend.typecheck", "BLOCKED", "frontend dependencies unavailable"))
        results.append(synthetic("frontend.build", "BLOCKED", "frontend dependencies unavailable"))

    cargo = plan["cargo"]
    lock_path = ROOT / cargo["lock"]
    cargo_ready = True
    if lock_path.is_file():
        results.append(synthetic("cargo.lock", "PASS", f"existing lockfile: {cargo['lock']}"))
    else:
        cargo_ready = prepare_cargo_lock(cargo, lock_path, report_dir, results, args.allow_network)
        if cargo_ready and not lock_path.is_file():
            results.append(synthetic("cargo.lock.artifact", "FAIL", "Cargo lock preparation returned success but Cargo.lock is missing"))
            cargo_ready = False

    if cargo_ready:
        cargo_ready = offline_then_optional_network(
            "cargo.fetch", cargo["fetchOffline"], cargo["fetchNetwork"], report_dir, results, args.allow_network,
        )

    build_ok = False
    if cargo_ready:
        env = {"CARGO_NET_OFFLINE": "true", "P2PKANBAN_UTS_SECRET_CANARY": secret_canary}
        test = run_command("cargo.test", cargo["test"], report_dir, env=env)
        results.append(test)
        build = run_command("cargo.build", cargo["build"], report_dir, env=env)
        results.append(build)
        build_ok = build.status == "PASS"
        if build_ok:
            build_ok = verify_artifact("cargo.binary", cargo["requiredArtifact"], results)
    else:
        results.append(synthetic("cargo.test", "BLOCKED", "Cargo lock/cache preparation unavailable"))
        results.append(synthetic("cargo.build", "BLOCKED", "Cargo lock/cache preparation unavailable"))

    for probe in host.get("postBuildProbes", []):
        step_id = "host." + probe["id"]
        if build_ok:
            result = run_command(step_id, expand(probe["command"], report_dir), report_dir)
            results.append(result)
            print(f"[{result.status}] {result.id}")
        else:
            results.append(synthetic(step_id, "BLOCKED", "native binary was not built successfully"))

    if args.no_runtime:
        results.append(synthetic("runtime.launch-probe", "SKIP", "disabled by --no-runtime"))
    elif build_ok:
        runtime = run_command("runtime.launch-probe", expand(host["runtimeProbe"], report_dir), report_dir)
        results.append(runtime)
    else:
        results.append(synthetic("runtime.launch-probe", "BLOCKED", "native binary was not built successfully"))

    # Re-run repository contracts after UTS has produced ignored build/runtime artifacts.
    # This makes one invocation prove repeatability instead of discovering state pollution
    # only on the next verifier run. No caches are deleted.
    run_deterministic_phase(plan, report_dir, results, "postbuild.deterministic.")

    leaked = []
    for log_path in sorted((report_dir / "logs").glob("*.log")):
        try:
            if secret_canary in log_path.read_text(encoding="utf-8", errors="replace"):
                leaked.append(log_path.name)
        except OSError:
            pass
    results.append(synthetic(
        "security.secret-canary-logs",
        "FAIL" if leaked else "PASS",
        "secret canary leaked into: " + ", ".join(leaked) if leaked else "generated A09 canary absent from verifier logs",
    ))

    return write_summary(plan, report_dir, results, args.allow_network)


if __name__ == "__main__":
    raise SystemExit(main())
