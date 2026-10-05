#!/usr/bin/env python3
"""Static regression checks for the Android native-auth HTTP contract."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NATIVE_ROUTES = (
    "/auth/native/sign-up",
    "/auth/native/sign-in",
    "/auth/native/refresh",
    "/auth/native/sign-out",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_router() -> None:
    router = (ROOT / "backend/src/auth/mod.rs").read_text(encoding="utf-8")
    handlers = (ROOT / "backend/src/auth/handler.rs").read_text(encoding="utf-8")
    service = (ROOT / "backend/src/auth/service.rs").read_text(encoding="utf-8")
    dto = (ROOT / "backend/src/auth/dto.rs").read_text(encoding="utf-8")
    middleware = (ROOT / "backend/src/http/middleware.rs").read_text(encoding="utf-8")

    for route in NATIVE_ROUTES:
        require(f'.route("{route}"' in router, f"backend route is missing: {route}")

    for handler in ("native_sign_up", "native_sign_in", "native_refresh", "native_sign_out"):
        require(f"pub async fn {handler}" in handlers, f"handler is missing: {handler}")

    require("NativeAuthSuccessResponse" in dto, "native auth response DTO is missing")
    require("pub refresh_token: String" in dto, "native response does not expose refreshToken")
    require(
        'mode: "native_refresh_token_plus_bearer"' in service,
        "native auth mode is missing",
    )
    require(
        'path.starts_with("/api/v1/auth/native/")' in middleware,
        "native auth routes are not rate limited",
    )


def check_openapi_parity() -> None:
    openapi = (ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8")
    for route in NATIVE_ROUTES:
        require(f"  {route}:" in openapi, f"OpenAPI route is missing: {route}")
    require("NativeAuthSuccessResponse:" in openapi, "OpenAPI native auth response is missing")
    require("refreshToken:" in openapi, "OpenAPI refreshToken field is missing")

    result = subprocess.run(
        [sys.executable, "-B", "tools/contract_parity_sweep.py", "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(result.returncode == 0, result.stdout)


def check_update_fingerprint() -> None:
    source = (ROOT / "tools/container_bootstrap.py").read_text(encoding="utf-8")
    ast.parse(source, filename="tools/container_bootstrap.py")
    require(
        'Path("backend/src")' in source,
        "local update fingerprint ignores backend source changes",
    )


def main() -> int:
    try:
        check_router()
        check_openapi_parity()
        check_update_fingerprint()
    except (AssertionError, OSError, SyntaxError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: Android native-auth routes, token response, rate limit, OpenAPI and update fingerprint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
