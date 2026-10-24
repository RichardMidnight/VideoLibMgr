#!/usr/bin/env python3
"""Development launcher: checks prerequisites, then starts the app."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    from vlm.bootstrap import ensure_prerequisites

    if not ensure_prerequisites():
        return 1

    from vlm.app import main as run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
