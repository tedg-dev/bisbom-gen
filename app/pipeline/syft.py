"""
Syft baseline SBOM generation for bisbom-gen.

Generates a manifest-based SPDX SBOM using Syft as a
supplementary baseline — not part of the core OmniBOR
build-time SBOM pipeline.
"""

from pathlib import Path

from app.config import lang_subdir, timestamp
from app.runner import CommandRunner


class SyftGenerator:
    """Generates a baseline manifest SBOM using Syft."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def generate(self, repo_name, repo_cfg,
                 paths_cfg, run_ts=None):
        """Generate Syft SBOM. Returns output file path."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name / ts
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        spdx_file = (
            spdx_dir
            / f"{repo_name}_syft.spdx.json"
        )

        rc = self.runner.run(
            f"syft dir:{repo_dir} "
            f"-o spdx-json={spdx_file}",
            description=(
                "Generating Syft manifest SBOM: "
                f"{spdx_file.name}"
            ),
        )
        if rc != 0:
            print(
                "[WARN] Syft SBOM generation "
                "may have failed"
            )

        # Generate HTML visualization
        if spdx_file.exists():
            try:
                import json as _viz_json
                from spdx_visualize import (
                    generate_html,
                )
                doc = _viz_json.loads(
                    spdx_file.read_text()
                )
                html_path = str(
                    spdx_file.with_suffix(".html")
                )
                generate_html(doc, html_path)
            except Exception as e:
                print(
                    "[WARN] Syft visualization "
                    f"failed: {e}"
                )

        return str(spdx_file)
