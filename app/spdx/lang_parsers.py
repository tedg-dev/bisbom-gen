"""
Language-specific artifact parsers for SPDX emission.

Provides parsers for Go, Rust, and C/C++ that extract
dependency metadata from lock files, module files, and
source paths. Used by SpdxEmitter to resolve versions
and classify dependency relationships.
"""

import re
from pathlib import Path


# Regex matching Go major-version suffix /vN (N>=2)
_GO_MAJOR_VER_RE = re.compile(r"^v\d+$")

# Well-known Go module hosting prefixes that use
# three path segments: host/owner/repo
_GO_THREE_SEGMENT_HOSTS = (
    "github.com", "gitlab.com", "bitbucket.org",
    "golang.org",
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

_CARGO_REGISTRY_RE = re.compile(
    r"/.cargo/registry/src/[^/]+/"
    r"([a-zA-Z0-9_-]+)-(\d+\.\d+\.\d+[^/]*)"
    r"/"
)


# ============================================================
# Go parsers
# ============================================================

def go_module_from_vendor_path(rest):
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

    if parts[0] in _GO_THREE_SEGMENT_HOSTS:
        if len(parts) < 3:
            return None
        base = "/".join(parts[:3])
        # Append /vN major version suffix if present
        if (
            len(parts) >= 4
            and _GO_MAJOR_VER_RE.match(
                parts[3]
            )
        ):
            return base + "/" + parts[3]
        return base
    # Other domains: 2 segments
    return "/".join(parts[:2])


def detect_go_version(go_stdlib):
    """Detect Go version from stdlib or install.

    Strategy:
      1. Look for -goversion flag in build commands
      2. Read /usr/local/go/VERSION file
      3. Fall back to 'unknown'
    """
    for art in go_stdlib:
        cmd = art.get("build_cmd", "")
        m = _GO_VERSION_RE.search(cmd)
        if m:
            return m.group(1).lstrip("go")
    # Fallback: read Go VERSION file
    ver_file = Path("/usr/local/go/VERSION")
    if ver_file.exists():
        # File is multi-line: "go1.26.0\ntime ..."
        first_line = (
            ver_file.read_text(
                encoding="utf-8"
            ).splitlines()[0]
        )
        return first_line.strip().lstrip("go")
    return "unknown"


def parse_go_mod(project_files):
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


def parse_go_modules_txt(project_files):
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


# ============================================================
# Rust parsers
# ============================================================

def rust_crate_from_registry_path(fp):
    """Extract (crate_name, version) from a Cargo
    registry source path.

    Paths look like:
      /root/.cargo/registry/src/index.crates.io-*/
        bitvec-1.0.1/src/lib.rs

    Returns (crate_name, version) or (None, None).
    """
    m = _CARGO_REGISTRY_RE.search(fp)
    if m:
        return m.group(1), m.group(2)
    return None, None


def parse_cargo_lock(
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


def parse_cargo_toml(
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
