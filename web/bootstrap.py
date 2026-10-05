#!/usr/bin/env python3
"""Small user-facing entry point for the container bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from container_bootstrap import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], project_root=PROJECT_ROOT))
