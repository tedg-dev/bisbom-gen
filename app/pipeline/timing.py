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
import re
import resource
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# Contention threshold: if actual CPU efficiency is below
# 70% of expected, flag as contention.
CONTENTION_THRESHOLD = 0.70

# Regex for make -j<N> patterns
_MAKE_J_RE = re.compile(
    r"-j\s*(\d+|\$\(nproc\))"
)


def infer_parallelism(build_cmd, cpu_count=None):
    """Infer expected CPU parallelism from a build command.

    Uses build-tool conventions to determine how many cores
    a command is expected to utilize.  This is generic —
    no repo-specific logic.

    Build tool defaults:
      - ``make -j<N>``       → N (or cpu_count for nproc)
      - ``make`` (bare)      → 1
      - ``go build``         → cpu_count (GOMAXPROCS)
      - ``cargo build``      → cpu_count (num_cpus)
      - ``mvn``              → 1 (sequential lifecycle)
      - ``gradlew``/``gradle`` → cpu_count (worker pool)
      - Other                → 1 (conservative default)

    Args:
        build_cmd: The build command string.
        cpu_count: Available CPU cores (defaults to
            ``os.cpu_count()``).

    Returns:
        Expected parallelism as an integer ≥ 1.
    """
    cpus = cpu_count or os.cpu_count() or 1
    cmd = build_cmd.strip()

    # make with -j flag
    if "make" in cmd:
        m = _MAKE_J_RE.search(cmd)
        if m:
            val = m.group(1)
            if val == "$(nproc)":
                return cpus
            return max(1, int(val))
        # bare make → single-threaded
        return 1

    # Go: inherently parallel (GOMAXPROCS = cpu_count)
    if cmd.startswith("go "):
        return cpus

    # Rust/Cargo: parallel by default (num_cpus)
    if "cargo " in cmd:
        return cpus

    # Gradle: worker pool = cpu_count by default
    if "gradlew" in cmd or "gradle " in cmd:
        return cpus

    # Maven: sequential lifecycle by default
    if "mvn " in cmd:
        return 1

    # Conservative default for unknown tools
    return 1


@dataclass
class StepMetrics:
    """Metrics for a single timed pipeline step."""

    name: str
    phase: str
    wall_sec: float = 0.0
    cpu_user_sec: float = 0.0
    cpu_sys_sec: float = 0.0
    cpu_count: int = 1
    expected_parallelism: int = 1
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

    @property
    def contention_severity(self):
        """How far below threshold, as a percentage.

        Returns 0.0 if no contention.  Otherwise returns
        the deficit — e.g. 45.0 means actual efficiency
        was 45% below the contention threshold.
        """
        if not self.contention or self.wall_sec <= 0:
            return 0.0
        threshold = (
            min(self.expected_parallelism, self.cpu_count)
            * CONTENTION_THRESHOLD
        )
        if threshold <= 0:
            return 0.0
        actual = self.cpu_efficiency
        return max(
            0.0, (1.0 - actual / threshold) * 100
        )

    def to_dict(self):
        """Serialize to dict for JSON storage."""
        d = asdict(self)
        d["cpu_total_sec"] = round(self.cpu_total_sec, 2)
        d["cpu_efficiency"] = round(
            self.cpu_efficiency, 2
        )
        d["contention_severity"] = round(
            self.contention_severity, 1
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

    @property
    def contention_steps(self):
        """Steps flagged with contention."""
        return [
            s for s in self.steps if s.contention
        ]

    @property
    def contention_total_sec(self):
        """Wall-clock seconds spent in contended steps."""
        return sum(
            s.wall_sec for s in self.contention_steps
        )

    @property
    def contention_pct(self):
        """Percentage of total time under contention."""
        t = self.total
        if t <= 0:
            return 0.0
        return self.contention_total_sec / t * 100

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
            "contention_summary": {
                "steps_flagged": len(
                    self.contention_steps
                ),
                "total_steps": len(self.steps),
                "duration_sec": round(
                    self.contention_total_sec, 2
                ),
                "pct_of_total": round(
                    self.contention_pct, 1
                ),
            },
            "steps": [
                s.to_dict() for s in self.steps
            ],
        }


class StepTimer:
    """Context manager that measures a pipeline step.

    Measures both ``RUSAGE_SELF`` (Python in-process work)
    and ``RUSAGE_CHILDREN`` (subprocesses) so that CPU
    efficiency is accurate for all step types — subprocess-
    heavy build steps and Python-internal analysis steps.

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
        self._start_self = None
        self._start_children = None
        self._start_load = (0.0, 0.0, 0.0)
        self._metrics = None

    @property
    def metrics(self):
        """Return ``StepMetrics`` after exiting."""
        return self._metrics

    def __enter__(self):
        """Record start timestamps."""
        self._start_load = _safe_loadavg()
        self._start_self = resource.getrusage(
            resource.RUSAGE_SELF,
        )
        self._start_children = resource.getrusage(
            resource.RUSAGE_CHILDREN,
        )
        self._start_wall = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Compute metrics from start/end deltas."""
        wall = time.monotonic() - self._start_wall
        end_self = resource.getrusage(
            resource.RUSAGE_SELF,
        )
        end_children = resource.getrusage(
            resource.RUSAGE_CHILDREN,
        )
        end_load = _safe_loadavg()
        cpu_count = os.cpu_count() or 1

        # Sum RUSAGE_SELF (Python) + RUSAGE_CHILDREN
        # (subprocesses) for total CPU consumed by
        # this step.  This ensures Python-internal
        # steps (spdx_gen, validate) report real CPU
        # instead of zero.
        user = (
            (end_self.ru_utime
             - self._start_self.ru_utime)
            + (end_children.ru_utime
               - self._start_children.ru_utime)
        )
        sys_ = (
            (end_self.ru_stime
             - self._start_self.ru_stime)
            + (end_children.ru_stime
               - self._start_children.ru_stime)
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
            expected_parallelism=self._expected,
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
    build_result, paths_cfg, repo_name, repo_cfg,
    run_ts=None,
):
    """Write baseline.json from a non-instrumented build.

    Args:
        build_result: ``BuildResult`` from
            ``build_baseline()`` with per-step metrics.
        paths_cfg: Paths config section.
        repo_name: Repository name.
        repo_cfg: Repository config section.
        run_ts: Timestamp string for when baseline was
            captured.
    """
    from app.config import lang_subdir

    lang = lang_subdir(repo_cfg)
    baseline_dir = (
        Path(paths_cfg["output_dir"])
        / "runtime" / lang / repo_name
    )
    baseline_dir.mkdir(parents=True, exist_ok=True)
    out_path = baseline_dir / "baseline.json"

    data = {
        "steps": [
            s.to_dict() for s in build_result.steps
        ],
    }
    if run_ts:
        data["run_ts"] = run_ts
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[OK] Baseline written to {out_path}")
    return str(out_path)


def baseline_build_step(baseline):
    """Extract the build step from a baseline dict.

    Finds the step named ``build`` in the baseline's
    ``steps`` array for apples-to-apples comparison
    against the instrumented build step.

    Supports both the current format (steps array) and
    legacy format (single flat dict with ``wall_sec``).

    Returns:
        Step dict with ``wall_sec``, ``cpu_total_sec``,
        etc., or ``None`` if not found.
    """
    if not baseline:
        return None
    # Current format: {"steps": [...]}
    if "steps" in baseline:
        for step in baseline["steps"]:
            if step.get("name") == "build":
                return step
        return None
    # Legacy format: single flat dict (aggregate)
    if "wall_sec" in baseline:
        return baseline
    return None
