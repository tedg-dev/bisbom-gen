"""
Gradle dependency parser.

Parses Gradle dependency trees and build.gradle/gradle.properties
files to extract dependency metadata for Java SPDX generation.
Produces output compatible with maven_parser.py so JavaSpdxGenerator
can consume either Maven or Gradle dependency data transparently.
"""

import re
import subprocess
from pathlib import Path


def get_gradle_deps(repo_dir, project=None):
    """Get Gradle dependencies via ./gradlew dependencies.

    Queries the runtimeClasspath configuration which includes
    implementation and runtimeOnly dependencies — the set of
    libraries that ship with the production artifact.

    Args:
        repo_dir: path to the repository root (must contain
            gradlew or build.gradle).
        project: optional Gradle subproject name. If provided,
            runs ``<project>:dependencies`` instead of
            ``:dependencies``.

    Returns list of dicts with groupId, artifactId,
    version, scope, direct, optional, parent.
    Compatible with maven_parser.get_maven_deps() output.
    """
    repo_path = Path(repo_dir)
    gradlew = repo_path / "gradlew"
    if not gradlew.exists():
        return []

    task = "dependencies"
    if project:
        task = f"{project}:dependencies"

    try:
        result = subprocess.run(
            [
                str(gradlew), task,
                "--configuration", "runtimeClasspath",
                "--no-daemon", "-q",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"[WARN] Gradle dependencies failed: "
                f"{result.stderr[:200]}"
            )
            return _parse_build_gradle(repo_path)

        return parse_gradle_dep_tree(result.stdout)
    except subprocess.TimeoutExpired:
        print("[WARN] Gradle dependencies timed out")
        return _parse_build_gradle(repo_path)
    except FileNotFoundError:
        print("[WARN] gradlew not found")
        return []


def parse_gradle_dep_tree(output):
    """Parse ./gradlew dependencies output.

    Gradle tree format (runtimeClasspath configuration):
        +--- group:artifact:version
        |    +--- group:artifact:version
        |    \\--- group:artifact:version -> resolved (*)

    Version conflict notation: ``declared -> resolved``
    indicates Gradle resolved to a different version.
    ``(*)`` means the subtree was already listed.
    ``(c)`` means a dependency constraint.
    ``(n)`` means not resolved (configuration not requested).

    Returns list of dicts compatible with
    maven_parser.parse_dep_tree() output.
    """
    deps = []
    parent_stack = [None]
    seen_config = False

    for line in output.split("\n"):
        # Skip until we hit the runtimeClasspath section
        if "runtimeClasspath" in line and "---" not in line:
            seen_config = True
            continue
        if not seen_config:
            continue

        # Stop at blank line or next configuration header
        stripped = line.rstrip()
        if not stripped:
            if seen_config and deps:
                break
            continue
        # Next configuration section starts without tree chars
        if stripped and stripped[0] not in ("+", "\\", "|", " "):
            if deps:
                break
            continue

        # Match dependency lines: find +--- or \--- marker
        marker_match = re.search(r"[+\\]---\s+", line)
        if not marker_match:
            continue

        marker_pos = marker_match.start()
        remainder = line[marker_match.end():]

        # Skip non-dependency lines
        if remainder.startswith("project "):
            continue

        # Parse group:artifact:version with optional -> resolved
        dep_match = re.match(
            r"([^:]+):([^:]+):([^\s]+)"
            r"(?:\s+->\s+(\S+))?"
            r"(?:\s+\([\w*]+\))*",
            remainder,
        )
        if not dep_match:
            continue

        group_id = dep_match.group(1)
        artifact_id = dep_match.group(2)
        declared_version = dep_match.group(3)
        resolved_version = dep_match.group(4)

        version = resolved_version or declared_version

        # Calculate depth from marker position
        # depth 0: marker at column 0
        # depth 1: marker at column 5
        # depth N: marker at column N*5
        depth = marker_pos // 5

        direct = (depth == 0)

        # Get parent artifact from stack
        parent = None
        if depth > 0 and len(parent_stack) > depth:
            parent = parent_stack[depth]

        # Update parent stack
        while len(parent_stack) <= depth + 1:
            parent_stack.append(None)
        parent_stack[depth + 1] = artifact_id

        # Gradle runtimeClasspath ≈ Maven compile scope
        deps.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "scope": "compile",
            "direct": direct,
            "optional": False,
            "parent": parent,
            "depth": depth,
        })

    return deps


