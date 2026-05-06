"""
Maven ``dependency:tree`` DOT format parser.

Parses the output of ``mvn dependency:tree -DoutputType=dot``
into structured dependency metadata.

DOT output format::

    digraph "com.example:app:jar:1.0" {
        "com.example:app:jar:1.0" ->
            "org.apache:commons-lang3:jar:3.12.0:compile" ;
        "org.apache:commons-lang3:jar:3.12.0:compile" ->
            "org.apache:commons-text:jar:1.10.0:compile" ;
    }

Each node uses the Maven coordinate format:
``groupId:artifactId:packaging:version[:scope]``

The root node (project itself) has no scope suffix.
Dependency nodes have a scope suffix (compile, runtime,
provided, test, system, import).

Multi-module projects produce multiple ``digraph`` blocks,
one per module.
"""

import re
import subprocess
from pathlib import Path


# Maven dependency scopes that appear in production artifacts.
# Test-scope dependencies are excluded from production SPDX.
_PRODUCTION_SCOPES = frozenset({
    "compile", "runtime", "provided", "system",
})

# Regex for DOT edge lines:
#   "group:artifact:type:ver:scope" -> "group:artifact:type:ver:scope" ;
_EDGE_RE = re.compile(
    r'"([^"]+)"\s*->\s*"([^"]+)"\s*;'
)

# Regex for DOT digraph header:
#   digraph "group:artifact:type:ver" {
_DIGRAPH_RE = re.compile(
    r'digraph\s+"([^"]+)"\s*\{'
)


def parse_maven_coordinate(coord):
    """Parse a Maven coordinate string into a dict.

    Handles two formats:

    - ``groupId:artifactId:packaging:version`` (root node)
    - ``groupId:artifactId:packaging:version:scope`` (dep)

    Args:
        coord: Maven coordinate string.

    Returns:
        A dict with keys: ``groupId``, ``artifactId``,
        ``packaging``, ``version``, ``scope``.
        Returns None if the coordinate is malformed.
    """
    parts = coord.split(":")
    if len(parts) == 4:
        return {
            "groupId": parts[0],
            "artifactId": parts[1],
            "packaging": parts[2],
            "version": parts[3],
            "scope": "",
        }
    if len(parts) == 5:
        return {
            "groupId": parts[0],
            "artifactId": parts[1],
            "packaging": parts[2],
            "version": parts[3],
            "scope": parts[4],
        }
    return None


def parse_dot_output(dot_text):
    """Parse ``mvn dependency:tree -DoutputType=dot`` output.

    Extracts all dependency edges from the DOT graph and
    builds a list of dependency dicts. The root project node
    is identified as the digraph name and excluded from the
    dependency list.

    Handles multi-module projects (multiple digraph blocks).

    Args:
        dot_text: Raw stdout from ``mvn dependency:tree
            -DoutputType=dot``, possibly including Maven
            ``[INFO]`` log prefix lines.

    Returns:
        A list of dicts, each with keys:

        - ``groupId``, ``artifactId``, ``version``, ``scope``
        - ``packaging`` (jar, pom, war, etc.)
        - ``direct`` (bool) — True if the parent is the
          project root
        - ``parent`` — the parent artifactId, or None for
          direct deps
        - ``is_test`` (bool) — True if scope is ``test``
        - ``module`` — the module coordinate that owns this
          dependency (for multi-module projects)
    """
    # Strip Maven [INFO] prefixes if present
    lines = []
    for raw_line in dot_text.splitlines():
        line = raw_line.strip()
        if line.startswith("[INFO] "):
            line = line[7:]
        lines.append(line)
    clean_text = "\n".join(lines)

    # Collect root nodes per digraph block
    roots = set()
    for match in _DIGRAPH_RE.finditer(clean_text):
        roots.add(match.group(1))

    # Parse all edges
    seen = set()
    deps = []
    for match in _EDGE_RE.finditer(clean_text):
        parent_coord = match.group(1)
        child_coord = match.group(2)

        child = parse_maven_coordinate(child_coord)
        if child is None:
            continue

        parent = parse_maven_coordinate(parent_coord)
        if parent is None:
            continue

        # Deduplicate by (groupId, artifactId) — Maven
        # resolves one version per artifact, so the first
        # occurrence (nearest/managed) wins.
        dep_key = (
            child["groupId"],
            child["artifactId"],
        )
        if dep_key in seen:
            continue
        seen.add(dep_key)

        # Direct dependency = parent is a root node
        is_direct = parent_coord in roots

        scope = child.get("scope", "compile") or "compile"

        deps.append({
            "groupId": child["groupId"],
            "artifactId": child["artifactId"],
            "version": child["version"],
            "scope": scope,
            "packaging": child.get("packaging", "jar"),
            "direct": is_direct,
            "parent": (
                None if is_direct
                else parent["artifactId"]
            ),
            "is_test": scope == "test",
            "module": parent_coord if is_direct else None,
        })

    return deps


def filter_production_deps(deps):
    """Filter dependency list to production-only scopes.

    Removes test-scope dependencies from the list.

    Args:
        deps: List of dependency dicts from
            ``parse_dot_output()``.

    Returns:
        A new list containing only dependencies with
        production scopes (compile, runtime, provided,
        system).
    """
    return [
        d for d in deps
        if d.get("scope", "compile") in _PRODUCTION_SCOPES
    ]


def classify_scopes(deps):
    """Classify dependencies by scope.

    Args:
        deps: List of dependency dicts.

    Returns:
        A dict mapping scope names to lists of deps.
    """
    result = {}
    for dep in deps:
        scope = dep.get("scope", "compile")
        result.setdefault(scope, []).append(dep)
    return result


def run_maven_dep_tree(repo_dir, runner=None):
    """Run ``mvn dependency:tree -DoutputType=dot``.

    Args:
        repo_dir: Path to the repository root (must
            contain ``pom.xml``).
        runner: Optional ``CommandRunner`` for logging.
            If None, uses subprocess directly.

    Returns:
        The raw stdout string, or None on failure.
    """
    repo_path = Path(repo_dir)
    pom_path = repo_path / "pom.xml"
    if not pom_path.exists():
        print(
            f"[WARN] No pom.xml found in {repo_dir}"
        )
        return None

    try:
        result = subprocess.run(
            [
                "mvn", "dependency:tree",
                "-DoutputType=dot",
            ],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(
                "[WARN] mvn dependency:tree failed: "
                f"{result.stderr[:200]}"
            )
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        print(
            "[WARN] mvn dependency:tree timed out "
            "(120s)"
        )
        return None
    except FileNotFoundError:
        print("[WARN] mvn not found on PATH")
        return None
