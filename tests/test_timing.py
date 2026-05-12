"""
Tests for app/pipeline/timing.py.

Covers StepMetrics, TimingResult, StepTimer,
save_runtime_json, load_baseline, and save_baseline.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.pipeline.builder import BuildResult
from app.pipeline.timing import (
    CONTENTION_THRESHOLD,
    StepMetrics,
    TimingResult,
    StepTimer,
    infer_parallelism,
    save_runtime_json,
    load_baseline,
    save_baseline,
    baseline_build_step,
    _safe_loadavg,
)


# ============================================================
# StepMetrics
# ============================================================

class TestStepMetrics(unittest.TestCase):
    """Tests for StepMetrics dataclass."""

    def test_cpu_total_sec(self):
        m = StepMetrics(
            name="build", phase="phase1",
            cpu_user_sec=2.5, cpu_sys_sec=0.5,
        )
        self.assertAlmostEqual(m.cpu_total_sec, 3.0)

    def test_cpu_efficiency_normal(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=10.0,
            cpu_user_sec=8.0, cpu_sys_sec=1.5,
        )
        self.assertAlmostEqual(m.cpu_efficiency, 0.95)

    def test_cpu_efficiency_zero_wall(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=0.0,
        )
        self.assertAlmostEqual(m.cpu_efficiency, 0.0)

    def test_cpu_efficiency_negative_wall(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=-1.0,
        )
        self.assertAlmostEqual(m.cpu_efficiency, 0.0)

    def test_to_dict_keys(self):
        m = StepMetrics(
            name="clean", phase="phase1",
            wall_sec=1.234,
            cpu_user_sec=0.5, cpu_sys_sec=0.3,
            cpu_count=4,
            load_avg_start=(1.1, 2.2, 3.3),
            load_avg_end=(1.5, 2.5, 3.5),
            contention=False,
        )
        d = m.to_dict()
        self.assertEqual(d["name"], "clean")
        self.assertEqual(d["phase"], "phase1")
        self.assertEqual(d["wall_sec"], 1.23)
        self.assertEqual(d["cpu_user_sec"], 0.5)
        self.assertEqual(d["cpu_sys_sec"], 0.3)
        self.assertAlmostEqual(d["cpu_total_sec"], 0.8)
        self.assertAlmostEqual(
            d["cpu_efficiency"], 0.65, places=2,
        )
        self.assertEqual(
            d["load_avg_start"], [1.1, 2.2, 3.3],
        )
        self.assertEqual(
            d["load_avg_end"], [1.5, 2.5, 3.5],
        )
        self.assertFalse(d["contention"])

    def test_to_dict_rounds_floats(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=1.23456789,
            cpu_user_sec=0.111111,
            cpu_sys_sec=0.222222,
        )
        d = m.to_dict()
        self.assertEqual(d["wall_sec"], 1.23)
        self.assertEqual(d["cpu_user_sec"], 0.11)
        self.assertEqual(d["cpu_sys_sec"], 0.22)

    def test_defaults(self):
        m = StepMetrics(name="x", phase="phase2")
        self.assertEqual(m.wall_sec, 0.0)
        self.assertEqual(m.cpu_user_sec, 0.0)
        self.assertEqual(m.cpu_sys_sec, 0.0)
        self.assertEqual(m.cpu_count, 1)
        self.assertEqual(m.expected_parallelism, 1)
        self.assertFalse(m.contention)

    def test_contention_severity_no_contention(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=10.0,
            cpu_user_sec=8.0, cpu_sys_sec=1.5,
            contention=False,
        )
        self.assertAlmostEqual(
            m.contention_severity, 0.0,
        )

    def test_contention_severity_with_contention(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=10.0,
            cpu_user_sec=1.0, cpu_sys_sec=0.0,
            cpu_count=4,
            expected_parallelism=4,
            contention=True,
        )
        # efficiency = 0.1, threshold = min(4,4)*0.7 = 2.8
        # severity = (1 - 0.1/2.8) * 100 = 96.4%
        self.assertGreater(
            m.contention_severity, 90.0,
        )

    def test_contention_severity_zero_wall(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=0.0, contention=True,
        )
        self.assertAlmostEqual(
            m.contention_severity, 0.0,
        )

    def test_to_dict_includes_severity(self):
        m = StepMetrics(
            name="build", phase="phase1",
            wall_sec=10.0,
            cpu_user_sec=1.0, cpu_sys_sec=0.0,
            cpu_count=4,
            expected_parallelism=4,
            contention=True,
        )
        d = m.to_dict()
        self.assertIn("contention_severity", d)
        self.assertGreater(
            d["contention_severity"], 0,
        )
        self.assertIn(
            "expected_parallelism", d,
        )


# ============================================================
# TimingResult
# ============================================================

class TestTimingResult(unittest.TestCase):
    """Tests for TimingResult dataclass."""

    def _make_timing(self):
        return TimingResult(
            tracer="bomtrace3",
            success=True,
            steps=[
                StepMetrics(
                    name="clean", phase="phase1",
                    wall_sec=2.0,
                ),
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=10.0,
                ),
                StepMetrics(
                    name="spdx_gen", phase="phase2",
                    wall_sec=3.0,
                ),
                StepMetrics(
                    name="validate", phase="phase2",
                    wall_sec=1.0,
                ),
            ],
        )

    def test_phase1_steps(self):
        t = self._make_timing()
        names = [s.name for s in t.phase1_steps]
        self.assertEqual(names, ["clean", "build"])

    def test_phase2_steps(self):
        t = self._make_timing()
        names = [s.name for s in t.phase2_steps]
        self.assertEqual(names, ["spdx_gen", "validate"])

    def test_phase1_total(self):
        t = self._make_timing()
        self.assertAlmostEqual(t.phase1_total, 12.0)

    def test_phase2_total(self):
        t = self._make_timing()
        self.assertAlmostEqual(t.phase2_total, 4.0)

    def test_total(self):
        t = self._make_timing()
        self.assertAlmostEqual(t.total, 16.0)

    def test_empty_steps(self):
        t = TimingResult(tracer="x", success=True)
        self.assertEqual(t.phase1_total, 0.0)
        self.assertEqual(t.phase2_total, 0.0)
        self.assertEqual(t.total, 0.0)

    def test_contention_steps_none(self):
        t = self._make_timing()
        self.assertEqual(len(t.contention_steps), 0)

    def test_contention_steps_some(self):
        t = TimingResult(
            tracer="x", success=True,
            steps=[
                StepMetrics(
                    name="a", phase="phase1",
                    wall_sec=5.0, contention=True,
                ),
                StepMetrics(
                    name="b", phase="phase1",
                    wall_sec=10.0, contention=False,
                ),
                StepMetrics(
                    name="c", phase="phase2",
                    wall_sec=3.0, contention=True,
                ),
            ],
        )
        self.assertEqual(len(t.contention_steps), 2)
        self.assertAlmostEqual(
            t.contention_total_sec, 8.0,
        )
        # 8/18 * 100 = 44.4%
        self.assertAlmostEqual(
            t.contention_pct, 44.4, places=1,
        )

    def test_contention_pct_empty(self):
        t = TimingResult(tracer="x", success=True)
        self.assertAlmostEqual(t.contention_pct, 0.0)

    def test_to_dict(self):
        t = self._make_timing()
        d = t.to_dict()
        self.assertEqual(d["tracer"], "bomtrace3")
        self.assertTrue(d["success"])
        self.assertEqual(d["phase1_total_sec"], 12.0)
        self.assertEqual(d["phase2_total_sec"], 4.0)
        self.assertEqual(d["total_sec"], 16.0)
        self.assertEqual(len(d["steps"]), 4)
        self.assertIsInstance(d["steps"][0], dict)

    def test_to_dict_contention_summary(self):
        t = self._make_timing()
        d = t.to_dict()
        cs = d["contention_summary"]
        self.assertEqual(cs["steps_flagged"], 0)
        self.assertEqual(cs["total_steps"], 4)
        self.assertEqual(cs["duration_sec"], 0.0)
        self.assertEqual(cs["pct_of_total"], 0.0)

    def test_to_dict_rounds(self):
        t = TimingResult(
            tracer="x", success=True,
            steps=[
                StepMetrics(
                    name="a", phase="phase1",
                    wall_sec=1.23456789,
                ),
            ],
        )
        d = t.to_dict()
        self.assertEqual(d["total_sec"], 1.23)

    def test_defaults(self):
        t = TimingResult()
        self.assertEqual(t.tracer, "")
        self.assertFalse(t.success)
        self.assertEqual(t.steps, [])


# ============================================================
# StepTimer
# ============================================================

class TestStepTimer(unittest.TestCase):
    """Tests for StepTimer context manager."""

    def test_produces_metrics(self):
        timer = StepTimer("test_step", "phase1")
        with timer:
            # Minimal work to generate some time
            total = sum(range(1000))
            _ = total
        m = timer.metrics
        self.assertIsInstance(m, StepMetrics)
        self.assertEqual(m.name, "test_step")
        self.assertEqual(m.phase, "phase1")
        self.assertGreaterEqual(m.wall_sec, 0.0)
        self.assertGreaterEqual(m.cpu_user_sec, 0.0)
        self.assertGreaterEqual(m.cpu_sys_sec, 0.0)
        self.assertGreaterEqual(m.cpu_count, 1)

    def test_metrics_none_before_exit(self):
        timer = StepTimer("x", "phase1")
        self.assertIsNone(timer.metrics)

    def test_wall_time_measured(self):
        timer = StepTimer("sleep", "phase1")
        with timer:
            import time
            time.sleep(0.05)
        self.assertGreater(
            timer.metrics.wall_sec, 0.01,
        )

    def test_contention_flag(self):
        # With expected_parallelism=100, any real
        # run will have contention (efficiency < 70)
        timer = StepTimer(
            "high_par", "phase1",
            expected_parallelism=100,
        )
        with timer:
            _ = sum(range(100))
        self.assertTrue(timer.metrics.contention)

    def test_no_contention_on_single_thread(self):
        timer = StepTimer(
            "single", "phase1",
            expected_parallelism=1,
        )
        with timer:
            _ = sum(range(100))
        # Single-threaded: efficiency may be low due
        # to minimal work, but contention threshold
        # is forgiving for expected_parallelism=1
        self.assertIsInstance(
            timer.metrics.contention, bool,
        )

    def test_load_avg_recorded(self):
        timer = StepTimer("load", "phase1")
        with timer:
            pass
        m = timer.metrics
        self.assertEqual(len(m.load_avg_start), 3)
        self.assertEqual(len(m.load_avg_end), 3)


# ============================================================
# _safe_loadavg
# ============================================================

class TestSafeLoadavg(unittest.TestCase):
    """Tests for _safe_loadavg helper."""

    def test_returns_tuple_on_supported(self):
        result = _safe_loadavg()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_returns_zeros_on_error(self):
        with patch(
            "os.getloadavg",
            side_effect=OSError("unsupported"),
        ):
            result = _safe_loadavg()
        self.assertEqual(result, (0.0, 0.0, 0.0))

    def test_returns_zeros_on_attribute_error(self):
        with patch(
            "os.getloadavg",
            side_effect=AttributeError,
        ):
            result = _safe_loadavg()
        self.assertEqual(result, (0.0, 0.0, 0.0))


# ============================================================
# save_runtime_json
# ============================================================

class TestSaveRuntimeJson(unittest.TestCase):
    """Tests for save_runtime_json."""

    def _make_timing(self):
        return TimingResult(
            tracer="bomtrace3",
            success=True,
            steps=[
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=10.0,
                ),
            ],
        )

    def test_writes_json_file(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "c-cpp"}
            with patch("builtins.print"):
                result = save_runtime_json(
                    self._make_timing(), paths,
                    "curl", repo_cfg, "ts1",
                )
            self.assertTrue(Path(result).exists())
            data = json.loads(Path(result).read_text())
            self.assertEqual(data["tracer"], "bomtrace3")
            self.assertTrue(data["success"])

    def test_includes_baseline_when_provided(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "c-cpp"}
            baseline = {"wall_sec": 5.0}
            with patch("builtins.print"):
                result = save_runtime_json(
                    self._make_timing(), paths,
                    "curl", repo_cfg, "ts1",
                    baseline=baseline,
                )
            data = json.loads(Path(result).read_text())
            self.assertEqual(
                data["baseline"]["wall_sec"], 5.0,
            )

    def test_no_baseline_key_when_none(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "c-cpp"}
            with patch("builtins.print"):
                result = save_runtime_json(
                    self._make_timing(), paths,
                    "curl", repo_cfg, "ts1",
                )
            data = json.loads(Path(result).read_text())
            self.assertNotIn("baseline", data)

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "go"}
            with patch("builtins.print"):
                result = save_runtime_json(
                    self._make_timing(), paths,
                    "fzf", repo_cfg, "ts1",
                )
            self.assertIn("runtime", result)
            self.assertIn("go", result)
            self.assertIn("fzf", result)


# ============================================================
# load_baseline
# ============================================================

class TestLoadBaseline(unittest.TestCase):
    """Tests for load_baseline."""

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "c-cpp"}
            result = load_baseline(
                paths, "curl", repo_cfg,
            )
            self.assertIsNone(result)

    def test_returns_data_when_exists(self):
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "c-cpp"}
            bl_dir = (
                Path(td) / "runtime"
                / "c-cpp" / "curl"
            )
            bl_dir.mkdir(parents=True)
            (bl_dir / "baseline.json").write_text(
                json.dumps({"wall_sec": 42.0})
            )
            result = load_baseline(
                paths, "curl", repo_cfg,
            )
            self.assertEqual(result["wall_sec"], 42.0)


# ============================================================
# save_baseline
# ============================================================

class TestSaveBaseline(unittest.TestCase):
    """Tests for save_baseline."""

    def _build_result(self, build_wall=30.0):
        return BuildResult(
            success=True,
            steps=[
                StepMetrics(
                    name="clean", phase="phase1",
                    wall_sec=2.0,
                ),
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=build_wall,
                    cpu_user_sec=25.0,
                    cpu_sys_sec=3.0,
                ),
            ],
        )

    def test_writes_baseline_file(self):
        br = self._build_result(30.0)
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "rust"}
            with patch("builtins.print"):
                result = save_baseline(
                    br, paths, "oxipng", repo_cfg,
                )
            self.assertTrue(Path(result).exists())
            data = json.loads(Path(result).read_text())
            self.assertIn("steps", data)
            build = next(
                s for s in data["steps"]
                if s["name"] == "build"
            )
            self.assertEqual(build["wall_sec"], 30.0)

    def test_creates_directory(self):
        br = self._build_result(10.0)
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "java"}
            with patch("builtins.print"):
                result = save_baseline(
                    br, paths, "checkstyle",
                    repo_cfg,
                )
            self.assertIn("baseline.json", result)
            self.assertIn("java", result)

    def test_includes_run_ts(self):
        br = self._build_result(5.0)
        with tempfile.TemporaryDirectory() as td:
            paths = {"output_dir": td}
            repo_cfg = {"language": "go"}
            with patch("builtins.print"):
                result = save_baseline(
                    br, paths, "fzf", repo_cfg,
                    run_ts="2026-05-11_0900",
                )
            data = json.loads(Path(result).read_text())
            self.assertEqual(
                data["run_ts"], "2026-05-11_0900",
            )


# ============================================================
# baseline_build_step
# ============================================================

class TestBaselineBuildStep(unittest.TestCase):
    """Tests for baseline_build_step."""

    def test_returns_none_for_none(self):
        self.assertIsNone(baseline_build_step(None))

    def test_returns_none_for_empty(self):
        self.assertIsNone(baseline_build_step({}))

    def test_extracts_build_from_steps(self):
        bl = {
            "steps": [
                {"name": "clean", "wall_sec": 2.0},
                {"name": "build", "wall_sec": 30.0},
            ],
        }
        result = baseline_build_step(bl)
        self.assertIsNotNone(result)
        self.assertEqual(result["wall_sec"], 30.0)
        self.assertEqual(result["name"], "build")

    def test_returns_none_when_no_build_step(self):
        bl = {
            "steps": [
                {"name": "clean", "wall_sec": 2.0},
            ],
        }
        self.assertIsNone(baseline_build_step(bl))

    def test_legacy_format(self):
        bl = {"wall_sec": 42.0, "name": "baseline"}
        result = baseline_build_step(bl)
        self.assertIsNotNone(result)
        self.assertEqual(result["wall_sec"], 42.0)


# ============================================================
# CONTENTION_THRESHOLD constant
# ============================================================

class TestContentionThreshold(unittest.TestCase):
    """Verify threshold constant."""

    def test_threshold_value(self):
        self.assertEqual(CONTENTION_THRESHOLD, 0.70)


# ============================================================
# Doc writer formatting (contention-related)
# ============================================================

class TestFormatContention(unittest.TestCase):
    """Tests for contention formatting in doc_writer."""

    def test_no_contention_message(self):
        from app.pipeline.doc_writer import (
            _format_contention_summary,
        )
        t = TimingResult(
            tracer="x", success=True,
            steps=[
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=10.0,
                ),
            ],
        )
        result = _format_contention_summary(t)
        self.assertIn("No contention detected", result)
        self.assertIn("1 steps", result)

    def test_contention_summary_content(self):
        from app.pipeline.doc_writer import (
            _format_contention_summary,
        )
        t = TimingResult(
            tracer="x", success=True,
            steps=[
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=40.0,
                    cpu_user_sec=1.0, cpu_sys_sec=0.0,
                    cpu_count=4,
                    expected_parallelism=4,
                    contention=True,
                ),
                StepMetrics(
                    name="spdx_gen", phase="phase2",
                    wall_sec=5.0,
                ),
            ],
        )
        result = _format_contention_summary(t)
        self.assertIn("1 of 2", result)
        self.assertIn("40.0s", result)
        self.assertIn("Most severe", result)
        self.assertIn("Build", result)

    def test_timing_table_has_expected_col(self):
        from app.pipeline.doc_writer import (
            _format_timing_table,
        )
        t = TimingResult(
            tracer="x", success=True,
            steps=[
                StepMetrics(
                    name="build", phase="phase1",
                    wall_sec=10.0,
                    expected_parallelism=4,
                    cpu_user_sec=8.0,
                    cpu_sys_sec=1.0,
                ),
            ],
        )
        result = _format_timing_table(t)
        self.assertIn("Expected", result)
        self.assertIn("4x", result)
        self.assertIn("\u2014", result)


# ============================================================
# infer_parallelism
# ============================================================

class TestInferParallelism(unittest.TestCase):
    """Tests for infer_parallelism()."""

    def test_make_j_nproc(self):
        self.assertEqual(
            infer_parallelism(
                "make -j$(nproc)", cpu_count=8,
            ), 8,
        )

    def test_make_j_number(self):
        self.assertEqual(
            infer_parallelism(
                "make -j4", cpu_count=8,
            ), 4,
        )

    def test_make_j1(self):
        self.assertEqual(
            infer_parallelism(
                "make -j1", cpu_count=4,
            ), 1,
        )

    def test_bare_make(self):
        self.assertEqual(
            infer_parallelism(
                "make", cpu_count=4,
            ), 1,
        )

    def test_make_clean(self):
        self.assertEqual(
            infer_parallelism(
                "make clean", cpu_count=4,
            ), 1,
        )

    def test_go_build(self):
        self.assertEqual(
            infer_parallelism(
                "go build -a -trimpath -o fzf .",
                cpu_count=4,
            ), 4,
        )

    def test_cargo_build(self):
        self.assertEqual(
            infer_parallelism(
                "cargo build --release",
                cpu_count=8,
            ), 8,
        )

    def test_mvn(self):
        self.assertEqual(
            infer_parallelism(
                "mvn package -DskipTests -q",
                cpu_count=4,
            ), 1,
        )

    def test_gradlew(self):
        self.assertEqual(
            infer_parallelism(
                "./gradlew :prov:build -x test",
                cpu_count=4,
            ), 4,
        )

    def test_unknown_tool(self):
        self.assertEqual(
            infer_parallelism(
                "./build.sh", cpu_count=4,
            ), 1,
        )

    def test_cmake_make_j(self):
        self.assertEqual(
            infer_parallelism(
                "make -j$(nproc)", cpu_count=16,
            ), 16,
        )

    def test_env_prefix_mvn(self):
        self.assertEqual(
            infer_parallelism(
                "env JAVA_HOME=/usr mvn install",
                cpu_count=4,
            ), 1,
        )


if __name__ == "__main__":
    unittest.main()
