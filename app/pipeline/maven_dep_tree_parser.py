r"""
Maven ``dependency:tree`` text format parser (per-module).

Parses the **default text** output of ``mvn dependency:tree`` into
per-module dependency subtrees for Phase 1 capture.

The default text format is used (not DOT, not JSON) because it is the
only universally-available output that carries the ``optional`` flag:

- **DOT** edges are labeled with scope only
  (``groupId:artifactId:type:version:scope``) — no ``optional``.
- **JSON** carries ``optional`` but requires
  ``maven-dependency-plugin >= 3.7.0``, a toolchain version that is not
  under our control (Phase 1 runs on the customer's build machine).
- **text** (the default) has emitted the ``:scope`` coordinate plus an
  ``(optional)`` suffix consistently across the plugin's 2.x/3.x life,
  so it imposes no version requirement.

Text output format (one tree per reactor module)::

    [INFO] com.example:app:jar:1.0
    [INFO] +- org.apache:commons-lang3:jar:3.12.0:compile
    [INFO] |  \- org.apache:commons-text:jar:1.10.0:compile
    [INFO] \- org.projectlombok:lombok:jar:1.18.0:provided (optional)

Each module begins with its root coordinate line
(``groupId:artifactId:packaging:version`` — no tree-branch prefix and
no scope suffix). A component shared by two modules appears under
**both** (no cross-module de-duplication).
"""

import re
import subprocess
from pathlib import Path

from app.spdx.maven_parser import parse_dep_tree


# Maven dependency scopes that appear in production artifacts.
# Test-scope dependencies are excluded from production SPDX.
_PRODUCTION_SCOPES = frozenset({
    "compile", "runtime", "provided", "system",
})

# A dependency tree branch line, e.g. ``+- g:a:...`` or ``|  \- g:a:...``
# or (when the parent is the last child) ``   +- g:a:...``.
_TREE_LINE_RE = re.compile(r"^[ |]*[+\\]- ")


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


def _strip_info_prefix(raw_line):
    """Remove a leading Maven ``[INFO]`` marker, preserving the tree
    indentation that follows it.

    The indentation after ``[INFO] `` encodes dependency depth and
    must not be stripped. Lines without an ``[INFO]`` marker (e.g.
    raw fixture input) are returned unchanged.
    """
    stripped = raw_line.lstrip()
    if stripped.startswith("[INFO]"):
        rest = stripped[len("[INFO]"):]
        if rest.startswith(" "):
            rest = rest[1:]
        return rest
    return raw_line


def _parse_root_line(line):
    """Return a module dict if *line* is a reactor module root
    coordinate, else None.

    A root line is a bare Maven coordinate
    (``groupId:artifactId:packaging:version``) with no tree-branch
    prefix and no scope suffix.
    """
    if not line or line[0] in "+\\| ":
        return None
    parts = line.split(":")
    if len(parts) != 4:
        return None
    if any((not p) or (" " in p) for p in parts):
        return None
    coord = parse_maven_coordinate(line)
    if coord is None:
        return None
    return {
        "key": f"{coord['groupId']}:{coord['artifactId']}",
        "groupId": coord["groupId"],
        "artifactId": coord["artifactId"],
        "version": coord["version"],
        "packaging": coord["packaging"],
        "deps": [],
    }


