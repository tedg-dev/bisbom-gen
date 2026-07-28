"""
Phase 1 dependency-capture reader (Phase 2 consumption).

Phase 2 generates per-module Java ``_build`` SBOMs from the dependency
metadata Phase 1 captured (``maven_deps.json`` / ``gradle_deps.json``),
with **no access to the source tree**. This module loads that capture
and resolves the dependency subtree for a given output JAR.

The capture is the per-module structure produced by
``app.pipeline.maven_dep_tree_parser.parse_text_output`` (Maven) and
``app.pipeline.gradle_dep_tree_parser.get_all_gradle_deps`` (Gradle)::

    {"tool": "maven", "modules": [
        {"key": "g:a", "groupId": "g", "artifactId": "a",
         "version": "1.0", "packaging": "jar", "deps": [...]}, ...]}

JAR -> module resolution uses artifact metadata that travels with the
build output (no source tree required):

1. **Primary** — the JAR filename's artifactId (Maven) or the
   subproject name (Gradle) matches the capture module key.
2. **Backup** — the module/subproject directory encoded in the JAR's
   relative path (``<module>/target/...`` for Maven,
   ``<subproject>/build/libs/...`` for Gradle), used when a custom
   ``<finalName>`` / ``archivesName`` breaks the filename convention.
3. **Single-module fallback** — if the capture has exactly one module,
   it is used.
"""

import json
from pathlib import Path


_CAPTURE_FILES = {
    "maven_deps.json": "target",
    "gradle_deps.json": "build",
}


def load_capture(bom_dir):
    """Load the Phase 1 dependency capture from *bom_dir*.

    Looks for ``maven_deps.json`` first, then ``gradle_deps.json``.

    Args:
        bom_dir: Directory containing the Phase 1 capture files.

    Returns:
        The parsed capture dict (with ``tool`` and ``modules`` keys),
        or None if no capture file is present.
    """
    bom_path = Path(bom_dir)
    for filename in _CAPTURE_FILES:
        candidate = bom_path / filename
        if candidate.exists():
            with open(candidate, encoding="utf-8") as handle:
                return json.load(handle)
    return None


def _module_dir_from_jar(jar_rel_path, marker):
    """Return the module/subproject directory encoded in a JAR's
    relative path, or None for a root-level artifact.

    The directory immediately preceding *marker* (``target`` for
    Maven, ``build`` for Gradle) is the module directory.
    """
    if not jar_rel_path:
        return None
    parts = Path(jar_rel_path).parts
    for index, part in enumerate(parts):
        if part == marker:
            return parts[index - 1] if index > 0 else None
    return None


def _resolve_maven(modules, artifact_name, jar_rel_path):
    """Resolve a Maven output JAR to its capture module."""
    if artifact_name:
        for module in modules:
            if module.get("artifactId") == artifact_name:
                return module
    mod_dir = _module_dir_from_jar(jar_rel_path, "target")
    if mod_dir:
        for module in modules:
            if module.get("artifactId") == mod_dir:
                return module
    if len(modules) == 1:
        return modules[0]
    return None


def _resolve_gradle(modules, artifact_name, jar_rel_path):
    """Resolve a Gradle output JAR to its capture module."""
    if artifact_name:
        want = ":" + artifact_name
        for module in modules:
            if module.get("key") == want:
                return module
    mod_dir = _module_dir_from_jar(jar_rel_path, "build")
    if mod_dir:
        want = ":" + mod_dir
        for module in modules:
            if module.get("key") == want:
                return module
    else:
        for module in modules:
            if module.get("key") == ":":
                return module
    if len(modules) == 1:
        return modules[0]
    return None


def resolve_module(capture, artifact_name, jar_rel_path=None):
    """Resolve the capture module for an output JAR.

    Args:
        capture: The capture dict from :func:`load_capture`.
        artifact_name: The JAR's artifactId (version stripped), e.g.
            ``"dependency-check-cli"``.
        jar_rel_path: The JAR path relative to the repository root
            (e.g. ``"cli/target/dependency-check-cli-9.2.0.jar"``),
            used for the directory-based backup match.

    Returns:
        The matching module dict (with a ``deps`` list), or None if no
        module could be resolved.
    """
    if not capture:
        return None
    modules = capture.get("modules") or []
    if not modules:
        return None
    if capture.get("tool") == "gradle":
        return _resolve_gradle(modules, artifact_name, jar_rel_path)
    return _resolve_maven(modules, artifact_name, jar_rel_path)


def get_module_deps(capture, artifact_name, jar_rel_path=None):
    """Return the dependency list for an output JAR's module.

    Returns:
        The module's ``deps`` list (parse-tree dict shape), or None if
        the module could not be resolved from the capture.
    """
    module = resolve_module(capture, artifact_name, jar_rel_path)
    if module is None:
        return None
    return module.get("deps", [])
