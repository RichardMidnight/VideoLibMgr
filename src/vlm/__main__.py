"""Entry point that can install missing prerequisites before importing Qt."""

from __future__ import annotations

from .bootstrap import ensure_prerequisites


def main() -> int:
    if not ensure_prerequisites():
        return 1
    from .app import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
