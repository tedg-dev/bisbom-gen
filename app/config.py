"""
Shared configuration utilities for OmniBOR Analysis.

Provides config loading, timestamp generation, and language
subfolder resolution used across the pipeline.
"""

import yaml
from datetime import datetime
from pathlib import Path


def load_config(config_path=None, validate=True):
    """Load config.yaml from the given path or script directory.

    When ``validate`` is true (the default), every repo entry that
    declares a ``build_profile`` is validated against the controlled
    vocabulary, and any repo lacking one is rejected. Pass
    ``validate=False`` to load raw YAML without schema enforcement.
    """
    if config_path is None:
        config_path = (
            Path(__file__).parent / "config.yaml"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if validate:
        validate_repos(config)
    return config


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

# ── build_profile schema ─────────────────────────────
# Controlled vocabulary for the per-repo ``build_profile`` block, which
# records the build-tool "flavor" of each repository in a generic,
# language-agnostic way. ``traits`` is an open list of additive factual
# descriptors (e.g. ``reactor``, ``vendored``, ``skip-tests``).
BUILD_TOOLS = frozenset({
    "autotools", "make", "cmake", "meson",
    "cargo", "go", "maven", "gradle",
})
BUILD_STRUCTURES = frozenset({
    "single-module", "multi-module", "workspace",
})


def validate_build_profile(profile, repo_name="<unknown>"):
    """Validate a single ``build_profile`` mapping.

    Args:
        profile: The ``build_profile`` value from a repo entry.
        repo_name: Repo name, used only for error messages.

    Raises:
        ValueError: If the profile is malformed or uses a value
            outside the controlled vocabulary.
    """
    if not isinstance(profile, dict):
        raise ValueError(
            f"repo '{repo_name}': build_profile must be a "
            f"mapping, got {type(profile).__name__}"
        )

    tool = profile.get("tool")
    if tool not in BUILD_TOOLS:
        raise ValueError(
            f"repo '{repo_name}': build_profile.tool '{tool}' "
            f"is not one of {sorted(BUILD_TOOLS)}"
        )

    structure = profile.get("structure")
    if structure not in BUILD_STRUCTURES:
        raise ValueError(
            f"repo '{repo_name}': build_profile.structure "
            f"'{structure}' is not one of "
            f"{sorted(BUILD_STRUCTURES)}"
        )

    dsl = profile.get("dsl")
    if dsl is not None and not isinstance(dsl, str):
        raise ValueError(
            f"repo '{repo_name}': build_profile.dsl must be a "
            f"string or omitted, got {type(dsl).__name__}"
        )

    tool_version = profile.get("tool_version")
    if tool_version is not None and not isinstance(
        tool_version, str
    ):
        raise ValueError(
            f"repo '{repo_name}': build_profile.tool_version "
            f"must be a quoted string or omitted, got "
            f"{type(tool_version).__name__}"
        )

    java_home = profile.get("java_home")
    if java_home is not None and not isinstance(java_home, str):
        raise ValueError(
            f"repo '{repo_name}': build_profile.java_home must be "
            f"a string (absolute JDK path) or omitted, got "
            f"{type(java_home).__name__}"
        )

    traits = profile.get("traits", [])
    if not isinstance(traits, list) or not all(
        isinstance(t, str) for t in traits
    ):
        raise ValueError(
            f"repo '{repo_name}': build_profile.traits must be "
            f"a list of strings"
        )


def validate_repos(config):
    """Validate the ``build_profile`` of every repo in a config.

    Every repo entry MUST declare a valid ``build_profile``. Configs
    without a ``repos`` section (e.g. minimal test fixtures) pass
    unchanged.

    Args:
        config: The full parsed config dict.

    Returns:
        The same config dict, for chaining.

    Raises:
        ValueError: If any repo is missing ``build_profile`` or the
            profile fails validation.
    """
    if not isinstance(config, dict):
        return config
    repos = config.get("repos")
    if not isinstance(repos, dict):
        return config
    for repo_name, repo_cfg in repos.items():
        if (
            not isinstance(repo_cfg, dict)
            or "build_profile" not in repo_cfg
        ):
            raise ValueError(
                f"repo '{repo_name}': missing required "
                f"build_profile"
            )
        validate_build_profile(
            repo_cfg["build_profile"], repo_name
        )
    return config


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
