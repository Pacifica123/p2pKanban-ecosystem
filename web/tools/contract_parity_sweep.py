#!/usr/bin/env python3
"""Check route parity between backend Axum routers, frontend API calls and OpenAPI paths.

The check is intentionally lightweight and dependency-free. It focuses on the
HTTP method + path surface; response/body details still belong to review and
smoke/integration tests.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

METHOD_NAMES = {"get", "post", "put", "patch", "delete"}
ROUTE_RE = re.compile(r'\.route\(\s*"([^"]+)"\s*,\s*([^\n;]+?)\)')
ROUTE_METHOD_RE = re.compile(r'\b(get|post|put|patch|delete)\s*\(')
API_REQUEST_RE = re.compile(r"apiRequest(?:<[^>]+>)?\(\s*([`'\"])(.+?)\1", re.DOTALL)
TEMPLATE_EXPR_RE = re.compile(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}")
HTTP_METHOD_RE = re.compile(r"method\s*:\s*['\"]([A-Za-z]+)['\"]")

EXCLUDED_BACKEND_PATHS = {"/health"}


@dataclass(frozen=True, order=True)
class Route:
    method: str
    path: str

    def render(self) -> str:
        return f"{self.method} {self.path}"


def project_root_from(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "backend").is_dir() and (candidate / "frontend").is_dir() and (candidate / "docs").is_dir():
            return candidate
    raise SystemExit("Could not find project root with backend/, frontend/ and docs/.")


def frontend_template_to_openapi_path(raw: str) -> str:
    return TEMPLATE_EXPR_RE.sub(lambda match: "{" + match.group(1) + "}", raw)


def extract_backend_routes(root: Path) -> set[Route]:
    files = [root / "backend/src/auth/mod.rs"] + sorted((root / "backend/src/modules").glob("*/mod.rs"))
    routes: set[Route] = set()
    for file_path in files:
        text = file_path.read_text(encoding="utf-8")
        for path, expression in ROUTE_RE.findall(text):
            if path in EXCLUDED_BACKEND_PATHS:
                continue
            methods = ROUTE_METHOD_RE.findall(expression)
            if not methods:
                continue
            for method in methods:
                routes.add(Route(method.upper(), path))
    return routes


def extract_frontend_calls(root: Path) -> set[Route]:
    routes: set[Route] = set()
    for file_path in sorted((root / "frontend/src").rglob("*.ts")) + sorted((root / "frontend/src").rglob("*.tsx")):
        if "/test/" in file_path.as_posix():
            continue
        text = file_path.read_text(encoding="utf-8")
        for match in API_REQUEST_RE.finditer(text):
            raw_path = match.group(2).strip()
            if not raw_path.startswith("/"):
                continue
            call_end = text.find(");", match.end())
            if call_end == -1 or call_end - match.end() > 800:
                call_end = min(len(text), match.end() + 260)
            call_tail = text[match.end() : call_end]
            method_match = HTTP_METHOD_RE.search(call_tail)
            method = method_match.group(1).upper() if method_match else "GET"
            routes.add(Route(method, frontend_template_to_openapi_path(raw_path)))
    return routes


def extract_openapi_routes(root: Path) -> set[Route]:
    spec_path = root / "docs/api/openapi.yaml"
    routes: set[Route] = set()
    in_paths = False
    current_path: str | None = None

    for raw_line in spec_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line == "paths:":
            in_paths = True
            current_path = None
            continue
        if not in_paths:
            continue
        if line and not line.startswith(" "):
            break
        path_match = re.match(r"^  (/[^:]+):\s*$", line)
        if path_match:
            current_path = path_match.group(1)
            continue
        method_match = re.match(r"^    (get|post|put|patch|delete):\s*$", line)
        if method_match and current_path:
            routes.add(Route(method_match.group(1).upper(), current_path))
    return routes


def sorted_render(routes: set[Route]) -> list[str]:
    return [route.render() for route in sorted(routes)]


def print_section(title: str, routes: set[Route]) -> None:
    print(f"\n{title} ({len(routes)})")
    for line in sorted_render(routes):
        print(f"  - {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check backend/frontend/OpenAPI route parity.")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--check", action="store_true", help="Return non-zero when parity mismatches are found.")
    parser.add_argument("--verbose", action="store_true", help="Print all discovered routes, not only mismatches.")
    args = parser.parse_args(argv)

    root = project_root_from(Path(args.root))
    backend = extract_backend_routes(root)
    frontend = extract_frontend_calls(root)
    openapi = extract_openapi_routes(root)

    backend_missing_in_openapi = backend - openapi
    openapi_without_backend = openapi - backend
    frontend_missing_in_backend = frontend - backend
    frontend_missing_in_openapi = frontend - openapi

    print("== contract parity sweep ==")
    print(f"Project root: {root}")
    print(f"Backend routes: {len(backend)}")
    print(f"Frontend API calls: {len(frontend)}")
    print(f"OpenAPI routes: {len(openapi)}")

    if args.verbose:
        print_section("Backend routes", backend)
        print_section("Frontend API calls", frontend)
        print_section("OpenAPI routes", openapi)

    mismatches = [
        ("Backend routes missing in OpenAPI", backend_missing_in_openapi),
        ("OpenAPI routes without backend route", openapi_without_backend),
        ("Frontend calls missing in backend", frontend_missing_in_backend),
        ("Frontend calls missing in OpenAPI", frontend_missing_in_openapi),
    ]

    has_mismatch = False
    for title, routes in mismatches:
        if routes:
            has_mismatch = True
            print_section(title, routes)

    if not has_mismatch:
        print("OK: backend routes, frontend API calls and OpenAPI paths are in parity.")
        return 0

    if args.check:
        print("FAIL: contract parity mismatches detected.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
