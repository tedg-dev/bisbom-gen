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

import os
import re
import subprocess
import tempfile
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


# Init script that registers a single-configuration dependency report
# task (``omniborDeps``) on every project exposing a ``runtimeClasspath``
# configuration. One Gradle invocation with this init script emits every
# module's runtime dependency tree, replacing one ``gradlew`` process per
# subproject. Registration is deferred to ``afterEvaluate`` because the
# Java plugin (which creates ``runtimeClasspath``) is applied during
# project evaluation, after the init script's ``allprojects`` closure runs.
_OMNIBOR_INIT_SCRIPT = """\
import org.gradle.api.tasks.diagnostics.DependencyReportTask

allprojects { p ->
    p.afterEvaluate {
        if (p.configurations.findByName('runtimeClasspath') != null) {
            p.tasks.register('omniborDeps', DependencyReportTask) { t ->
                t.configuration = 'runtimeClasspath'
            }
        }
    }
}
"""

# Dependency-report section header: a line of dashes, then
# ``Root project 'name'`` or ``Project ':path'`` (optionally followed by
# a ``- description`` suffix), then another line of dashes.
_SECTION_HEADER = re.compile(
    r"-{10,}\s*\n(Root project|Project)\s+'([^']*)'[^\n]*\n-{10,}",
)


def run_gradle_all_dep_trees(repo_dir, runner=None):
    """Run one ``gradlew`` invocation reporting every module's
    ``runtimeClasspath`` dependency tree via an injected init script.

    Runs offline (the Gradle cache is complete after the build) and with
    ``--continue`` so one failing module does not abort the rest. ``-q``
    is intentionally omitted: on some Gradle versions the custom report
    task renders below the quiet log level.

    Args:
        repo_dir: Path to the repository root.
        runner: Unused; kept for API consistency.

    Returns:
        Raw stdout string, or None if ``gradlew`` is missing or the
        invocation produced no output.
    """
    repo_path = Path(repo_dir)
    gradlew = repo_path / "gradlew"
    if not gradlew.exists():
        print(f"[WARN] No gradlew found in {repo_dir}")
        return None

    init_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gradle", delete=False, encoding="utf-8",
        ) as handle:
            handle.write(_OMNIBOR_INIT_SCRIPT)
            init_file = handle.name
        result = subprocess.run(
            [
                str(gradlew), "omniborDeps",
                "--init-script", init_file,
                "--offline", "--continue",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        return result.stdout or None
    except subprocess.TimeoutExpired:
        print("[WARN] Gradle omniborDeps timed out (600s)")
        return None
    except FileNotFoundError:
        print("[WARN] gradlew not found on PATH")
        return None
    finally:
        if init_file:
            try:
                os.unlink(init_file)
            except OSError:
                pass


def _split_dep_report_sections(output):
    """Split an aggregated multi-project dependency report into a
    mapping of ``{project_key: section_text}``.

    ``Root project`` maps to the ``":"`` key; ``Project ':path'`` maps to
    the normalized project path.
    """
    sections = {}
    matches = list(_SECTION_HEADER.finditer(output))
    for index, match in enumerate(matches):
        kind, name = match.group(1), match.group(2)
        if kind == "Root project":
            key = ":"
        else:
            key = _normalize_project_key(name)
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(output)
        )
        sections[key] = output[start:end]
    return sections


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
    # Primary: one invocation reports every module via the init script.
    output = run_gradle_all_dep_trees(repo_dir)
    sections = _split_dep_report_sections(output) if output else {}
    if sections:
        modules = []
        for key, section_text in sections.items():
            project = None if key == ":" else key.lstrip(":")
            modules.append({
                "key": key,
                "project": project,
                "deps": parse_gradle_dep_tree(section_text),
            })
        return modules

    # Fallback: one invocation per subproject, for builds where the
    # aggregated init-script report yielded no parseable sections.
    return _get_all_gradle_deps_per_subproject(
        repo_dir, include_subprojects,
    )


def _get_all_gradle_deps_per_subproject(
    repo_dir: str,
    include_subprojects: bool = True,
) -> List[dict]:
    """Per-subproject capture fallback (one ``gradlew`` per project).

    Used only when the single-invocation init-script report produces no
    sections. Returns the same module structure as
    :func:`get_all_gradle_deps`.
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
