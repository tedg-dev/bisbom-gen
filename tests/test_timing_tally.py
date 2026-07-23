"""
Tests for app/pipeline/timing_tally.py.

Covers runtime discovery, adg sub-step reading, row building,
aggregation, and markdown/console rendering.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.pipeline.timing_tally import (
    aggregate,
    build_row,
    collect_rows,
    find_latest_runtimes,
    format_console,
    format_markdown,
    read_adg_substeps,
)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _runtime(steps, total, success=True, tracer="dep:tree"):
    return {
        "tracer": tracer,
        "success": success,
        "total_sec": total,
        "steps": steps,
    }


def _step(name, phase, wall, category=None):
    d = {"name": name, "phase": phase, "wall_sec": wall}
    if category is not None:
        d["category"] = category
    return d


# ============================================================
# find_latest_runtimes
# ============================================================

class TestFindLatestRuntimes(unittest.TestCase):

    def test_missing_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            result = find_latest_runtimes(
                Path(td) / "nope"
            )
            self.assertEqual(result, {})

    def test_picks_latest_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_json(
                root / "jsoup" / "2026-01-01_0900"
                / "runtime.json", _runtime([], 1.0),
            )
            _write_json(
                root / "jsoup" / "2026-02-01_0900"
                / "runtime.json", _runtime([], 2.0),
            )
            result = find_latest_runtimes(root)
            self.assertIn("jsoup", result)
            self.assertIn("2026-02-01_0900", str(result["jsoup"]))

    def test_ignores_repo_without_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "empty" / "2026-01-01").mkdir(
                parents=True,
            )
            _write_json(
                root / "jsoup" / "2026-01-01"
                / "runtime.json", _runtime([], 1.0),
            )
            result = find_latest_runtimes(root)
            self.assertEqual(list(result), ["jsoup"])

    def test_ignores_non_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "stray.txt").write_text(
                "x", encoding="utf-8",
            )
            _write_json(
                root / "jsoup" / "2026-01-01"
                / "runtime.json", _runtime([], 1.0),
            )
            # a file where a ts dir is expected is ignored
            (root / "jsoup" / "note.txt").write_text(
                "y", encoding="utf-8",
            )
            result = find_latest_runtimes(root)
            self.assertEqual(list(result), ["jsoup"])


# ============================================================
# read_adg_substeps
# ============================================================

class TestReadAdgSubsteps(unittest.TestCase):

    def test_missing_file_returns_zeros(self):
        with tempfile.TemporaryDirectory() as td:
            out = read_adg_substeps(td, "jsoup", "ts1")
            self.assertEqual(
                out, {"treedb": 0.0, "dep_tree": 0.0},
            )

    def test_reads_values(self):
        with tempfile.TemporaryDirectory() as td:
            _write_json(
                Path(td) / "jsoup" / "ts1"
                / "adg_substeps.json",
                [
                    {"name": "treedb", "wall_sec": 3.5},
                    {"name": "dep_tree", "wall_sec": 1.2},
                ],
            )
            out = read_adg_substeps(td, "jsoup", "ts1")
            self.assertEqual(out["treedb"], 3.5)
            self.assertEqual(out["dep_tree"], 1.2)

    def test_malformed_json_returns_zeros(self):
        with tempfile.TemporaryDirectory() as td:
            p = (
                Path(td) / "jsoup" / "ts1"
                / "adg_substeps.json"
            )
            p.parent.mkdir(parents=True)
            p.write_text("{not json", encoding="utf-8")
            out = read_adg_substeps(td, "jsoup", "ts1")
            self.assertEqual(out["treedb"], 0.0)

    def test_ignores_unknown_substep_names(self):
        with tempfile.TemporaryDirectory() as td:
            _write_json(
                Path(td) / "jsoup" / "ts1"
                / "adg_substeps.json",
                [{"name": "other", "wall_sec": 9.9}],
            )
            out = read_adg_substeps(td, "jsoup", "ts1")
            self.assertEqual(out["treedb"], 0.0)


# ============================================================
# build_row
# ============================================================

class TestBuildRow(unittest.TestCase):

    def _setup(self, td):
        runtime_root = Path(td) / "runtime" / "java"
        omnibor_root = Path(td) / "omnibor" / "java"
        steps = [
            _step("build", "phase1", 20.0, "build"),
            _step("adg", "phase1", 8.0, "sidecar"),
            _step(
                "identity_index", "phase1", 1.5, "sidecar",
            ),
            _step("manifest", "phase1", 0.5, "sidecar"),
            _step("spdx_gen", "phase2", 3.0, "phase2"),
        ]
        rt = (
            runtime_root / "spring-boot" / "ts1"
            / "runtime.json"
        )
        _write_json(rt, _runtime(steps, 33.0))
        _write_json(
            omnibor_root / "spring-boot" / "ts1"
            / "adg_substeps.json",
            [
                {"name": "treedb", "wall_sec": 5.0},
                {"name": "dep_tree", "wall_sec": 3.0},
            ],
        )
        return rt, omnibor_root

    def test_row_fields(self):
        with tempfile.TemporaryDirectory() as td:
            rt, omnibor_root = self._setup(td)
            row = build_row(
                "spring-boot", rt, omnibor_root,
            )
            self.assertEqual(row["repo"], "spring-boot")
            self.assertEqual(row["run_ts"], "ts1")
            self.assertTrue(row["success"])
            self.assertEqual(row["ci_build_sec"], 20.0)
            self.assertEqual(row["sidecar_sec"], 10.0)
            self.assertEqual(row["treedb_sec"], 5.0)
            self.assertEqual(row["dep_tree_sec"], 3.0)
            self.assertEqual(row["identity_sec"], 1.5)
            self.assertEqual(row["manifest_sec"], 0.5)
            self.assertEqual(row["phase2_sec"], 3.0)
            self.assertEqual(row["total_sec"], 33.0)

    def test_row_without_category_uses_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_root = Path(td) / "runtime" / "java"
            omnibor_root = Path(td) / "omnibor" / "java"
            # No category keys — must fall back to name/phase.
            steps = [
                _step("build", "phase1", 10.0),
                _step("adg", "phase1", 4.0),
                _step("spdx_gen", "phase2", 2.0),
            ]
            rt = (
                runtime_root / "jsoup" / "ts1"
                / "runtime.json"
            )
            _write_json(rt, _runtime(steps, 16.0))
            row = build_row("jsoup", rt, omnibor_root)
            self.assertEqual(row["ci_build_sec"], 10.0)
            self.assertEqual(row["sidecar_sec"], 4.0)
            self.assertEqual(row["phase2_sec"], 2.0)


# ============================================================
# collect_rows
# ============================================================

class TestCollectRows(unittest.TestCase):

    def test_multiple_repos_sorted(self):
        with tempfile.TemporaryDirectory() as td:
            runtime_root = Path(td) / "runtime" / "java"
            for repo in ("zeta", "alpha"):
                _write_json(
                    runtime_root / repo / "ts1"
                    / "runtime.json",
                    _runtime(
                        [_step("build", "phase1", 1.0)], 1.0,
                    ),
                )
            rows = collect_rows(td, "java")
            self.assertEqual(
                [r["repo"] for r in rows],
                ["alpha", "zeta"],
            )

    def test_empty_when_no_runtimes(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(collect_rows(td, "java"), [])


# ============================================================
# aggregate
# ============================================================

class TestAggregate(unittest.TestCase):

    def test_sums_fields(self):
        rows = [
            {"ci_build_sec": 10.0, "sidecar_sec": 5.0,
             "treedb_sec": 3.0, "dep_tree_sec": 2.0,
             "identity_sec": 1.0, "manifest_sec": 0.5,
             "phase2_sec": 4.0, "total_sec": 19.5},
            {"ci_build_sec": 20.0, "sidecar_sec": 8.0,
             "treedb_sec": 5.0, "dep_tree_sec": 3.0,
             "identity_sec": 1.0, "manifest_sec": 0.5,
             "phase2_sec": 2.0, "total_sec": 30.0},
        ]
        agg = aggregate(rows)
        self.assertEqual(agg["ci_build_sec"], 30.0)
        self.assertEqual(agg["sidecar_sec"], 13.0)
        self.assertEqual(agg["total_sec"], 49.5)

    def test_empty_rows(self):
        agg = aggregate([])
        self.assertEqual(agg["ci_build_sec"], 0.0)


# ============================================================
# format_markdown / format_console
# ============================================================

class TestFormatMarkdown(unittest.TestCase):

    def _rows(self):
        return [{
            "repo": "spring-boot", "run_ts": "ts1",
            "success": True, "tracer": "dep:tree",
            "ci_build_sec": 21.7, "sidecar_sec": 60.3,
            "treedb_sec": 58.3, "dep_tree_sec": 23.5,
            "identity_sec": 1.5, "manifest_sec": 0.5,
            "phase2_sec": 3.0, "total_sec": 85.0,
        }]

    def test_header_and_row(self):
        md = format_markdown(self._rows())
        self.assertIn("| Repo |", md)
        self.assertIn("`spring-boot`", md)
        self.assertIn("21.70", md)

    def test_total_line(self):
        md = format_markdown(self._rows())
        self.assertIn("**TOTAL**", md)

    def test_empty_rows_header_only(self):
        md = format_markdown([])
        self.assertIn("| Repo |", md)
        self.assertNotIn("TOTAL", md)


class TestFormatConsole(unittest.TestCase):

    def _rows(self):
        return [{
            "repo": "spring-boot", "run_ts": "ts1",
            "success": True, "tracer": "dep:tree",
            "ci_build_sec": 21.7, "sidecar_sec": 60.3,
            "treedb_sec": 58.3, "dep_tree_sec": 23.5,
            "identity_sec": 1.5, "manifest_sec": 0.5,
            "phase2_sec": 3.0, "total_sec": 85.0,
        }]

    def test_contains_titles_and_data(self):
        out = format_console(self._rows())
        self.assertIn("CI/CD build", out)
        self.assertIn("spring-boot", out)
        self.assertIn("TOTAL", out)

    def test_empty_rows_titles_only(self):
        out = format_console([])
        self.assertIn("Repo", out)
        self.assertNotIn("TOTAL", out)


if __name__ == "__main__":
    unittest.main()
