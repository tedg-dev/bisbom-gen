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


# Valid pipeline modes
VALID_MODES = ("standalone", "sidecar")
DEFAULT_MODE = "standalone"

# Valid phase isolation phases
VALID_PHASES = ("build", "spdx")

# Maps language names to their omnibor config keys
_LANG_OMNIBOR_KEYS = {
    "c-cpp": "omnibor",
    "go": "omnibor_go",
    "rust": "omnibor_rust",
    "java": "omnibor_java",
}


def resolve_omnibor_cfg(config, language):
    """Select the correct omnibor config for a language and mode.

    Supports two config formats:

    **Legacy flat format** (auto-detected)::

        omnibor:
          tracer: bomtrace3
          ...

    **Nested mode format**::

        mode: sidecar
        omnibor:
          standalone:
            tracer: bomtrace3
          sidecar:
            wrapper: /opt/bomsh/bin/bomsh_hook.sh

    When the config section has ``standalone`` or ``sidecar``
    sub-keys, selects the sub-key matching ``config["mode"]``.
    Otherwise returns the section as-is (backward compatible).

    Args:
        config: The full parsed config dict.
        language: Language string (e.g. ``"c-cpp"``,
            ``"java"``).

    Returns:
        The resolved omnibor config dict for the
        given language and mode.

    Raises:
        KeyError: If the omnibor config key is missing.
        ValueError: If the mode is invalid or the mode
            sub-key is missing from a nested config.
    """
    mode = config.get("mode", DEFAULT_MODE)
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode '{mode}'; "
            f"must be one of {VALID_MODES}"
        )

    cfg_key = _LANG_OMNIBOR_KEYS.get(
        language, "omnibor",
    )
    section = config.get(cfg_key)
    if section is None:
        raise KeyError(
            f"Missing config key '{cfg_key}' "
            f"for language '{language}'"
        )

    # Detect nested vs flat format
    if _is_nested_format(section):
        if mode not in section:
            raise ValueError(
                f"Config '{cfg_key}' has nested "
                f"format but no '{mode}' sub-key"
            )
        return section[mode]

    # Legacy flat format — return as-is
    return section


def resolve_paths(config):
    """Resolve all paths from config, env vars, and defaults.

    Priority: config.yaml → environment variable → default.

    Extends the ``paths`` section with tool-specific paths
    that can be auto-detected from environment variables.

    Args:
        config: The full parsed config dict.

    Returns:
        A dict of resolved paths with all keys populated.
    """
    import os

    paths = dict(config.get("paths", {}))

    # Tool-specific paths: config → env → default
    _TOOL_PATHS = {
        "go_root": ("GOROOT", "/usr/local/go"),
        "cargo_home": ("CARGO_HOME", "~/.cargo"),
        "java_home": (
            "JAVA_HOME",
            "/usr/lib/jvm/java-17-openjdk-amd64",
        ),
        "bomsh_dir": ("BOMSH_DIR", "/opt/bomsh"),
    }

    for key, (env_var, default) in _TOOL_PATHS.items():
        if key not in paths:
            env_val = os.environ.get(env_var)
            if env_val:
                paths[key] = env_val
            else:
                paths[key] = default

    # Expand ~ in paths
    for key, val in paths.items():
        if isinstance(val, str) and "~" in val:
            paths[key] = os.path.expanduser(val)

    return paths


def _is_nested_format(section):
    """Check if a config section uses the nested mode format.

    A section is nested if it has ``standalone`` or
    ``sidecar`` as top-level keys.
    """
    if not isinstance(section, dict):
        return False
    return (
        "standalone" in section or "sidecar" in section
    )
