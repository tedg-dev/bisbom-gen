"""
Gradle dependency tree parser for pipeline use.

Wraps ``app.spdx.gradle_parser`` with multi-project
support and output format compatible with the Maven
DOT parser (``maven_dep_tree_parser.py``).

Gradle tree format::

    +--- group:artifact:version
    |    +--- group:artifact:version
    |    \\--- group:artifact:declared -> resolved (*)

Version conflict notation: ``declared -> resolved``
indicates Gradle resolved to a different version.
``(*)`` means the subtree was already listed.
"""

import subprocess
from pathlib import Path
from typing import List

from app.spdx.gradle_parser import (
    parse_gradle_dep_tree,
)


def _normalize_project_key(project):
    """Return a Gradle project path key (``:name`` form).

    ``settings.gradle`` ``include`` directives may use either
    ``'core'`` or ``':core'``; both map to the project path ``:core``,
    which also matches the subproject directory name used in the JAR
    output path (``core/build/libs/...``).
    """
    return project if project.startswith(":") else ":" + project


def run_gradle_dep_tree(
    repo_dir, project=None, runner=None,
):
    """Run ``./gradlew dependencies`` for a project.

    Runs in offline mode (``--offline``) because this is
    called after a successful build — the Gradle cache is
    guaranteed complete.  Omits ``--no-daemon`` so the build
    daemon (if still warm from the build) can serve the
    query without a cold JVM start.

    Args:
        repo_dir: Path to the repository root.
        project: Optional Gradle subproject name.
        runner: Optional ``CommandRunner`` (unused,
            kept for API consistency).

    Returns:
        Raw stdout string, or None on failure.
    """
    repo_path = Path(repo_dir)
    gradlew = repo_path / "gradlew"
    if not gradlew.exists():
        print(
            f"[WARN] No gradlew found in {repo_dir}"
        )
        return None

    task = "dependencies"
    if project:
        task = f"{project}:dependencies"

    try:
        result = subprocess.run(
            [
                str(gradlew), task,
                "--configuration", "runtimeClasspath",
                "--offline", "-q",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            print(
                "[WARN] Gradle dependencies failed: "
                f"{result.stderr[:200]}"
            )
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        print(
            "[WARN] Gradle dependencies timed out "
            "(120s)"
        )
        return None
    except FileNotFoundError:
        print("[WARN] gradlew not found on PATH")
        return None


def find_gradle_subprojects(repo_dir):
    """Discover Gradle subprojects from settings.gradle.

    Parses ``settings.gradle`` or ``settings.gradle.kts``
    for ``include`` directives.

    Args:
        repo_dir: Path to the repository root.

    Returns:
        List of subproject names (e.g. ``[":core", ":web"]``).
    """
    repo_path = Path(repo_dir)
    for name in (
        "settings.gradle", "settings.gradle.kts",
    ):
        settings = repo_path / name
        if settings.exists():
            return _parse_settings(settings)
    return []


def _parse_settings(settings_path):
    """Extract ``include`` directives from settings file."""
    projects = []
    try:
        content = settings_path.read_text(
            encoding="utf-8",
        )
    except OSError:
        return projects

    import re
    # Match: include 'project1', 'project2'
    # Match: include("project1", "project2")
    for match in re.finditer(
        r"""include\s*\(?\s*['"]([^'"]+)['"]""",
        content,
    ):
        projects.append(match.group(1))

    # Also match comma-separated in same include
    for match in re.finditer(
        r""",\s*['"]([^'"]+)['"]""",
        content,
    ):
        val = match.group(1)
        if val.startswith(":"):
            projects.append(val)

    return projects


def get_all_gradle_deps(
    repo_dir: str,
    include_subprojects: bool = True,
) -> List[dict]:
    """Get per-subproject dependency subtrees for Phase 1 capture.

    Each Gradle subproject (and the root project) is captured as its
    own subtree so that Phase 2 can generate a per-subproject
    ``_build`` SBOM from this metadata alone. There is **no**
    de-duplication across subprojects — a component used by two
    subprojects appears under both.

    Args:
        repo_dir: Path to the repository root.
        include_subprojects: If True, iterate over subprojects
            discovered from ``settings.gradle``.

    Returns:
        A list of module dicts, each with keys:

        - ``key`` — Gradle project path (``":"`` for the root,
          ``":<name>"`` for a subproject)
        - ``project`` — the ``settings.gradle`` include name, or
          None for the root project
        - ``deps`` — list of dependency dicts in the shape produced
          by ``app.spdx.gradle_parser.parse_gradle_dep_tree``
          (``groupId``, ``artifactId``, ``version``, ``scope``,
          ``direct``, ``optional``, ``parent``, ``depth``).
    """
    modules = []

    # Root project
    output = run_gradle_dep_tree(repo_dir)
    if output is not None:
        modules.append({
            "key": ":",
            "project": None,
            "deps": parse_gradle_dep_tree(output),
        })

    # Subprojects
    if include_subprojects:
        for proj in find_gradle_subprojects(repo_dir):
            output = run_gradle_dep_tree(
                repo_dir, project=proj,
            )
            if output is not None:
                modules.append({
                    "key": _normalize_project_key(proj),
                    "project": proj,
                    "deps": parse_gradle_dep_tree(output),
                })

    return modules
