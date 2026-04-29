"""
Metadata collection for OmniBOR Analysis.

Collects component metadata (dpkg) and dynamic library
dependencies for each output binary after the instrumented build.
"""

from pathlib import Path

from app.config import lang_subdir, timestamp
from app.runner import CommandRunner


class MetadataCollector:
    """Collect component metadata and dynamic lib info.

    Runs after the instrumented build to gather:
    1. component_metadata.json — dpkg metadata for all
       system files found in the bomsh treedb
    2. dynamic_libs.json — per-binary dynamic library
       dependencies with dpkg metadata

    Both outputs are consumed by AdgSpdxStep.
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def collect(
        self, repo_name, repo_cfg, paths_cfg,
        run_ts=None,
    ):
        """Collect metadata and dynamic libs.

        Returns True if at least component_metadata.json
        was created successfully.
        """
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        meta_dir = bom_dir / "metadata"
        repos_dir = paths_cfg["repos_dir"]
        repo_dir = Path(repos_dir) / repo_name

        treedb_path = (
            meta_dir / "bomsh"
            / "bomsh_omnibor_treedb"
        )
        if not treedb_path.exists():
            print(
                "[WARN] treedb not found — "
                "skipping metadata collection"
            )
            return False

        # Step 1: collect_metadata.py (once)
        meta_out = meta_dir / "component_metadata.json"
        if not meta_out.exists():
            print(
                "\n"
                + "=" * 60
                + "\n"
                "  Collecting component metadata\n"
                + "=" * 60
            )
            try:
                from collect_metadata import (
                    main as collect_meta,
                )
                collect_meta(
                    str(treedb_path),
                    repos_dir,
                    str(meta_dir),
                    repo_name=repo_name,
                    config_branch=repo_cfg.get(
                        "branch"
                    ),
                )
            except Exception as e:
                print(
                    f"[ERROR] collect_metadata failed: "
                    f"{e}"
                )
                return False

        # Step 2: collect_dynamic_libs.py (per binary)
        bins = repo_cfg.get("output_binaries", [])
        for rel_path in bins:
            bin_name = Path(rel_path).name
            bin_path = repo_dir / rel_path
            if not bin_path.exists():
                print(
                    f"[WARN] Binary not found: "
                    f"{bin_path}"
                )
                continue

            # Per-binary metadata dir
            bin_meta = meta_dir / bin_name
            dynlib_out = bin_meta / "dynamic_libs.json"
            if dynlib_out.exists():
                continue

            bin_meta.mkdir(parents=True, exist_ok=True)
            # Copy component_metadata.json to per-binary
            # dir so AdgSpdxStep can find it
            if meta_out.exists():
                import shutil
                comp_dst = (
                    bin_meta
                    / "component_metadata.json"
                )
                if not comp_dst.exists():
                    shutil.copy2(
                        str(meta_out), str(comp_dst),
                    )

            print(
                f"\n  Collecting dynamic libs: "
                f"{bin_name}"
            )
            try:
                from collect_dynamic_libs import (
                    main as collect_dynlibs,
                )
                collect_dynlibs(
                    str(bin_path), str(bin_meta),
                    project_bins=bins,
                )
            except Exception as e:
                print(
                    f"[ERROR] collect_dynamic_libs "
                    f"failed for {bin_name}: {e}"
                )

        return meta_out.exists()
