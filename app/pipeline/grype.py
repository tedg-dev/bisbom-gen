"""
Grype vulnerability scanner integration for OmniBOR Analysis.

Scans SPDX SBOM files using Grype to identify known CVEs in
dependency packages. Produces a JSON vulnerability report
alongside each scanned SPDX file.

Grype matches packages by PURL, CPE, and distro metadata.
The _build.spdx.json files contain Maven/Go/Cargo dependency
PURLs which Grype uses for CVE lookups against its local
vulnerability database.
"""

import json
from pathlib import Path

from app.config import lang_subdir
from app.runner import CommandRunner


class GrypeScanner:
    """Scans SPDX SBOMs for known vulnerabilities using Grype."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def scan_file(self, spdx_path):
        """Scan a single SPDX JSON file with Grype.

        Args:
            spdx_path: path to an SPDX JSON file.

        Returns:
            str: path to Grype JSON output, or None on failure.
        """
        spdx_path = Path(spdx_path)
        if not spdx_path.exists():
            print(
                f"[WARN] SPDX file not found: {spdx_path}"
            )
            return None

        # Handle double extension: .spdx.json
        base_name = spdx_path.name
        if base_name.endswith(".spdx.json"):
            base_name = base_name[:-len(".spdx.json")]
        else:
            base_name = spdx_path.stem
        grype_output = spdx_path.with_name(
            base_name + "_grype.json"
        )

        rc = self.runner.run(
            f"grype sbom:{spdx_path} -o json "
            f"--file {grype_output}",
            description=(
                f"Grype CVE scan: {spdx_path.name}"
            ),
        )
        if rc != 0:
            print(
                "[WARN] Grype scan may have failed "
                f"for {spdx_path.name}"
            )
            return None

        if not grype_output.exists():
            return None

        summary = self._summarize(grype_output)
        self._print_summary(spdx_path.name, summary)

        # Re-generate HTML with CVE overlay
        self.annotate_html(spdx_path, grype_output)

        return str(grype_output)

    def scan_directory(self, spdx_dir, pattern="*_build.spdx.json"):
        """Scan all matching SPDX files in a directory.

        Args:
            spdx_dir: directory containing SPDX files.
            pattern: glob pattern for files to scan.
                Defaults to _build.spdx.json (full
                dependency graph).

        Returns:
            list[str]: paths to Grype JSON outputs.
        """
        spdx_dir = Path(spdx_dir)
        if not spdx_dir.is_dir():
            print(
                f"[WARN] SPDX directory not found: "
                f"{spdx_dir}"
            )
            return []

        results = []
        spdx_files = sorted(spdx_dir.glob(pattern))
        if not spdx_files:
            print(
                f"[WARN] No files matching {pattern} "
                f"in {spdx_dir}"
            )
            return results

        for spdx_file in spdx_files:
            result = self.scan_file(spdx_file)
            if result:
                results.append(result)

        return results

    def scan_repo(
        self, repo_name, repo_cfg, paths_cfg,
        run_ts=None, pattern="*_build.spdx.json",
    ):
        """Scan all SPDX files for a repo run.

        Args:
            repo_name: repository name.
            repo_cfg: repo config dict.
            paths_cfg: paths config dict.
            run_ts: run timestamp subdirectory.
            pattern: glob pattern for SPDX files.

        Returns:
            list[str]: paths to Grype JSON outputs.
        """
        lang = lang_subdir(repo_cfg)
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / lang / repo_name
        )
        if run_ts:
            spdx_dir = spdx_dir / run_ts

        return self.scan_directory(spdx_dir, pattern)

    @staticmethod
    def annotate_html(spdx_path, grype_output_path):
        """Re-generate HTML visualization with CVE overlay.

        Reads an existing SPDX JSON and its Grype results,
        then produces (or overwrites) the companion HTML
        with CVE diamond indicators on affected packages.

        Args:
            spdx_path: path to the SPDX JSON file.
            grype_output_path: path to the Grype JSON output.

        Returns:
            str: path to the annotated HTML file, or None.
        """
        spdx_path = Path(spdx_path)
        grype_path = Path(grype_output_path)
        if not spdx_path.exists() or not grype_path.exists():
            return None

        try:
            spdx_doc = json.loads(spdx_path.read_text())
            grype_data = json.loads(grype_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(
                f"[WARN] CVE annotation failed: {e}"
            )
            return None

        from app.spdx_visualize import generate_html
        html_path = str(spdx_path.with_suffix(".html"))
        generate_html(
            spdx_doc, html_path,
            grype_data=grype_data,
        )
        print(
            f"[OK] CVE-annotated HTML: "
            f"{Path(html_path).name}"
        )
        return html_path

    @staticmethod
    def _summarize(grype_output_path):
        """Parse Grype JSON output and return summary dict."""
        try:
            data = json.loads(
                Path(grype_output_path).read_text()
            )
        except (json.JSONDecodeError, OSError) as e:
            return {"error": str(e)}

        matches = data.get("matches", [])
        severity_counts = {}
        cve_ids = set()

        for match in matches:
            vuln = match.get("vulnerability", {})
            sev = vuln.get("severity", "Unknown")
            severity_counts[sev] = (
                severity_counts.get(sev, 0) + 1
            )
            cve_id = vuln.get("id", "")
            if cve_id:
                cve_ids.add(cve_id)

        return {
            "total_matches": len(matches),
            "unique_cves": len(cve_ids),
            "severity_counts": severity_counts,
        }

    @staticmethod
    def _print_summary(spdx_name, summary):
        """Print a human-readable CVE scan summary."""
        if "error" in summary:
            print(
                f"[WARN] Could not parse Grype output "
                f"for {spdx_name}: {summary['error']}"
            )
            return

        total = summary["total_matches"]
        unique = summary["unique_cves"]
        if total == 0:
            print(
                f"[OK] {spdx_name}: "
                f"no known vulnerabilities"
            )
            return

        sev = summary["severity_counts"]
        parts = []
        for level in [
            "Critical", "High", "Medium",
            "Low", "Negligible", "Unknown",
        ]:
            count = sev.get(level, 0)
            if count > 0:
                parts.append(f"{count} {level}")

        sev_str = ", ".join(parts)
        print(
            f"[CVE] {spdx_name}: "
            f"{unique} unique CVEs "
            f"({total} matches — {sev_str})"
        )
