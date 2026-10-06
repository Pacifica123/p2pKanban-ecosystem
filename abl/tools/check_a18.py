#!/usr/bin/env python3
"""A18 deterministic gate: budgets contract, canary logic, process-tree plumbing, UTS wiring.

Needs no display, no built binary and no network. The /proc plumbing is
exercised against a stub process tree, so this gate does NOT claim any real
measurement: those come from the UTS host/runtime probes and the release run.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import a18_common as common
import a18_rolling_canary as canary

ROOT = common.ROOT


def fail(message: str) -> None:
    raise SystemExit("A18 CHECK FAILED: " + message)


def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ budgets contract
budgets = common.load_budgets()
metrics = {b["metric"] for b in budgets["budgets"]}
for required in ("startupSettleMs", "idlePssMiB", "idleCpuPercent", "idleWakeupsPerSecond",
                 "xdgFootprintMiB", "fixtureProfileMiB", "idleInetSockets", "processesAfterExit"):
    expect(required in metrics, f"Gate G budget dimension missing: {required}")
expect(budgets["fixture"]["cards"] >= 10000 and budgets["fixture"]["pendingLocalChanges"] >= 100000,
       "fixture must cover the Gate B scale (10k cards, 100k pending operations)")
expect(budgets["measurementProfile"] == "release", "budgets are defined for the release profile")
invariants = {b["id"] for b in budgets["budgets"] if b["kind"] == "invariant"}
expect({b["metric"] for b in budgets["budgets"] if b["id"] in invariants} == {"idleInetSockets", "processesAfterExit"},
       "network silence and clean exit must stay invariants")

broken = copy.deepcopy(budgets)
broken["acceptedDeviations"] = [{"budgetId": "startup.empty", "adr": "none"}]
try:
    common.validate_budgets(broken)
    fail("a deviation without an ADR was accepted")
except ValueError:
    pass

sample = {
    "runtime-empty": {"startupSettleMs": 5000, "idleInetSockets": 1, "idleCpuPercent": 0.5},
}
rows = {r["id"]: r for r in common.evaluate(budgets, sample, "debug")}
expect(rows["startup.empty"]["verdict"] == "within", "debug allowance not applied to time budgets")
expect(rows["network.idle.empty"]["verdict"] == "over" and rows["network.idle.empty"]["limit"] == 0,
       "invariants must never get a debug allowance")
expect(rows["memory.idle.empty"]["verdict"] == "unmeasured", "a missing metric must be unmeasured, not within")
rows = {r["id"]: r for r in common.evaluate(budgets, sample, "release")}
expect(rows["startup.empty"]["verdict"] == "over", "release must use the raw threshold")
accepted = copy.deepcopy(budgets)
accepted["acceptedDeviations"] = [{"budgetId": "startup.empty", "adr": "ADR-999-example", "reason": "test"}]
common.validate_budgets(accepted)
rows = {r["id"]: r for r in common.evaluate(accepted, sample, "release")}
expect(rows["startup.empty"]["verdict"] == "accepted-deviation" and rows["startup.empty"]["adr"] == "ADR-999-example",
       "ADR-backed deviation not reported")

# ------------------------------------------------------------------ canary logic
LDD = """\tlinux-vdso.so.1 (0x00007ffc)
\tlibwebkit2gtk-4.1.so.0 => /usr/lib/libwebkit2gtk-4.1.so.0 (0x00007f00)
\tlibgtk-3.so.0 => /usr/lib/libgtk-3.so.0 (0x00007f01)
\tlibicuuc.so.76 => not found
\t/lib64/ld-linux-x86-64.so.2 => /usr/lib64/ld-linux-x86-64.so.2 (0x00007f02)
"""
resolved, missing = canary.parse_ldd(LDD)
expect(missing == ["libicuuc.so.76"], f"ldd 'not found' not detected: {missing}")
expect(resolved.get("libgtk-3.so.0") == "/usr/lib/libgtk-3.so.0" and "linux-vdso.so.1" not in resolved, "ldd parse drifted")

for old, new, kind in (
    ("2.48.3-1", "2.48.3-1", "same"),
    ("2.48.3-1", "2.48.3-2", "pkgrel"),
    ("2.48.3-1", "2.48.5-1", "update"),
    ("2.48.3-1", "2.50.0-1", "transition"),
    ("3.24.49-1", "1:3.24.49-1", "transition"),
    ("2.40+r16+gaa533d58ff-2", "2.41+r6+g7a0d4e4d6b-1", "transition"),
    ("2.40+r16+gaa533d58ff-2", "2.40+r20+g1b2c3d4e5f-1", "update"),
    (None, "3.4.4-1", "transition"),
):
    expect(canary.classify_version(old, new) == kind, f"classify {old} -> {new} != {kind}")

base = {"packages": {"webkit2gtk-4.1": "2.48.3-1", "gtk3": "1:3.24.49-1", "glibc": "2.41+r6+g7a0d4e4d6b-1"},
        "sonames": {"libwebkit2gtk-4.1.so.0": "/usr/lib/a", "libicuuc.so.76": "/usr/lib/b"},
        "missing": [], "helpers": {"WebKitWebProcess": "/usr/lib/webkit2gtk-4.1/WebKitWebProcess"},
        "helperMissing": {}, "binarySha256": "0" * 64}
expect(canary.compare(None, base)["verdict"] == "ok", "first run without baseline must not block")
expect(canary.compare(base, copy.deepcopy(base))["verdict"] == "ok", "identical system must be ok")
drift = copy.deepcopy(base); drift["packages"]["gtk3"] = "1:3.24.49-2"
expect(canary.compare(base, drift)["verdict"] == "uts", "pkgrel drift must ask for a UTS rerun")
move = copy.deepcopy(base); move["packages"]["webkit2gtk-4.1"] = "2.50.0-1"
expect(canary.compare(base, move)["verdict"] == "rebuild-and-uts", "WebKitGTK minor transition must ask for a rebuild")
soname = copy.deepcopy(base); soname["sonames"] = {"libwebkit2gtk-4.1.so.0": "/usr/lib/a", "libicuuc.so.77": "/usr/lib/c"}
expect(canary.compare(base, soname)["verdict"] == "rebuild-and-uts", "soname change must ask for a rebuild")
gone = copy.deepcopy(move); gone["missing"] = ["libicuuc.so.76"]
result = canary.compare(base, gone)
expect(result["verdict"] == "broken" and any("libicuuc" in r for r in result["reasons"]), "missing library must be broken")
helper = copy.deepcopy(base); helper["helpers"]["WebKitNetworkProcess"] = None
expect(canary.compare(base, helper)["verdict"] == "broken", "missing WebKit helper must be broken")
expect(any("pacman -Syu" in line for line in canary.diagnosis("broken")), "broken diagnosis must point at a full upgrade")

expect(ROOT not in canary.STATE.parents and canary.STATE.name == "p2pkanban-dev",
       "canary baseline must live outside the project tree (UserTestSpace copies are fresh)")
with tempfile.TemporaryDirectory(prefix="p2pkanban-a18-canary-") as temp:
    state = Path(temp)
    canary.STATE, canary.BASELINE = state, state / "baseline.json"
    canary.CANDIDATE, canary.HISTORY = state / "candidate.json", state / "history.jsonl"
    expect(canary.promote_candidate() == "none", "promotion without candidate")
    for overall, promoted in (("fail", False), ("pass", True)):
        run_dir = state / f"run-{overall}"
        run_dir.mkdir()
        (run_dir / "results.json").write_text(json.dumps({"overall": overall}))
        canary.CANDIDATE.write_text(json.dumps({"reportDir": str(run_dir), "fingerprint": base}))
        outcome = canary.promote_candidate()
        expect(canary.BASELINE.is_file() == promoted, f"UTS {overall}: baseline promotion wrong ({outcome})")
        expect(not canary.CANDIDATE.exists(), "candidate must be consumed")
    canary.CANDIDATE.write_text(json.dumps({"reportDir": str(state / "never-finished"), "fingerprint": move}))
    canary.promote_candidate()
    expect(json.loads(canary.BASELINE.read_text())["packages"] == base["packages"],
           "an unfinished UTS run must not replace the baseline")

# ------------------------------------------------------------------ /proc plumbing on a stub tree
STUB = textwrap.dedent("""\
    #!/usr/bin/env python3
    import os, signal, subprocess, sys, time
    mode = os.environ.get("A18_STUB_MODE", "clean")
    child = [sys.executable, "-c", "import time\\nwhile True: time.sleep(0.2)"]
    if mode == "orphan":
        # a detached helper that ignores SIGTERM: exactly what the exit invariant must catch
        subprocess.Popen([sys.executable, "-c",
            "import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\nwhile True: time.sleep(0.2)"],
            start_new_session=True)
    else:
        helper = subprocess.Popen(child)
        signal.signal(signal.SIGTERM, lambda *_: (helper.terminate(), sys.exit(0)))
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        pass
    while True:
        time.sleep(0.2)
