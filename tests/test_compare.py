#!/usr/bin/env python3
"""
Tests for app/compare.py — class-based SBOM comparison.

Uses unittest.mock to avoid real file system dependencies.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add app/ to path so we can import compare
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import compare
from compare import (
    SpdxLoader, PackageExtractor, SbomComparator,
    ReportGenerator, ComparisonPipeline,
    load_config, timestamp,
)


# ============================================================
# Utilities
# ============================================================

class TestLoadConfig(unittest.TestCase):
    """Tests for load_config()."""

    def test_loads_real_config(self):
        config = load_config()
        self.assertIn("repos", config)
        self.assertIn("paths", config)

    def test_loads_custom_path(self):
        import yaml
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            yaml.dump({"test": True}, f)
            tmp = Path(f.name)
        result = load_config(tmp)
        self.assertTrue(result["test"])
        tmp.unlink()


class TestTimestamp(unittest.TestCase):
    """Tests for timestamp()."""

    def test_format(self):
        ts = timestamp()
        self.assertRegex(
            ts, r"\d{4}-\d{2}-\d{2}_\d{4}"
        )


# ============================================================
# SpdxLoader
# ============================================================

class TestSpdxLoader(unittest.TestCase):
    """Tests for SpdxLoader."""

    def test_load_valid_spdx(self):
        spdx = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {"name": "curl", "versionInfo": "8.0"},
                {"name": "zlib", "versionInfo": "1.3"},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(spdx, f)
            tmp = Path(f.name)

        data, pkgs = SpdxLoader.load(str(tmp))
        self.assertEqual(len(pkgs), 2)
        self.assertEqual(
            data["spdxVersion"], "SPDX-2.3"
        )
        tmp.unlink()

    def test_load_no_packages(self):
        spdx = {"spdxVersion": "SPDX-2.3"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(spdx, f)
            tmp = Path(f.name)

        _, pkgs = SpdxLoader.load(str(tmp))
        self.assertEqual(pkgs, [])
        tmp.unlink()

    def test_find_latest_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "a_omnibor_01.spdx.json"
            p2 = Path(tmpdir) / "a_omnibor_02.spdx.json"
            p1.write_text("{}")
            p2.write_text("{}")

            result = SpdxLoader.find_latest(
                tmpdir, "a_omnibor_*.spdx.json"
            )
            self.assertIsNotNone(result)

    def test_find_latest_no_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = SpdxLoader.find_latest(
                tmpdir, "*.spdx.json"
            )
            self.assertIsNone(result)

    def test_find_latest_no_dir(self):
        result = SpdxLoader.find_latest(
            "/nonexistent/dir", "*.json"
        )
        self.assertIsNone(result)


# ============================================================
# PackageExtractor
# ============================================================

class TestPackageExtractor(unittest.TestCase):
    """Tests for PackageExtractor."""

    def test_extract_names(self):
        pkgs = [
            {"name": "Curl"},
            {"name": "zlib"},
            {"name": "  OpenSSL  "},
            {"name": ""},
        ]
        names = PackageExtractor.extract_names(pkgs)
        self.assertEqual(
            names, {"curl", "zlib", "openssl"}
        )

    def test_extract_names_empty(self):
        self.assertEqual(
            PackageExtractor.extract_names([]),
            set(),
        )

    def test_extract_map(self):
        pkgs = [
            {
                "name": "Curl",
                "versionInfo": "8.0",
                "supplier": "curl.se",
                "SPDXID": "SPDXRef-curl",
            },
        ]
        m = PackageExtractor.extract_map(pkgs)
        self.assertIn("curl", m)
        self.assertEqual(m["curl"]["version"], "8.0")
        self.assertEqual(
            m["curl"]["supplier"], "curl.se"
        )
        self.assertEqual(
            m["curl"]["spdxId"], "SPDXRef-curl"
        )

    def test_extract_map_defaults(self):
        pkgs = [{"name": "zlib"}]
        m = PackageExtractor.extract_map(pkgs)
        self.assertEqual(
            m["zlib"]["version"], "UNKNOWN"
        )
        self.assertEqual(
            m["zlib"]["supplier"], "UNKNOWN"
        )

    def test_extract_map_skips_empty(self):
        pkgs = [{"name": ""}, {"other": "x"}]
        m = PackageExtractor.extract_map(pkgs)
        self.assertEqual(m, {})


# ============================================================
# SbomComparator
# ============================================================

class TestSbomComparator(unittest.TestCase):
    """Tests for SbomComparator."""

    def _pkgs(self, names_versions):
        return [
            {
                "name": n,
                "versionInfo": v,
            }
            for n, v in names_versions
        ]

    def test_compare_identical(self):
        pkgs = self._pkgs([
            ("curl", "8.0"), ("zlib", "1.3"),
        ])
        comp = SbomComparator()
        result = comp.compare(pkgs, pkgs)
        self.assertEqual(len(result["common"]), 2)
        self.assertEqual(
            len(result["bisbom_only"]), 0
        )
        self.assertEqual(
            len(result["binary_only"]), 0
        )
        self.assertEqual(
            len(result["version_match"]), 2
        )

    def test_compare_disjoint(self):
        bisbom = self._pkgs([("curl", "8.0")])
        binary = self._pkgs([("zlib", "1.3")])
        comp = SbomComparator()
        result = comp.compare(bisbom, binary)
        self.assertEqual(len(result["common"]), 0)
        self.assertEqual(
            result["bisbom_only"], ["curl"]
        )
        self.assertEqual(
            result["binary_only"], ["zlib"]
        )

    def test_compare_version_mismatch(self):
        bisbom = self._pkgs([("curl", "8.0")])
        binary = self._pkgs([("curl", "7.0")])
        comp = SbomComparator()
        result = comp.compare(bisbom, binary)
        self.assertEqual(len(result["common"]), 1)
        self.assertEqual(
            len(result["version_mismatch"]), 1
        )
        self.assertEqual(
            result["version_mismatch"][0],
            ("curl", "8.0", "7.0"),
        )

    def test_compare_partial_overlap(self):
        bisbom = self._pkgs([
            ("curl", "8.0"), ("openssl", "3.0"),
        ])
        binary = self._pkgs([
            ("curl", "8.0"), ("zlib", "1.3"),
        ])
        comp = SbomComparator()
        result = comp.compare(bisbom, binary)
        self.assertEqual(
            result["common"], ["curl"]
        )
        self.assertEqual(
            result["bisbom_only"], ["openssl"]
        )
        self.assertEqual(
            result["binary_only"], ["zlib"]
        )

    def test_compare_empty(self):
        comp = SbomComparator()
        result = comp.compare([], [])
        self.assertEqual(
            result["bisbom_total"], 0
        )
        self.assertEqual(
            result["binary_total"], 0
        )

    def test_injected_extractor(self):
        ext = MagicMock()
        ext.extract_names.return_value = set()
        ext.extract_map.return_value = {}
        comp = SbomComparator(extractor=ext)
        comp.compare([], [])
        self.assertEqual(
            ext.extract_names.call_count, 2
        )


# ============================================================
# ReportGenerator
# ============================================================

class TestReportGenerator(unittest.TestCase):
    """Tests for ReportGenerator."""

    def _result(self):
        return {
            "bisbom_total": 2,
            "binary_total": 2,
            "common": ["curl"],
            "bisbom_only": ["openssl"],
            "binary_only": ["zlib"],
            "version_match": [("curl", "8.0")],
            "version_mismatch": [],
            "bisbom_map": {
                "curl": {
                    "name": "curl",
                    "version": "8.0",
                },
                "openssl": {
                    "name": "openssl",
                    "version": "3.0",
                },
            },
            "binary_map": {
                "curl": {
                    "name": "curl",
                    "version": "8.0",
                },
                "zlib": {
                    "name": "zlib",
                    "version": "1.3",
                },
            },
        }

    def test_generate_report(self):
        report = ReportGenerator.generate(
            "curl", self._result(),
            "bisbom.spdx.json",
            "binary.spdx.json",
        )
        self.assertIn("curl", report)
        self.assertIn("SBOM Comparison Report", report)
        self.assertIn("bisbom.spdx.json", report)
        self.assertIn("binary.spdx.json", report)
        self.assertIn("openssl", report)
        self.assertIn("zlib", report)

    def test_report_overlap_percentage(self):
        report = ReportGenerator.generate(
            "curl", self._result(),
            "a.json", "b.json",
        )
        self.assertIn("33.3%", report)

    def test_report_with_version_mismatch(self):
        result = self._result()
        result["version_mismatch"] = [
            ("curl", "8.0", "7.0")
        ]
        report = ReportGenerator.generate(
            "curl", result, "a.json", "b.json",
        )
        self.assertIn("Version Mismatches", report)
        self.assertIn("7.0", report)

    def test_report_no_version_mismatch(self):
        report = ReportGenerator.generate(
            "curl", self._result(),
            "a.json", "b.json",
        )
        self.assertNotIn(
            "Version Mismatches", report
        )

    def test_report_empty_result(self):
        result = {
            "bisbom_total": 0,
            "binary_total": 0,
            "common": [],
            "bisbom_only": [],
            "binary_only": [],
            "version_match": [],
            "version_mismatch": [],
            "bisbom_map": {},
            "binary_map": {},
        }
        report = ReportGenerator.generate(
            "empty", result, "a.json", "b.json",
        )
        self.assertIn("0.0%", report)

    def test_report_footer(self):
        report = ReportGenerator.generate(
            "curl", self._result(),
            "a.json", "b.json",
        )
        self.assertIn(
            "Generated by bisbom-gen", report
        )


# ============================================================
# ComparisonPipeline
# ============================================================

class TestComparisonPipeline(unittest.TestCase):
    """Tests for ComparisonPipeline facade."""

    def test_default_construction(self):
        p = ComparisonPipeline()
        self.assertIsInstance(p.loader, SpdxLoader)
        self.assertIsInstance(
            p.comparator, SbomComparator
        )
        self.assertIsInstance(
            p.reporter, ReportGenerator
        )

    def test_injected_components(self):
        loader = MagicMock()
        p = ComparisonPipeline(loader=loader)
        self.assertIs(p.loader, loader)


# ============================================================
# main() CLI
# ============================================================

class TestMainMissingFiles(unittest.TestCase):
    """Tests for main() with missing SPDX files."""

    @patch("compare.ComparisonPipeline")
    @patch(
        "sys.argv",
        ["compare.py", "--repo", "curl"],
    )
    def test_no_bisbom_file(self, mock_cls):
        p = ComparisonPipeline(
            loader=MagicMock(),
            comparator=MagicMock(),
            reporter=MagicMock(),
        )
        p.loader.find_latest.return_value = None
        mock_cls.return_value = p

        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                compare.main()
            self.assertEqual(cm.exception.code, 1)

    @patch("compare.ComparisonPipeline")
    @patch(
        "sys.argv",
        ["compare.py", "--repo", "curl"],
    )
    def test_no_binary_file(self, mock_cls):
        p = ComparisonPipeline(
            loader=MagicMock(),
            comparator=MagicMock(),
            reporter=MagicMock(),
        )
        p.loader.find_latest.side_effect = [
            "/tmp/omnibor.json", None,
        ]
        mock_cls.return_value = p

        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                compare.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainFullRun(unittest.TestCase):
    """Tests for main() full comparison run."""

    @patch("compare.ComparisonPipeline")
    @patch(
        "sys.argv",
        [
            "compare.py", "--repo", "curl",
            "--bisbom-file", "/tmp/o.json",
            "--binary-file", "/tmp/b.json",
        ],
    )
    def test_full_run(self, mock_cls):
        p = ComparisonPipeline(
            loader=MagicMock(),
            comparator=MagicMock(),
            reporter=MagicMock(),
        )
        p.loader.load.return_value = (
            {}, [{"name": "curl"}]
        )
        p.comparator.compare.return_value = {
            "common": ["curl"],
            "bisbom_only": [],
            "binary_only": [],
            "version_mismatch": [],
        }
        p.reporter.generate.return_value = "# Report"
        mock_cls.return_value = p

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "compare.load_config",
                return_value={
                    "paths": {
                        "output_dir": tmpdir,
                    },
                    "repos": {
                        "curl": {
                            "language": "c-cpp",
                        },
                    },
                },
            ):
                with patch("builtins.print"):
                    compare.main()

        p.loader.load.assert_called()
        p.comparator.compare.assert_called_once()
        p.reporter.generate.assert_called_once()


class TestMainAutoDiscover(unittest.TestCase):
    """Tests for main() auto-discovering SPDX files."""

    @patch("compare.ComparisonPipeline")
    @patch(
        "sys.argv",
        ["compare.py", "--repo", "curl"],
    )
    def test_auto_discover(self, mock_cls):
        p = ComparisonPipeline(
            loader=MagicMock(),
            comparator=MagicMock(),
            reporter=MagicMock(),
        )
        p.loader.find_latest.side_effect = [
            "/tmp/omnibor.json",
            "/tmp/binary.json",
        ]
        p.loader.load.return_value = ({}, [])
        p.comparator.compare.return_value = {
            "common": [],
            "bisbom_only": [],
            "binary_only": [],
            "version_mismatch": [],
        }
        p.reporter.generate.return_value = "# Report"
        mock_cls.return_value = p

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "compare.load_config",
                return_value={
                    "paths": {
                        "output_dir": tmpdir,
                    },
                    "repos": {
                        "curl": {
                            "language": "c-cpp",
                        },
                    },
                },
            ):
                with patch("builtins.print"):
                    compare.main()

        self.assertEqual(
            p.loader.find_latest.call_count, 2
        )


if __name__ == "__main__":
    unittest.main()
