"""
Java ADG SPDX Generator.

Generates SPDX 2.3 SBOMs for Java projects using:
- OmniBOR treedb for .java → .class → .jar relationships
- mvn dependency:tree for full transitive Maven dependencies
"""

import json
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from app.spdx.parser import AdgParser


class JavaSpdxGenerator:
    """Generate SPDX SBOMs for Java projects.

    Unlike native binaries, Java JARs don't have dynamic
    library dependencies. Instead, dependencies come from
    Maven and are resolved via `mvn dependency:tree`.
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

        # Get Maven dependencies via dependency:tree
        # Filter to only runtime dependencies (compile, runtime, provided)
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
        print(
            f"[{bin_name}] Maven dependencies: "
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

    def _get_maven_deps(self, pom_dir=None):
        """Get Maven dependencies via mvn dependency:tree.

        Args:
            pom_dir: directory containing pom.xml.
                If None, uses repo root.

        Returns list of dicts with groupId, artifactId,
        version, scope, direct, optional, parent_artifact.
        """
        mvn_dir = Path(pom_dir) if pom_dir else self.repo_dir
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
                return self._parse_pom(pom_path)

            return self._parse_dep_tree(result.stdout)
        except subprocess.TimeoutExpired:
            print("[WARN] mvn dependency:tree timed out")
            return self._parse_pom(pom_path)
        except FileNotFoundError:
            print("[WARN] mvn not found, using pom.xml")
            return self._parse_pom(pom_path)

    def _parse_dep_tree(self, output):
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

    def _parse_pom(self, pom_path):
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
                    ver_text = self._resolve_property(
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

    def _resolve_property(self, value, properties):
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

    def _get_version(self):
        """Try to get version from pom.xml."""
        pom_path = self.repo_dir / "pom.xml"
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
                # Strip -SNAPSHOT suffix — we're
                # analyzing a specific commit, not a
                # development snapshot.
                if ver.endswith("-SNAPSHOT"):
                    ver = ver[: -len("-SNAPSHOT")]
                return ver
        except ET.ParseError:
            pass

        return "unknown"

    def _get_project_group_id(self):
        """Get the project's groupId from root pom.xml.

        Used to detect sibling modules (same groupId = same project).
        """
        pom_path = self.repo_dir / "pom.xml"
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
