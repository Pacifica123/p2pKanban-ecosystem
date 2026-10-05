#!/usr/bin/env python3
"""Read-only Secret Service capability evidence for A09.

Absence is a supported Linux state, not a failure. This probe never unlocks,
creates, deletes or mutates keyring items and never invokes root/systemd tools.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    data = {
        "schemaVersion": 1,
        "sessionBusEnvironment": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
        "busctlAvailable": shutil.which("busctl") is not None,
        "secretServiceNamePresent": None,
        "observation": "not-probed",
    }
    if data["sessionBusEnvironment"] and data["busctlAvailable"]:
        proc = subprocess.run(
            ["busctl", "--user", "--no-pager", "--no-legend", "list"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if proc.returncode == 0:
            names = {line.split()[0] for line in proc.stdout.splitlines() if line.split()}
            data["secretServiceNamePresent"] = "org.freedesktop.secrets" in names
            data["observation"] = "present" if data["secretServiceNamePresent"] else "absent"
        else:
            data["observation"] = "session-bus-query-failed"
    elif not data["sessionBusEnvironment"]:
        data["observation"] = "no-session-bus-environment"
    else:
        data["observation"] = "busctl-unavailable"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(data, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
