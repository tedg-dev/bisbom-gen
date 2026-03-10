#!/usr/bin/env python3
"""
OmniBOR Analysis — Main orchestration script (shim).

This module re-exports all classes, functions, and the CLI
entry point from the refactored ``app.pipeline`` and
``app.config`` packages so that existing imports continue
to work unchanged:

    from analyze import CommandRunner, AnalysisPipeline
    import analyze; analyze.main()

New code should import directly from the sub-packages:

    from app.config import load_config, timestamp, lang_subdir
    from app.runner import CommandRunner
    from app.pipeline import AnalysisPipeline
"""

# Ensure parent of app/ is on sys.path so that
# ``from app.xxx import ...`` works when this file
# is executed directly (e.g. inside Docker).
import sys as _sys
from pathlib import Path as _Path
_app_parent = str(_Path(__file__).resolve().parent.parent)
if _app_parent not in _sys.path:
    _sys.path.insert(0, _app_parent)

# Keep top-level module imports that tests patch against:
#   @patch("analyze.subprocess.run")
#   @patch("analyze.time.time")
#   @patch("analyze.timestamp", ...)
import argparse          # noqa: F401
import os                # noqa: F401
import re                # noqa: F401
import subprocess        # noqa: F401
import sys               # noqa: F401
import time              # noqa: F401
import yaml              # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path       # noqa: F401

# --- Shared utilities ---
from app.config import load_config, timestamp, lang_subdir  # noqa: F401

# --- Command runner ---
from app.runner import CommandRunner  # noqa: F401

# --- Pipeline components ---
from app.pipeline.validator import DependencyValidator        # noqa: F401
from app.pipeline.cloner import RepoCloner                    # noqa: F401
from app.pipeline.builder import BomtraceBuilder              # noqa: F401
from app.pipeline.spdx_generator import SpdxGenerator         # noqa: F401
from app.pipeline.spdx_validator import SpdxValidator         # noqa: F401
from app.pipeline.syft import SyftGenerator                   # noqa: F401
from app.pipeline.metadata_collector import MetadataCollector  # noqa: F401
from app.pipeline.adg_spdx import AdgSpdxStep                 # noqa: F401
from app.pipeline.binary_collector import BinaryCollector      # noqa: F401
from app.pipeline.doc_writer import DocWriter                  # noqa: F401
from app.pipeline.facade import AnalysisPipeline              # noqa: F401
from app.pipeline.runners import (                             # noqa: F401
    main,
    _run_c_cpp_pipeline,
    _run_rust_pipeline,
    _run_go_pipeline,
)


if __name__ == "__main__":
    main()
