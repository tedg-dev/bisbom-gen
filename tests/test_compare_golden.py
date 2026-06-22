"""Tests for scripts/compare_golden.py.

Verifies the golden-comparison reporter detects EVERY kind of
difference: package identity/fields, file identity, file
checksums, and relationships. These tests guard against the
under-reporting bug where an equal file COUNT masked a complete
file-set swap.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

# Load scripts/compare_golden.py (not an importable package).
_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "compare_golden.py"
)
_spec = importlib.util.spec_from_file_location(
    "compare_golden", _SCRIPT,
)
compare_golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_golden)


def _spdx(packages=None, files=None, relationships=None):
    return {
        "packages": packages or [],
        "files": files or [],
        "relationships": relationships or [],
    }


def _file(name, sha="a" * 40):
    return {
        "SPDXID": f"SPDXRef-File-{name}",
        "fileName": name,
        "checksums": [
            {"algorithm": "SHA1", "checksumValue": sha},
        ],
    }


def _pkg(spdxid, name, version="1.0", **extra):
    p = {
        "SPDXID": spdxid,
        "name": name,
        "versionInfo": version,
    }
    p.update(extra)
    return p


class _CompareHarness(unittest.TestCase):
    def _compare(self, golden, new):
        with tempfile.TemporaryDirectory() as td:
            gp = Path(td) / "g.spdx.json"
            np_ = Path(td) / "n.spdx.json"
            gp.write_text(json.dumps(golden))
            np_.write_text(json.dumps(new))
            return compare_golden.compare(gp, np_)


class TestFileChecksumHelper(unittest.TestCase):
    def test_returns_sha1(self):
        f = _file("a.java", sha="b" * 40)
        self.assertEqual(
            compare_golden._file_checksum(f), "b" * 40,
        )

    def test_no_checksums_returns_empty(self):
        self.assertEqual(
            compare_golden._file_checksum({"checksums": []}),
            "",
        )

    def test_falls_back_to_first_when_no_sha1(self):
        f = {
            "checksums": [
                {"algorithm": "SHA256", "checksumValue": "x"},
            ],
        }
        self.assertEqual(
            compare_golden._file_checksum(f), "x",
        )


class TestCappedList(unittest.TestCase):
    def test_caps_and_reports_remainder(self):
        diffs = []
        items = [f"item{i:03d}" for i in range(25)]
        compare_golden._capped_list(
            diffs, "Things", items, "-", cap=20,
        )
        # header + 20 items + "... and 5 more"
        self.assertEqual(len(diffs), 22)
        self.assertIn("Things (25):", diffs[0])
        self.assertIn("and 5 more", diffs[-1])


class TestCompare(_CompareHarness):
    def test_identical_no_diff(self):
        doc = _spdx(
            packages=[_pkg("SPDXRef-P", "app")],
            files=[_file("a.java"), _file("b.java")],
        )
        self.assertFalse(self._compare(doc, doc))

    def test_file_swap_same_count_detected(self):
        """Equal file count but different identities must be
        flagged (the original under-reporting bug)."""
        golden = _spdx(files=[_file("a.java"), _file("b.java")])
        new = _spdx(files=[_file("a.java"), _file("c.java")])
        self.assertTrue(self._compare(golden, new))

    def test_checksum_change_detected(self):
        golden = _spdx(files=[_file("a.java", sha="1" * 40)])
        new = _spdx(files=[_file("a.java", sha="2" * 40)])
        self.assertTrue(self._compare(golden, new))

    def test_package_version_change_detected(self):
        golden = _spdx(packages=[_pkg("SPDXRef-P", "app", "1.0")])
        new = _spdx(packages=[_pkg("SPDXRef-P", "app", "2.0")])
        self.assertTrue(self._compare(golden, new))

    def test_package_field_change_detected(self):
        golden = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", supplier="Org: A",
            )],
        )
        new = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", supplier="Org: B",
            )],
        )
        self.assertTrue(self._compare(golden, new))

    def test_missing_and_added_files_detected(self):
        golden = _spdx(files=[_file("only_golden.java")])
        new = _spdx(files=[_file("only_new.java")])
        self.assertTrue(self._compare(golden, new))

    def test_source_info_change_detected(self):
        golden = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", sourceInfo="from A",
            )],
        )
        new = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", sourceInfo="from B",
            )],
        )
        self.assertTrue(self._compare(golden, new))

    def test_comment_change_detected(self):
        golden = _spdx(
            packages=[_pkg("SPDXRef-P", "app", comment="old")],
        )
        new = _spdx(
            packages=[_pkg("SPDXRef-P", "app", comment="new")],
        )
        self.assertTrue(self._compare(golden, new))

    def test_source_info_rename_detected(self):
        """Legacy packageSourceInfo -> sourceInfo rename must
        surface, not be silently ignored."""
        golden = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", packageSourceInfo="built X",
            )],
        )
        new = _spdx(
            packages=[_pkg(
                "SPDXRef-P", "app", sourceInfo="built X",
            )],
        )
        self.assertTrue(self._compare(golden, new))


if __name__ == "__main__":
    unittest.main()
