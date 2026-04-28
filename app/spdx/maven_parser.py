"""
Maven dependency and POM parser.

Parses Maven dependency trees and pom.xml files to extract
dependency metadata for Java SPDX generation. Resolves
Maven property references and classifies dependency scope.
"""

import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def get_maven_deps(repo_dir, pom_dir=None):
    """Get Maven dependencies via mvn dependency:tree.

    Args:
        repo_dir: path to the repository root
        pom_dir: directory containing pom.xml.
            If None, uses repo_dir.

    Returns list of dicts with groupId, artifactId,
    version, scope, direct, optional, parent_artifact.
    """
    mvn_dir = Path(pom_dir) if pom_dir else Path(repo_dir)
    pom_path = mvn_dir / "pom.xml"
    if not pom_path.exists():
        return []

    try:
        result = subprocess.run(
            [
                "mvn", "dependency:tree",
                "-DoutputType=text",
            ],
            cwd=str(mvn_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(
                f"[WARN] mvn dependency:tree failed: "
                f"{result.stderr[:200]}"
            )
            # Fall back to pom.xml parsing
            return parse_pom(pom_path)

        return parse_dep_tree(result.stdout)
    except subprocess.TimeoutExpired:
        print("[WARN] mvn dependency:tree timed out")
        return parse_pom(pom_path)
    except FileNotFoundError:
        print("[WARN] mvn not found, using pom.xml")
        return parse_pom(pom_path)


def parse_dep_tree(output):
    """Parse mvn dependency:tree output.

    Format: [INFO] +- group:artifact:type:version:scope
    or:     [INFO] |  \\- group:artifact:type:version:scope
    """
    deps = []
    parent_stack = [None]  # Track parent at each depth

    for line in output.split("\n"):
        if not line.startswith("[INFO] "):
            continue
        line = line[7:]  # Strip [INFO]

        # Match dependency lines
        match = re.match(
            r"^([+|\\| -]+)"
            r"([^:]+):([^:]+):([^:]+):([^:]+):(\S+)"
            r"(\s+\(optional\))?",
            line
        )
        if not match:
            continue

        prefix = match.group(1)
        group_id = match.group(2)
        artifact_id = match.group(3)
        # type = match.group(4)  # jar, pom, etc.
        version = match.group(5)
        scope = match.group(6)
        optional = bool(match.group(7))

        # Calculate depth from prefix
        # +- or \- at depth 0, |  +- at depth 1, etc.
        depth = (len(prefix) - 2) // 3

        # Direct deps are at depth 0
        direct = (depth == 0)

        # Get parent artifact
        parent = None
        if depth > 0 and len(parent_stack) > depth:
            parent = parent_stack[depth]

        # Update parent stack
        while len(parent_stack) <= depth + 1:
            parent_stack.append(None)
        parent_stack[depth + 1] = artifact_id

        deps.append({
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "scope": scope,
            "direct": direct,
            "optional": optional,
            "parent": parent,
            "depth": depth,
        })

    return deps


def parse_pom(pom_path):
    """Parse pom.xml for dependencies.

    Returns list of dicts with groupId, artifactId,
    version, scope. Resolves Maven property references.
    """
    deps = []
    properties = {}
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()

        # Handle Maven namespace
        ns = {}
        if root.tag.startswith("{"):
            ns_uri = root.tag.split("}")[0] + "}"
            ns = {"m": ns_uri[1:-1]}

        # Extract properties for variable resolution
        if ns:
            props_elem = root.find("m:properties", ns)
        else:
            props_elem = root.find("properties")

        if props_elem is not None:
            for prop in props_elem:
                # Strip namespace from tag name
                tag = prop.tag
                if "}" in tag:
                    tag = tag.split("}")[1]
                if prop.text:
                    properties[tag] = prop.text

        # Find dependencies
        if ns:
            dep_elems = root.findall(
                ".//m:dependencies/m:dependency", ns
            )
        else:
            dep_elems = root.findall(
                ".//dependencies/dependency"
            )

        for dep in dep_elems:
            if ns:
                group = dep.find("m:groupId", ns)
                artifact = dep.find("m:artifactId", ns)
                version = dep.find("m:version", ns)
                scope = dep.find("m:scope", ns)
            else:
                group = dep.find("groupId")
                artifact = dep.find("artifactId")
                version = dep.find("version")
                scope = dep.find("scope")

            if group is not None and artifact is not None:
                ver_text = (
                    version.text if version is not None
                    else "unknown"
                )
                # Resolve Maven property references
                ver_text = resolve_property(
                    ver_text, properties
                )

                deps.append({
                    "groupId": group.text,
                    "artifactId": artifact.text,
                    "version": ver_text,
                    "scope": (
                        scope.text if scope is not None
                        else "compile"
                    ),
                    "direct": True,  # pom.xml only has direct deps
                    "optional": False,
                    "parent": None,
                })
    except ET.ParseError as e:
        print(f"[WARN] Failed to parse pom.xml: {e}")

    return deps


def resolve_property(value, properties):
    """Resolve Maven property references like ${prop.name}."""
    if not value or "${" not in value:
        return value

    # Match ${property.name} pattern
    pattern = r"\$\{([^}]+)\}"
    match = re.search(pattern, value)
    if match:
        prop_name = match.group(1)
        if prop_name in properties:
            return properties[prop_name]
        # Try with dots replaced by hyphens
        alt_name = prop_name.replace(".", "-")
        if alt_name in properties:
            return properties[alt_name]
    return value


def get_version(repo_dir):
    """Try to get version from pom.xml.

    Resolves Maven CI-friendly version properties
    (``${revision}``, ``${sha1}``, ``${changelist}``)
    using ``<properties>`` from the POM.
    """
    pom_path = Path(repo_dir) / "pom.xml"
    if not pom_path.exists():
        return "unknown"

    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()

        ns = {}
        if root.tag.startswith("{"):
            ns_uri = root.tag.split("}")[0] + "}"
            ns = {"m": ns_uri[1:-1]}

        if ns:
            version = root.find("m:version", ns)
        else:
            version = root.find("version")

        if version is not None:
            ver = version.text or "unknown"

            # Resolve CI-friendly properties
            if "${" in ver:
                ver = _resolve_pom_version(
                    ver, root, ns,
                )

            # Strip -SNAPSHOT suffix — we're
            # analyzing a specific commit, not a
            # development snapshot.
            if ver.endswith("-SNAPSHOT"):
                ver = ver[: -len("-SNAPSHOT")]

            return ver
    except ET.ParseError:
        pass

    return "unknown"


def _resolve_pom_version(ver, root, ns):
    """Resolve ``${...}`` placeholders against POM
    ``<properties>``."""
    properties = {}
    if ns:
        props_elem = root.find(
            "m:properties", ns,
        )
    else:
        props_elem = root.find("properties")

    if props_elem is not None:
        for prop in props_elem:
            tag = prop.tag
            if "}" in tag:
                tag = tag.split("}")[1]
            if prop.text:
                properties[tag] = prop.text

    return resolve_property(ver, properties)


def get_project_group_id(repo_dir):
    """Get the project's groupId from root pom.xml.

    Used to detect sibling modules (same groupId = same project).
    """
    pom_path = Path(repo_dir) / "pom.xml"
    if not pom_path.exists():
        return None

    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()

        ns = {}
        if root.tag.startswith("{"):
            ns_uri = root.tag.split("}")[0] + "}"
            ns = {"m": ns_uri[1:-1]}

        if ns:
            group_id = root.find("m:groupId", ns)
        else:
            group_id = root.find("groupId")

        if group_id is not None:
            return group_id.text
    except ET.ParseError:
        pass

    return None
