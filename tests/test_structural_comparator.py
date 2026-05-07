"""Tests for SPDX structural comparator."""

import json
import tempfile
import unittest
from pathlib import Path

from app.spdx.structural_comparator import (
    ComparisonResult,
    SpdxStructuralComparator,
)


def _minimal_spdx(
    packages=None, files=None,
    relationships=None,
):
    """Build a minimal valid SPDX 2.3 JSON dict."""
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "test-doc",
        "documentNamespace": (
            "https://example.com/test"
        ),
        "creationInfo": {
            "created": "2026-01-01T00:00:00Z",
            "creators": ["Tool: test"],
        },
        "packages": packages or [],
        "files": files or [],
        "relationships": relationships or [],
    }


def _write_spdx(path, doc):
    """Write an SPDX dict as JSON to path."""
    Path(path).write_text(
        json.dumps(doc, indent=2),
        encoding="utf-8",
    )


class TestComparisonResult(unittest.TestCase):
    """Tests for ComparisonResult."""

    def test_empty_result_is_equivalent(self):
        r = ComparisonResult()
        self.assertTrue(r.is_equivalent)
        self.assertEqual(len(r.diffs), 0)

    def test_with_diff_not_equivalent(self):
        r = ComparisonResult()
        r.add_diff("packages", "missing: foo")
        self.assertFalse(r.is_equivalent)

    def test_summary_contains_paths(self):
        r = ComparisonResult(
            baseline_path="/a.json",
            candidate_path="/b.json",
        )
        s = r.summary()
        self.assertIn("/a.json", s)
        self.assertIn("/b.json", s)

    def test_summary_shows_equivalent(self):
        r = ComparisonResult()
        self.assertIn(
            "STRUCTURALLY EQUIVALENT", r.summary()
        )

    def test_summary_shows_diffs(self):
        r = ComparisonResult()
        r.add_diff("packages", "missing: foo")
        s = r.summary()
        self.assertIn("1 difference(s)", s)
        self.assertIn("missing: foo", s)


class TestIdenticalDocuments(unittest.TestCase):
    """Comparing identical documents should pass."""

    def test_identical_empty(self):
        cmp = SpdxStructuralComparator()
        doc = _minimal_spdx()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, doc)
            _write_spdx(b, doc)
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)

    def test_identical_with_packages(self):
        pkgs = [
            {
                "SPDXID": "SPDXRef-Pkg-1",
                "name": "jsoup",
                "versionInfo": "1.22.1",
                "filesAnalyzed": True,
            },
            {
                "SPDXID": "SPDXRef-Dep-0",
                "name": "jspecify",
                "versionInfo": "1.0.0",
                "filesAnalyzed": False,
            },
        ]
        doc = _minimal_spdx(packages=pkgs)
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, doc)
            _write_spdx(b, doc)
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)
        self.assertEqual(result.baseline_pkg_count, 2)
        self.assertEqual(result.candidate_pkg_count, 2)


class TestDynamicFieldsIgnored(unittest.TestCase):
    """Dynamic fields (UUID, timestamp) must be ignored."""

    def test_different_namespace_ignored(self):
        a_doc = _minimal_spdx()
        a_doc["documentNamespace"] = (
            "https://example.com/uuid-111"
        )
        b_doc = _minimal_spdx()
        b_doc["documentNamespace"] = (
            "https://example.com/uuid-222"
        )
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, a_doc)
            _write_spdx(b, b_doc)
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)

    def test_different_timestamp_ignored(self):
        a_doc = _minimal_spdx()
        a_doc["creationInfo"]["created"] = (
            "2026-01-01T00:00:00Z"
        )
        b_doc = _minimal_spdx()
        b_doc["creationInfo"]["created"] = (
            "2026-05-07T12:00:00Z"
        )
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, a_doc)
            _write_spdx(b, b_doc)
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)


