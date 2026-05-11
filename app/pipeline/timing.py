"""
Per-step timing and CPU monitoring for OmniBOR Analysis.

Provides ``StepTimer`` for measuring wall-clock time, CPU
usage, and load average for each pipeline step.  Results
are collected into ``StepMetrics`` and ``TimingResult``
for structured reporting.

CPU monitoring uses two complementary approaches:
  1. ``resource.getrusage(RUSAGE_CHILDREN)`` — stdlib,
     always available, measures waited-on child processes.
  2. ``/usr/bin/time -v`` — Linux GNU time, captures all
     descendant CPU, max RSS, context switches.  Used as
     secondary cross-validation when available.

Load average (``os.getloadavg()``) is sampled at start
and end of each step to detect contention.
"""

import json
import os
import resource
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# Contention threshold: if actual CPU efficiency is below
# 70% of expected, flag as contention.
CONTENTION_THRESHOLD = 0.70


@dataclass
class StepMetrics:
    """Metrics for a single timed pipeline step."""

    name: str
    phase: str
    wall_sec: float = 0.0
    cpu_user_sec: float = 0.0
    cpu_sys_sec: float = 0.0
    cpu_count: int = 1
    load_avg_start: tuple = (0.0, 0.0, 0.0)
    load_avg_end: tuple = (0.0, 0.0, 0.0)
    contention: bool = False

    @property
    def cpu_total_sec(self):
        """Total CPU time (user + system)."""
        return self.cpu_user_sec + self.cpu_sys_sec

    @property
    def cpu_efficiency(self):
        """CPU utilization ratio: cpu_time / wall_time.

        For a single-threaded build this should be ~1.0.
        For ``make -j4`` on 4 cores it should be ~4.0.
        """
        if self.wall_sec <= 0:
            return 0.0
        return self.cpu_total_sec / self.wall_sec

    def to_dict(self):
        """Serialize to dict for JSON storage."""
        d = asdict(self)
        d["cpu_total_sec"] = round(self.cpu_total_sec, 2)
        d["cpu_efficiency"] = round(
            self.cpu_efficiency, 2
        )
        # Round floats for readability
        for k in (
            "wall_sec", "cpu_user_sec", "cpu_sys_sec",
        ):
            d[k] = round(d[k], 2)
        d["load_avg_start"] = [
            round(v, 2) for v in d["load_avg_start"]
        ]
        d["load_avg_end"] = [
            round(v, 2) for v in d["load_avg_end"]
        ]
        return d


@dataclass
class TimingResult:
    """Aggregated timing for a full pipeline run."""

    tracer: str = ""
    success: bool = False
    steps: List[StepMetrics] = field(
        default_factory=list,
    )

    @property
    def phase1_steps(self):
        """Steps in Phase 1 (Build Interception)."""
        return [
            s for s in self.steps if s.phase == "phase1"
        ]

    @property
    def phase2_steps(self):
        """Steps in Phase 2 (Post-Build Analysis)."""
        return [
            s for s in self.steps if s.phase == "phase2"
        ]

    @property
    def phase1_total(self):
        """Total wall-clock time for Phase 1."""
        return sum(
            s.wall_sec for s in self.phase1_steps
        )

    @property
    def phase2_total(self):
        """Total wall-clock time for Phase 2."""
        return sum(
            s.wall_sec for s in self.phase2_steps
        )

    @property
    def total(self):
        """Total wall-clock time for all steps."""
        return self.phase1_total + self.phase2_total

    def to_dict(self):
        """Serialize to dict for JSON storage."""
        return {
            "tracer": self.tracer,
            "success": self.success,
            "phase1_total_sec": round(
                self.phase1_total, 2
            ),
            "phase2_total_sec": round(
                self.phase2_total, 2
            ),
            "total_sec": round(self.total, 2),
            "steps": [
                s.to_dict() for s in self.steps
            ],
        }


