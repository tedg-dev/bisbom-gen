"""
Instrumented build with bomtrace for OmniBOR Analysis.

Runs pre-build steps, the instrumented build via bomtrace3/bomtrace2,
and generates OmniBOR ADG documents.

All steps here are Phase 1 (build + metadata capture):
clean, prebuild, instrumented build, and ADG generation.
Phase 2 (SPDX generation) lives in ``lang_runners``.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from app.config import lang_subdir, timestamp
from app.pipeline.timing import (
    StepMetrics, StepTimer, infer_parallelism,
)
from app.runner import CommandRunner


@dataclass
class BuildResult:
    """Result from ``build()``, ``build_java()``, or
    ``build_baseline()``.

    Carries success flag plus per-phase ``StepMetrics``
    so callers can assign Phase 1 vs Phase 2 timing.
    """

    success: bool = False
    steps: List[StepMetrics] = field(
        default_factory=list,
    )


class BomtraceBuilder:
    """Instruments the build with bomtrace and generates OmniBOR ADG.

    Works for both C/C++ (bomtrace3) and Go (bomtrace2 with
    Go-specific bomtrace.conf).  The tracer binary is specified
    in the omnibor config section passed to build().
    """

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def build(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=None, strategy=None,
    ):
        """Run pre-build steps, instrumented build, and ADG generation.

        Args:
            strategy: Optional ``InterceptionStrategy``.
                When provided, delegates command
                transformation and ADG generation to
                the strategy.  When ``None``, uses
                legacy hardcoded bomtrace behavior.

        Returns:
            ``BuildResult`` with per-phase metrics.
        """
        result = BuildResult()
        ts = run_ts or timestamp()
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )

        # --- Phase 1a: Clean ---
        clean_cmd = repo_cfg.get("clean_cmd")
        if clean_cmd:
            timer = StepTimer("clean", "phase1")
            with timer:
                self.runner.run(
                    clean_cmd, cwd=str(repo_dir),
                    description=(
                        f"Clean: {clean_cmd}"
                    ),
                )
                # Ignore clean_cmd exit code — it may
                # fail on a fresh clone
            result.steps.append(timer.metrics)

        # --- Phase 1b: Pre-build steps ---
        build_steps = repo_cfg["build_steps"]
        pre_steps = build_steps[:-1]
        if pre_steps:
            timer = StepTimer("prebuild", "phase1")
            with timer:
                for step in pre_steps:
                    rc = self.runner.run(
                        step, cwd=str(repo_dir),
                        description=(
                            f"Pre-build: {step[:60]}"
                        ),
                    )
                    if rc != 0:
                        print(
                            "[ERROR] Pre-build step "
                            f"failed: {step}"
                        )
                        result.steps.append(
                            timer.metrics
                        )
                        return result
            result.steps.append(timer.metrics)

        # --- Phase 1c: Instrumented build ---
        make_cmd = build_steps[-1]
        if strategy:
            instrumented, env = (
                strategy.instrument_command(
                    make_cmd, str(repo_dir),
                )
            )
        else:
            tracer = omnibor_cfg["tracer"]
            instrumented = f"{tracer} {make_cmd}"
            env = None

        parallelism = infer_parallelism(make_cmd)
        timer = StepTimer(
            "build", "phase1", parallelism,
        )
        with timer:
            rc = self.runner.run(
                instrumented, cwd=str(repo_dir),
                env=env,
                description=(
                    f"Instrumented build: "
                    f"{instrumented[:60]}"
                ),
            )
        result.steps.append(timer.metrics)
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return result

        # --- Phase 1d: ADG generation ---
        timer = StepTimer("adg", "phase1")
        adg_ok = True
        with timer:
            if strategy:
                adg_ok = bool(
                    strategy.generate_adg(
                        str(repo_dir), str(bom_dir),
                        omnibor_cfg,
                    )
                )
            else:
                create_bom = (
                    omnibor_cfg["create_bom_script"]
                )
                raw_logfile = omnibor_cfg["raw_logfile"]
                rc = self.runner.run(
                    f"{create_bom} -r {raw_logfile} "
                    f"-b {bom_dir}",
                    cwd=str(repo_dir),
                    description=(
                        "Generating OmniBOR ADG "
                        "documents"
                    ),
                )
                adg_ok = rc == 0
        # Append metrics AFTER the timer context exits so
        # the step records real timing (timer.metrics is
        # None until __exit__ runs).  This holds for both
        # the success and failure paths.
        result.steps.append(timer.metrics)
        if not adg_ok:
            print("[ERROR] ADG generation failed")
            return result

        print(
            "[OK] OmniBOR ADG documents "
            f"written to {bom_dir}"
        )
        result.success = True
        return result

    def build_baseline(
        self, repo_name, repo_cfg, paths_cfg,
    ):
        """Run non-instrumented build for baseline timing.

        Executes clean + prebuild + build WITHOUT any
        tracer (no bomtrace/strace).  Each step is timed
        separately — exactly mirroring the instrumented
        path — so the build step can be compared
        apples-to-apples against the instrumented build.

        Returns:
            ``BuildResult`` with per-step metrics, or
            ``None`` if the build failed.
        """
        result = BuildResult()
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        build_steps = repo_cfg["build_steps"]
        clean_cmd = repo_cfg.get("clean_cmd")
        pre_steps = build_steps[:-1]
        make_cmd = build_steps[-1]

        # --- Clean (ignore exit code) ---
        if clean_cmd:
            timer = StepTimer("clean", "phase1")
            with timer:
                self.runner.run(
                    clean_cmd, cwd=str(repo_dir),
                    description=(
                        f"Clean: {clean_cmd}"
                    ),
                )
            result.steps.append(timer.metrics)

        # --- Pre-build steps ---
        if pre_steps:
            timer = StepTimer("prebuild", "phase1")
            with timer:
                for step in pre_steps:
                    rc = self.runner.run(
                        step, cwd=str(repo_dir),
                        description=(
                            f"Pre-build: {step[:60]}"
                        ),
                    )
                    if rc != 0:
                        print(
                            "[ERROR] Baseline pre-build "
                            f"failed: {step}"
                        )
                        result.steps.append(
                            timer.metrics
                        )
                        return result
            result.steps.append(timer.metrics)

        # --- Build (NO tracer) ---
        parallelism = infer_parallelism(make_cmd)
        timer = StepTimer(
            "build", "phase1", parallelism,
        )
        with timer:
            rc = self.runner.run(
                make_cmd, cwd=str(repo_dir),
                description=(
                    f"Baseline: {make_cmd[:60]}"
                ),
            )
        result.steps.append(timer.metrics)
        if rc != 0:
            print(
                "[ERROR] Baseline build failed"
            )
            return result

        result.success = True
        return result

    def build_java(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_java_cfg,
        run_ts=None,
    ):
        """Run Java build with strace, then bomsh_create_bom_java.py.

        Java uses a different approach than C/C++/Rust/Go:
        1. Build with strace to capture file I/O (openat syscalls)
        2. Run bomsh_create_bom_java.py with strace log to create treedb

        Returns:
            ``BuildResult`` with per-phase metrics.
        """
        result = BuildResult()
        ts = run_ts or timestamp()
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        bom_dir.mkdir(parents=True, exist_ok=True)
        meta_dir = bom_dir / "metadata" / "bomsh"
        meta_dir.mkdir(parents=True, exist_ok=True)

        strace_opts = omnibor_java_cfg["strace_opts"]
        strace_log = omnibor_java_cfg["strace_logfile"]
        create_bom = omnibor_java_cfg["create_bom_script"]

        # --- Phase 1a: Clean ---
        clean_cmd = repo_cfg.get("clean_cmd")
        if clean_cmd:
            timer = StepTimer("clean", "phase1")
            with timer:
                self.runner.run(
                    clean_cmd, cwd=str(repo_dir),
                    description=(
                        f"Clean: {clean_cmd}"
                    ),
                )
            result.steps.append(timer.metrics)

        # Gradle's `clean` task does not clean
        # buildSrc/build/ — it is an included build
        # with its own lifecycle.  When cached classes
        # exist, Gradle skips recompilation and strace
        # never sees the .java file opens.  Remove
        # buildSrc/build/ to force a full recompile so
        # strace captures all source file access.
        buildsrc_build = repo_dir / "buildSrc" / "build"
        if buildsrc_build.is_dir():
            shutil.rmtree(str(buildsrc_build))
            print(
                "[OK] Cleaned buildSrc/build "
                "(Gradle included build cache)"
            )

        # --- Phase 1b: Pre-build steps ---
        build_steps = repo_cfg["build_steps"]
        pre_steps = build_steps[:-1]
        if pre_steps:
            timer = StepTimer("prebuild", "phase1")
            with timer:
                for step in pre_steps:
                    rc = self.runner.run(
                        step, cwd=str(repo_dir),
                        description=(
                            f"Pre-build: {step[:60]}"
                        ),
                    )
                    if rc != 0:
                        print(
                            "[ERROR] Pre-build step "
                            f"failed: {step}"
                        )
                        result.steps.append(
                            timer.metrics
                        )
                        return result
            result.steps.append(timer.metrics)

        # --- Phase 1c: Instrumented build ---
        build_cmd = build_steps[-1]
        instrumented = (
            f"strace {strace_opts} -o {strace_log} "
            f"{build_cmd}"
        )
        parallelism = infer_parallelism(build_cmd)
        timer = StepTimer(
            "build", "phase1", parallelism,
        )
        with timer:
            rc = self.runner.run(
                instrumented, cwd=str(repo_dir),
                description=(
                    f"Instrumented build: "
                    f"strace {build_cmd[:40]}"
                ),
            )
        result.steps.append(timer.metrics)
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return result

        # --- Phase 1d: ADG generation ---
        timer = StepTimer("adg", "phase1")
        with timer:
            treedb_file = (
                meta_dir / "bomsh_omnibor_treedb"
            )
            rc = self.runner.run(
                f"{create_bom} -r {repo_dir} "
                f"-j {treedb_file}",
                cwd=str(repo_dir),
                description=(
                    "Generating OmniBOR treedb "
                    "for Java workspace"
                ),
            )
            if rc != 0:
                print(
                    "[ERROR] "
                    "bomsh_create_bom_java.py failed"
                )
                result.steps.append(timer.metrics)
                return result

            # Archive strace log to metadata dir
            strace_archive = (
                meta_dir / "strace_java_logfile"
            )
            strace_src = Path(strace_log)
            if strace_src.exists():
                shutil.copy2(
                    str(strace_src),
                    str(strace_archive),
                )
                print(
                    "[OK] strace log archived to "
                    f"{strace_archive}"
                )
            else:
                print(
                    f"[WARN] strace log not found: "
                    f"{strace_log}"
                )
        result.steps.append(timer.metrics)

        print(
            "[OK] OmniBOR treedb written to "
            f"{treedb_file}"
        )
        result.success = True
        return result