class TestPackageDiffs(unittest.TestCase):
    """Package-level structural differences."""

    def test_missing_package(self):
        a_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": True},
            {"name": "guava", "versionInfo": "33.0",
             "filesAnalyzed": False},
        ]
        b_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": True},
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(packages=a_pkgs)
            )
            _write_spdx(
                b, _minimal_spdx(packages=b_pkgs)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        msgs = [d["message"] for d in result.diffs]
        self.assertTrue(
            any("guava" in m for m in msgs)
        )

    def test_extra_package(self):
        a_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": True},
        ]
        b_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": True},
            {"name": "re2j", "versionInfo": "1.8",
             "filesAnalyzed": False},
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(packages=a_pkgs)
            )
            _write_spdx(
                b, _minimal_spdx(packages=b_pkgs)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        msgs = [d["message"] for d in result.diffs]
        self.assertTrue(
            any("extra" in m and "re2j" in m
                for m in msgs)
        )

    def test_version_mismatch(self):
        a_pkgs = [
            {"name": "jsoup", "versionInfo": "1.22.1",
             "filesAnalyzed": True},
        ]
        b_pkgs = [
            {"name": "jsoup", "versionInfo": "1.22.2",
             "filesAnalyzed": True},
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(packages=a_pkgs)
            )
            _write_spdx(
                b, _minimal_spdx(packages=b_pkgs)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        msgs = [d["message"] for d in result.diffs]
        self.assertTrue(
            any("version mismatch" in m for m in msgs)
        )

    def test_files_analyzed_mismatch(self):
        a_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": True},
        ]
        b_pkgs = [
            {"name": "jsoup", "versionInfo": "1.0",
             "filesAnalyzed": False},
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(packages=a_pkgs)
            )
            _write_spdx(
                b, _minimal_spdx(packages=b_pkgs)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        msgs = [d["message"] for d in result.diffs]
        self.assertTrue(
            any("filesAnalyzed" in m for m in msgs)
        )


class TestFileDiffs(unittest.TestCase):
    """File-level structural differences."""

    def _make_files(self, count):
        return [
            {
                "SPDXID": f"SPDXRef-File-{i}",
                "fileName": f"src/File{i}.java",
                "checksums": [
                    {"algorithm": "SHA1",
                     "checksumValue": f"abc{i:04d}"},
                ],
            }
            for i in range(count)
        ]

    def test_identical_files_pass(self):
        files = self._make_files(100)
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(files=files)
            )
            _write_spdx(
                b, _minimal_spdx(files=files)
            )
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)
        self.assertEqual(
            result.file_count_diff_pct, 0.0
        )

    def test_within_tolerance_passes(self):
        """4% difference with 5% tolerance = pass."""
        a_files = self._make_files(100)
        b_files = self._make_files(96)
        cmp = SpdxStructuralComparator(tolerance_pct=5)
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(files=a_files)
            )
            _write_spdx(
                b, _minimal_spdx(files=b_files)
            )
            result = cmp.compare(a, b)
        # File count diff is within tolerance
        file_diffs = [
            d for d in result.diffs
            if d["category"] == "files"
        ]
        self.assertEqual(len(file_diffs), 0)

    def test_exceeds_tolerance_fails(self):
        """10% difference with 5% tolerance = fail."""
        a_files = self._make_files(100)
        b_files = self._make_files(90)
        cmp = SpdxStructuralComparator(tolerance_pct=5)
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(files=a_files)
            )
            _write_spdx(
                b, _minimal_spdx(files=b_files)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        file_diffs = [
            d for d in result.diffs
            if d["category"] == "files"
        ]
        self.assertGreater(len(file_diffs), 0)

    def test_both_empty_passes(self):
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(files=[])
            )
            _write_spdx(
                b, _minimal_spdx(files=[])
            )
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)