def _parse_build_gradle(repo_path):
    """Fallback: extract dependencies from build.gradle.

    Only captures directly declared dependencies (no transitives).
    Similar to maven_parser.parse_pom() as a fallback.
    """
    deps = []
    build_file = repo_path / "build.gradle"
    if not build_file.exists():
        build_file = repo_path / "build.gradle.kts"
    if not build_file.exists():
        return deps

    try:
        content = build_file.read_text()
    except OSError:
        return deps

    # Map Gradle configurations to Maven-equivalent scopes
    config_to_scope = {
        "implementation": "compile",
        "api": "compile",
        "runtimeOnly": "runtime",
        "compileOnly": "provided",
        "testImplementation": "test",
        "testRuntimeOnly": "test",
        "testCompileOnly": "test",
    }

    # Match Groovy DSL: configuration 'group:artifact:version'
    # Match Kotlin DSL: configuration("group:artifact:version")
    pattern = re.compile(
        r"(\w+)\s*\(?\s*['\"]"
        r"([^:'\"]+):([^:'\"]+):([^'\"]+)"
        r"['\"]"
    )

    for match in pattern.finditer(content):
        config = match.group(1)
        if config not in config_to_scope:
            continue
        deps.append({
            "groupId": match.group(2),
            "artifactId": match.group(3),
            "version": match.group(4),
            "scope": config_to_scope[config],
            "direct": True,
            "optional": False,
            "parent": None,
            "depth": 0,
        })

    return deps


def get_gradle_version(repo_dir):
    """Try to get project version from Gradle files.

    Checks (in order):
    1. gradle.properties for ``version=x.y.z``
    2. build.gradle for ``version = 'x.y.z'``
    """
    repo_path = Path(repo_dir)

    # Check gradle.properties first
    props_file = repo_path / "gradle.properties"
    if props_file.exists():
        try:
            for line in props_file.read_text().split("\n"):
                match = re.match(
                    r"^\s*version\s*=\s*(.+)", line
                )
                if match:
                    ver = match.group(1).strip().strip("'\"")
                    if ver.endswith("-SNAPSHOT"):
                        ver = ver[: -len("-SNAPSHOT")]
                    return ver
        except OSError:
            pass

    # Check build.gradle
    for name in ("build.gradle", "build.gradle.kts"):
        build_file = repo_path / name
        if build_file.exists():
            try:
                content = build_file.read_text()
                match = re.search(
                    r"""version\s*=\s*['"]([^'"]+)['"]""",
                    content,
                )
                if match:
                    ver = match.group(1)
                    if ver.endswith("-SNAPSHOT"):
                        ver = ver[: -len("-SNAPSHOT")]
                    return ver
            except OSError:
                pass

    return "unknown"


def get_gradle_group(repo_dir):
    """Get the project's group from Gradle files.

    Checks (in order):
    1. gradle.properties for ``group=com.example``
    2. build.gradle for ``group = 'com.example'``

    Used to detect sibling modules (same group = same project).
    """
    repo_path = Path(repo_dir)

    # Check gradle.properties first
    props_file = repo_path / "gradle.properties"
    if props_file.exists():
        try:
            for line in props_file.read_text().split("\n"):
                match = re.match(
                    r"^\s*group\s*=\s*(.+)", line
                )
                if match:
                    return match.group(1).strip().strip("'\"")
        except OSError:
            pass

    # Check build.gradle
    for name in ("build.gradle", "build.gradle.kts"):
        build_file = repo_path / name
        if build_file.exists():
            try:
                content = build_file.read_text()
                match = re.search(
                    r"""group\s*=\s*['"]([^'"]+)['"]""",
                    content,
                )
                if match:
                    return match.group(1)
            except OSError:
                pass

    return None


def is_gradle_project(repo_dir):
    """Check if repo_dir is a Gradle project.

    Returns True if the directory contains gradlew or
    build.gradle / build.gradle.kts.
    """
    repo_path = Path(repo_dir)
    return (
        (repo_path / "gradlew").exists()
        or (repo_path / "build.gradle").exists()
        or (repo_path / "build.gradle.kts").exists()
    )
