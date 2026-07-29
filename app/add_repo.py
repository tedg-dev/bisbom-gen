#!/usr/bin/env python3
"""
bisbom-gen — Smart repo discovery and config generation (shim).

This module re-exports all classes and the CLI entry point from
the refactored ``app.repo_discovery`` package so that existing
imports continue to work unchanged:

    from add_repo import GitHubClient, RepoDiscovery

New code should import directly from the sub-packages:

    from app.repo_discovery.github_client import GitHubClient
    from app.repo_discovery.facade import RepoDiscovery
"""

# Keep top-level imports that may be patched by tests
import argparse    # noqa: F401
import base64      # noqa: F401
import json        # noqa: F401
import re          # noqa: F401
import subprocess  # noqa: F401
import sys         # noqa: F401
import yaml        # noqa: F401
from pathlib import Path  # noqa: F401

from data_loader import DataLoader  # noqa: F401

# --- Re-exports from app.repo_discovery ---
from app.repo_discovery.github_client import GitHubClient          # noqa: F401
from app.repo_discovery.build_system_detector import BuildSystemDetector  # noqa: F401
from app.repo_discovery.dependency_analyzer import DependencyAnalyzer     # noqa: F401
from app.repo_discovery.binary_detector import BinaryDetector      # noqa: F401
from app.repo_discovery.build_step_generator import BuildStepGenerator   # noqa: F401
from app.repo_discovery.config_generator import ConfigGenerator    # noqa: F401
from app.repo_discovery.facade import RepoDiscovery                # noqa: F401
from app.repo_discovery.cli import main                            # noqa: F401


if __name__ == "__main__":
    main()
