"""
Per-binary ADG SPDX generation for bisbom-gen.

Wraps spdx_from_adg.AdgSpdxGenerator to produce one SPDX 2.3
JSON file per output binary.
"""

from pathlib import Path

from app.config import lang_subdir, timestamp


class AdgSpdxStep:
    """Generate per-binary SPDX SBOMs from ADG data.

    Wraps spdx_from_adg.AdgSpdxGenerator to produce one
    SPDX 2.3 JSON file per output binary. Runs inside the
    container where source file paths match the treedb,
    enabling vendored dependency version detection.
    """

    @staticmethod
    def generate(repo_name, repo_cfg, paths_cfg,
                 run_ts=None, vcs_uri="NOASSERTION"):
        """Generate ADG SPDX for each output binary.

        Returns list of output file paths.
        """
        from spdx_from_adg import AdgSpdxGenerator

        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "bisbom" / lang / repo_name / ts
        )
        repos_dir = paths_cfg["repos_dir"]
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name / ts
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        bins = repo_cfg.get("output_binaries", [])
        if not bins:
            print(
                "[WARN] No output_binaries for "
                f"ADG SPDX: {repo_name}"
            )
            return []

        gen = AdgSpdxGenerator(
            bom_dir=str(bom_dir),
            repos_dir=repos_dir,
            repo_name=repo_name,
            vendored_dirs=repo_cfg.get(
                "vendored_dirs"
            ),
            vcs_uri=vcs_uri,
        )

        # Expand glob patterns to actual file paths, dropping
        # non-product JARs (auxiliary artifacts and build-logic JARs
        # such as Gradle ``buildSrc``) so every mode applies one
        # consistent product-JAR definition.
        from app.pipeline.binary_collector import (
            BinaryCollector,
        )
        repo_dir = Path(repos_dir) / repo_name
        excluded = BinaryCollector.excluded_binaries(
            repo_dir, repo_cfg.get("exclude_binaries", []),
        )
        expanded_bins = []
        for rel_path in bins:
            if '*' in rel_path or '?' in rel_path:
                matches = [
                    m for m in repo_dir.glob(rel_path)
                    if not BinaryCollector.is_non_product_jar(
                        m, repo_dir,
                    )
                    and m not in excluded
                ]
                expanded_bins.extend(
                    str(m.relative_to(repo_dir))
                    for m in matches
                )
            else:
                expanded_bins.append(rel_path)

        results = []
        for rel_path in expanded_bins:
            bin_name = Path(rel_path).name
            # Clean up name for SPDX filename
            spdx_name = bin_name.replace(
                ".jar", ""
            ).replace("-SNAPSHOT", "")

            # Use direct-only for binaries that
            # link against a shared lib also in
            # the output list (e.g. curl links
            # libcurl.so — transitive deps belong
            # to libcurl's SBOM).
            has_shared_lib = any(
                b != rel_path
                and (".so" in b or ".so." in b)
                for b in expanded_bins
            )
            is_app = (
                ".so" not in rel_path
                and ".so." not in rel_path
            )
            direct_only = (
                has_shared_lib and is_app
            )

            # Per-binary dynlib dir if it exists
            dynlib_dir = (
                bom_dir / "metadata" / bin_name
            )
            dl_dir = (
                str(dynlib_dir)
                if dynlib_dir.is_dir()
                else None
            )

            # Generate ANALYZED SBOM (CISA Analyzed):
            # only what's compiled into the binary
            analyzed_path = (
                spdx_dir
                / f"{spdx_name}_analyzed.spdx.json"
            )
            result = gen.generate(
                output_path=str(analyzed_path),
                binary_name=bin_name,
                dynlib_dir=dl_dir,
                direct_only=direct_only,
                static_only=True,
            )
            if result:
                results.append(result)

            # Generate BUILD SBOM (CISA Build):
            # full dependency graph
            build_path = (
                spdx_dir
                / f"{spdx_name}_build.spdx.json"
            )
            result = gen.generate(
                output_path=str(build_path),
                binary_name=bin_name,
                dynlib_dir=dl_dir,
                direct_only=direct_only,
                static_only=False,
            )
            if result:
                results.append(result)

        return results