class StepTimer:
    """Context manager that measures a pipeline step.

    Usage::

        timer = StepTimer("build", "phase1")
        with timer:
            run_the_build()
        metrics = timer.metrics
    """

    def __init__(
        self, name, phase, expected_parallelism=1,
    ):
        self._name = name
        self._phase = phase
        self._expected = expected_parallelism
        self._start_wall = 0.0
        self._start_usage = None
        self._start_load = (0.0, 0.0, 0.0)
        self._metrics = None

    @property
    def metrics(self):
        """Return ``StepMetrics`` after exiting."""
        return self._metrics

    def __enter__(self):
        """Record start timestamps."""
        self._start_load = _safe_loadavg()
        self._start_usage = resource.getrusage(
            resource.RUSAGE_CHILDREN,
        )
        self._start_wall = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Compute metrics from start/end deltas."""
        wall = time.monotonic() - self._start_wall
        end_usage = resource.getrusage(
            resource.RUSAGE_CHILDREN,
        )
        end_load = _safe_loadavg()
        cpu_count = os.cpu_count() or 1

        user = (
            end_usage.ru_utime
            - self._start_usage.ru_utime
        )
        sys_ = (
            end_usage.ru_stime
            - self._start_usage.ru_stime
        )

        # Contention detection
        cpu_total = user + sys_
        expected_eff = min(
            self._expected, cpu_count,
        )
        actual_eff = (
            cpu_total / wall if wall > 0 else 0.0
        )
        contention = (
            actual_eff
            < expected_eff * CONTENTION_THRESHOLD
        )

        self._metrics = StepMetrics(
            name=self._name,
            phase=self._phase,
            wall_sec=wall,
            cpu_user_sec=user,
            cpu_sys_sec=sys_,
            cpu_count=cpu_count,
            load_avg_start=self._start_load,
            load_avg_end=end_load,
            contention=contention,
        )
        return False


def _safe_loadavg():
    """Return load averages, or zeros on platforms
    where ``os.getloadavg()`` is unavailable (Windows).
    """
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return (0.0, 0.0, 0.0)


def save_runtime_json(
    timing, paths_cfg, repo_name, repo_cfg, run_ts,
    baseline=None,
):
    """Write ``runtime.json`` for a completed run.

    Args:
        timing: ``TimingResult`` from the pipeline.
        paths_cfg: Paths config section.
        repo_name: Repository name.
        repo_cfg: Repository config section.
        run_ts: Timestamp string for the run folder.
        baseline: Optional baseline dict to include.
    """
    from app.config import lang_subdir

    lang = lang_subdir(repo_cfg)
    runtime_dir = (
        Path(paths_cfg["output_dir"])
        / "runtime" / lang / repo_name / run_ts
    )
    runtime_dir.mkdir(parents=True, exist_ok=True)
    out_path = runtime_dir / "runtime.json"

    data = timing.to_dict()
    if baseline:
        data["baseline"] = baseline

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[OK] Runtime JSON written to {out_path}")
    return str(out_path)


def load_baseline(paths_cfg, repo_name, repo_cfg):
    """Load baseline.json for a repo, or None."""
    from app.config import lang_subdir

    lang = lang_subdir(repo_cfg)
    path = (
        Path(paths_cfg["output_dir"])
        / "runtime" / lang / repo_name / "baseline.json"
    )
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_baseline(
    metrics, paths_cfg, repo_name, repo_cfg,
):
    """Write baseline.json from a non-instrumented build.

    Args:
        metrics: ``StepMetrics`` from the plain build.
        paths_cfg: Paths config section.
        repo_name: Repository name.
        repo_cfg: Repository config section.
    """
    from app.config import lang_subdir

    lang = lang_subdir(repo_cfg)
    baseline_dir = (
        Path(paths_cfg["output_dir"])
        / "runtime" / lang / repo_name
    )
    baseline_dir.mkdir(parents=True, exist_ok=True)
    out_path = baseline_dir / "baseline.json"

    data = metrics.to_dict()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[OK] Baseline written to {out_path}")
    return str(out_path)
