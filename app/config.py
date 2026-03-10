"""
Shared configuration utilities for OmniBOR Analysis.

Provides config loading, timestamp generation, and language
subfolder resolution used across the pipeline.
"""

import yaml
from datetime import datetime
from pathlib import Path


def load_config(config_path=None):
    """Load config.yaml from the given path or script directory."""
    if config_path is None:
        config_path = (
            Path(__file__).parent / "config.yaml"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def timestamp():
    """Return current timestamp in configured format."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def lang_subdir(repo_cfg):
    """Return the language subfolder name from repo config.

    Used to organize output by language, e.g. c-cpp, go.
    Falls back to 'unknown' if not specified.
    """
    return repo_cfg.get("language", "unknown")
