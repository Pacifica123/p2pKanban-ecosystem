#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uiux.browser_discovery import discover_browsers
from uiux.evidence import write_json, write_text
from uiux.scenario_runner import execute_scenario, report_markdown, validate_all_scenarios

ROOT = Path(__file__).resolve().parents[1]


def default_report_dir(name: str) -> Path:
    return ROOT / ".dev-bootstrap" / "runs" / "manual-uiux" / name


def print_json(payload: dict) -> None:
    # Keep stdout ASCII-safe for Windows release-gates captures that may use
    # legacy console encodings such as cp1251. Human-readable UTF-8 copies are
    # still written to report artifacts by write_json().
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    sys.stdout.write(text)
    sys.stdout.write("\n")


def command_discover_browser(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir) if args.report_dir else default_report_dir("discover-browser")
    result = discover_browsers()
    payload = result.to_dict()
    write_json(report_dir / "browser-discovery.json", payload)
    lines = ["# UIX browser discovery", "", f"- Status: `{result.status}`", f"- Classification: `{result.classification}`", f"- Message: {result.message}", "", "## Candidates", ""]
    for item in result.candidates:
        lines.append(f"- `{item.path}` — exists={item.exists}, executable={item.executable}, version={item.version or item.error or '<unknown>'}")
    write_text(report_dir / "browser-discovery.md", "\n".join(lines) + "\n")
    if args.json:
        print_json(payload)
    else:
        print(f"{result.status}: {result.message}")
        print(f"Report: {report_dir}")
    return 0 if result.status == "ok" else 2


def command_validate_scenarios(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir) if args.report_dir else default_report_dir("validate-scenarios")
    payload = validate_all_scenarios(ROOT)
    write_json(report_dir / "scenario-validation.json", payload)
    lines = ["# UIX scenario validation", "", f"- Status: `{payload['status']}`", f"- Classification: `{payload['classification']}`", f"- Message: {payload['message']}", "", "## Scenarios", ""]
    for item in payload["scenarios"]:
        lines.append(f"- `{item['name']}` / `{item['path']}` — {'OK' if not item['errors'] else 'FAILED'}")
        for error in item["errors"]:
            lines.append(f"  - {error}")
    if payload["missingMarkers"]:
        lines.extend(["", "## Missing markers", ""])
        lines.extend(f"- `{marker}`" for marker in payload["missingMarkers"])
    write_text(report_dir / "scenario-validation.md", "\n".join(lines) + "\n")
    if args.json:
        print_json(payload)
    else:
        print(f"{payload['status']}: {payload['message']}")
        print(f"Report: {report_dir}")
    return 0 if payload["status"] == "ok" else 1


def command_boot(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir) if args.report_dir else default_report_dir("boot")
    report = execute_scenario(
        scenario_name="boot",
        report_dir=report_dir,
        base_url=args.base_url,
        api_base_url=args.api_base_url,
        browser_executable=args.browser_executable,
        start_frontend_server=args.start_frontend,
        project_root=ROOT,
    )
    if args.json:
        print_json(report)
    else:
        print(f"{report['status']}: {report['message']}")
        print(f"Report: {report_dir / 'report.md'}")
    return status_exit_code(report["status"])


def command_scenario(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir) if args.report_dir else default_report_dir(args.name)
    report = execute_scenario(
        scenario_name=args.name,
        report_dir=report_dir,
        base_url=args.base_url,
        api_base_url=args.api_base_url,
        browser_executable=args.browser_executable,
        start_frontend_server=args.start_frontend,
        project_root=ROOT,
    )
    if args.json:
        print_json(report)
    else:
        print(f"{report['status']}: {report['message']}")
        print(f"Report: {report_dir / 'report.md'}")
    return status_exit_code(report["status"])


def command_report(args: argparse.Namespace) -> int:
    input_dir = Path(args.input)
    reports = sorted(input_dir.glob("*/report.json"))
    payload = {"schemaVersion": 1, "tool": "uiux_evidence", "kind": "aggregate-report", "input": str(input_dir), "reports": []}
    for report_path in reports:
        payload["reports"].append(json.loads(report_path.read_text(encoding="utf-8")))
    failed = [item for item in payload["reports"] if item.get("status") != "ok"]
    payload["status"] = "failed" if failed else "ok"
    payload["classification"] = failed[0].get("classification", "REL-UIUX") if failed else "ok"
    if args.json:
        print_json(payload)
    else:
        print(f"{payload['status']}: {len(payload['reports'])} UIX reports found")
        for item in payload["reports"]:
            print(f"- {item.get('scenario')}: {item.get('status')} / {item.get('classification')}")
    return 0 if not failed else 1


def status_exit_code(status: str) -> int:
    if status == "ok":
        return 0
    if status == "skipped_prerequisite":
        return 2
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project-specific UI/UX Evidence Runner v1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover-browser", help="Find a system Chromium-compatible browser and write prerequisite evidence.")
    discover.add_argument("--report-dir")
    discover.add_argument("--json", action="store_true")
    discover.set_defaults(func=command_discover_browser)

    validate = subparsers.add_parser("validate-scenarios", help="Validate scenario JSON files and frontend marker contract.")
    validate.add_argument("--report-dir")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=command_validate_scenarios)

    boot = subparsers.add_parser("boot", help="Open the app and capture boot DOM/console/storage/network evidence.")
    add_runtime_args(boot)
    boot.set_defaults(func=command_boot)

    scenario = subparsers.add_parser("scenario", help="Run a named UIX scenario.")
    scenario.add_argument("--name", required=True, choices=["boot", "mocked-core-flow", "real-backend-core-flow"])
    add_runtime_args(scenario)
    scenario.set_defaults(func=command_scenario)

    aggregate = subparsers.add_parser("report", help="Summarize a directory of UIX evidence reports.")
    aggregate.add_argument("--input", required=True)
    aggregate.add_argument("--json", action="store_true")
    aggregate.set_defaults(func=command_report)
    return parser


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", help="Frontend base URL. Not required with --start-frontend.")
    parser.add_argument("--api-base-url", help="Backend/mock API base URL. Mocked scenarios create a temporary mock API when omitted.")
    parser.add_argument("--browser-executable", help="Explicit Chromium-compatible browser executable path.")
    parser.add_argument("--start-frontend", action="store_true", help="Start a temporary Vite frontend server owned by this runner.")
    parser.add_argument("--report-dir")
    parser.add_argument("--json", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
