"""
Java ADG SPDX Generator.

Generates SPDX 2.3 SBOMs for Java projects using:
- OmniBOR treedb for .java → .class → .jar relationships
- mvn dependency:tree or ./gradlew dependencies for
  full transitive dependency graphs
"""

import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
from app.spdx.relationships import (
    BUILD_TOOL_OF,
    CONTAINED_BY,
    DESCRIBES,
    java_dep_relationship,
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
        vcs_uri="NOASSERTION",
    ):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.repo_name = repo_name
        self.repo_dir = self.repos_dir / repo_name
        self.vcs_uri = vcs_uri
        # Set of absolute file paths opened during
        # the build (from strace openat log).  Used
        # as secondary verification of treedb’s
        # heuristic class→source mapping.  Logged as
        # warnings when discrepancies found, but does
        # NOT discard files — treedb is authoritative.
        self.strace_accessed = strace_accessed or set()

    # -------------------------------------------------
    # Build-system-aware delegates
    # -------------------------------------------------
    def _is_gradle(self):
        return is_gradle_project(self.repo_dir)

    def _get_maven_deps(self, pom_dir=None):
        if self._is_gradle():
            project = self._gradle_project_from_dir(
                pom_dir
            )
            return get_gradle_deps(
                self.repo_dir, project=project
            )
        return get_maven_deps(
            self.repo_dir, pom_dir=pom_dir,
        )

    def _gradle_project_from_dir(self, module_dir):
        """Derive Gradle project path from module directory.

        E.g. /repos/spring-boot/spring-boot-project/spring-boot
        with repo_dir /repos/spring-boot
        → ':spring-boot-project:spring-boot'
        """
        if not module_dir:
            return None
        try:
            rel = Path(module_dir).relative_to(
                self.repo_dir
            )
            parts = rel.parts
            if not parts or parts == ('.',):
                return None
            return ':' + ':'.join(parts)
        except ValueError:
            return None

    def _parse_dep_tree(self, output):
        return parse_dep_tree(output)

    def _parse_pom(self, pom_path):
        return parse_pom(pom_path)

    @staticmethod
    def _resolve_property(value, properties):
        return resolve_property(value, properties)

    def _get_version(self, artifact_path=None):
        if self._is_gradle():
            ver = get_gradle_version(self.repo_dir)
        else:
            ver = get_version(self.repo_dir)

        # Universal fallback: if the build-system
        # parser returned an unresolved placeholder
        # or "unknown", extract from the artifact
        # filename (e.g. log4j-core-2.24.3.jar).
        if artifact_path and (
            ver == "unknown" or "${" in ver
        ):
            ver = (
                self._version_from_artifact(
                    artifact_path,
                ) or ver
            )
        return ver

    @staticmethod
    def _version_from_artifact(filename):
        """Extract version from an artifact filename.

        Works for any naming convention that uses
        ``name-X.Y.Z.ext`` (JAR, WAR, EAR, etc.).
        Returns *None* if no version is found.
        """
        stem = Path(filename).stem
        m = re.search(r"-(\d+\.\d[\w.]*)", stem)
        return m.group(1) if m else None

    @staticmethod
    def _artifact_annotation(dep):
        """Return an annotation string if the artifact
        is a known non-code dependency, else *None*.

        Covers:
        - Placeholder/conflict-avoidance stubs (e.g.,
          ``listenablefuture`` with version
          ``9999.0-empty-to-avoid-conflict-with-guava``).
        - BOM/platform artifacts that contain no
          compiled code (POM-only).
        """
        ver = dep.get("version", "")
        aid = dep.get("artifactId", "")

        if "empty-to-avoid-conflict" in ver:
            return (
                "Placeholder artifact — empty JAR "
                "for conflict avoidance"
            )
        if (
            aid.endswith("-bom")
            or aid.endswith("_bom")
            or aid.endswith("-dependencies")
        ):
            return (
                "BOM/platform artifact — POM-only, "
                "no compiled code"
            )
        return None

    def _get_project_group_id(self):
        if self._is_gradle():
            return get_gradle_group(self.repo_dir)
        return get_project_group_id(self.repo_dir)

    # -------------------------------------------------
    # Build tool version detection
    # -------------------------------------------------
    @staticmethod
    def _detect_javac_version():
        """Detect the JDK version from ``javac -version``.

        Returns:
            Version string (e.g. ``"17.0.13"``) or None.
        """
        try:
            result = subprocess.run(
                ["javac", "-version"],
                capture_output=True, text=True,
                timeout=10, check=False,
            )
            # javac output: "javac 17.0.13"
            output = (
                result.stdout.strip()
                or result.stderr.strip()
            )
            m = re.search(r"(\d+[\d.]*)", output)
            return m.group(1) if m else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _detect_maven_version():
        """Detect the Maven version from ``mvn --version``.

        Returns:
            Version string (e.g. ``"3.9.15"``) or None.
        """
        try:
            result = subprocess.run(
                ["mvn", "--version"],
                capture_output=True, text=True,
                timeout=10, check=False,
            )
            # First line: "Apache Maven 3.9.15 (...)"
            m = re.search(
                r"Apache Maven (\d+[\d.]*)",
                result.stdout,
            )
            return m.group(1) if m else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _detect_gradle_version(repo_dir):
        """Detect Gradle version from wrapper or system.

        Returns:
            Version string (e.g. ``"8.5"``) or None.
        """
        # Check gradle-wrapper.properties first
        props = (
            Path(repo_dir) / "gradle" / "wrapper"
            / "gradle-wrapper.properties"
        )
        if props.exists():
            try:
                text = props.read_text(
                    encoding="utf-8",
                )
                m = re.search(
                    r"gradle-(\d+[\d.]*)", text,
                )
                if m:
                    return m.group(1)
            except OSError:
                pass
        # Fallback: system gradle
        try:
            result = subprocess.run(
                ["gradle", "--version"],
                capture_output=True, text=True,
                timeout=10, check=False,
            )
            m = re.search(
                r"Gradle (\d+[\d.]*)",
                result.stdout,
            )
            return m.group(1) if m else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _add_build_tools(self, doc, root_pkg_id):
        """Add JDK and build system as BUILD_TOOL_OF.

        Mirrors how ``emitter.py`` adds gcc/go/rustc for
        other languages.  Every compiled artifact has at
        least a compiler (javac) and a build system
        (Maven or Gradle) that produced it.
        """
        # ── javac (JDK compiler) ──────────────────────
        jdk_ver = self._detect_javac_version()
        if jdk_ver:
            jdk_id = "SPDXRef-BuildTool-javac"
            doc["packages"].append({
                "SPDXID": jdk_id,
                "name": "javac",
                "versionInfo": jdk_ver,
                "supplier": "Organization: Oracle",
                "downloadLocation": (
                    "https://jdk.java.net/"
                ),
                "filesAnalyzed": False,
                "primaryPackagePurpose":
                    "APPLICATION",
                "externalRefs": [{
                    "referenceCategory": "SECURITY",
                    "referenceType": "cpe23Type",
                    "referenceLocator": (
                        f"cpe:2.3:a:oracle:jdk:"
                        f"{jdk_ver}:*:*:*:*:*:*:*"
                    ),
                }],
                "comment": (
                    f"Java compiler (JDK {jdk_ver}) "
                    "used to compile .java sources "
                    "into .class bytecode."
                ),
            })
            doc["relationships"].append({
                "spdxElementId": jdk_id,
                "relatedSpdxElement": root_pkg_id,
                "relationshipType": BUILD_TOOL_OF,
            })

        # ── Build system (Maven or Gradle) ────────────
        if self._is_gradle():
            gradle_ver = self._detect_gradle_version(
                self.repo_dir,
            )
            if gradle_ver:
                gid = "SPDXRef-BuildTool-gradle"
                doc["packages"].append({
                    "SPDXID": gid,
                    "name": "gradle",
                    "versionInfo": gradle_ver,
                    "supplier": (
                        "Organization: Gradle Inc"
                    ),
                    "downloadLocation": (
                        "https://gradle.org/"
                    ),
                    "filesAnalyzed": False,
                    "primaryPackagePurpose":
                        "APPLICATION",
                    "externalRefs": [{
                        "referenceCategory":
                            "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": (
                            "pkg:maven/"
                            "org.gradle/gradle@"
                            f"{gradle_ver}"
                        ),
                    }],
                    "comment": (
                        f"Gradle {gradle_ver} build "
                        "system used to orchestrate "
                        "compilation and packaging."
                    ),
                })
                doc["relationships"].append({
                    "spdxElementId": gid,
                    "relatedSpdxElement": root_pkg_id,
                    "relationshipType": BUILD_TOOL_OF,
                })
        else:
            mvn_ver = self._detect_maven_version()
            if mvn_ver:
                mid = "SPDXRef-BuildTool-maven"
                doc["packages"].append({
                    "SPDXID": mid,
                    "name": "maven",
                    "versionInfo": mvn_ver,
                    "supplier": (
                        "Organization: "
                        "Apache Software Foundation"
                    ),
                    "downloadLocation": (
                        "https://maven.apache.org/"
                    ),
                    "filesAnalyzed": False,
                    "primaryPackagePurpose":
                        "APPLICATION",
                    "externalRefs": [{
                        "referenceCategory":
                            "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": (
                            "pkg:maven/"
                            "org.apache.maven/maven@"
                            f"{mvn_ver}"
                        ),
                    }],
                    "comment": (
                        f"Apache Maven {mvn_ver} "
                        "build system used to "
                        "orchestrate compilation "
                        "and packaging."
                    ),
                })
                doc["relationships"].append({
                    "spdxElementId": mid,
                    "relatedSpdxElement": root_pkg_id,
                    "relationshipType": BUILD_TOOL_OF,
                })

    def generate(
        self, output_path, binary_name=None,
        sbom_type="build", jar_files=None,
        pom_dir=None, plugin_detection=None,
        deps=None, jar_sha1=None, jar_gitoid=None,
    ):
        """Generate SPDX for a Java JAR.

        Args:
            output_path: where to write the SPDX JSON
            binary_name: JAR filename (for SPDX naming)
            sbom_type: 'analyzed' (only what's in the
                JAR — source files, no deps) or 'build'
                (full dependency graph).
            jar_files: list of dicts with sha1
                and file_path — per-JAR source files
                from AdgParser.get_jar_source_files().
                Required; None is an error.
            pom_dir: optional directory containing the
                module's pom.xml for per-module Maven
                dependency resolution. Only used by the
                co-located dev/test live fallback when
                *deps* is None.
            plugin_detection: optional ``DetectionResult``
                from ``maven_plugin_detector``. When present
                and a shade/assembly plugin is detected,
                the SPDX ``creationInfo`` is annotated.
            deps: optional pre-resolved dependency list (the
                module's subtree from Phase 1 capture). When
                provided, it is used directly and **no**
                source-tree resolution is performed (the
                enterprise Phase 2 path). When None, the
                generator falls back to live resolution via
                *pom_dir* (the co-located dev/test path).
            jar_sha1: the JAR's own git-blob SHA1 (its OmniBOR
                Artifact ID, sha1 flavor) from the treedb key.
                Emitted as the root package ``checksums`` value.
            jar_gitoid: the JAR's OmniBOR document id from
                ``load_doc_mapping()``. Emitted as the root
                package ``gitoid`` ``externalRef``. Both mirror
                the C emitter so every language records the
                built artifact's OmniBOR identity
                (see project/artifact-identity.md).

        Returns output path on success, None on failure.
        """
        bin_name = binary_name or f"{self.repo_name}.jar"

        # jar_files must be provided by the caller
        # (per-JAR source files from treedb).  Never
        # fall back to all project_source — that would
        # silently include files from other JARs.
        if jar_files is None:
            print(
                f"[ERROR] {bin_name}: jar_files is "
                f"None — cannot generate SPDX "
                f"without per-JAR file list"
            )
            return None
        all_files = jar_files

        source_files = [
            f for f in all_files
            if not self._is_test_file(
                f.get("file_path", "")
            )
            and not self._is_extraction_artifact(
                f.get("file_path", "")
            )
        ]
        test_files_excluded = (
            len(all_files) - len(source_files)
        )

        # Secondary verification: compare treedb
        # files against strace openat log.  Treedb
        # uses heuristic path-similarity scoring for
        # class→source mapping, so discrepancies may
        # indicate false positives.  Log warnings but
        # do NOT discard — strace can also miss files
        # (e.g. Gradle included-build caching).
        strace_unverified = 0
        if self.strace_accessed:
            for f in source_files:
                fp = f.get("file_path", "")
                if fp not in self.strace_accessed:
                    strace_unverified += 1

        strace_msg = ""
        if strace_unverified:
            strace_msg = (
                f", {strace_unverified} not in "
                f"strace log (kept)"
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

        # Dependency source (CISA build SBOM):
        #   - enterprise Phase 2: *deps* is the module's subtree from
        #     Phase 1 capture (no source tree touched).
        #   - co-located dev/test fallback: *deps* is None, so resolve
        #     live via mvn dependency:tree / ./gradlew dependencies.
        # Filter to only runtime deps (compile, runtime, provided);
        # exclude test scope — those aren't in the final JAR.
        if deps is not None:
            all_deps = deps
        else:
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
            plugin_detection=plugin_detection,
            jar_sha1=jar_sha1, jar_gitoid=jar_gitoid,
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

    @staticmethod
    def _creation_info(created_ts, plugin_detection=None):
        """Build SPDX ``creationInfo`` block.

        When a repackaging plugin (shade, assembly) is
        detected, appends the warning to the ``comment``
        field so downstream consumers know the SBOM may
        not reflect the full JAR contents.
        """
        info = {
            "created": created_ts,
            "creators": [
                "Tool: omnibor-analysis",
                "Tool: bomsh_create_bom_java.py",
            ],
            "licenseListVersion": "3.19",
        }
        if (
            plugin_detection
            and plugin_detection.spdx_comment
        ):
            info["comment"] = (
                plugin_detection.spdx_comment
            )
        return info

    def _build_spdx(
        self, bin_name, source_files, maven_deps,
        sbom_type="build", plugin_detection=None,
        jar_sha1=None, jar_gitoid=None,
    ):
        """Build SPDX 2.3 document.

        sbom_type controls what goes in:
          'analyzed' — only source files compiled into
              the JAR (thin JAR has zero bundled deps)
          'build' — full Maven dependency graph

        plugin_detection: optional ``DetectionResult``;
          when present, annotates ``creationInfo.comment``
          with repackaging plugin warnings.

        jar_sha1 / jar_gitoid: the built JAR's OmniBOR
          artifact identity (git-blob SHA1 checksum and
          OmniBOR document id).  Emitted on the root
          package; see ``generate`` and
          project/artifact-identity.md.
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
            "creationInfo": self._creation_info(
                now, plugin_detection,
            ),
            "packages": [],
            "files": [],
            "relationships": [],
        }

        # Extract artifact name from JAR filename
        # e.g., dependency-check-utils-9.2.0.jar → dependency-check-utils
        artifact_name = self._extract_artifact_name(bin_name)

        # Add root package for the JAR
        root_pkg_id = f"SPDXRef-Package-{clean_name}"

        # OmniBOR artifact identity for the built JAR.  The JAR's
        # own git-blob SHA1 (its Artifact ID) is the checksum; its
        # OmniBOR document id is the gitoid externalRef.  Mirrors
        # the C emitter (app/spdx/emitter.py) so every language
        # records the built artifact's identity — the core point
        # of OmniBOR (see project/artifact-identity.md).
        external_refs = [{
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": (
                f"pkg:maven/{self.repo_name}/"
                f"{artifact_name}"
            ),
        }]
        checksums = []
        if jar_sha1:
            checksums.append({
                "algorithm": "SHA1",
                "checksumValue": jar_sha1,
            })
        if jar_gitoid:
            external_refs.append({
                "referenceCategory": "PERSISTENT-ID",
                "referenceType": "gitoid",
                "referenceLocator": (
                    f"gitoid:blob:sha1:{jar_gitoid}"
                ),
            })
        if not jar_sha1 or not jar_gitoid:
            print(
                f"[WARN] {bin_name}: missing OmniBOR artifact "
                f"identity (sha1={bool(jar_sha1)}, "
                f"gitoid={bool(jar_gitoid)}) — root package "
                f"will lack full artifact identity"
            )

        doc["packages"].append({
            "SPDXID": root_pkg_id,
            "name": artifact_name,
            "versionInfo": self._get_version(
                artifact_path=bin_name,
            ),
            "downloadLocation": self.vcs_uri,
            "filesAnalyzed": True,
            "primaryPackagePurpose": "APPLICATION",
            "supplier": "NOASSERTION",
            "externalRefs": external_refs,
            "checksums": checksums,
        })

        # Add DESCRIBES relationship
        doc["relationships"].append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relatedSpdxElement": root_pkg_id,
            "relationshipType": DESCRIBES,
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
                "relationshipType": CONTAINED_BY,
            })

        # ── Build tools (javac + build system) ────────
        # Same pattern as gcc/go/rustc in emitter.py:
        # detect the compiler and build system that
        # produced this artifact and emit BUILD_TOOL_OF.
        self._add_build_tools(doc, root_pkg_id)

        # For analyzed SBOMs, strip BUILD_TOOL_OF rels
        # and their orphaned packages — build tools
        # aren't compiled into the binary.
        if sbom_type == "analyzed":
            bt_ids = {
                r["spdxElementId"]
                for r in doc["relationships"]
                if r["relationshipType"]
                == BUILD_TOOL_OF
            }
            doc["relationships"] = [
                r for r in doc["relationships"]
                if r["relationshipType"]
                != BUILD_TOOL_OF
            ]
            # Remove orphaned build-tool packages
            still_used = {
                r["spdxElementId"]
                for r in doc["relationships"]
            } | {
                r["relatedSpdxElement"]
                for r in doc["relationships"]
            }
            doc["packages"] = [
                p for p in doc["packages"]
                if p["SPDXID"] not in bt_ids
                or p["SPDXID"] in still_used
            ]
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
        # (they belong in the sibling's own SPDX file).
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
            annotation = self._artifact_annotation(dep)
            if annotation:
                comment_parts.append(annotation)
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

            # Classify by scope only — all dependency
            # tree entries are library deps (DEPENDS_ON
            # etc.).  Build tools are emitted separately
            # by _add_build_tools().
            rel_type = java_dep_relationship(
                dep.get("scope", "compile"),
            )
            if rel_type is None:
                continue

            # Direction: parent DEPENDS_ON child
            doc["relationships"].append({
                "spdxElementId": target,
                "relatedSpdxElement": dep_id,
                "relationshipType": rel_type,
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
    def _is_extraction_artifact(file_path):
        """Return True if path is a bomsh extraction artifact.

        ``bomsh_create_bom_java.py`` extracts JARs into
        ``/tmp/bomjdir/`` for introspection.  These paths
        appear in the treedb but are not project source
        files — they are intermediate extraction artifacts
        (e.g. ``.class`` files from multi-release JARs).

        In standalone mode the strace ``openat`` filter
        already excludes them.  This filter ensures
        sidecar mode is consistent.
        """
        return "/tmp/bomjdir/" in file_path

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
