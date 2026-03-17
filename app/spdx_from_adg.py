#!/usr/bin/env python3
"""
Generate a complete SPDX 2.3 JSON document from OmniBOR ADG data (shim).

This module re-exports all classes and the CLI entry point from
the refactored ``app.spdx`` package so that existing imports
continue to work unchanged:

    from spdx_from_adg import AdgParser, AdgSpdxGenerator

New code should import directly from the sub-packages:

    from app.spdx.parser import AdgParser
    from app.spdx.generator import AdgSpdxGenerator
"""

# Keep top-level imports that may be patched by tests
import argparse   # noqa: F401
import json       # noqa: F401
import re         # noqa: F401
import uuid       # noqa: F401
from datetime import datetime, timezone  # noqa: F401
from pathlib import Path                 # noqa: F401

# --- Re-exports from app.spdx ---
from app.spdx.parser import AdgParser                        # noqa: F401
from app.spdx.resolver import ComponentResolver               # noqa: F401
from app.version_detection import VendoredVersionDetector       # noqa: F401
from app.spdx.emitter import SpdxEmitter                      # noqa: F401
from app.spdx.generator import AdgSpdxGenerator               # noqa: F401
from app.spdx.cli import main                                 # noqa: F401


if __name__ == "__main__":
    main()
