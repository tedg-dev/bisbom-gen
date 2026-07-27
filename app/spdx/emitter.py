"""
SPDX Emitter — produces SPDX 2.3 JSON from resolved components.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.version_detection import VendoredVersionDetector
from app.spdx.identity import (
    spdx_2_3_file_checksums,
    try_from_file,
)
from app.spdx.lang_parsers import (
    detect_go_version,
    go_module_from_vendor_path,
    parse_cargo_lock,
    parse_cargo_toml,
    parse_go_mod,
    parse_go_modules_txt,
    rust_crate_from_registry_path,
)
from app.spdx.relationships import (
    BUILD_TOOL_OF,
    CONTAINS,
    DEPENDS_ON,
    DESCRIBES,
    DYNAMIC_LINK,
    STATIC_LINK,
)
from app.spdx.vendored import (
    VENDORED_DIRS as _DEFAULT_VENDORED_DIRS,
    detect_vendored_groups,
)


class SpdxEmitter:
    """Produce SPDX 2.3 JSON from resolved components.

    Generates a complete SPDX document with:
      - Document-level metadata (namespace, creators)
      - Root package for the target binary
      - One package per dynamically linked library
        (primaryPackagePurpose: LIBRARY)
      - ExternalRefs: PURL, CPE, OmniBOR gitoid
      - Relationships: DYNAMIC_LINK, BUILD_TOOL_OF
      - File entries for project source files
    """

    NAMESPACE_PREFIX = (
        "https://omnibor.io/bisbom-gen"
    )

    def __init__(
        self, repo_name, repo_version,
        distro, gcc_version,
        bomtrace_version="unknown",
        bomsh_version="unknown",
        binary_name=None,
        vendored_dirs=None,
        repos_dir=None,
        vcs_uri="NOASSERTION",
    ):
        self.repo_name = repo_name
        self.repo_version = repo_version
        self.distro = distro
        self.gcc_version = gcc_version
        self.bomtrace_version = bomtrace_version
        self.bomsh_version = bomsh_version
        self.binary_name = (
            binary_name or repo_name
        )
        self.repos_dir = repos_dir
        self.vcs_uri = vcs_uri
        self._spdx_id_counter = 0
        self._sub_versions = {}
        if vendored_dirs is not None:
            self._vendored_dirs = tuple(
                vendored_dirs
            )
        else:
            self._vendored_dirs = self.VENDORED_DIRS

    # -------------------------------------------------
    # Backward-compatible class constants & delegates
    # -------------------------------------------------

    def _next_spdx_id(self, prefix="Package"):
        """Generate unique SPDX identifier."""
        self._spdx_id_counter += 1
        return (
            f"SPDXRef-{prefix}"
            f"-{self._spdx_id_counter}"
        )

    def _sanitize_spdx_id(self, name):
        """Sanitize a name for use in SPDX IDs.

        SPDX 2.3 IDs allow only [a-zA-Z0-9.-].
        """
        return re.sub(r"[^a-zA-Z0-9.-]", "-", name)

    # Directories that indicate vendored/embedded
    # third-party source code.
    VENDORED_DIRS = _DEFAULT_VENDORED_DIRS

    # Backward-compatible static method delegates.
    # These preserve the original API so that tests
    # calling SpdxEmitter._go_module_from_vendor_path
    # etc. continue to work.
    _detect_go_version = staticmethod(
        detect_go_version
    )
    _go_module_from_vendor_path = staticmethod(
        go_module_from_vendor_path
    )
    _rust_crate_from_registry_path = staticmethod(
        rust_crate_from_registry_path
    )
    _parse_cargo_lock = staticmethod(
        parse_cargo_lock
    )
    _parse_cargo_toml = staticmethod(
        parse_cargo_toml
    )
    _parse_go_mod = staticmethod(
        parse_go_mod
    )
    _parse_go_modules_txt = staticmethod(
        parse_go_modules_txt
    )

    def _detect_vendored_groups(self, project_files):
        """Group source files by vendored library.

        Delegates to vendored.detect_vendored_groups().

        Returns:
          vendored: dict[lib_name] -> list[artifact]
          own: list[artifact]  (non-vendored)

        Side-effect: populates self._sub_versions
        with {lib_name: version} for sub-components
        whose version was found during splitting.
        """
        vendored, own, self._sub_versions = (
            detect_vendored_groups(
                project_files,
                vendored_dirs=self._vendored_dirs,
            )
        )
        return vendored, own

    def emit(  # pylint: disable=unused-argument
        self, components, project_files,
        doc_mapping, logfile_hashes,
        direct_only=False,
        static_only=False,
        go_stdlib=None,
    ):
        """Generate SPDX 2.3 JSON dict.

        Args:
            components: list of resolved component dicts
            project_files: list of project source artifacts
            doc_mapping: bomsh sha1 -> omnibor_doc_id.
                Topology only (never surfaced in the SBOM);
                retained as the bridge the future SHA-256
                OMID reconstruction will re-key. See the
                design of record (project/artifact-identity.md).
            logfile_hashes: file_path -> build-time sha1.
                Used only to locate the built binary's path;
                identity is computed by reading that file.
            direct_only: if True, include only direct
                dependencies (exclude transitive).
                Use for two-tier SBOMs where transitive
                deps belong to a downstream SBOM.
            static_only: if True, omit dynamically linked
                library packages and build tools. Only
                include the root binary and
                vendored/static libs (CISA Analyzed).
            go_stdlib: list of Go standard library
                source artifacts (from AdgParser), or
                None for non-Go projects.

        Returns:
            dict: complete SPDX 2.3 JSON document
        """
        doc_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        doc = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": self.binary_name,
            "documentNamespace": (
                f"{self.NAMESPACE_PREFIX}"
                f"/{self.binary_name}-{doc_uuid}"
            ),
            "creationInfo": {
                "created": now,
                "creators": [
                    f"Tool: bomtrace3"
                    f"-{self.bomtrace_version}",
                    f"Tool: bomsh"
                    f"-{self.bomsh_version}",
                    "Tool: bisbom-gen"
                    " (github.com/tedg-dev"
                    "/omnibor-analysis)",
                ],
                "licenseListVersion": "3.19",
            },
            "packages": [],
            "files": [],
            "relationships": [],
        }

        # --- Root package: the target binary ---
        is_shared_lib = (
            self.binary_name.endswith(".so")
            or ".so." in self.binary_name
        )
        root_purpose = (
            "LIBRARY" if is_shared_lib
            else "APPLICATION"
        )
        root_id = "SPDXRef-Package-root"
        root_pkg = {
            "SPDXID": root_id,
            "name": self.binary_name,
            "downloadLocation": self.vcs_uri,
            "filesAnalyzed": True,
            "primaryPackagePurpose": root_purpose,
            "builtDate": now,
            "externalRefs": [],
            "checksums": [],
            "comment": (
                f"Built on {self.distro} with "
                f"{self.gcc_version}"
            ),
        }
        if self.repo_version:
            root_pkg["versionInfo"] = (
                self.repo_version
            )

        # OmniBOR identity for the built binary (design of
        # record: project/artifact-identity.md).  The checksum
        # is the raw SHA-256 of the artifact; the gitoid
        # externalRef is the artifact's own SHA-256 OmniBOR
        # Artifact ID.  Both are computed by reading the built
        # binary -- bomsh's SHA-1 treedb (doc_mapping) is
        # topology only and is never surfaced in the SBOM.
        for bin_path in logfile_hashes:
            if Path(bin_path).name != self.binary_name:
                continue
            ident = try_from_file(bin_path)
            if ident is not None:
                root_pkg["externalRefs"].append(
                    ident.as_spdx_gitoid_ref()
                )
                root_pkg["checksums"].append(
                    ident.as_spdx_checksum()
                )
            else:
                print(
                    f"[WARN] {self.binary_name}: built "
                    f"artifact not readable at "
                    f"{bin_path} -- root package will "
                    f"lack OmniBOR identity"
                )
            break

        doc["packages"].append(root_pkg)

        # DESCRIBES relationship
        doc["relationships"].append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": DESCRIBES,
            "relatedSpdxElement": root_id,
        })

        # --- Dynamic library packages ---
        if not static_only:
            if direct_only:
                components = [
                    c for c in components
                    if c.get("direct")
                ]

            for comp in components:
                safe_name = self._sanitize_spdx_id(
                    comp["name"]
                )
                pkg_id = self._next_spdx_id(safe_name)

                linkage = (
                    "direct" if comp.get("direct")
                    else "transitive"
                )
                sonames = comp.get("sonames", [])

                if comp.get("project_built"):
                    # Project-built shared library
                    # (e.g. libavcodec.so from FFmpeg)
                    pkg = {
                        "SPDXID": pkg_id,
                        "name": comp["name"],
                        "downloadLocation":
                            "NOASSERTION",
                        "filesAnalyzed": False,
                        "primaryPackagePurpose":
                            "LIBRARY",
                        "externalRefs": [],
                        "comment": (
                            f"Project-built shared "
                            f"library ({linkage}). "
                            f"sonames: "
                            f"{', '.join(sonames)}"
                        ),
                        "sourceInfo": (
                            f"Built from project "
                            f"source as part of "
                            f"{self.repo_name} build."
                        ),
                    }
                    if self.repo_version:
                        pkg["versionInfo"] = (
                            self.repo_version
                        )
                else:
                    # System (dpkg) library
                    dpkg_pkgs = comp.get(
                        "dpkg_packages", []
                    )
                    dl = (
                        comp["homepage"]
                        if comp.get("homepage")
                        and comp["homepage"]
                        != "NOASSERTION"
                        else "NOASSERTION"
                    )
                    pkg = {
                        "SPDXID": pkg_id,
                        "name": comp["name"],
                        "downloadLocation": dl,
                        "filesAnalyzed": False,
                        "primaryPackagePurpose":
                            "LIBRARY",
                        "externalRefs": [],
                        "comment": (
                            f"Dynamically linked "
                            f"({linkage}). "
                            f"sonames: "
                            f"{', '.join(sonames)}. "
                            f"dpkg: "
                            f"{', '.join(dpkg_pkgs)}"
                            f" ({comp.get('architecture', 'amd64')})"
                        ),
                    }

                    # PURL
                    if comp.get("purl"):
                        pkg["externalRefs"].append({
                            "referenceCategory":
                                "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator":
                                comp["purl"],
                        })

                    # CPE
                    if comp.get("cpe23"):
                        pkg["externalRefs"].append({
                            "referenceCategory":
                                "SECURITY",
                            "referenceType":
                                "cpe23Type",
                            "referenceLocator":
                                comp["cpe23"],
                        })

                    # Add optional fields
                    if comp.get("version"):
                        pkg["versionInfo"] = (
                            comp["version"]
                        )
                    supplier = comp.get(
                        "supplier", ""
                    )
                    if (
                        supplier
                        and supplier != "NOASSERTION"
                    ):
                        pkg["supplier"] = (
                            f"Organization: "
                            f"{supplier}"
                        )
                    hp = comp.get("homepage", "")
                    if hp and hp != "NOASSERTION":
                        pkg["homepage"] = hp

                    # Package source info for dpkg libs
                    dpkg_desc = (
                        ", ".join(dpkg_pkgs)
                        if dpkg_pkgs
                        else comp["name"]
                    )
                    pkg["sourceInfo"] = (
                        f"Installed via dpkg package "
                        f"{dpkg_desc} on "
                        f"{self.distro}."
                    )

                doc["packages"].append(pkg)

                # DYNAMIC_LINK from root
                doc["relationships"].append({
                    "spdxElementId": root_id,
                    "relationshipType":
                        DYNAMIC_LINK,
                    "relatedSpdxElement": pkg_id,
                })

        # --- Build tool(s) ---
        is_go = go_stdlib and len(go_stdlib) > 0

        if is_go:
            # Go compiler as build tool
            go_id = self._next_spdx_id("go")
            go_ver = self._detect_go_version(
                go_stdlib
            )
            go_pkg = {
                "SPDXID": go_id,
                "name": "go",
                "versionInfo": go_ver,
                "supplier": (
                    "Organization: "
                    "The Go Authors"
                ),
                "downloadLocation":
                    "https://go.dev/dl/",
                "homepage": "https://go.dev/",
                "filesAnalyzed": False,
                "primaryPackagePurpose":
                    "APPLICATION",
                "externalRefs": [{
                    "referenceCategory": "SECURITY",
                    "referenceType": "cpe23Type",
                    "referenceLocator": (
                        f"cpe:2.3:a:golang:go:"
                        f"{go_ver}:*:*:*:*:*:*:*"
                    ),
                }],
                "sourceInfo": (
                    "System-installed Go toolchain "
                    "at /usr/local/go/."
                ),
            }
            doc["packages"].append(go_pkg)
            doc["relationships"].append({
                "spdxElementId": go_id,
                "relationshipType": BUILD_TOOL_OF,
                "relatedSpdxElement": root_id,
            })

            # Go stdlib as dependency
            stdlib_id = self._next_spdx_id(
                "go-stdlib"
            )
            stdlib_count = len([
                a for a in go_stdlib
                if a["file_path"].endswith(".go")
            ])
            stdlib_pkg = {
                "SPDXID": stdlib_id,
                "name": "go-stdlib",
                "versionInfo": go_ver,
                "supplier": (
                    "Organization: "
                    "The Go Authors"
                ),
                "downloadLocation":
                    "https://go.dev/dl/",
                "homepage":
                    "https://pkg.go.dev/std",
                "filesAnalyzed": False,
                "primaryPackagePurpose":
                    "LIBRARY",
                "externalRefs": [{
                    "referenceCategory":
                        "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": (
                        f"pkg:golang/stdlib"
                        f"@{go_ver}"
                    ),
                }],
                "comment": (
                    f"Go standard library "
                    f"(bundled with Go {go_ver}). "
                    f"Provides core packages "
                    f"(fmt, os, net, etc.) that "
                    f"are statically compiled "
                    f"into every Go binary. "
                    f"{stdlib_count} .go files "
                    f"compiled into "
                    f"{self.binary_name}."
                ),
                "sourceInfo": (
                    f"Bundled with Go toolchain "
                    f"{go_ver}. Source at "
                    f"/usr/local/go/src/."
                ),
            }
            doc["packages"].append(stdlib_pkg)
            doc["relationships"].append({
                "spdxElementId": root_id,
                "relationshipType": DEPENDS_ON,
                "relatedSpdxElement": stdlib_id,
            })

        # GCC as build tool (always present for
        # C/C++; also present for Go CGo builds)
        gcc_id = self._next_spdx_id("gcc")
        gcc_ver_clean = re.search(
            r"(\d+\.\d+\.\d+)", self.gcc_version
        )
        gcc_ver = (
            gcc_ver_clean.group(1)
            if gcc_ver_clean
            else self.gcc_version
        )
        gcc_pkg = {
            "SPDXID": gcc_id,
            "name": "gcc",
            "versionInfo": gcc_ver,
            "supplier": (
                "Organization: "
                "Free Software Foundation"
            ),
            "downloadLocation": "https://gcc.gnu.org/",
            "homepage": "https://gcc.gnu.org/",
            "filesAnalyzed": False,
            "primaryPackagePurpose": "APPLICATION",
            "externalRefs": [{
                "referenceCategory": "SECURITY",
                "referenceType": "cpe23Type",
                "referenceLocator": (
                    f"cpe:2.3:a:gnu:gcc:{gcc_ver}"
                    f":*:*:*:*:*:*:*"
                ),
            }],
            "sourceInfo": (
                f"System-installed build toolchain "
                f"on {self.distro}."
            ),
        }
        doc["packages"].append(gcc_pkg)
        doc["relationships"].append({
            "spdxElementId": gcc_id,
            "relationshipType": BUILD_TOOL_OF,
            "relatedSpdxElement": root_id,
        })

        # --- Vendored (statically linked) packages ---
        vendored, own_files = (
            self._detect_vendored_groups(
                project_files
            )
        )
        ver_detector = VendoredVersionDetector()
        # Parse Go modules.txt for versions
        go_mod_versions = self._parse_go_modules_txt(
            project_files
        )
        # Parse go.mod for direct vs indirect
        go_mod_indirect = self._parse_go_mod(
            project_files
        )
        # Parse Cargo.lock for Rust crate versions
        cargo_lock_versions = self._parse_cargo_lock(
            project_files,
            repos_dir=self.repos_dir,
            repo_name=self.repo_name,
        )
        # Parse Cargo.toml for direct Rust deps
        cargo_toml_direct = self._parse_cargo_toml(
            project_files,
            repos_dir=self.repos_dir,
            repo_name=self.repo_name,
        )
        # Map vendored lib name -> SPDX package ID
        vendored_pkg_ids = {}
        for lib_name in sorted(vendored.keys()):
            safe_name = self._sanitize_spdx_id(
                lib_name
            )
            pkg_id = self._next_spdx_id(safe_name)
            vendored_pkg_ids[lib_name] = pkg_id

            file_paths = [
                a["file_path"]
                for a in vendored[lib_name]
            ]
            is_go_module = (
                "." in lib_name.split("/")[0]
                and any(
                    fp.endswith(".go")
                    for fp in file_paths
                )
            )
            is_rust_crate = any(
                fp.endswith(".rs")
                for fp in file_paths
            )
            src_exts = (
                (".go",)
                if is_go_module
                else (".rs",)
                if is_rust_crate
                else (
                    ".c", ".h", ".s", ".inc",
                    ".cc", ".cpp", ".cxx", ".hpp",
                )
            )
            src_count = len([
                fp for fp in file_paths
                if Path(fp).suffix.lower()
                in src_exts
            ])

            if is_go_module:
                dl = (
                    f"https://pkg.go.dev/{lib_name}"
                )
                is_indirect = (
                    lib_name in go_mod_indirect
                )
                src_info = (
                    "Indirect dependency "
                    "vendored via go mod vendor."
                    if is_indirect
                    else
                    "Vendored via go mod vendor. "
                    f"Source at vendor/{lib_name}/."
                )
                if is_indirect:
                    dep_detail = (
                        "Go module (indirect). "
                        "Transitive dependency — "
                        "not listed directly in "
                        "go.mod; pulled in by a "
                        "direct dependency. "
                        "Identified by '// indirect'"
                        " comment in go.mod require "
                        "block."
                    )
                else:
                    dep_detail = (
                        "Go module (direct). "
                        "Explicitly listed in "
                        "go.mod require block "
                        "without '// indirect' "
                        "comment — this project "
                        "imports it directly."
                    )
                pkg = {
                    "SPDXID": pkg_id,
                    "name": lib_name,
                    "downloadLocation": dl,
                    "filesAnalyzed": True,
                    "primaryPackagePurpose":
                        "LIBRARY",
                    "externalRefs": [],
                    "comment": (
                        f"{dep_detail} "
                        f"{src_count} source files "
                        f"compiled into "
                        f"{self.binary_name}."
                    ),
                    "sourceInfo": src_info,
                }
            elif is_rust_crate:
                dl = (
                    f"https://crates.io/crates/"
                    f"{lib_name}"
                )
                is_direct_crate = (
                    not cargo_toml_direct
                    or lib_name in cargo_toml_direct
                )
                crate_kind = (
                    "direct" if is_direct_crate
                    else "transitive"
                )
                src_info = (
                    "Downloaded from crates.io "
                    "registry. Source at "
                    "~/.cargo/registry/src/."
                    if is_direct_crate
                    else
                    "Transitive dependency via "
                    "Cargo. Downloaded from "
                    "crates.io registry."
                )
                pkg = {
                    "SPDXID": pkg_id,
                    "name": lib_name,
                    "downloadLocation": dl,
                    "filesAnalyzed": True,
                    "primaryPackagePurpose":
                        "LIBRARY",
                    "externalRefs": [],
                    "comment": (
                        f"Rust crate ({crate_kind}, "
                        f"statically linked). "
                        f"{src_count} source files "
                        f"compiled into "
                        f"{self.binary_name}"
                    ),
                    "sourceInfo": src_info,
                }
            else:
                # Determine vendored dir pattern
                vdir_label = "deps"
                sample_fp = file_paths[0] if (
                    file_paths
                ) else ""
                for vd in self._vendored_dirs:
                    if vd in sample_fp:
                        vdir_label = (
                            vd.strip("/")
                            .split("/")[-1]
                        )
                        break
                pkg = {
                    "SPDXID": pkg_id,
                    "name": lib_name,
                    "downloadLocation":
                        "NOASSERTION",
                    "filesAnalyzed": True,
                    "primaryPackagePurpose":
                        "LIBRARY",
                    "externalRefs": [],
                    "comment": (
                        f"Vendored source compiled "
                        f"into {self.binary_name}. "
                        f"{src_count} source files."
                    ),
                    "sourceInfo": (
                        f"Vendored from "
                        f"{self.repo_name}/"
                        f"{vdir_label}/{lib_name}/. "
                        f"Source compiled into "
                        f"static archive and linked."
                    ),
                }

            # Detect version: Cargo.lock / Go
            # modules.txt first, then C/C++ header
            # detection, then sub-component fallback
            ver = cargo_lock_versions.get(lib_name)
            if not ver:
                ver = go_mod_versions.get(lib_name)
            if not ver:
                ver = ver_detector.detect(
                    lib_name, file_paths
                )
            if not ver:
                sub_vers = getattr(
                    self, "_sub_versions", {}
                )
                ver = sub_vers.get(lib_name)
            if ver:
                pkg["versionInfo"] = ver

            # Add PURL for Go modules and Rust crates
            if is_go_module and ver:
                purl = (
                    f"pkg:golang/{lib_name}"
                    f"@{ver}"
                )
                pkg["externalRefs"].append({
                    "referenceCategory":
                        "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": purl,
                })
            elif is_rust_crate and ver:
                purl = (
                    f"pkg:cargo/{lib_name}"
                    f"@{ver}"
                )
                pkg["externalRefs"].append({
                    "referenceCategory":
                        "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": purl,
                })

            doc["packages"].append(pkg)

            # Determine relationship type:
            # - Go modules: DEPENDS_ON (all)
            # - Rust crates: STATIC_LINK (all —
            #   every crate is statically compiled
            #   into the binary)
            # - C/C++ vendored: STATIC_LINK +
            #   CONTAINS (source tree containment)
            # A package is vendored only if its
            # source files actually reside under a
            # vendored directory pattern (not just
            # because it's non-Go / non-Rust).
            is_vendored = (
                not is_go_module
                and not is_rust_crate
                and any(
                    vd in fp_
                    for fp_ in file_paths
                    for vd in self._vendored_dirs
                )
            )
            if is_go_module:
                rel_type = DEPENDS_ON
            elif is_rust_crate:
                rel_type = STATIC_LINK
            else:
                rel_type = STATIC_LINK
            doc["relationships"].append({
                "spdxElementId": root_id,
                "relationshipType": rel_type,
                "relatedSpdxElement": pkg_id,
            })

            # Vendored source: also emit CONTAINS
            # to indicate source tree containment.
            # This is distinct from STATIC_LINK
            # (binary linkage) — both are needed
            # for vulnerability tracking.
            if is_vendored:
                doc["relationships"].append({
                    "spdxElementId": root_id,
                    "relationshipType": CONTAINS,
                    "relatedSpdxElement": pkg_id,
                })

        # --- Project source files ---
        all_source = (
            [(art, None) for art in own_files]
            + [
                (art, lib)
                for lib, arts in vendored.items()
                for art in arts
            ]
        )
        for art, vendored_lib in all_source:
            fp = art["file_path"]
            # Only include source files
            ext = Path(fp).suffix.lower()
            if ext not in (
                ".c", ".h", ".s", ".inc",
                ".cc", ".cpp", ".cxx", ".hpp",
                ".go", ".rs",
            ):
                continue

            safe = self._sanitize_spdx_id(
                Path(fp).name
            )
            file_id = self._next_spdx_id(
                f"File-{safe}"
            )
            # Make path relative to repo
            rel_path = fp
            try:
                rel_path = str(
                    Path(fp).relative_to(
                        Path(fp).parents[
                            len(Path(fp).parts) - 3
                        ]
                    )
                )
            except (ValueError, IndexError):
                pass

            # SPDX 2.3 File checksums: the spec-mandated raw SHA-1
            # (Clause 8.4, Table 39) plus the raw SHA-256 identity
            # hash.  The SHA-1 is a legacy corruption checksum, not
            # an identity value; SPDX 3.x drops it (see
            # spdx_2_3_file_checksums and artifact-identity.md).
            # bomsh's SHA-1 git-blob treedb key is topology only and
            # is never surfaced here.
            file_entry = {
                "SPDXID": file_id,
                "fileName": rel_path,
                "checksums": spdx_2_3_file_checksums(fp),
            }
            doc["files"].append(file_entry)

            # Vendored files belong to their
            # library package; others to root
            owner_id = (
                vendored_pkg_ids[vendored_lib]
                if vendored_lib
                else root_id
            )
            doc["relationships"].append({
                "spdxElementId": owner_id,
                "relationshipType": CONTAINS,
                "relatedSpdxElement": file_id,
            })

        # --- Analyzed SBOM post-processing ---
        # When static_only (CISA Analyzed), strip
        # all BUILD_TOOL_OF relationships and their
        # orphaned packages. Build tools weren't
        # compiled into the binary.
        if static_only:
            build_tool_ids = {
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
            # IDs still referenced by other rels
            still_used = set()
            for r in doc["relationships"]:
                still_used.add(r["spdxElementId"])
                still_used.add(
                    r["relatedSpdxElement"]
                )
            orphans = (
                build_tool_ids - still_used
            )
            if orphans:
                doc["packages"] = [
                    p for p in doc["packages"]
                    if p["SPDXID"] not in orphans
                ]

        return doc
