#!/usr/bin/env python3
"""
Generate a complete SPDX 2.3 JSON document from OmniBOR ADG data.

Reads the bomsh treedb, doc_mapping, raw logfile, and
component_metadata.json (produced by collect_metadata.py) to
build an SPDX SBOM that accurately represents every component
compiled into the target binary.

Each upstream source package (e.g. openssl, zlib, brotli) becomes
an SPDX Package with:
  - name, version, supplier, homepage
  - PURL (pkg:deb/ubuntu/...)
  - CPE 2.3 identifier
  - OmniBOR ExternalRef (gitoid) where available
  - DEPENDS_ON relationship from the main binary package

The target binary itself is the root package with its OmniBOR
ExternalRef and a CONTAINS relationship to its source files.

Usage (standalone):

    python3 spdx_from_adg.py \\
        --bom-dir /output/omnibor/curl \\
        --repos-dir /workspace/repos \\
        --repo-name curl \\
        --output /output/spdx/curl/curl_adg.spdx.json

Classes:

    - AdgParser: reads treedb and classifies artifacts
    - ComponentResolver: maps artifacts to named components
    - SpdxEmitter: produces SPDX 2.3 JSON from resolved data
    - AdgSpdxGenerator: facade orchestrating the pipeline
"""

import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# ADG Parser
# ============================================================

class AdgParser:
    """Parse bomsh treedb and classify artifacts.

    Artifact categories:
      - system_lib: shared libraries under /usr/lib
      - system_header: headers under /usr/include
      - project_source: files under the project repo
      - build_intermediate: .o files under the project repo
      - crt_object: C runtime objects (crt*.o)
    """

    def __init__(self, bom_dir, repos_dir):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.meta_dir = (
            self.bom_dir / "metadata" / "bomsh"
        )

    def parse(self):
        """Return classified artifacts dict.

        Keys: system_lib, system_header,
              project_source, build_intermediate,
              crt_object.
        Each value is a list of dicts with keys:
          sha1, file_path, build_cmd (if present).
        """
        treedb_path = (
            self.meta_dir / "bomsh_omnibor_treedb"
        )
        treedb = json.loads(treedb_path.read_text())

        classified = {
            "system_lib": [],
            "system_header": [],
            "project_source": [],
            "build_intermediate": [],
            "crt_object": [],
            "go_stdlib": [],
        }

        go_stdlib_prefix = "/usr/local/go/src/"

        for sha1, entry in treedb.items():
            fp = entry.get("file_path", "")
            if not fp:
                continue

            item = {
                "sha1": sha1,
                "file_path": fp,
            }
            if "build_cmd" in entry:
                item["build_cmd"] = entry["build_cmd"]

            if fp.startswith(go_stdlib_prefix):
                classified["go_stdlib"].append(item)
            elif fp.startswith("/usr/lib"):
                base = Path(fp).name
                if base.startswith("crt") and (
                    base.endswith(".o")
                ):
                    classified["crt_object"].append(
                        item
                    )
                elif base.endswith(".so") or (
                    ".so." in base
                ):
                    classified["system_lib"].append(
                        item
                    )
                else:
                    # Static libs, other objects
                    classified["system_lib"].append(
                        item
                    )
            elif fp.startswith("/usr/include"):
                classified["system_header"].append(
                    item
                )
            elif fp.startswith(str(self.repos_dir)):
                if fp.endswith(".o"):
                    classified[
                        "build_intermediate"
                    ].append(item)
                else:
                    classified[
                        "project_source"
                    ].append(item)
            elif "/.cargo/registry/src/" in fp:
                # Rust crate sources from Cargo registry
                classified[
                    "project_source"
                ].append(item)
            else:
                # Other system files (incl. /tmp/go-build)
                classified["system_header"].append(
                    item
                )

        return classified

    def load_doc_mapping(self):
        """Return dict: sha1 -> omnibor_doc_id."""
        path = (
            self.meta_dir / "bomsh_omnibor_doc_mapping"
        )
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def load_raw_logfile_hashes(self):
        """Return dict: file_path -> build-time sha1."""
        path = (
            self.meta_dir / "bomsh_hook_raw_logfile"
        )
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text(
            errors="replace"
        ).splitlines():
            m = re.match(
                r"^outfile:\s+([0-9a-f]{40})"
                r"\s+path:\s+(.+)$",
                line,
            )
            if m:
                result[m.group(2)] = m.group(1)
        return result


