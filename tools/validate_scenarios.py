#!/usr/bin/env python3
"""Thin wrapper to the canonical synthetic validator implementation."""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "generators" / "validate_scenarios.py"
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
