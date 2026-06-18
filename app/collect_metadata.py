"""Collect OS package metadata for system files in the bomsh treedb.

Runs inside the build container to resolve every system file
(libraries, headers, CRT objects) to its OS package and extract
rich metadata: name, version, source, maintainer, homepage,
architecture, section.

Supports Debian/Ubuntu (dpkg), RHEL/CentOS/Fedora (rpm), and
Alpine (apk) via the ``PackageResolver`` abstraction.

Outputs component_metadata.json alongside the treedb.
"""
import json
import os
import re
import subprocess
from pathlib import Path

# Matches semver-like version in git tags
_TAG_VER_RE = re.compile(
    r"(\d+\.\d+(?:\.\d+){0,2})"
)


def _version_from_tag(tag):
    """Extract version from a git tag string.

    Handles common tag formats:
        v0.25.9  -> 0.25.9
        v10.1.0  -> 10.1.0
        7.2.4    -> 7.2.4
        release-1.2.3 -> 1.2.3
        main, master  -> None
    """
    if not tag:
        return None
    m = _TAG_VER_RE.search(tag)
    return m.group(1) if m else None


def _detect_repo_version(
    repo_name, repos_dir, config_branch=None,
):
    """Detect the repo's own version.

    Priority:
    1. Config branch/tag (most reliable — explicit
       release tag from config.yaml)
    2. File-based detection (VERSION files,
       Cargo.toml, pom.xml, #define macros, etc.)
    """
    # 1. Try config branch/tag first
    ver = _version_from_tag(config_branch)
    if ver:
        return ver

    # 2. Fall back to file-based detection
    try:
        from app.version_detection import (
            VendoredVersionDetector,
        )
    except ImportError:
        return None
    repo_dir = Path(repos_dir) / repo_name
    if not repo_dir.exists():
        return None
    # Root-level files only — avoids vendored lib versions
    files = [
        str(f) for f in repo_dir.iterdir()
        if f.is_file()
    ]
    # Also include include/ headers (version #defines)
    include_dir = repo_dir / "include"
    if include_dir.exists():
        for f in include_dir.rglob("*.h"):
            files.append(str(f))
    # Include src/ headers too
    src_dir = repo_dir / "src"
    if src_dir.exists():
        for f in src_dir.rglob("*.h"):
            files.append(str(f))
    if not files:
        return None
    detector = VendoredVersionDetector()
    return detector.detect(repo_name, files)


def _detect_distro(os_release_path="/etc/os-release"):
    """Return the distro PRETTY_NAME, or 'unknown' if unavailable."""
    try:
        with open(os_release_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return (
                        line.split("=", 1)[1].strip().strip('"')
                    )
    except OSError:
        pass
    return "unknown"


def _gcc_version():
    """Return the first line of 'gcc --version', or 'unknown'."""
    try:
        return subprocess.check_output(
            ["gcc", "--version"], text=True,
        ).splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(
    treedb_path, repos_dir, out_dir,
    repo_name=None, config_branch=None,
    resolver=None,
):
    if resolver is None:
        from app.spdx.package_resolver import (
            auto_detect_resolver,
        )
        resolver = auto_detect_resolver()

    treedb = json.load(open(treedb_path))

    # Collect all system file paths (not under repos)
    system_files = set()
    for sha, entry in treedb.items():
        fp = entry.get("file_path", "")
        if fp and not fp.startswith(repos_dir):
            system_files.add(fp)

    print(f"System files in treedb: {len(system_files)}")

    # Resolve canonical paths (some have /../)
    canonical = {}
    for fp in system_files:
        real = os.path.realpath(fp)
        canonical[fp] = real

    # Resolve each unique real path to its OS package
    unique_reals = set(canonical.values())
    file_to_pkg = {}
    failed = []

    for real_path in sorted(unique_reals):
        result = resolver.resolve(real_path)
        if result:
            file_to_pkg[real_path] = result.name
        else:
            failed.append(real_path)

    print(f"Resolved to packages: {len(file_to_pkg)}")
    print(f"Failed to resolve: {len(failed)}")
    for f in failed[:10]:
        print(f"  unresolved: {f}")

    # Collect metadata for each unique package
    # The resolver caches metadata, so re-resolving is cheap
    unique_pkgs = sorted(set(file_to_pkg.values()))
    print(f"Unique packages: {len(unique_pkgs)}")

    pkg_metadata = {}
    for real_path, pkg_name in file_to_pkg.items():
        if pkg_name in pkg_metadata:
            continue
        result = resolver.resolve(real_path)
        if result:
            meta = {
                "Package": result.name,
                "Version": result.version,
            }
            if result.source:
                meta["Source"] = result.source
            if result.maintainer:
                meta["Maintainer"] = result.maintainer
            if result.homepage:
                meta["Homepage"] = result.homepage
            if result.architecture:
                meta["Architecture"] = result.architecture
            if result.section:
                meta["Section"] = result.section
            for k, v in result.extra.items():
                meta[k] = v
            pkg_metadata[pkg_name] = meta

    # Map original treedb paths to packages
    treedb_path_to_pkg = {}
    for fp in system_files:
        real = canonical.get(fp, fp)
        pkg = file_to_pkg.get(real)
        if pkg:
            treedb_path_to_pkg[fp] = pkg

    # Repo version detection (generic — works for any repo)
    repo_version = None
    if repo_name:
        repo_version = _detect_repo_version(
            repo_name, repos_dir,
            config_branch=config_branch,
        )

    # Distro and GCC info
    distro = _detect_distro()
    gcc_version = _gcc_version()

    result = {
        "distro": distro,
        "gcc_version": gcc_version,
        "repo_version": repo_version,
        "pkg_metadata": pkg_metadata,
        "file_to_pkg": treedb_path_to_pkg,
        "unresolved_files": failed,
    }

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "component_metadata.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nWrote: {out_path}")
    print(f"Distro: {distro}")
    print(f"GCC: {gcc_version}")
    if repo_version:
        print(f"Repo version: {repo_version}")
    print(f"Packages with metadata: {len(pkg_metadata)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Collect OS package metadata for treedb system files",
    )
    ap.add_argument("treedb", help="Path to bomsh_omnibor_treedb")
    ap.add_argument("repos_dir", help="Path to repos directory")
    ap.add_argument(
        "out_dir",
        help="Output directory for metadata JSON",
    )
    ap.add_argument(
        "--repo-name", default=None,
        help="Repo name for version detection",
    )
    args = ap.parse_args()
    main(args.treedb, args.repos_dir, args.out_dir, repo_name=args.repo_name)