# ============================================================
# Component Resolver
# ============================================================

class ComponentResolver:
    """Resolve artifacts to named software components.

    Uses component_metadata.json (from collect_metadata.py)
    and dynamic_libs.json (from collect_dynamic_libs.py)
    to identify runtime dependencies with full metadata.
    """

    def __init__(self, metadata_path):
        self.metadata = json.loads(
            Path(metadata_path).read_text()
        )
        self._dynamic_libs = None

    @property
    def distro(self):
        return self.metadata.get("distro", "unknown")

    @property
    def distro_codename(self):
        """Extract distro version for PURL qualifier."""
        d = self.distro.lower()
        # "Ubuntu 22.04.5 LTS" -> "ubuntu-22.04"
        m = re.search(r"ubuntu\s+([\d.]+)", d)
        if m:
            # Use major.minor only
            parts = m.group(1).split(".")
            ver = ".".join(parts[:2])
            return f"ubuntu-{ver}"
        return "linux"

    @property
    def gcc_version(self):
        return self.metadata.get(
            "gcc_version", "unknown"
        )

    @property
    def curl_version(self):
        return self.metadata.get(
            "curl_version", "unknown"
        )

    def load_dynamic_libs(self, path):
        """Load dynamic_libs.json."""
        self._dynamic_libs = json.loads(
            Path(path).read_text()
        )

    def resolve_dynamic_components(self):
        """Resolve dynamic libraries to components.

        Groups libraries by upstream source package.
        Each component has:
          name, version, supplier, homepage,
          dpkg_packages, architecture, purl, cpe23,
          sonames, direct (bool).
        """
        if not self._dynamic_libs:
            return []

        libs = self._dynamic_libs.get(
            "dynamic_libs", {}
        )

        # Group by upstream source
        source_groups = {}
        for soname, info in libs.items():
            meta = info.get("metadata", {})
            source = info.get("source", soname)
            if not meta.get("Version"):
                continue
            if source not in source_groups:
                source_groups[source] = {
                    "meta": meta,
                    "sonames": [],
                    "direct": False,
                    "dpkg_packages": set(),
                }
            source_groups[source][
                "sonames"
            ].append(soname)
            if info.get("direct"):
                source_groups[source][
                    "direct"
                ] = True
            dpkg = info.get("dpkg_package")
            if dpkg:
                source_groups[source][
                    "dpkg_packages"
                ].add(dpkg)

        components = []
        for source, group in sorted(
            source_groups.items()
        ):
            meta = group["meta"]
            version = meta.get("Version", "unknown")
            arch = meta.get(
                "Architecture", "amd64"
            )
            dpkg_pkgs = sorted(
                group["dpkg_packages"]
            )
            dpkg_pkg = (
                dpkg_pkgs[0] if dpkg_pkgs
                else source
            )
            cpe_ver = self._clean_version(version)

            comp = {
                "name": dpkg_pkg,
                "source": source,
                "version": version,
                "supplier": meta.get(
                    "Maintainer", "NOASSERTION"
                ),
                "homepage": meta.get(
                    "Homepage", "NOASSERTION"
                ),
                "dpkg_packages": dpkg_pkgs,
                "architecture": arch,
                "purl": self._make_purl(
                    dpkg_pkg, version, arch
                ),
                "cpe23": self._make_cpe(
                    source, cpe_ver
                ),
                "sonames": sorted(
                    group["sonames"]
                ),
                "direct": group["direct"],
            }
            components.append(comp)

        # Project-built shared libraries
        # (e.g. libavcodec.so built by FFmpeg)
        proj_libs = self._dynamic_libs.get(
            "project_built_libs", {}
        )
        for soname, info in sorted(
            proj_libs.items()
        ):
            name = info.get("name", soname)
            comp = {
                "name": name,
                "source": name,
                "sonames": [soname],
                "direct": info.get("direct", True),
                "project_built": True,
            }
            components.append(comp)

        return components

    def _clean_version(self, version):
        """Strip epoch, dfsg, ubuntu suffixes for CPE."""
        v = version
        # Remove epoch (e.g. "1:1.2.11...")
        if ":" in v:
            v = v.split(":", 1)[1]
        # Remove dfsg suffix
        v = re.sub(r"[.+]dfsg.*", "", v)
        # Remove ubuntu/build suffix
        v = re.sub(r"-\d+ubuntu.*", "", v)
        v = re.sub(r"-\d+build.*", "", v)
        v = re.sub(r"-\d+$", "", v)
        return v

    def _make_purl(self, dpkg_pkg, version, arch):
        """Generate Package URL."""
        distro = self.distro_codename
        return (
            f"pkg:deb/ubuntu/{dpkg_pkg}"
            f"@{version}"
            f"?arch={arch}&distro={distro}"
        )

    def _make_cpe(self, source, version):
        """Generate CPE 2.3 identifier."""
        # Normalize vendor: use source name as vendor
        vendor = source.replace("-", "_")
        product = source.replace("-", "_")
        return (
            f"cpe:2.3:a:{vendor}:{product}"
            f":{version}:*:*:*:*:*:*:*"
        )


