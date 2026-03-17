"""
SPDX Emitter — produces SPDX 2.3 JSON from resolved components.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.version_detection import VendoredVersionDetector


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
        "https://omnibor.io/omnibor-analysis"
    )

    def __init__(
        self, repo_name, repo_version,
        distro, gcc_version,
        bomtrace_version="unknown",
        bomsh_version="unknown",
        binary_name=None,
        vendored_dirs=None,
        repos_dir=None,
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
        self._spdx_id_counter = 0
        self._sub_versions = {}
        if vendored_dirs is not None:
            self._vendored_dirs = tuple(
                vendored_dirs
            )
        else:
            self._vendored_dirs = self.VENDORED_DIRS

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
    VENDORED_DIRS = (
        "/deps/", "/vendor/", "/third_party/",
        "/thirdparty/", "/external/", "/contrib/",
    )

    # Regex for #define PREFIX_VERSION "x.y.z"
    # Captures (prefix, version_string)
    _SUB_VERSION_RE = re.compile(
        r'#define\s+(\w+?)_VERSION\s+'
        r'"[^"]*?(\d+\.\d+(?:\.\d+)?)'
    )

    # Regex to extract Go version from build commands
    _GO_VERSION_RE = re.compile(
        r"-goversion\s+(go\d+\.\d+(?:\.\d+)?)"
    )

    @staticmethod
    def _detect_go_version(go_stdlib):
        """Detect Go version from stdlib or install.

        Strategy:
          1. Look for -goversion flag in build commands
          2. Read /usr/local/go/VERSION file
          3. Fall back to 'unknown'
        """
        for art in go_stdlib:
            cmd = art.get("build_cmd", "")
            m = SpdxEmitter._GO_VERSION_RE.search(cmd)
            if m:
                return m.group(1).lstrip("go")
        # Fallback: read Go VERSION file
        ver_file = Path("/usr/local/go/VERSION")
        if ver_file.exists():
            # File is multi-line: "go1.26.0\ntime ..."
            first_line = (
                ver_file.read_text().splitlines()[0]
            )
            return first_line.strip().lstrip("go")
        return "unknown"

    # Well-known Go module hosting prefixes that use
    # three path segments: host/owner/repo
    _GO_THREE_SEGMENT_HOSTS = (
        "github.com", "gitlab.com", "bitbucket.org",
        "golang.org",
    )

    # Regex matching Go major-version suffix /vN (N>=2)
    _GO_MAJOR_VER_RE = re.compile(r"^v\d+$")

    @staticmethod
    def _go_module_from_vendor_path(rest):
        """Extract Go module name from vendor-relative path.

        Go modules under vendor/ have multi-segment names:
          github.com/fatih/color/color.go      -> github.com/fatih/color
          github.com/gdamore/tcell/v2/foo.go   -> github.com/gdamore/tcell/v2
          golang.org/x/sys/unix/syscall.go     -> golang.org/x/sys
          dario.cat/mergo/merge.go             -> dario.cat/mergo
          gopkg.in/yaml.v3/yaml.go             -> gopkg.in/yaml.v3
          gopkg.in/ozeidan/fuzzy-patricia.v3/
            -> gopkg.in/ozeidan/fuzzy-patricia.v3

        Rules:
          - github.com, gitlab.com, bitbucket.org,
            golang.org -> 3 segments (+ optional /vN)
          - gopkg.in -> 2 or 3 segments depending on
            whether second segment has a dot
          - Everything else -> 2 segments
          - Must contain a dot in first segment (domain)
          - /vN suffix (N>=2) appended when present
        """
        parts = rest.split("/")
        if len(parts) < 2:
            return None
        # First segment must look like a domain
        if "." not in parts[0]:
            return None

        # gopkg.in special handling:
        #   gopkg.in/yaml.v3     -> 2 segments
        #   gopkg.in/ozeidan/... -> 3 segments
        if parts[0] == "gopkg.in":
            # If second segment contains a dot
            # (e.g. yaml.v3), it's a 2-segment module
            if "." in parts[1]:
                return "/".join(parts[:2])
            if len(parts) >= 3:
                return "/".join(parts[:3])
            return None

        if parts[0] in SpdxEmitter._GO_THREE_SEGMENT_HOSTS:
            if len(parts) < 3:
                return None
            base = "/".join(parts[:3])
            # Append /vN major version suffix if present
            if (
                len(parts) >= 4
                and SpdxEmitter._GO_MAJOR_VER_RE.match(
                    parts[3]
                )
            ):
                return base + "/" + parts[3]
            return base
        # Other domains: 2 segments
        return "/".join(parts[:2])

    _CARGO_REGISTRY_RE = re.compile(
        r"/.cargo/registry/src/[^/]+/"
        r"([a-zA-Z0-9_-]+)-(\d+\.\d+\.\d+[^/]*)"
        r"/"
    )

    @classmethod
    def _rust_crate_from_registry_path(cls, fp):
        """Extract (crate_name, version) from a Cargo
        registry source path.

        Paths look like:
          /root/.cargo/registry/src/index.crates.io-*/
            bitvec-1.0.1/src/lib.rs

        Returns (crate_name, version) or (None, None).
        """
        m = cls._CARGO_REGISTRY_RE.search(fp)
        if m:
            return m.group(1), m.group(2)
        return None, None

    @staticmethod
    def _parse_cargo_lock(
        project_files, repos_dir=None,
        repo_name=None,
    ):
        """Parse Cargo.lock for crate versions.

        Returns dict: crate_name -> version string.

        Cargo.lock format:
          [[package]]
          name = "bitvec"
          version = "1.0.1"

        Searches for Cargo.lock in two ways:
        1. Directly in repos_dir/repo_name/
        2. Walking up from each project file path
        """
        versions = {}
        if not project_files:
            return versions

        # Build list of candidate Cargo.lock paths
        candidates = []
        if repos_dir and repo_name:
            candidates.append(
                Path(repos_dir) / repo_name
                / "Cargo.lock"
            )
        for pf in project_files:
            p = Path(pf["file_path"])
            while p.parent != p:
                candidates.append(
                    p / "Cargo.lock"
                )
                p = p.parent

        for lock_file in candidates:
            if lock_file.exists():
                name = None
                for line in (
                    lock_file.read_text()
                    .splitlines()
                ):
                    line = line.strip()
                    if line.startswith(
                        "name = "
                    ):
                        name = line.split(
                            '"'
                        )[1]
                    elif (
                        line.startswith(
                            "version = "
                        )
                        and name
                    ):
                        ver = line.split(
                            '"'
                        )[1]
                        versions[name] = ver
                        name = None
                return versions
        return versions

    @staticmethod
    def _parse_cargo_toml(
        project_files, repos_dir=None,
        repo_name=None,
    ):
        """Parse Cargo.toml for direct dependency names.

        Returns set of crate names that are direct
        dependencies (listed under [dependencies] or
        [target.*.dependencies]).

        Cargo.toml format (simplified):
          [dependencies]
          clap = "4.5"
          rayon = { version = "1.10" }
        """
        direct = set()
        if not project_files:
            return direct

        candidates = []
        if repos_dir and repo_name:
            candidates.append(
                Path(repos_dir) / repo_name
                / "Cargo.toml"
            )
        for pf in project_files:
            p = Path(pf["file_path"])
            while p.parent != p:
                candidates.append(
                    p / "Cargo.toml"
                )
                p = p.parent

        for toml_file in candidates:
            if toml_file.exists():
                in_deps = False
                for line in (
                    toml_file.read_text()
                    .splitlines()
                ):
                    stripped = line.strip()
                    if stripped.startswith("["):
                        in_deps = (
                            "dependencies" in stripped
                            and "dev" not in stripped
                            and "build" not in stripped
                        )
                        continue
                    if in_deps and "=" in stripped:
                        name = stripped.split(
                            "="
                        )[0].strip()
                        # Normalize: Cargo.toml uses
                        # hyphens, Cargo.lock uses
                        # either form
                        direct.add(name)
                        direct.add(
                            name.replace("-", "_")
                        )
                        direct.add(
                            name.replace("_", "-")
                        )
                return direct
        return direct

    @staticmethod
    def _parse_go_mod(project_files):
        """Parse go.mod for direct vs indirect deps.

        Returns set of indirect module paths.
        Modules NOT in the set are direct deps.
        Lines with '// indirect' are indirect.
        """
        indirect = set()
        if not project_files:
            return indirect
        sample = project_files[0]["file_path"]
        p = Path(sample)
        while p.parent != p:
            go_mod = p / "go.mod"
            if go_mod.exists():
                for line in go_mod.read_text(
                ).splitlines():
                    line = line.strip()
                    if "// indirect" in line:
                        tokens = line.split()
                        if tokens and (
                            tokens[0] != "require"
                            and tokens[0] != "//"
                            and tokens[0] != "("
                        ):
                            indirect.add(tokens[0])
                return indirect
            p = p.parent
        return indirect

    @staticmethod
    def _parse_go_modules_txt(project_files):
        """Parse vendor/modules.txt for module versions.

        Returns dict: module_path -> version string.
        Lines like: # github.com/fatih/color v1.16.0
        """
        versions = {}
        # Find a project file path to locate the repo root
        if not project_files:
            return versions
        sample = project_files[0]["file_path"]
        # Walk up to find vendor/modules.txt
        p = Path(sample)
        while p.parent != p:
            modules_txt = p / "vendor" / "modules.txt"
            if modules_txt.exists():
                for line in modules_txt.read_text(
                ).splitlines():
                    if line.startswith("# "):
                        tokens = line[2:].split()
                        if len(tokens) >= 2:
                            versions[tokens[0]] = (
                                tokens[1].lstrip("v")
                            )
                return versions
            p = p.parent
        return versions

    def _detect_vendored_groups(self, project_files):
        """Group source files by vendored library.

        Scans project_files for paths matching
        VENDORED_DIRS patterns, then splits out
        embedded sub-components that declare their
        own version identifiers.

        For Go vendor directories, extracts full
        Go module names (e.g. github.com/fatih/color)
        instead of just the first path component.

        Returns:
          vendored: dict[lib_name] -> list[artifact]
          own: list[artifact]  (non-vendored)

        Side-effect: populates self._sub_versions
        with {lib_name: version} for sub-components
        whose version was found during splitting.
        """
        vendored = {}
        own = []
        for art in project_files:
            # Normalize path to resolve ../ components
            # (e.g. /libnetutil/../nbase/x.h -> /nbase/x.h)
            fp = str(Path(art["file_path"]).resolve())
            matched = False
            # Try Rust crate from Cargo registry first
            crate_name, _ = (
                self._rust_crate_from_registry_path(fp)
            )
            if crate_name:
                vendored.setdefault(
                    crate_name, []
                ).append(art)
                continue
            for vdir in self._vendored_dirs:
                idx = fp.find(vdir)
                if idx < 0:
                    continue
                rest = fp[idx + len(vdir):]
                # Try Go module extraction first
                go_mod = self._go_module_from_vendor_path(
                    rest
                )
                if go_mod:
                    vendored.setdefault(
                        go_mod, []
                    ).append(art)
                    matched = True
                    break
                # C/C++ fallback: generic patterns use
                # first component; specific dirs use
                # the directory name itself
                if vdir in self.VENDORED_DIRS:
                    lib = rest.split("/")[0]
                else:
                    lib = (
                        vdir.strip("/").split("/")[-1]
                    )
                if lib:
                    vendored.setdefault(
                        lib, []
                    ).append(art)
                    matched = True
                    break
            if not matched:
                own.append(art)

        # Split out sub-components (C/C++ only)
        vendored, self._sub_versions = (
            self._split_sub_components(vendored)
        )
        return vendored, own

    def _split_sub_components(self, vendored):
        """Split embedded sub-libraries out of
        vendored groups.

        Scans .c files in each vendored group for
        #define PREFIX_VERSION "x.y.z" where PREFIX
        does not match the parent library name.
        Files whose basename matches the sub-component
        prefix are moved to a new group.

        Example: deps/lua/src/lua_cjson.c defines
        CJSON_VERSION "2.1.0" -> split into a new
        "lua-cjson" group.

        Returns:
            (result, versions) where result is the
            updated vendored dict and versions is
            {full_name: version} for sub-components.
        """
        result = {}
        versions = {}
        for lib_name, arts in vendored.items():
            parent_prefix = (
                lib_name.upper()
                .replace("-", "_")
                .replace(".", "_")
            )
            sub_map = {}  # key -> (name, ver, [arts])
            remaining = []

            for art in arts:
                fp = art["file_path"]
                ext = Path(fp).suffix.lower()
                if ext not in (".c", ".h"):
                    remaining.append(art)
                    continue

                sub = self._detect_sub_component(
                    fp, parent_prefix
                )
                if sub:
                    sub_name, sub_ver = sub
                    key = sub_name.lower()
                    if key not in sub_map:
                        sub_map[key] = (
                            sub_name, sub_ver, []
                        )
                    sub_map[key][2].append(art)
                else:
                    remaining.append(art)

            # Assign remaining files that match a
            # sub-component by basename prefix
            still_remaining = []
            for art in remaining:
                basename = Path(
                    art["file_path"]
                ).stem.lower()
                assigned = False
                for key in sub_map:
                    if key in basename:
                        sub_map[key][2].append(art)
                        assigned = True
                        break
                if not assigned:
                    still_remaining.append(art)

            # Keep parent group with remaining files
            if still_remaining:
                result[lib_name] = still_remaining

            # Add sub-component groups
            for key, (name, ver, sub_arts) in (
                sub_map.items()
            ):
                full_name = f"{lib_name}-{name}"
                result[full_name] = sub_arts
                if ver:
                    versions[full_name] = ver

        return result, versions

    def _detect_sub_component(
        self, file_path, parent_prefix
    ):
        """Check if a source file defines its own
        version distinct from the parent library.

        Returns (sub_name, version) or None.
        """
        try:
            text = Path(file_path).read_text(
                errors="replace"
            )
        except OSError:
            return None

        for m in self._SUB_VERSION_RE.finditer(text):
            prefix = m.group(1)
            version = m.group(2)
            norm = prefix.upper().replace(
                "-", "_"
            )
            # Skip if this is the parent lib's own
            # version define (e.g. LUA_VERSION,
            # LUA_VERSION_NUM) but NOT a different
            # library that starts with the parent
            # name (e.g. LUA_BITOP is lua-bitop)
            if norm == parent_prefix:
                continue
            # Skip generic names
            if norm in (
                "VERSION", "LIB", "PACKAGE",
                "MODULE",
            ):
                continue
            # Derive readable name from prefix
            name = prefix.lower().replace("_", "-")
            # Strip leading "lua-" etc. if parent
            # is already in the name
            lp = parent_prefix.lower()
            if name.startswith(lp + "-"):
                name = name[len(lp) + 1:]
            return (name, version)

        return None

    def emit(
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
            doc_mapping: sha1 -> omnibor_doc_id
            logfile_hashes: file_path -> build-time sha1
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
                    "Tool: omnibor-analysis"
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
            "downloadLocation": "NOASSERTION",
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

        # Add OmniBOR ref for root binary
        for bin_path, sha1 in (
            logfile_hashes.items()
        ):
            basename = Path(bin_path).name
            if basename == self.binary_name:
                omnibor_id = doc_mapping.get(sha1)
                if omnibor_id:
                    root_pkg["externalRefs"].append({
                        "referenceCategory":
                            "PERSISTENT-ID",
                        "referenceType": "gitoid",
                        "referenceLocator":
                            f"gitoid:blob:sha1:"
                            f"{omnibor_id}",
                    })
                root_pkg["checksums"].append({
                    "algorithm": "SHA1",
                    "checksumValue": sha1,
                })
                break

        doc["packages"].append(root_pkg)

        # DESCRIBES relationship
        doc["relationships"].append({
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
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
                        "packageSourceInfo": (
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
                    pkg["packageSourceInfo"] = (
                        f"Installed via dpkg package "
                        f"{dpkg_desc} on "
                        f"{self.distro}."
                    )

                doc["packages"].append(pkg)

                # DYNAMIC_LINK from root
                doc["relationships"].append({
                    "spdxElementId": root_id,
                    "relationshipType":
                        "DYNAMIC_LINK",
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
                "packageSourceInfo": (
                    "System-installed Go toolchain "
                    "at /usr/local/go/."
                ),
            }
            doc["packages"].append(go_pkg)
            doc["relationships"].append({
                "spdxElementId": go_id,
                "relationshipType": "BUILD_TOOL_OF",
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
                    f"Go standard library. "
                    f"{stdlib_count} .go files "
                    f"compiled into "
                    f"{self.binary_name}"
                ),
                "packageSourceInfo": (
                    f"Bundled with Go toolchain "
                    f"{go_ver}. Source at "
                    f"/usr/local/go/src/."
                ),
            }
            doc["packages"].append(stdlib_pkg)
            doc["relationships"].append({
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
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
            "packageSourceInfo": (
                f"System-installed build toolchain "
                f"on {self.distro}."
            ),
        }
        doc["packages"].append(gcc_pkg)
        doc["relationships"].append({
            "spdxElementId": gcc_id,
            "relationshipType": "BUILD_TOOL_OF",
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
                dep_kind = (
                    "indirect" if is_indirect
                    else "direct"
                )
                src_info = (
                    "Indirect dependency "
                    "vendored via go mod vendor."
                    if is_indirect
                    else
                    "Vendored via go mod vendor. "
                    f"Source at vendor/{lib_name}/."
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
                        f"Go module ({dep_kind}). "
                        f"{src_count} source files "
                        f"compiled into "
                        f"{self.binary_name}"
                    ),
                    "packageSourceInfo": src_info,
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
                    "packageSourceInfo": src_info,
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
                    "packageSourceInfo": (
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
            # - Rust crates: STATIC_LINK (direct),
            #   DEPENDS_ON (transitive)
            # - C/C++ vendored: STATIC_LINK +
            #   CONTAINS (source tree containment)
            is_vendored = (
                not is_go_module
                and not is_rust_crate
            )
            if is_go_module:
                rel_type = "DEPENDS_ON"
            elif is_rust_crate:
                if (
                    cargo_toml_direct
                    and lib_name
                    not in cargo_toml_direct
                ):
                    rel_type = "DEPENDS_ON"
                else:
                    rel_type = "STATIC_LINK"
            else:
                rel_type = "STATIC_LINK"
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
                    "relationshipType": "CONTAINS",
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

            file_entry = {
                "SPDXID": file_id,
                "fileName": rel_path,
                "checksums": [{
                    "algorithm": "SHA1",
                    "checksumValue": art["sha1"],
                }],
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
                "relationshipType": "CONTAINS",
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
                == "BUILD_TOOL_OF"
            }
            doc["relationships"] = [
                r for r in doc["relationships"]
                if r["relationshipType"]
                != "BUILD_TOOL_OF"
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
