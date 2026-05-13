"""
Maven shade/assembly plugin detector.

Scans ``pom.xml`` files for ``maven-shade-plugin`` and
``maven-assembly-plugin`` configurations that repackage
transitive dependencies into uber-JARs.  When detected,
``mvn dependency:tree`` may not reflect the actual JAR
contents (shaded deps are inlined, not declared).

Used by the Java pipeline to annotate SPDX documents
with accuracy caveats.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# Known repackaging plugins that affect dep:tree accuracy
_REPACKAGING_PLUGINS = {
    "maven-shade-plugin": {
        "group_id": "org.apache.maven.plugins",
        "warning": (
            "maven-shade-plugin detected — uber-JAR "
            "may contain shaded transitive dependencies "
            "not listed in dependency:tree"
        ),
    },
    "maven-assembly-plugin": {
        "group_id": "org.apache.maven.plugins",
        "warning": (
            "maven-assembly-plugin detected — "
            "assembled archive may bundle dependencies "
            "not listed in dependency:tree"
        ),
    },
    "spring-boot-maven-plugin": {
        "group_id": "org.springframework.boot",
        "warning": (
            "spring-boot-maven-plugin detected — "
            "fat JAR bundles all runtime dependencies; "
            "dependency:tree is accurate for this case"
        ),
    },
}


@dataclass
class PluginDetection:
    """Result of scanning a pom.xml for repackaging plugins.

    Attributes:
        plugin_id: The Maven artifactId of the plugin.
        group_id: The Maven groupId of the plugin.
        warning: Human-readable warning message.
        pom_path: Path to the pom.xml where detected.
        has_filters: Whether the shade config includes
            artifact filters (reduces false positives).
    """
    plugin_id: str
    group_id: str
    warning: str
    pom_path: str
    has_filters: bool = False


@dataclass
class DetectionResult:
    """Aggregated result from scanning all pom.xml files.

    Attributes:
        detections: List of individual plugin detections.
        spdx_comment: Pre-formatted comment for SPDX
            ``creationInfo`` annotation.
        is_uber_jar: True if any shading/assembly plugin
            was detected.
    """
    detections: List[PluginDetection] = field(
        default_factory=list,
    )

    @property
    def is_uber_jar(self) -> bool:
        """True if any repackaging plugin was detected."""
        return len(self.detections) > 0

    @property
    def spdx_comment(self) -> str:
        """SPDX creationInfo comment annotation.

        Returns empty string if no plugins detected.
        """
        if not self.detections:
            return ""
        seen = []
        for d in self.detections:
            if d.warning not in seen:
                seen.append(d.warning)
        return "; ".join(seen)

    @property
    def plugin_ids(self) -> List[str]:
        """List of detected plugin artifactIds."""
        return [d.plugin_id for d in self.detections]


def detect_repackaging_plugins(
    repo_dir: str,
    pom_subpath: Optional[str] = None,
) -> DetectionResult:
    """Scan pom.xml files for repackaging plugins.

    Searches the root ``pom.xml`` and, for multi-module
    projects, each module's ``pom.xml``.

    Args:
        repo_dir: Path to the repository root.
        pom_subpath: Optional relative path to a specific
            ``pom.xml`` (e.g. ``"core/pom.xml"``).  If
            None, scans root + all modules listed in the
            root POM.

    Returns:
        A ``DetectionResult`` with all findings.
    """
    result = DetectionResult()
    repo_path = Path(repo_dir)

    if pom_subpath:
        pom_paths = [repo_path / pom_subpath]
    else:
        root_pom = repo_path / "pom.xml"
        if not root_pom.exists():
            return result
        pom_paths = [root_pom]
        # Add module POMs for multi-module projects
        modules = _find_modules(root_pom)
        for mod in modules:
            mod_pom = repo_path / mod / "pom.xml"
            if mod_pom.exists():
                pom_paths.append(mod_pom)

    for pom in pom_paths:
        detections = _scan_pom(pom)
        result.detections.extend(detections)

    return result


def _find_modules(pom_path: Path) -> List[str]:
    """Extract ``<modules><module>`` list from a POM."""
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        ns = _maven_ns(root)

        if ns:
            modules_elem = root.find("m:modules", ns)
        else:
            modules_elem = root.find("modules")

        if modules_elem is None:
            return []

        result = []
        for mod in modules_elem:
            if mod.text:
                result.append(mod.text.strip())
        return result
    except ET.ParseError:
        return []


def _scan_pom(pom_path: Path) -> List[PluginDetection]:
    """Scan a single pom.xml for repackaging plugins."""
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
    except ET.ParseError:
        return []

    ns = _maven_ns(root)
    detections = []

    # Search both build/plugins and build/pluginManagement
    plugin_paths = [
        ".//m:build/m:plugins/m:plugin" if ns
        else ".//build/plugins/plugin",
        ".//m:build/m:pluginManagement/m:plugins/m:plugin"
        if ns else
        ".//build/pluginManagement/plugins/plugin",
    ]

    for xpath in plugin_paths:
        plugins = root.findall(xpath, ns) if ns else (
            root.findall(xpath)
        )
        for plugin in plugins:
            detection = _check_plugin(
                plugin, ns, str(pom_path),
            )
            if detection:
                detections.append(detection)

    return detections


def _check_plugin(
    plugin_elem, ns, pom_path: str,
) -> Optional[PluginDetection]:
    """Check if a ``<plugin>`` element is a repackaging plugin."""
    if ns:
        artifact_elem = plugin_elem.find(
            "m:artifactId", ns,
        )
        group_elem = plugin_elem.find(
            "m:groupId", ns,
        )
    else:
        artifact_elem = plugin_elem.find("artifactId")
        group_elem = plugin_elem.find("groupId")

    if artifact_elem is None or not artifact_elem.text:
        return None

    artifact_id = artifact_elem.text.strip()
    group_id = (
        group_elem.text.strip()
        if group_elem is not None and group_elem.text
        else "org.apache.maven.plugins"
    )

    if artifact_id not in _REPACKAGING_PLUGINS:
        return None

    info = _REPACKAGING_PLUGINS[artifact_id]

    # Check for artifact filters (shade plugin)
    has_filters = _has_shade_filters(
        plugin_elem, ns,
    )

    return PluginDetection(
        plugin_id=artifact_id,
        group_id=group_id,
        warning=info["warning"],
        pom_path=pom_path,
        has_filters=has_filters,
    )


def _has_shade_filters(plugin_elem, ns) -> bool:
    """Check if shade plugin has ``<artifactSet>`` filters."""
    if ns:
        filters = plugin_elem.find(
            ".//m:configuration/m:artifactSet", ns,
        )
    else:
        filters = plugin_elem.find(
            ".//configuration/artifactSet",
        )
    return filters is not None


def _maven_ns(root) -> dict:
    """Extract Maven XML namespace from root element."""
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0] + "}"
        return {"m": ns_uri[1:-1]}
    return {}
