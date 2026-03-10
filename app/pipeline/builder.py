"""
Instrumented build with bomtrace for OmniBOR Analysis.

Runs pre-build steps, the instrumented build via bomtrace3/bomtrace2,
and generates OmniBOR ADG documents.
"""

from pathlib import Path

from app.config import lang_subdir, timestamp
from app.runner import CommandRunner


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
        run_ts=None,
    ):
        """Run pre-build steps, instrumented build, and ADG generation.

        Returns True on success, False on failure.
        """
        ts = run_ts or timestamp()
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / lang / repo_name / ts
        )
        tracer = omnibor_cfg["tracer"]
        raw_logfile = omnibor_cfg["raw_logfile"]

        # Clean stale build artifacts so bomtrace3
        # intercepts a full recompilation.
        # Without this, a prior build leaves object
        # files in place and make becomes a no-op —
        # bomtrace3 intercepts zero compiler calls
        # and bomsh_create_bom.py has no data.
        clean_cmd = repo_cfg.get("clean_cmd")
        if clean_cmd:
            self.runner.run(
                clean_cmd, cwd=str(repo_dir),
                description=(
                    f"Clean: {clean_cmd}"
                ),
            )
            # Ignore clean_cmd exit code — it may
            # fail on a fresh clone (nothing to clean)

        # Pre-build steps (configure, etc.)
        build_steps = repo_cfg["build_steps"]
        for step in build_steps[:-1]:
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
                return False

        # Final build step with bomtrace3
        make_cmd = build_steps[-1]
        instrumented = f"{tracer} {make_cmd}"
        rc = self.runner.run(
            instrumented, cwd=str(repo_dir),
            description=(
                f"Instrumented build: "
                f"{tracer} {make_cmd[:40]}"
            ),
        )
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return False

        # Generate OmniBOR ADG documents
        create_bom = omnibor_cfg["create_bom_script"]
        rc = self.runner.run(
            f"{create_bom} -r {raw_logfile} "
            f"-b {bom_dir}",
            cwd=str(repo_dir),
            description=(
                "Generating OmniBOR ADG documents"
            ),
        )
        if rc != 0:
            print("[ERROR] ADG generation failed")
            return False

        print(
            "[OK] OmniBOR ADG documents "
            f"written to {bom_dir}"
        )
        return True
