"""
SBOM Comparison Report Generator.

Generates markdown comparison reports from SPDX SBOM
comparison results. Separated from compare.py to keep
file sizes manageable.
"""

from datetime import datetime


class ReportGenerator:
    """Generates markdown comparison reports."""

    @staticmethod
    def generate(
        repo_name, result,
        omnibor_file, binary_file,
    ):
        """Generate a markdown comparison report string."""
        now = datetime.now().isoformat()
        total_union = len(
            set(result["common"])
            | set(result["omnibor_only"])
            | set(result["binary_only"])
        )
        overlap_pct = (
            (
                len(result["common"])
                / total_union * 100
            )
            if total_union > 0 else 0
        )

        report = (
            f"# SBOM Comparison Report"
            f" — {repo_name}\n\n"
            f"**Date:** {now}\n"
            f"**OmniBOR SPDX:** `{omnibor_file}`\n"
            f"**Binary Scan SPDX:** "
            f"`{binary_file}`\n\n"
            "## Summary\n\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            f"| OmniBOR packages | "
            f"{result['omnibor_total']} |\n"
            f"| Binary scan packages | "
            f"{result['binary_total']} |\n"
            f"| Common (both detected) | "
            f"{len(result['common'])} |\n"
            f"| OmniBOR only | "
            f"{len(result['omnibor_only'])} |\n"
            f"| Binary scan only | "
            f"{len(result['binary_only'])} |\n"
            f"| Overlap | {overlap_pct:.1f}% |\n"
            f"| Version agreement | "
            f"{len(result['version_match'])} |\n"
            f"| Version mismatch | "
            f"{len(result['version_mismatch'])} "
            "|\n\n"
            "## Common Packages "
            "(detected by both)\n\n"
            "| Package | OmniBOR Version "
            "| Binary Scan Version | Match |\n"
            "|---------|----------------"
            "|--------------------:|-------|\n"
        )

        for name in result["common"]:
            ov = (
                result["omnibor_map"][name]["version"]
            )
            bv = (
                result["binary_map"][name]["version"]
            )
            match = (
                "YES" if ov == bv else "**NO**"
            )
            report += (
                f"| {name} | {ov} "
                f"| {bv} | {match} |\n"
            )

        report += (
            "\n## OmniBOR Only "
            "(not detected by binary scanner)\n\n"
            "These components were identified "
            "during build interception but not\n"
            "found by the binary scanner. "
            "Possible reasons:\n"
            "- Source-only headers or "
            "build-time dependencies\n"
            "- Components compiled into the "
            "binary without distinct signatures\n"
            "- Intermediate build artifacts\n\n"
        )
        for name in result["omnibor_only"]:
            pkg = result["omnibor_map"][name]
            report += (
                f"- **{pkg['name']}** "
                f"({pkg['version']})\n"
            )

        report += (
            "\n## Binary Scan Only "
            "(not detected by OmniBOR)\n\n"
            "These components were identified "
            "by binary signature matching but "
            "not\n"
            "tracked by build interception. "
            "Possible reasons:\n"
            "- Pre-compiled commercial SDKs "
            "or vendor binaries\n"
            "- Statically linked libraries "
            "from system packages\n"
            "- Components not compiled from "
            "source in this build\n\n"
        )
        for name in result["binary_only"]:
            pkg = result["binary_map"][name]
            report += (
                f"- **{pkg['name']}** "
                f"({pkg['version']})\n"
            )

        if result["version_mismatch"]:
            report += (
                "\n## Version Mismatches\n\n"
                "| Package | OmniBOR "
                "| Binary Scan |\n"
                "|---------|---------|"
                "-------------|\n"
            )
            for name, ov, bv in (
                result["version_mismatch"]
            ):
                report += (
                    f"| {name} | {ov} | {bv} |\n"
                )

        report += (
            "\n## Analysis Notes\n\n"
            "- **OmniBOR strengths:** Tracks every "
            "source file through compilation;\n"
            "  captures undeclared and transitive "
            "build dependencies\n"
            "- **Binary scan strengths:** Detects "
            "pre-compiled commercial components\n"
            "  and statically linked code not "
            "visible to build interception\n"
            "- **Combined coverage** provides the "
            "most complete SBOM\n\n"
            "---\n"
            "*Generated by omnibor-analysis "
            f"compare.py on {now}*\n"
        )
        return report
