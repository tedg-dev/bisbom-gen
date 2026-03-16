"""Collect dpkg metadata for all system files in the bomsh treedb.

Runs inside the build container to resolve every system file
(libraries, headers, CRT objects) to its dpkg package and extract
rich metadata: name, version, source, maintainer, homepage,
architecture, section.

Outputs component_metadata.json alongside the treedb.
"""
import json
import os
import subprocess
from pathlib import Path


def _detect_repo_version(repo_name, repos_dir):
    """Detect the repo's own version from its source tree."""
    try:
        from spdx.version_detector import (
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


def main(treedb_path, repos_dir, out_dir, repo_name=None):
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

    # dpkg -S for each unique real path
    unique_reals = set(canonical.values())
    file_to_pkg = {}
    failed = []

    for real_path in sorted(unique_reals):
        try:
            out = subprocess.check_output(
                ["dpkg", "-S", real_path],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            # Format: "pkg1, pkg2: /path"
            pkg_part = out.split(":")[0]
            pkg = pkg_part.split(",")[0].strip()
            file_to_pkg[real_path] = pkg
        except subprocess.CalledProcessError:
            failed.append(real_path)

    print(f"Resolved to dpkg packages: {len(file_to_pkg)}")
    print(f"Failed to resolve: {len(failed)}")
    for f in failed[:10]:
        print(f"  unresolved: {f}")

    # Query full metadata for each unique package
    unique_pkgs = sorted(set(file_to_pkg.values()))
    print(f"Unique dpkg packages: {len(unique_pkgs)}")

    fields = [
        "Package", "Version", "Source", "Maintainer",
        "Homepage", "Architecture", "Section", "Priority",
    ]
    fmt = "|".join(["${" + f + "}" for f in fields])

    pkg_metadata = {}
    for pkg in unique_pkgs:
        try:
            out = subprocess.check_output(
                ["dpkg-query", "-W", "-f", fmt, pkg],
                text=True, stderr=subprocess.DEVNULL,
            )
            parts = out.split("|")
            meta = {}
            for i, f in enumerate(fields):
                if i < len(parts) and parts[i]:
                    meta[f] = parts[i]
            pkg_metadata[pkg] = meta
        except Exception:
            pass

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
            repo_name, repos_dir
        )

    # Distro info
    distro = "unknown"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    distro = (
                        line.split("=", 1)[1]
                        .strip().strip('"')
                    )
                    break
    except Exception:
        pass

    # GCC version
    gcc_version = "unknown"
    try:
        gcc_version = subprocess.check_output(
            ["gcc", "--version"], text=True,
        ).splitlines()[0]
    except Exception:
        pass

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
        description="Collect dpkg metadata for treedb system files",
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