# ============================================================
# Vendored Version Detector
# ============================================================

class VendoredVersionDetector:
    """Detect versions of vendored libraries from source.

    Scans vendored source directories for version info
    using common patterns:
      - VERSION files
      - #define macros (e.g. LIB_VERSION_MAJOR)
      - Header comment version strings
      - .pc.in / CMakeLists.txt / configure.ac
    """

    # Regex for semantic version: X.Y or X.Y.Z
    _VER_RE = re.compile(
        r"(\d+\.\d+(?:\.\d+)?)"
    )

    def detect(self, lib_name, file_paths):
        """Detect version for a vendored library.

        Args:
            lib_name: library name (e.g. "lua")
            file_paths: list of absolute file paths
                belonging to this vendored library

        Returns:
            version string or None
        """
        # Collect unique directories
        dirs = set()
        for fp in file_paths:
            p = Path(fp)
            dirs.add(p.parent)
            if p.parent.name == "src":
                dirs.add(p.parent.parent)

        # Strategy 1: VERSION file
        for d in sorted(dirs):
            vf = d / "VERSION"
            if vf.exists():
                v = self._parse_version_file(vf)
                if v:
                    return v

        # Strategy 2: header #define macros
        headers = [
            fp for fp in file_paths
            if fp.endswith(".h")
        ]
        for h in sorted(headers):
            v = self._parse_header_defines(
                h, lib_name
            )
            if v:
                return v

        # Strategy 3: header comment version
        for h in sorted(headers):
            v = self._parse_header_comment(h)
            if v:
                return v

        # Strategy 4: .pc.in files
        for d in sorted(dirs):
            for pc in sorted(d.glob("*.pc.in")):
                v = self._parse_pc_in(pc)
                if v:
                    return v

        return None

    def _parse_version_file(self, path):
        """Parse a VERSION file for semver."""
        try:
            text = path.read_text().strip()
            m = self._VER_RE.search(text)
            return m.group(1) if m else None
        except OSError:
            return None

    def _parse_header_defines(self, path, lib_name):
        """Parse #define VERSION macros.

        Looks for patterns like:
          #define LIB_MAJOR 1
          #define LIB_MINOR 2
          #define LIB_PATCH 0
        or:
          #define LIB_VERSION "1.2.0"
          #define LIB_RELEASE "Lib 1.2.0"
        """
        try:
            text = Path(path).read_text(
                errors="replace"
            )
        except OSError:
            return None

        # Normalize lib name for matching
        prefix = lib_name.upper().replace("-", "_")

        # Try single-line version string
        for pattern in [
            rf"#define\s+{prefix}_RELEASE\s+"
            rf'"[^"]*?({self._VER_RE.pattern})',
            rf"#define\s+{prefix}_VERSION\s+"
            rf'"({self._VER_RE.pattern})',
            rf"#define\s+\w*VERSION\w*\s+"
            rf'"[^"]*?({self._VER_RE.pattern})',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)

        # Try MAJOR/MINOR/PATCH defines
        major = minor = patch = None
        for line in text.splitlines():
            line = line.strip()
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?MAJOR\s+(\d+)",
                line,
            )
            if m:
                major = m.group(1)
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?MINOR\s+(\d+)",
                line,
            )
            if m:
                minor = m.group(1)
            m = re.match(
                r"#define\s+\w*"
                r"(?:VERSION_)?PATCH\s+(\d+)",
                line,
            )
            if m:
                patch = m.group(1)

        if major is not None and minor is not None:
            if patch is not None:
                return f"{major}.{minor}.{patch}"
            return f"{major}.{minor}"

        return None

    def _parse_header_comment(self, path):
        """Parse version from header comment block.

        Looks for patterns like:
          /* lib.h -- VERSION 1.0
        in the first 10 lines.
        """
        try:
            with open(
                str(path), errors="replace"
            ) as f:
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    m = re.search(
                        r"VERSION\s+"
                        rf"({self._VER_RE.pattern})",
                        line,
                        re.IGNORECASE,
                    )
                    if m:
                        return m.group(1)
        except OSError:
            pass
        return None

    def _parse_pc_in(self, path):
        """Parse Version: from .pc.in file."""
        try:
            for line in path.read_text(
                errors="replace"
            ).splitlines():
                m = re.match(
                    r"Version:\s*(.+)", line
                )
                if m:
                    val = m.group(1).strip()
                    vm = self._VER_RE.search(val)
                    if vm:
                        return vm.group(1)
        except OSError:
            pass
        return None