""")
with tempfile.TemporaryDirectory(prefix="p2pkanban-a18-stub-") as temp:
    work = Path(temp)
    stub = work / "stub-app"
    stub.write_text(STUB)
    stub.chmod(0o755)
    for mode, survivors in (("clean", 0), ("orphan", 1)):
        env = common.isolated_env(work / mode, keep_display=False)
        env["A18_STUB_MODE"] = mode
        app = common.App(stub, env, work / "logs", mode)
        try:
            settle = app.wait_settled(timeout=20, webkit_grace=0.5)
            idle = app.idle_window(1.0)
        except RuntimeError as exc:
            app.kill()
            fail(f"stub {mode}: {exc}")
        expect(settle >= 1000, f"settle must not be reported before the 1 s floor: {settle}")
        expect(idle["processCount"] >= 2 and idle["idleCpuPercent"] < 50, f"stub {mode}: idle sample implausible {idle}")
        expect(idle["idlePssMiB"] > 0 and idle["idleInetSockets"] == 0, f"stub {mode}: memory/socket sample implausible {idle}")
        expect(app.stop(timeout=2) == survivors, f"stub {mode}: exit invariant must count {survivors} survivor(s)")

# ------------------------------------------------------------------ tool safety
for rel in ("tools/a18_common.py", "tools/a18_host_budget_probe.py", "tools/a18_host_chaos_probe.py", "tools/a18_rolling_canary.py"):
    source = read(rel)
    for forbidden in ('"sudo"', '"systemctl"', '"rtcwake"', '"pkexec"', '["pacman", "-S', '"iptables"', '"nft"'):
        expect(forbidden not in source, f"{rel} must not invoke {forbidden}")
expect('"pacman", "-Q"' in read("tools/a18_rolling_canary.py"), "canary must stay a read-only pacman query")

# ------------------------------------------------------------------ UTS wiring
plan = json.loads(read("tools/uts_plan.json"))
stage = str(plan.get("stage", ""))
expect(stage[:1] == "A" and int(stage[1:3]) >= 18, f"UTS plan stage regressed: {stage}")
expect(any(item["id"] == "a18" for item in plan["deterministic"]), "check_a18 missing from deterministic plan")
post = {item["id"]: item["command"] for item in plan["host"]["postBuildProbes"]}
expect("--in-uts" in post.get("a18-rolling-canary", []), "rolling canary must run in UTS mode")
expect("profile-scale" in post.get("a18-profile-scale", []), "profile-scale budget probe missing")
runtime = {item["id"]: item["command"] for item in plan["host"].get("runtimeProbes", [])}
expect("runtime" in runtime.get("a18-runtime-budgets", []), "runtime budget probe missing")
expect("tools/a18_host_chaos_probe.py" in runtime.get("a18-chaos", []), "chaos probe missing")
for command in [*post.values(), *runtime.values()]:
    if "--report" in command:
        expect(command[command.index("--report") + 1].startswith("{report_dir}/"), f"report outside the UTS dir: {command}")
verify = read("tools/uts_verify.py")
expect('host.get("runtimeProbes", [])' in verify and '"disabled by --no-runtime"' in verify,
       "uts_verify must run runtimeProbes and skip them with --no-runtime")
expect("'A17' == json.loads" not in read("tools/check_a17.py"), "check_a17 still freezes the UTS stage")
expect(any(line.startswith("A18 real suspend") for line in plan["manualEvidence"]), "real suspend stays manual evidence")

# ------------------------------------------------------------------ docs and evidence
doc = read("docs/A18_PERFORMANCE_POWER_ROLLING.md")
for needle in ("proposed", "release", "rolling-release", "freeze-thaw", "Gate G", "прокси"):
    expect(needle in doc, f"A18 doc must cover: {needle}")
expect("A18 performance/power/rolling-release hardening" in read("docs/IMPLEMENTATION_STATUS.md")
       and "experiment-needed" not in [line for line in read("docs/IMPLEMENTATION_STATUS.md").splitlines()
                                       if line.startswith("| A18")][0], "IMPLEMENTATION_STATUS A18 row not updated")
expect("## A18 implemented boundary" in read("docs/NEXT_PATCH_SEQUENCE.md"), "NEXT_PATCH_SEQUENCE lacks the A18 boundary")
evidence = json.loads(read("evidence/a18-performance-power-rolling.json"))
expect(evidence.get("formatVersion") == 1 and evidence.get("stage") == "A18", "A18 evidence metadata mismatch")
for source in evidence["sources"]:
    actual = hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
    expect(actual == source["sha256"], f"A18 evidence digest drift: {source['path']}")

print("A18 OK: budgets contract, rolling canary, stub process-tree plumbing and UTS wiring; real measurements are host evidence")