class TestRelationshipDiffs(unittest.TestCase):
    """Relationship-level structural differences."""

    def test_same_relationships_pass(self):
        rels = [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": "SPDXRef-Pkg",
                "relationshipType": "DESCRIBES",
            },
            {
                "spdxElementId": "SPDXRef-File-0",
                "relatedSpdxElement": "SPDXRef-Pkg",
                "relationshipType": "CONTAINED_BY",
            },
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(relationships=rels)
            )
            _write_spdx(
                b, _minimal_spdx(relationships=rels)
            )
            result = cmp.compare(a, b)
        self.assertTrue(result.is_equivalent)
        self.assertEqual(
            result.baseline_rel_types,
            {"DESCRIBES": 1, "CONTAINED_BY": 1},
        )

    def test_different_type_distribution(self):
        a_rels = [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": "SPDXRef-Pkg",
                "relationshipType": "DESCRIBES",
            },
            {
                "spdxElementId": "SPDXRef-Pkg",
                "relatedSpdxElement": "SPDXRef-Dep",
                "relationshipType": "DEPENDS_ON",
            },
        ]
        b_rels = [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": "SPDXRef-Pkg",
                "relationshipType": "DESCRIBES",
            },
        ]
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(
                a, _minimal_spdx(relationships=a_rels)
            )
            _write_spdx(
                b, _minimal_spdx(relationships=b_rels)
            )
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)
        msgs = [d["message"] for d in result.diffs]
        self.assertTrue(
            any("DEPENDS_ON" in m for m in msgs)
        )


class TestMetadataDiffs(unittest.TestCase):
    """SPDX metadata comparison."""

    def test_different_spdx_version_detected(self):
        a_doc = _minimal_spdx()
        a_doc["spdxVersion"] = "SPDX-2.3"
        b_doc = _minimal_spdx()
        b_doc["spdxVersion"] = "SPDX-2.2"
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, a_doc)
            _write_spdx(b, b_doc)
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)

    def test_different_license_detected(self):
        a_doc = _minimal_spdx()
        a_doc["dataLicense"] = "CC0-1.0"
        b_doc = _minimal_spdx()
        b_doc["dataLicense"] = "Apache-2.0"
        cmp = SpdxStructuralComparator()
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            _write_spdx(a, a_doc)
            _write_spdx(b, b_doc)
            result = cmp.compare(a, b)
        self.assertFalse(result.is_equivalent)


class TestGoldenFileComparison(unittest.TestCase):
    """Test with real golden files if they exist."""

    GOLDEN_DIR = Path(
        "tests/golden/spdx/java/jsoup"
    )

    @unittest.skipUnless(
        Path("tests/golden/spdx/java/jsoup/"
             "jsoup-1.22.1_build.spdx.json").exists(),
        "Golden files not present",
    )
    def test_golden_self_comparison(self):
        """Golden file compared to itself = equivalent."""
        golden = (
            self.GOLDEN_DIR
            / "jsoup-1.22.1_build.spdx.json"
        )
        cmp = SpdxStructuralComparator()
        result = cmp.compare(golden, golden)
        self.assertTrue(result.is_equivalent)
        self.assertGreater(
            result.baseline_pkg_count, 0
        )
        self.assertGreater(
            result.baseline_file_count, 0
        )

    @unittest.skipUnless(
        Path("tests/golden/spdx/java/jsoup/"
             "jsoup-1.22.1_analyzed.spdx.json").exists(),
        "Golden files not present",
    )
    def test_analyzed_vs_build_differs(self):
        """analyzed (no deps) vs build (with deps)
        should differ in packages."""
        analyzed = (
            self.GOLDEN_DIR
            / "jsoup-1.22.1_analyzed.spdx.json"
        )
        build = (
            self.GOLDEN_DIR
            / "jsoup-1.22.1_build.spdx.json"
        )
        cmp = SpdxStructuralComparator()
        result = cmp.compare(build, analyzed)
        self.assertFalse(result.is_equivalent)
        # Build has deps, analyzed doesn't
        self.assertGreater(
            result.baseline_pkg_count,
            result.candidate_pkg_count,
        )


if __name__ == "__main__":
    unittest.main()