# ============================================================
# SPDX Emitter
# ============================================================

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
            fp = art["file_path"]
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
                library packages. Only include the root
                binary, vendored/static libs, and the
                build tool.
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
                }
            elif is_rust_crate:
                dl = (
                    f"https://crates.io/crates/"
                    f"{lib_name}"
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
                        f"Rust crate (statically "
                        f"linked). "
                        f"{src_count} source files "
                        f"compiled into "
                        f"{self.binary_name}"
                    ),
                }
            else:
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
                        f"Vendored/statically linked. "
                        f"{src_count} source files "
                        f"compiled into "
                        f"{self.binary_name}"
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

            # Go modules use DEPENDS_ON;
            # C/C++ vendored libs use STATIC_LINK
            rel_type = (
                "DEPENDS_ON"
                if is_go_module
                else "STATIC_LINK"
            )
            doc["relationships"].append({
                "spdxElementId": root_id,
                "relationshipType": rel_type,
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

        return doc


# ============================================================
# Facade
# ============================================================

class AdgSpdxGenerator:
    """Facade: generate per-binary SPDX from ADG data.

    Orchestrates AdgParser, ComponentResolver, and
    SpdxEmitter to produce one SPDX 2.3 JSON file per
    binary (e.g. curl, libcurl.so).
    """

    def __init__(
        self, bom_dir, repos_dir, repo_name,
        bomtrace_version="unknown",
        bomsh_version="unknown",
        vendored_dirs=None,
    ):
        self.bom_dir = Path(bom_dir)
        self.repos_dir = Path(repos_dir)
        self.repo_name = repo_name
        self.bomtrace_version = bomtrace_version
        self.bomsh_version = bomsh_version
        self.vendored_dirs = vendored_dirs

    def generate(
        self, output_path,
        binary_name=None,
        dynlib_dir=None,
        direct_only=False,
        static_only=False,
    ):
        """Generate SPDX for a single binary.

        Args:
            output_path: where to write the SPDX JSON
            binary_name: name of the binary
                (e.g. "curl" or "libcurl.so");
                defaults to repo_name
            dynlib_dir: path to directory containing
                dynamic_libs.json for this binary;
                defaults to bom_dir/metadata
            direct_only: if True, include only direct
                dependencies. Use when transitive deps
                belong to a downstream binary's SBOM.
            static_only: if True, omit dynamically
                linked library packages.

        Returns the output path on success, None on
        failure.
        """
        bin_name = binary_name or self.repo_name

        # Parse ADG for OmniBOR data
        parser = AdgParser(
            self.bom_dir, self.repos_dir
        )
        classified = parser.parse()
        doc_mapping = parser.load_doc_mapping()
        logfile_hashes = (
            parser.load_raw_logfile_hashes()
        )

        go_stdlib_count = len(
            classified.get("go_stdlib", [])
        )
        extra = (
            f", Go stdlib: {go_stdlib_count}"
            if go_stdlib_count
            else ""
        )
        print(
            f"[{bin_name}] Source files: "
            f"{len(classified['project_source'])}, "
            f"Build intermediates: "
            f"{len(classified['build_intermediate'])}"
            f"{extra}"
        )

        # Load component metadata
        meta_path = (
            self.bom_dir / "metadata"
            / "component_metadata.json"
        )
        if not meta_path.exists():
            print(
                "[ERROR] component_metadata.json "
                "not found. Run collect_metadata.py "
                "first."
            )
            return None

        resolver = ComponentResolver(str(meta_path))

        # Load dynamic library data
        dl_dir = Path(
            dynlib_dir
            if dynlib_dir
            else self.bom_dir / "metadata"
        )
        dynlib_path = dl_dir / "dynamic_libs.json"
        if not dynlib_path.exists():
            print(
                f"[ERROR] {dynlib_path} not found. "
                f"Run collect_dynamic_libs.py for "
                f"{bin_name} first."
            )
            return None

        resolver.load_dynamic_libs(
            str(dynlib_path)
        )
        components = (
            resolver.resolve_dynamic_components()
        )

        direct = sum(
            1 for c in components if c["direct"]
        )
        trans = len(components) - direct
        print(
            f"[{bin_name}] Dynamic libraries: "
            f"{len(components)} components "
            f"({direct} direct, "
            f"{trans} transitive)"
        )

        # Emit SPDX
        emitter = SpdxEmitter(
            repo_name=self.repo_name,
            repo_version=resolver.curl_version,
            distro=resolver.distro,
            gcc_version=resolver.gcc_version,
            bomtrace_version=self.bomtrace_version,
            bomsh_version=self.bomsh_version,
            binary_name=bin_name,
            vendored_dirs=self.vendored_dirs,
            repos_dir=self.repos_dir,
        )

        doc = emitter.emit(
            components=components,
            project_files=(
                classified["project_source"]
            ),
            doc_mapping=doc_mapping,
            logfile_hashes=logfile_hashes,
            direct_only=direct_only,
            static_only=static_only,
            go_stdlib=classified.get("go_stdlib"),
        )

        # Write output
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(doc, indent=2) + "\n"
        )

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
            html_path = str(
                out.with_suffix(".html")
            )
            generate_html(doc, html_path)
        except Exception as e:
            print(
                f"[WARN] Visualization failed: {e}"
            )

        return str(out)


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Generate SPDX 2.3 from OmniBOR ADG data"
        ),
    )
    ap.add_argument(
        "--bom-dir", required=True,
        help="Path to OmniBOR output dir for repo",
    )
    ap.add_argument(
        "--repos-dir", required=True,
        help="Path to repos directory",
    )
    ap.add_argument(
        "--repo-name", required=True,
        help="Repository name (e.g. curl)",
    )
    ap.add_argument(
        "--output", required=True,
        help="Output SPDX JSON file path",
    )
    ap.add_argument(
        "--bomtrace-version", default="unknown",
    )
    ap.add_argument(
        "--bomsh-version", default="unknown",
    )
    ap.add_argument(
        "--binary-name", default=None,
        help=(
            "Binary name (e.g. curl, libcurl.so). "
            "Defaults to --repo-name"
        ),
    )
    ap.add_argument(
        "--dynlib-dir", default=None,
        help=(
            "Directory containing "
            "dynamic_libs.json for this binary"
        ),
    )
    ap.add_argument(
        "--direct-only",
        action="store_true",
        default=False,
        help=(
            "Include only direct dependencies. "
            "Use for two-tier SBOMs where "
            "transitive deps belong to a "
            "downstream binary's SBOM."
        ),
    )
    ap.add_argument(
        "--static-only",
        action="store_true",
        default=False,
        help=(
            "Omit dynamically linked library "
            "packages. Only include root binary, "
            "vendored/static libs, and build tool."
        ),
    )
    args = ap.parse_args()

    gen = AdgSpdxGenerator(
        bom_dir=args.bom_dir,
        repos_dir=args.repos_dir,
        repo_name=args.repo_name,
        bomtrace_version=args.bomtrace_version,
        bomsh_version=args.bomsh_version,
    )
    result = gen.generate(
        args.output,
        binary_name=args.binary_name,
        dynlib_dir=args.dynlib_dir,
        direct_only=args.direct_only,
        static_only=args.static_only,
    )
    if result:
        print(f"Success: {result}")
    else:
        print("Failed to generate SPDX")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
