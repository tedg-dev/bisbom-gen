"""
Parse Ivy resolution-report XML into the shared dependency-capture format.

Ant builds that use Ivy emit one resolution report per *configuration*
(conf), typically named ``<organisation>-<module>-<conf>.xml`` under the
Ivy report directory (``${ivy.report.dir}`` / the ``ivy:report`` task
output). Each report lists the resolved modules with ``organisation``,
``name``, ``revision``, and the caller chain that pulled them in.

This module turns those reports into the same capture structure produced by
``app.pipeline.maven_dep_tree_parser`` / ``gradle_dep_tree_parser`` so that
Phase 2 (``app.spdx.dep_capture_reader`` -> ``java_generator``) can consume
Ivy captures with no new code path::

    {"tool": "ivy", "modules": [
        {"key": "g:a", "groupId": "g", "artifactId": "a",
         "version": "1.0", "packaging": "jar", "deps": [
             {"groupId": "...", "artifactId": "...", "version": "...",
              "packaging": "jar", "scope": "compile",
              "direct": True, "parent": None}, ...]}]}

The report schema (validated against real Ant+Ivy reports)::

    <ivy-report>
      <info organisation=".." module=".." revision=".." conf=".."/>
      <dependencies>
        <module organisation=".." name="..">
          <revision name="<version>" evicted="..?">
            <caller organisation=".." name=".."/>
          </revision>
        </module>
      </dependencies>
    </ivy-report>
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# Ivy confs are project-defined, but these names are conventional. Map them
# to the Maven-style scopes Phase 2 understands; everything unrecognized is
# treated as ``compile`` (the safe production default).
_CONF_SCOPE = {
    "test": "test",
    "runtime": "runtime",
    "provided": "provided",
}


def _scope_from_conf(conf):
    """Map an Ivy conf name to a Maven-style scope."""
    if not conf:
        return "compile"
    return _CONF_SCOPE.get(conf.strip().lower(), "compile")


def parse_ivy_report(xml_text):
    """Parse a single Ivy resolution report (one conf).

    Args:
        xml_text: The report XML as a string.

    Returns:
        A dict ``{"conf", "scope", "root": (org, name), "root_version",
        "deps": [...]}``. ``deps`` excludes evicted revisions; each entry
        carries ``direct`` (a caller equals the root module) and ``parent``
        (the first non-root caller's name, or None).

    Raises:
        xml.etree.ElementTree.ParseError: if *xml_text* is not valid XML.
    """
    root = ET.fromstring(xml_text)
    info = root.find("info")
    root_org = info.get("organisation") if info is not None else None
    root_name = info.get("module") if info is not None else None
    root_rev = info.get("revision") if info is not None else None
    conf = info.get("conf") if info is not None else None
    scope = _scope_from_conf(conf)

    deps = []
    deps_el = root.find("dependencies")
    if deps_el is not None:
        for module in deps_el.findall("module"):
            org = module.get("organisation")
            name = module.get("name")
            for rev in module.findall("revision"):
                if rev.get("evicted"):
                    continue
                callers = rev.findall("caller")
                direct = any(
                    c.get("organisation") == root_org
                    and c.get("name") == root_name
                    for c in callers
                )
                parent = None
                if not direct:
                    for caller in callers:
                        parent = caller.get("name")
                        break
                deps.append({
                    "groupId": org,
                    "artifactId": name,
                    "version": rev.get("name"),
                    "packaging": "jar",
                    "scope": scope,
                    "direct": direct,
                    "parent": parent,
                })

    return {
        "conf": conf,
        "scope": scope,
        "root": (root_org, root_name),
        "root_version": root_rev,
        "deps": deps,
    }


def _merge_reports(reports):
    """Merge per-conf reports into one deduplicated dependency list.

    Test-scope reports are dropped. Duplicates (same group/artifact/version)
    are collapsed; ``direct`` is OR-ed so a dep that is direct in any
    production conf stays direct.
    """
    merged = {}
    order = []
    root = (None, None)
    root_version = None
    for report in reports:
        if report["scope"] == "test":
            continue
        if report.get("root") and report["root"] != (None, None):
            root = report["root"]
        root_version = root_version or report.get("root_version")
        for dep in report["deps"]:
            key = (dep["groupId"], dep["artifactId"], dep["version"])
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(dep)
                order.append(key)
            elif dep["direct"]:
                existing["direct"] = True
    return [merged[k] for k in order], root, root_version


def build_capture(reports):
    """Build the ``tool="ivy"`` capture dict from parsed conf reports.

    Args:
        reports: An iterable of dicts from :func:`parse_ivy_report`.

    Returns:
        A capture dict ``{"tool": "ivy", "modules": [<module>]}`` with a
        single module (Ant+Ivy projects resolve one root module).
    """
    deps, (org, name), root_version = _merge_reports(list(reports))
    if org and name:
        key = f"{org}:{name}"
    else:
        key = name or ""
    module = {
        "key": key,
        "groupId": org,
        "artifactId": name,
        "version": root_version or "",
        "packaging": "jar",
        "deps": deps,
    }
    return {"tool": "ivy", "modules": [module]}


def parse_ivy_report_dir(report_dir):
    """Parse every Ivy resolution report in *report_dir* into a capture.

    Non-XML files and XML files whose root element is not ``ivy-report``
    are skipped with a debug log. Files that fail to parse are skipped with
    a warning (one malformed report must not abort the whole capture).

    Args:
        report_dir: Directory containing ``*.xml`` Ivy reports.

    Returns:
        The capture dict from :func:`build_capture` (one module). If no
        valid reports are found, the module's ``deps`` is empty.
    """
    reports = []
    for path in sorted(Path(report_dir).glob("*.xml")):
        try:
            xml_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not read Ivy report %s: %s", path, exc)
            continue
        try:
            report = parse_ivy_report(xml_text)
        except ET.ParseError as exc:
            logger.warning("Malformed Ivy report %s: %s", path, exc)
            continue
        if report["root"] == (None, None):
            logger.debug("Skipping non-ivy-report XML: %s", path)
            continue
        reports.append(report)
    return build_capture(reports)
