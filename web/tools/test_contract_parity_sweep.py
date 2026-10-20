#!/usr/bin/env python3
"""Route parity sweep: template paths, info.version vs VERSION (docs/api/contract-parity-sweep-v1.md)."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import contract_parity_sweep as sweep

SPEC = """openapi: 3.0.3
info:
  title: test
  version: {version}
paths:
  /ring:
    get:
      summary: ring
  /cards/{{cardId}}:
    patch:
      summary: card
components: {{}}
"""
ROUTER = """pub fn router() -> Router {
    Router::new()
        .route("/ring", get(ring)).route("/cards/{id}", patch(card))
}
"""
CLIENT = """export const ring = () => apiRequest<Ring>(`/ring`);
export const card = (card: Card) => apiRequest(`/cards/${encodeURIComponent(card.id)}?x=1`, { method: 'PATCH' });
"""


def project(root: Path, spec_version: str = "2.1.0", version: str = "2.1.0") -> Path:
    for rel, body in {
        "VERSION": version + "\n",
        "docs/api/openapi.yaml": SPEC.format(version=spec_version),
        "backend/src/auth/mod.rs": "pub fn router() {}\n",
        "backend/src/modules/ring/mod.rs": ROUTER,
        "frontend/src/features/ring/api/ring.ts": CLIENT,
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def run(root: Path) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = sweep.main(["--root", str(root), "--check"])
    return code, out.getvalue()


class ContractParitySweepTest(unittest.TestCase):
    def test_template_paths_match_backend_and_openapi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(project(Path(tmp)))
        self.assertEqual(code, 0, out)
        self.assertIn("OK:", out)

    def test_expression_template_becomes_parameter(self) -> None:
        self.assertEqual(sweep.frontend_template_to_openapi_path("/cards/${encodeURIComponent(card.id)}?x=1"), "/cards/{param}")
        self.assertEqual(sweep.frontend_template_to_openapi_path("/boards/${boardId}/cards"), "/boards/{boardId}/cards")

    def test_info_version_must_match_version_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(project(Path(tmp), spec_version="0.2.0"))
        self.assertEqual(code, 1, out)
        self.assertIn("info.version 0.2.0 != VERSION 2.1.0", out)

    def test_repository_spec_is_in_parity(self) -> None:
        code, out = run(Path(__file__).resolve().parents[1])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