def parse_text_output(dep_tree_text):
    """Parse default ``mvn dependency:tree`` (text) reactor output
    into per-module dependency subtrees.

    Dependencies are de-duplicated WITHIN a module only (Maven prints
    each resolved artifact once per module); there is no
    de-duplication ACROSS modules, so a component shared by two
    modules appears under both — which is exactly what per-module
    ``_build`` SBOMs require.

    Args:
        dep_tree_text: Raw stdout from ``mvn dependency:tree``
            (default text output), possibly including Maven
            ``[INFO]`` log prefix lines.

    Returns:
        A list of module dicts, each with keys:

        - ``key`` — ``"groupId:artifactId"`` module coordinate
        - ``groupId``, ``artifactId``, ``version``, ``packaging``
        - ``deps`` — list of dependency dicts in the shape produced
          by ``app.spdx.maven_parser.parse_dep_tree`` (``groupId``,
          ``artifactId``, ``version``, ``scope``, ``direct``,
          ``optional``, ``parent``, ``depth``).
    """
    modules = []
    state = {"current": None, "block": []}

    def _flush():
        current = state["current"]
        if current is not None:
            current["deps"] = parse_dep_tree(
                "\n".join(state["block"])
            )
            modules.append(current)

    for raw_line in dep_tree_text.splitlines():
        content = _strip_info_prefix(raw_line)

        root = _parse_root_line(content)
        if root is not None:
            _flush()
            state["current"] = root
            state["block"] = []
            continue

        if (
            state["current"] is not None
            and _TREE_LINE_RE.match(content)
        ):
            state["block"].append("[INFO] " + content)

    _flush()
    return modules


def filter_production_deps(deps):
    """Filter dependency list to production-only scopes.

    Removes test-scope dependencies from the list.

    Args:
        deps: List of dependency dicts (e.g. a module's
            ``deps`` list from ``parse_text_output()``).

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


def run_maven_dep_tree(
    repo_dir, runner=None, maven_modules=None,
):
    """Run ``mvn dependency:tree -DoutputType=dot``.

    Attempts offline mode (``-o``) first: when the local
    ``.m2/repository`` cache is warm, this avoids redundant
    remote metadata checks.  If the offline run fails — for
    example because a required plugin (the
    ``maven-dependency-plugin`` itself) was not cached by
    the preceding build — it falls back to an online run.
    The build step runs online, so the network is
    available and the online ``dependency:tree`` is the
    authoritative dependency graph.  Skip flags prevent
    lifecycle plugins from firing unnecessarily.

    Args:
        repo_dir: Path to the repository root (must
            contain ``pom.xml``).
        runner: Optional ``CommandRunner`` for logging.
            If None, uses subprocess directly.
        maven_modules: Optional ``-pl`` value for
            multi-module projects (e.g. ``"crawler4j"``).
            When set, dep:tree targets only the specified
            module(s) instead of the entire reactor.

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

    # Use the DEFAULT text output (no -DoutputType): it is the only
    # universally-available format that carries the ``optional`` flag
    # and imposes no maven-dependency-plugin version requirement on
    # the customer's build toolchain (DOT lacks optional; JSON needs
    # plugin >= 3.7.0).
    base_cmd = [
        "mvn", "dependency:tree",
        "-DskipTests",
        "-Dmaven.javadoc.skip=true",
        "-Denforcer.skip=true",
        "-Dcheckstyle.skip=true",
    ]
    if maven_modules:
        base_cmd.extend(["-pl", maven_modules, "-am"])

    # runner is accepted for interface consistency
    # with other pipeline functions but not yet used
    # for dep:tree (subprocess.run is sufficient).
    _ = runner

    # Offline-first, then online fallback.  Each attempt is
    # the same command; the offline attempt inserts ``-o``.
    last_output = ""
    for offline in (True, False):
        cmd = list(base_cmd)
        if offline:
            cmd.insert(2, "-o")
        # cmd index 2 is the first option after
        # ``mvn dependency:tree``; -o is inserted there.
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(
                "[WARN] mvn dependency:tree timed out "
                "(120s)"
            )
            return None
        except FileNotFoundError:
            print("[WARN] mvn not found on PATH")
            return None

        if result.returncode == 0:
            if not offline:
                print(
                    "[INFO] mvn dependency:tree "
                    "succeeded online (offline .m2 "
                    "cache incomplete)"
                )
            return result.stdout

        # Maven writes resolution errors to stdout, not
        # stderr — capture both so failures are visible.
        last_output = (
            (result.stdout or "")
            + (result.stderr or "")
        )
        if offline:
            print(
                "[WARN] offline mvn dependency:tree "
                "failed; retrying online"
            )

    print(
        "[ERROR] mvn dependency:tree failed:\n"
        f"{last_output[-500:]}"
    )
    return None
