#!/usr/bin/env python3
"""Entry point for the waw developer tool. See README.md."""
import pathlib
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wawlib.cli import main  # noqa: E402

raise SystemExit(main())
