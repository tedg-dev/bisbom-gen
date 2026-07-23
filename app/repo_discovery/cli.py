"""
CLI entry point for repo discovery and config generation.
"""

import argparse
import sys
import yaml
from pathlib import Path

from app.repo_discovery.facade import RepoDiscovery


def main():
    parser = argparse.ArgumentParser(
        description=(
            "OmniBOR — Smart repo discovery "
            "and config generation"
        )
    )
    parser.add_argument(
        "repo",
        help=(
            "Repo name (e.g., 'curl'), "
            "owner/repo, or full GitHub URL"
        ),
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write the entry to config.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show generated config without writing",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(
        f"  OmniBOR — Add Repository: {args.repo}"
    )
    print(f"{'='*60}\n")

    discovery = RepoDiscovery()

    # Step 1: Find repo
    print("[1/6] Searching GitHub...")
    repo_info = discovery.github.get_repo_info(
        args.repo
    )
    if not repo_info:
        print(
            "[ERROR] Could not find repository "
            f"for '{args.repo}'"
        )
        sys.exit(1)

    full_name = repo_info["fullName"]
    branch = repo_info["defaultBranch"]
    repo_name = full_name.split("/")[-1].lower()
    stars = repo_info.get("stargazersCount", "?")
    print(f"  Found: {full_name} ({stars} stars)")
    print(f"  Branch: {branch}")
    lang = repo_info.get("language", "unknown")
    desc = repo_info.get("description", "N/A")
    print(f"  Language: {lang}")
    print(f"  Description: {desc}")

    # Step 2: File tree
    print("\n[2/6] Inspecting repository contents...")
    files = discovery.github.get_file_tree(
        full_name, branch
    )
    if not files:
        print(
            "[ERROR] Could not read repository "
            "file tree"
        )
        sys.exit(1)
    print(
        f"  Found {len(files)} files in "
        "top-level + src/ + lib/"
    )

    # Step 3: Build system
    print("\n[3/6] Detecting build system...")
    build_system = discovery.detector.detect(files)
    print(f"  Build system: {build_system}")

    # Step 4: Dependencies
    print("\n[4/6] Analyzing dependencies...")
    flags, apt_packages = (
        discovery.analyzer.analyze(
            full_name, branch, build_system, files
        )
    )
    if flags:
        flags_str = " ".join(flags)
        print(f"  Configure flags: {flags_str}")
    else:
        print(
            "  No optional dependency flags detected"
        )
    if apt_packages:
        pkgs_str = ", ".join(sorted(apt_packages))
        print(
            f"  Required apt packages: {pkgs_str}"
        )

    # Step 5: Binaries
    print("\n[5/6] Identifying output binaries...")
    binaries = discovery.binary_detector.detect(
        full_name, repo_name, build_system, files
    )
    for b in binaries:
        print(f"  - {b}")

    # Step 6: Config
    print("\n[6/6] Generating config entry...")
    stats = discovery.config.get_repo_stats(
        full_name, discovery.github
    )
    description = discovery.build_description(
        repo_info, stats, repo_name
    )
    build_steps = discovery.steps.generate(
        build_system, flags
    )
    build_profile = discovery.config.build_profile_for(
        build_system
    )
    entry = discovery.config.generate_entry(
        repo_info, build_steps,
        binaries, description,
        apt_deps=apt_packages,
        build_profile=build_profile,
    )

    # Display YAML
    sep = "=" * 60
    print(f"\n{sep}")
    print(
        f"  Generated config.yaml entry for "
        f"'{repo_name}':"
    )
    print(f"{sep}\n")
    yaml_str = yaml.dump(
        {repo_name: entry},
        default_flow_style=False,
        sort_keys=False, width=120,
    )
    print(yaml_str)

    if apt_packages:
        print(f"{sep}")
        print("  Required Dockerfile additions:")
        print(f"{sep}\n")
        dockerfile_path = (
            Path(__file__).parent.parent
            / "docker" / "Dockerfile"
        )
        existing_pkgs = set()
        if dockerfile_path.exists():
            df_content = dockerfile_path.read_text()
            for pkg in apt_packages:
                if pkg in df_content:
                    existing_pkgs.add(pkg)

        new_pkgs = [
            p for p in sorted(apt_packages)
            if p not in existing_pkgs
        ]
        if new_pkgs:
            print(
                "  Add to docker/Dockerfile "
                "apt-get install:"
            )
            for pkg in new_pkgs:
                print(f"    {pkg}")
            installed = (
                ", ".join(sorted(existing_pkgs))
                or "none"
            )
            print(
                "\n  Already installed: "
                f"{installed}"
            )
        else:
            print(
                "  All required packages already "
                "in Dockerfile"
            )

    if args.write:
        print("\n[WRITE] Writing to config.yaml...")
        discovery.config.write_entry(
            repo_name, entry
        )
        print("\n[WRITE] Creating output dirs...")
        discovery.config.create_output_dirs(
            repo_name
        )
        print(
            f"\n[DONE] '{repo_name}' is ready. Run:"
        )
        print(
            f"  python3 app/analyze.py "
            f"--repo {repo_name}"
        )
    else:
        print(
            "\n[DRY-RUN] No changes written. "
            "Use --write to save to config.yaml"
        )


if __name__ == "__main__":
    main()
