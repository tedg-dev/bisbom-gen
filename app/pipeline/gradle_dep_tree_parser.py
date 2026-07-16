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

import json
import os
import re
import subprocess
import tempfile
import time
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


# Init script that uses Gradle's ResolutionResult API to extract
# dependency graphs as JSON. This is faster than DependencyReportTask
# because it skips ASCII tree formatting and outputs structured data
# directly. Industry best practice per Gradle documentation.
_OMNIBOR_INIT_SCRIPT_JSON = """\
import groovy.json.JsonOutput
import org.gradle.api.artifacts.result.ResolvedDependencyResult

allprojects { p ->
    p.afterEvaluate {
        def config = p.configurations.findByName('runtimeClasspath')
        if (config != null) {
            p.tasks.register('omniborDepsJson') {
                def configName = 'runtimeClasspath'
                doLast {
                    def cfg = p.configurations.getByName(configName)
                    def result = cfg.incoming.resolutionResult
                    def root = result.root

                    def collectDeps
                    collectDeps = { component, depth, parent ->
                        def deps = []
                        component.dependencies.each { dep ->
                            if (dep instanceof ResolvedDependencyResult) {
                                def selected = dep.selected
                                def modVer = selected.moduleVersion
                                if (modVer != null) {
                                    def depMap = [
                                        groupId: modVer.group ?: '',
                                        artifactId: modVer.name ?: '',
                                        version: modVer.version ?: '',
                                        scope: 'runtime',
                                        depth: depth,
                                        direct: (depth == 1),
                                        parent: parent
                                    ]
                                    deps << depMap
                                    def parentId = modVer.group + ':' + modVer.name
                                    deps.addAll(collectDeps(selected, depth + 1, parentId))
                                }
                            }
                        }
                        return deps
                    }

                    def allDeps = collectDeps(root, 1, null)

                    def output = [
                        key: p.path,
                        project: (p.path == ':' ? null : p.path.substring(1)),
                        deps: allDeps
                    ]

                    println '===OMNIBOR_JSON_START==='
                    println JsonOutput.toJson(output)
                    println '===OMNIBOR_JSON_END==='
                }
            }
        }
    }
}
"""

# Legacy text-based init script (fallback)
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
    t0 = time.monotonic()
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
            timeout=900,
            check=False,
        )
        elapsed = time.monotonic() - t0
        if result.returncode != 0:
            print(
                f"[WARN] Gradle omniborDeps failed after {elapsed:.1f}s "
                f"(returncode={result.returncode}): {result.stderr[:300]}"
            )
            return None
        if not result.stdout:
            print(
                f"[WARN] Gradle omniborDeps produced no output after {elapsed:.1f}s"
            )
            return None
        print(
            f"[OK] Gradle omniborDeps single-invocation succeeded in {elapsed:.1f}s"
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        print(f"[WARN] Gradle omniborDeps timed out after {elapsed:.1f}s")
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


def run_gradle_all_dep_trees_json(repo_dir, runner=None):
    """Run gradlew with JSON ResolutionResult API init script.

    Faster than text-based DependencyReportTask because it skips
    ASCII tree formatting. Uses Gradle's ResolutionResult API
    (industry best practice per Gradle documentation).

    Includes --parallel and --configuration-cache flags for
    maximum performance.

    Args:
        repo_dir: Path to repository root.
        runner: Unused; kept for API consistency.

    Returns:
        Raw stdout string, or None on failure.
    """
    repo_path = Path(repo_dir)
    gradlew = repo_path / "gradlew"
    if not gradlew.exists():
        print(f"[WARN] No gradlew found in {repo_dir}")
        return None

    init_file = None
    t0 = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".gradle", delete=False, encoding="utf-8",
        ) as handle:
            handle.write(_OMNIBOR_INIT_SCRIPT_JSON)
            init_file = handle.name
        result = subprocess.run(
            [
                str(gradlew), "omniborDepsJson",
                "--init-script", init_file,
                "--offline", "--continue",
                "--parallel", "--max-workers=4",
                "--configuration-cache",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        elapsed = time.monotonic() - t0
        if result.returncode != 0:
            print(
                f"[WARN] Gradle omniborDepsJson failed after {elapsed:.1f}s "
                f"(returncode={result.returncode}): {result.stderr[:300]}"
            )
            return None
        if not result.stdout:
            print(
                f"[WARN] Gradle omniborDepsJson produced no output after {elapsed:.1f}s"
            )
            return None
        print(
            f"[OK] Gradle omniborDepsJson (JSON API + parallel + cache) "
            f"succeeded in {elapsed:.1f}s"
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        print(f"[WARN] Gradle omniborDepsJson timed out after {elapsed:.1f}s")
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


def _parse_json_dep_output(output):
    """Parse JSON dependency output from omniborDepsJson task.

    Extracts JSON blocks delimited by ===OMNIBOR_JSON_START=== markers
    and converts to the same structure as text parser output.

    Args:
        output: Raw stdout from gradlew omniborDepsJson.

    Returns:
        Dict mapping project keys to module dicts with deps list.
    """
    modules = {}
    lines = output.split('\n')
    i = 0
    while i < len(lines):
        if lines[i].strip() == '===OMNIBOR_JSON_START===':
            j = i + 1
            while j < len(lines) and lines[j].strip() != '===OMNIBOR_JSON_END===':
                j += 1
            if j < len(lines):
                json_text = '\n'.join(lines[i+1:j])
                try:
                    module_data = json.loads(json_text)
                    modules[module_data['key']] = module_data
                except json.JSONDecodeError as e:
                    print(f"[WARN] Failed to parse JSON for project: {e}")
            i = j + 1
        else:
            i += 1

    return modules


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
    # Primary: JSON API (fastest - no text formatting overhead)
    output = run_gradle_all_dep_trees_json(repo_dir)
    if output:
        modules_dict = _parse_json_dep_output(output)
        if modules_dict:
            modules = []
            for key, module_data in modules_dict.items():
                modules.append({
                    "key": key,
                    "project": module_data.get("project"),
                    "deps": module_data.get("deps", []),
                })
            print(
                f"[OK] Gradle JSON API: parsed {len(modules)} modules"
            )
            return modules
        print(
            "[WARN] Gradle JSON API produced no parseable modules; "
            "falling back to text API"
        )

    # Fallback 1: Text-based single invocation
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
        print(
            f"[OK] Gradle text API (fallback): parsed {len(modules)} modules"
        )
        return modules

    # Fallback 2: Per-subproject invocations
    print(
        "[WARN] Both JSON and text APIs failed; "
        "falling back to per-subproject invocations"
    )
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
