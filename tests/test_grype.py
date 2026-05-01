"""Tests for app.pipeline.grype — Grype CVE scanner integration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from app.pipeline.grype import GrypeScanner
from app.viz.extract import merge_grype_cves


# ============================================================
# Sample data
# ============================================================

SAMPLE_GRYPE_OUTPUT = {
    "matches": [
        {
            "vulnerability": {
                "id": "CVE-2023-1234",
                "severity": "High",
            },
            "artifact": {
                "name": "commons-collections",
                "version": "3.2.2",
            },
        },
        {
            "vulnerability": {
                "id": "CVE-2023-5678",
                "severity": "Critical",
            },
            "artifact": {
                "name": "log4j-core",
                "version": "2.14.1",
            },
        },
        {
            "vulnerability": {
                "id": "CVE-2023-1234",
                "severity": "High",
            },
            "artifact": {
                "name": "commons-beanutils",
                "version": "1.9.4",
            },
        },
    ],
}

SAMPLE_SPDX = {
    "spdxVersion": "SPDX-2.3",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": "test-build",
    "packages": [
        {
            "SPDXID": "SPDXRef-Dep-0",
            "name": "commons-collections",
            "versionInfo": "3.2.2",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": (
                    "pkg:maven/commons-collections"
                    "/commons-collections@3.2.2"
                ),
            }],
        },
    ],
}

EMPTY_GRYPE_OUTPUT = {"matches": []}


# ============================================================
# _summarize
# ============================================================

class TestSummarize:
    """Tests for GrypeScanner._summarize."""

    def test_summarize_with_matches(self, tmp_path):
        grype_file = tmp_path / "results.json"
        grype_file.write_text(
            json.dumps(SAMPLE_GRYPE_OUTPUT)
        )
        summary = GrypeScanner._summarize(grype_file)
        assert summary["total_matches"] == 3
        assert summary["unique_cves"] == 2
        assert summary["severity_counts"]["High"] == 2
        assert summary["severity_counts"]["Critical"] == 1

    def test_summarize_empty(self, tmp_path):
        grype_file = tmp_path / "empty.json"
        grype_file.write_text(
            json.dumps(EMPTY_GRYPE_OUTPUT)
        )
        summary = GrypeScanner._summarize(grype_file)
        assert summary["total_matches"] == 0
        assert summary["unique_cves"] == 0
        assert summary["severity_counts"] == {}

    def test_summarize_invalid_json(self, tmp_path):
        grype_file = tmp_path / "bad.json"
        grype_file.write_text("not json")
        summary = GrypeScanner._summarize(grype_file)
        assert "error" in summary

    def test_summarize_missing_file(self, tmp_path):
        grype_file = tmp_path / "missing.json"
        summary = GrypeScanner._summarize(grype_file)
        assert "error" in summary


# ============================================================
# _print_summary
# ============================================================

class TestPrintSummary:
    """Tests for GrypeScanner._print_summary."""

    def test_print_no_vulns(self, capsys):
        summary = {
            "total_matches": 0,
            "unique_cves": 0,
            "severity_counts": {},
        }
        GrypeScanner._print_summary("test.spdx.json", summary)
        out = capsys.readouterr().out
        assert "no known vulnerabilities" in out

    def test_print_with_vulns(self, capsys):
        summary = {
            "total_matches": 3,
            "unique_cves": 2,
            "severity_counts": {
                "High": 2,
                "Critical": 1,
            },
        }
        GrypeScanner._print_summary("test.spdx.json", summary)
        out = capsys.readouterr().out
        assert "[CVE]" in out
        assert "2 unique CVEs" in out
        assert "1 Critical" in out
        assert "2 High" in out

    def test_print_error(self, capsys):
        summary = {"error": "parse failed"}
        GrypeScanner._print_summary("test.spdx.json", summary)
        out = capsys.readouterr().out
        assert "Could not parse" in out


# ============================================================
# scan_file
# ============================================================

class TestScanFile:
    """Tests for GrypeScanner.scan_file."""

    def test_scan_file_success(self, tmp_path):
        spdx_file = tmp_path / "test_build.spdx.json"
        spdx_file.write_text(json.dumps(SAMPLE_SPDX))

        grype_out = tmp_path / "test_build_grype.json"

        runner = MagicMock()

        def fake_run(cmd, description=""):
            grype_out.write_text(
                json.dumps(SAMPLE_GRYPE_OUTPUT)
            )
            return 0

        runner.run.side_effect = fake_run

        scanner = GrypeScanner(runner=runner)
        result = scanner.scan_file(spdx_file)

        assert result == str(grype_out)
        runner.run.assert_called_once()
        cmd = runner.run.call_args[0][0]
        assert "grype sbom:" in cmd
        assert "-o json" in cmd

    def test_scan_file_missing_spdx(self, tmp_path):
        scanner = GrypeScanner(runner=MagicMock())
        result = scanner.scan_file(
            tmp_path / "nonexistent.spdx.json"
        )
        assert result is None

    def test_scan_file_grype_failure(self, tmp_path):
        spdx_file = tmp_path / "test_build.spdx.json"
        spdx_file.write_text(json.dumps(SAMPLE_SPDX))

        runner = MagicMock()
        runner.run.return_value = 1

        scanner = GrypeScanner(runner=runner)
        result = scanner.scan_file(spdx_file)
        assert result is None


# ============================================================
# scan_directory
# ============================================================

class TestScanDirectory:
    """Tests for GrypeScanner.scan_directory."""

    def test_scan_directory_finds_build_spdx(self, tmp_path):
        f1 = tmp_path / "a_build.spdx.json"
        f2 = tmp_path / "b_build.spdx.json"
        f3 = tmp_path / "c_analyzed.spdx.json"
        for f in [f1, f2, f3]:
            f.write_text(json.dumps(SAMPLE_SPDX))

        runner = MagicMock()

        def fake_run(cmd, description=""):
            # Extract the --file path from command
            parts = cmd.split("--file ")
            if len(parts) > 1:
                out_path = Path(parts[1].strip())
                out_path.write_text(
                    json.dumps(EMPTY_GRYPE_OUTPUT)
                )
            return 0

        runner.run.side_effect = fake_run

        scanner = GrypeScanner(runner=runner)
        results = scanner.scan_directory(tmp_path)

        # Only _build files matched by default pattern
        assert len(results) == 2
        assert runner.run.call_count == 2

    def test_scan_directory_missing(self, tmp_path):
        scanner = GrypeScanner(runner=MagicMock())
        results = scanner.scan_directory(
            tmp_path / "nope"
        )
        assert results == []

    def test_scan_directory_no_matching_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hi")
        scanner = GrypeScanner(runner=MagicMock())
        results = scanner.scan_directory(tmp_path)
        assert results == []


# ============================================================
# scan_repo
# ============================================================

class TestScanRepo:
    """Tests for GrypeScanner.scan_repo."""

    def test_scan_repo_builds_correct_path(self, tmp_path):
        spdx_dir = (
            tmp_path / "spdx" / "java"
            / "checkstyle" / "2024-01-01_0000"
        )
        spdx_dir.mkdir(parents=True)
        f1 = spdx_dir / "check_build.spdx.json"
        f1.write_text(json.dumps(SAMPLE_SPDX))

        runner = MagicMock()

        def fake_run(cmd, description=""):
            parts = cmd.split("--file ")
            if len(parts) > 1:
                Path(parts[1].strip()).write_text(
                    json.dumps(EMPTY_GRYPE_OUTPUT)
                )
            return 0

        runner.run.side_effect = fake_run

        scanner = GrypeScanner(runner=runner)
        results = scanner.scan_repo(
            "checkstyle",
            {"language": "java"},
            {"output_dir": str(tmp_path)},
            run_ts="2024-01-01_0000",
        )
        assert len(results) == 1


# ============================================================
# Facade integration
# ============================================================

# ============================================================
# merge_grype_cves
# ============================================================

class TestMergeGrypeCves:
    """Tests for merge_grype_cves."""

    def test_merge_matches_by_name_version(self):
        nodes = [
            {"name": "commons-collections", "version": "3.2.2"},
            {"name": "log4j-core", "version": "2.14.1"},
            {"name": "clean-lib", "version": "1.0"},
        ]
        count = merge_grype_cves(nodes, SAMPLE_GRYPE_OUTPUT)
        assert count == 2
        assert len(nodes[0]["cves"]) == 1
        assert nodes[0]["cves"][0]["id"] == "CVE-2023-1234"
        assert len(nodes[1]["cves"]) == 1
        assert nodes[1]["cves"][0]["id"] == "CVE-2023-5678"
        assert nodes[2]["cves"] == []

    def test_merge_no_grype_data(self):
        nodes = [{"name": "x", "version": "1"}]
        count = merge_grype_cves(nodes, None)
        assert count == 0

    def test_merge_empty_matches(self):
        nodes = [{"name": "x", "version": "1"}]
        count = merge_grype_cves(nodes, EMPTY_GRYPE_OUTPUT)
        assert count == 0
        assert nodes[0]["cves"] == []

    def test_merge_deduplicates_cves(self):
        """Same CVE on multiple artifacts with same name/version."""
        grype = {
            "matches": [
                {"vulnerability": {"id": "CVE-1", "severity": "High"},
                 "artifact": {"name": "foo", "version": "1.0"}},
                {"vulnerability": {"id": "CVE-1", "severity": "High"},
                 "artifact": {"name": "foo", "version": "1.0"}},
            ]
        }
        nodes = [{"name": "foo", "version": "1.0"}]
        merge_grype_cves(nodes, grype)
        assert len(nodes[0]["cves"]) == 1

    def test_merge_case_insensitive(self):
        grype = {
            "matches": [
                {"vulnerability": {"id": "CVE-9", "severity": "Low"},
                 "artifact": {"name": "MyLib", "version": "2.0"}},
            ]
        }
        nodes = [{"name": "mylib", "version": "2.0"}]
        merge_grype_cves(nodes, grype)
        assert len(nodes[0]["cves"]) == 1


# ============================================================
# annotate_html
# ============================================================

class TestAnnotateHtml:
    """Tests for GrypeScanner.annotate_html."""

    def test_annotate_html_produces_file(self, tmp_path):
        spdx_file = tmp_path / "test_build.spdx.json"
        spdx_file.write_text(json.dumps({
            "name": "test",
            "creationInfo": {"created": "2026-01-01"},
            "packages": [
                {
                    "SPDXID": "SPDXRef-Root",
                    "name": "myapp",
                    "versionInfo": "1.0",
                    "primaryPackagePurpose": "APPLICATION",
                },
                {
                    "SPDXID": "SPDXRef-Dep-0",
                    "name": "commons-collections",
                    "versionInfo": "3.2.2",
                    "primaryPackagePurpose": "LIBRARY",
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Root",
                },
                {
                    "spdxElementId": "SPDXRef-Root",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Dep-0",
                },
            ],
        }))
        grype_file = tmp_path / "test_build_grype.json"
        grype_file.write_text(json.dumps(SAMPLE_GRYPE_OUTPUT))

        result = GrypeScanner.annotate_html(
            spdx_file, grype_file
        )
        assert result is not None
        html_path = Path(result)
        assert html_path.exists()
        content = html_path.read_text()
        assert "cve-indicator" in content
        assert "cve-tooltip" in content
        assert "CVE found" in content

    def test_annotate_html_missing_files(self, tmp_path):
        result = GrypeScanner.annotate_html(
            tmp_path / "no.spdx.json",
            tmp_path / "no_grype.json",
        )
        assert result is None


# ============================================================
# generate_html with grype_data
# ============================================================

class TestGenerateHtmlWithCves:
    """Tests for generate_html with CVE overlay."""

    def test_html_without_grype(self, tmp_path):
        from app.spdx_visualize import generate_html
        doc = {
            "name": "test",
            "creationInfo": {"created": "2026"},
            "packages": [{
                "SPDXID": "SPDXRef-Root",
                "name": "myapp",
                "versionInfo": "1.0",
                "primaryPackagePurpose": "APPLICATION",
            }],
            "relationships": [{
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Root",
            }],
        }
        out = tmp_path / "out.html"
        generate_html(doc, str(out))
        content = out.read_text()
        assert "CVE found (0 pkgs)" in content

    def test_html_with_grype(self, tmp_path):
        from app.spdx_visualize import generate_html
        doc = {
            "name": "test",
            "creationInfo": {"created": "2026"},
            "packages": [
                {
                    "SPDXID": "SPDXRef-Root",
                    "name": "myapp",
                    "versionInfo": "1.0",
                    "primaryPackagePurpose": "APPLICATION",
                },
                {
                    "SPDXID": "SPDXRef-D0",
                    "name": "commons-collections",
                    "versionInfo": "3.2.2",
                    "primaryPackagePurpose": "LIBRARY",
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Root",
                },
                {
                    "spdxElementId": "SPDXRef-Root",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-D0",
                },
            ],
        }
        out = tmp_path / "out.html"
        generate_html(
            doc, str(out),
            grype_data=SAMPLE_GRYPE_OUTPUT,
        )
        content = out.read_text()
        assert "CVE found (1 pkg)" in content
        assert "CVE-2023-1234" in content


class TestFacadeIntegration:
    """Verify GrypeScanner is wired into the facade."""

    def test_facade_has_grype_scanner(self):
        from app.pipeline.facade import AnalysisPipeline
        p = AnalysisPipeline()
        assert hasattr(p, "grype_scanner")
        assert isinstance(p.grype_scanner, GrypeScanner)

    def test_facade_accepts_custom_scanner(self):
        from app.pipeline.facade import AnalysisPipeline
        mock_scanner = MagicMock()
        p = AnalysisPipeline(grype_scanner=mock_scanner)
        assert p.grype_scanner is mock_scanner
