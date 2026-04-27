"""
Java ADG SPDX Generator.

Generates SPDX 2.3 SBOMs for Java projects using:
- OmniBOR treedb for .java → .class → .jar relationships
- mvn dependency:tree or ./gradlew dependencies for
  full transitive dependency graphs
"""

import json
import re
import subprocess  # noqa: F401  kept for mock paths
import uuid
import xml.etree.ElementTree as ET  # noqa: F401
from datetime import datetime, timezone
from pathlib import Path

from app.spdx.parser import AdgParser
from app.spdx.maven_parser import (
    get_maven_deps,
    get_version,
    get_project_group_id,
    parse_dep_tree,
    parse_pom,
    resolve_property,
)
from app.spdx.gradle_parser import (
    get_gradle_deps,
    get_gradle_version,
    get_gradle_group,
    is_gradle_project,
)


class JavaSpdxGenerator:
    """Generate SPDX SBOMs for Java projects.

    Unlike native binaries, Java JARs don't have dynamic
    library dependencies. Instead, dependencies come from
    Maven or Gradle and are resolved via
    ``mvn dependency:tree`` or ``./gradlew dependencies``.

    Build system is auto-detected: if gradlew exists in the
    repo root, Gradle is used; otherwise Maven.
    """

    def __init__(
        self, bom_dir, repos_dir, repo_name,
        strace_accessed=None,
    ):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.repo_name = repo_name
        self.repo_dir = self.repos_dir / repo_name
        # Set of absolute file paths opened during
        # the build (from strace openat log).  Used
        # to filter workspace-scan results to only
        # files actually accessed — mirrors how
        # C/C++ uses the raw logfile for evidence.
        self.strace_accessed = strace_accessed or set()

    # -------------------------------------------------
    # Build-system-aware delegates
    # -------------------------------------------------
    def _is_gradle(self):
        return is_gradle_project(self.repo_dir)

    def _get_maven_deps(self, pom_dir=None):
        if self._is_gradle():
            return get_gradle_deps(self.repo_dir)
        return get_maven_deps(
            self.repo_dir, pom_dir=pom_dir,
        )

    def _parse_dep_tree(self, output):
        return parse_dep_tree(output)

    def _parse_pom(self, pom_path):
        return parse_pom(pom_path)

    @staticmethod
    def _resolve_property(value, properties):
        return resolve_property(value, properties)

    def _get_version(self):
        if self._is_gradle():
            return get_gradle_version(self.repo_dir)
        return get_version(self.repo_dir)

    def _get_project_group_id(self):
        if self._is_gradle():
            return get_gradle_group(self.repo_dir)
        return get_project_group_id(self.repo_dir)

    def generate(
        self, output_path, binary_name=None,
        sbom_type="build", jar_files=None,
        pom_dir=None,
    ):
        """Generate SPDX for a Java JAR.

        Args:
            output_path: where to write the SPDX JSON
            binary_name: JAR filename (for SPDX naming)
            sbom_type: 'analyzed' (only what's in the
                JAR — source files, no deps) or 'build'
                (full dependency graph).
            jar_files: optional list of dicts with sha1
                and file_path — per-JAR source files
                from AdgParser.get_jar_source_files().
                If None, falls back to all
                project_source from treedb.
            pom_dir: optional directory containing the
                module's pom.xml for per-module Maven
                dependency resolution.

        Returns output path on success, None on failure.
        """
        bin_name = binary_name or f"{self.repo_name}.jar"

        # Use per-JAR filtered files if provided,
        # otherwise fall back to all project_source
        if jar_files is not None:
            all_files = jar_files
        else:
            parser = AdgParser(
                self.bom_dir, self.repos_dir
            )
            try:
                classified = parser.parse()
            except FileNotFoundError as e:
                print(f"[ERROR] {e}")
                return None
            all_files = classified.get(
                "project_source", []
            )

        source_files = [
            f for f in all_files
            if not self._is_test_file(
                f.get("file_path", "")
            )
        ]
        test_files_excluded = (
            len(all_files) - len(source_files)
        )

        # Filter to strace-verified files when the
        # openat log is available.  This narrows
        # workspace-scan results to only files the
        # build actually opened.
        strace_excluded = 0
        if self.strace_accessed:
            verified = []
            for f in source_files:
                fp = f.get("file_path", "")
                if fp in self.strace_accessed:
                    verified.append(f)
                else:
                    strace_excluded += 1
            source_files = verified

        strace_msg = ""
        if strace_excluded:
            strace_msg = (
                f", {strace_excluded} not in "
                f"strace log"
            )
        test_msg = (
            f", {test_files_excluded} test excluded"
            if test_files_excluded else ""
        )
        print(
            f"[{bin_name}] Source files: "
            f"{len(source_files)} production"
            f"{test_msg}{strace_msg}"
        )

        # Get dependencies via mvn dependency:tree
        # or ./gradlew dependencies (auto-detected).
        # Filter to only runtime deps (compile, runtime, provided).
        # Exclude test scope - those aren't in the final JAR
        all_deps = self._get_maven_deps(
            pom_dir=pom_dir
        )
        maven_deps = [
            d for d in all_deps
            if d["scope"] in (
                "compile", "runtime", "provided"
            )
        ]
        test_deps = len(all_deps) - len(maven_deps)
        direct = sum(
            1 for d in maven_deps if d["direct"]
        )
        trans = len(maven_deps) - direct
        build_sys = (
            "Gradle" if self._is_gradle()
            else "Maven"
        )
        print(
            f"[{bin_name}] {build_sys} dependencies: "
            f"{len(maven_deps)} runtime "
            f"({direct} direct, "
            f"{trans} transitive), "
            f"{test_deps} test excluded"
        )

        # Build SPDX document
        doc = self._build_spdx(
            bin_name, source_files, maven_deps,
            sbom_type=sbom_type,
        )

        # Write output
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2) + "\n")

        pkg_count = len(doc["packages"])
        file_count = len(doc["files"])
        rel_count = len(doc["relationships"])
        print(
            f"[OK] {bin_name} SPDX: {out.name} "
            f"({pkg_count} packages, "
            f"{file_count} files, "
            f"{rel_count} relationships)"
        )

        # Generate HTML visualization
        try:
            from spdx_visualize import generate_html
            html_path = str(out.with_suffix(".html"))
            generate_html(doc, html_path)
        except Exception as e:
            print(f"[WARN] Visualization failed: {e}")

        return str(out)

    def _build_spdx(
        self, bin_name, source_files, maven_deps,
        sbom_type="build",
    ):
        """Build SPDX 2.3 document.

        sbom_type controls what goes in:
          'analyzed' — only source files compiled into
              the JAR (thin JAR has zero bundled deps)
          'build' — full Maven dependency graph
        """
        now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        doc_uuid = str(uuid.uuid4())

        # Clean binary name for SPDX ID
        clean_name = re.sub(
            r"[^a-zA-Z0-9._-]", "-", bin_name
        )

        doc = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"{self.repo_name}-{clean_name}",
            "documentNamespace": (
                f"https://omnibor.io/spdx/"
                f"{self.repo_name}/{doc_uuid}"
            ),
            "creationInfo": {
                "created": now,
                "creators": [
                    "Tool: omnibor-analysis",
                    "Tool: bomsh_create_bom_java.py",
                ],
                "licenseListVersion": "3.19",
            },
            "packages": [],
            "files": [],
            "relationships": [],
        }

        # Extract artifact name from JAR filename
        # e.g., dependency-check-utils-9.2.0.jar → dependency-check-utils
        artifact_name = self._extract_artifact_name(bin_name)

        # Add root package for the JAR
        root_pkg_id = f"SPDXRef-Package-{clean_name}"
        doc["packages"].append({
            "SPDXID": root_pkg_id,
            "name": artifact_name,
            "versionInfo": self._get_version(),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "primaryPackagePurpose": "APPLICATION",
            "supplier": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": (
                    f"pkg:maven/{self.repo_name}/"
                    f"{artifact_name}"
                ),
            }],
        })

        # Add DESCRIBES relationship
        doc["relationships"].append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relatedSpdxElement": root_pkg_id,
            "relationshipType": "DESCRIBES",
        })

        # Add source files
        for i, src in enumerate(source_files):
            file_path = src.get("file_path", "")
            sha1 = src.get("sha1", "")

            # Make path relative to repo
            rel_path = file_path
            repo_prefix = str(self.repo_dir) + "/"
            if file_path.startswith(repo_prefix):
                rel_path = file_path[len(repo_prefix):]

            file_id = f"SPDXRef-File-{i}"
            doc["files"].append({
                "SPDXID": file_id,
                "fileName": rel_path,
                "checksums": [{
                    "algorithm": "SHA1",
                    "checksumValue": sha1,
                }] if sha1 else [],
            })

            # File CONTAINED_BY root package
            doc["relationships"].append({
                "spdxElementId": file_id,
                "relatedSpdxElement": root_pkg_id,
                "relationshipType": "CONTAINED_BY",
            })

        # For analyzed SBOMs, skip Maven deps entirely —
        # thin JARs don't bundle dependency code
        if sbom_type == "analyzed":
            return doc

        # Add Maven dependencies as packages
        # Build artifact ID to SPDX ID mapping for relationships
        artifact_to_spdx = {}
        project_group_id = self._get_project_group_id()

        # First pass: identify sibling artifacts
        sibling_artifacts = set()
        for dep in maven_deps:
            if (project_group_id is not None
                    and dep["groupId"] == project_group_id):
                sibling_artifacts.add(dep["artifactId"])

        # Build parent->children map for BFS
        children_of = {}
        for dep in maven_deps:
            parent = dep.get("parent")
            if parent:
                children_of.setdefault(parent, []).append(
                    dep["artifactId"]
                )

        # BFS to find ALL artifacts reachable through siblings
        # (not just direct children of siblings)
        sibling_transitive = set()
        queue = list(sibling_artifacts)
        while queue:
            current = queue.pop(0)
            for child in children_of.get(current, []):
                if child not in sibling_transitive:
                    if child not in sibling_artifacts:
                        sibling_transitive.add(child)
                        queue.append(child)

        # Filter deps: exclude transitive deps of siblings
        # (they belong in the sibling's own SPDX file)
        filtered_deps = []
        for dep in maven_deps:
            if dep["artifactId"] in sibling_transitive:
                continue
            filtered_deps.append(dep)

        for i, dep in enumerate(filtered_deps):
            dep_id = f"SPDXRef-Dep-{i}"
            artifact_to_spdx[dep["artifactId"]] = dep_id

            purl = (
                f"pkg:maven/{dep['groupId']}/"
                f"{dep['artifactId']}@{dep['version']}"
            )

            # Detect sibling modules (same groupId = same project)
            is_sibling = (
                project_group_id is not None
                and dep["groupId"] == project_group_id
            )

            # Build comment with dependency metadata
            comment_parts = []
            if is_sibling:
                # Mark as sibling module with reference to its SPDX
                sibling_spdx = (
                    f"{dep['artifactId']}-{dep['version']}"
                    "_build.spdx.json"
                )
                comment_parts.append(
                    f"Sibling module. See: {sibling_spdx}"
                )
            comment_parts.append(f"Maven scope: {dep['scope']}")
            if dep.get("direct"):
                comment_parts.append("Direct dependency")
            else:
                comment_parts.append("Transitive dependency")
            if dep.get("optional"):
                comment_parts.append("Optional")
            if dep.get("parent") and not is_sibling:
                comment_parts.append(
                    f"Required by: {dep['parent']}"
                )
            comment = ". ".join(comment_parts)

            # Build PackageSourceInfo
            source_info = (
                f"Maven Central: {dep['groupId']}:"
                f"{dep['artifactId']}:{dep['version']}"
            )

            pkg = {
                "SPDXID": dep_id,
                "name": dep["artifactId"],
                "versionInfo": dep["version"],
                "downloadLocation": (
                    f"https://repo.maven.apache.org/maven2/"
                    f"{dep['groupId'].replace('.', '/')}/"
                    f"{dep['artifactId']}/{dep['version']}/"
                    f"{dep['artifactId']}-{dep['version']}.jar"
                ),
                "filesAnalyzed": False,
                "supplier": f"Organization: {dep['groupId']}",
                "comment": comment,
                "sourceInfo": source_info,
                "externalRefs": [{
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": purl,
                }],
            }
            doc["packages"].append(pkg)

        # Add relationships for dependencies
        for i, dep in enumerate(filtered_deps):
            dep_id = f"SPDXRef-Dep-{i}"

            # Determine relationship target:
            # Direct deps → root package
            # Transitive deps → their parent in the
            #   Maven dependency tree
            if dep.get("direct"):
                target = root_pkg_id
            else:
                parent = dep.get("parent")
                if parent and parent in artifact_to_spdx:
                    target = artifact_to_spdx[parent]
                else:
                    target = root_pkg_id

            # SPDX relationship direction:
            #   DEPENDS_ON: A depends on B →
            #     "A DEPENDS_ON B" (parent→child)
            #   BUILD_TOOL_OF: tool builds target →
            #     "tool BUILD_TOOL_OF target"
            if dep["scope"] == "provided":
                # Provided = compile-time only tool
                doc["relationships"].append({
                    "spdxElementId": dep_id,
                    "relatedSpdxElement": target,
                    "relationshipType": "BUILD_TOOL_OF",
                })
            else:
                # Runtime dep: parent DEPENDS_ON child
                doc["relationships"].append({
                    "spdxElementId": target,
                    "relatedSpdxElement": dep_id,
                    "relationshipType": "DEPENDS_ON",
                })

        return doc

    @staticmethod
    def _extract_artifact_name(jar_filename):
        """Extract Maven artifact name from JAR filename.

        Strips version suffix and .jar extension.
        Examples:
          dependency-check-utils-9.2.0.jar → dependency-check-utils
          jsoup-1.17.2.jar → jsoup
          my-lib-1.0-SNAPSHOT.jar → my-lib
        """
        name = jar_filename
        # Strip .jar extension
        if name.endswith(".jar"):
            name = name[:-4]

        # Strip version suffix: -X.Y.Z or -X.Y.Z-SNAPSHOT
        # Pattern: dash followed by digit, then version chars
        version_pattern = re.compile(
            r"-\d+(\.\d+)*(-SNAPSHOT)?$"
        )
        name = version_pattern.sub("", name)

        return name

    @staticmethod
    def _is_test_file(file_path):
        """Return True if file_path is a test artifact.

        Excludes:
          - target/test-classes/ (compiled test .class)
          - src/test/ (unit test sources)
          - src/it/ (integration test sources)
          - *Test.java / *Tests.java in non-main dirs
        """
        test_dir_markers = (
            "target/test-classes/",
            "src/test/",
            "src/it/",
            "/test-classes/",
        )
        for marker in test_dir_markers:
            if marker in file_path:
                return True
        return False
