#!/usr/bin/env python3
"""Standalone entry point for the PyQt6 Tech News Scraper GUI."""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Pre-import numpy (and datasketch which wraps it) on the main thread.
# On macOS / Apple Silicon, numpy's first-time initialisation runs a
# self-test (_mac_os_check → polyfit → linalg.inv) that invokes BLAS/LAPACK.
# If that first import happens from a background thread (e.g. AsyncBridge) the
# BLAS layer crashes with a bus error.  Importing here, before any threads are
# spawned, avoids the problem entirely.
try:
    import numpy  # noqa: F401
    import datasketch  # noqa: F401
except ImportError:
    pass

from gui_qt.app_qt_migrated import main

if __name__ == "__main__":
    main()
