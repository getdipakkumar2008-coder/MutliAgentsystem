#!/usr/bin/env python3
"""Launcher: lets hooks and users run the CLI without installing the package."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from agentic.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
