"""
CLI entry point for standalone ADG-to-SPDX generation.
"""

import argparse

from app.spdx.generator import AdgSpdxGenerator


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
