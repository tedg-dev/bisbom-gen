"""
Instrumented build with bomtrace for OmniBOR Analysis.

Runs pre-build steps, the instrumented build via bomtrace3/bomtrace2,
and generates OmniBOR ADG documents.
"""

import shutil
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
        run_ts=None, strategy=None,
    ):
        """Run pre-build steps, instrumented build, and ADG generation.

        Args:
            strategy: Optional ``InterceptionStrategy``.
                When provided, delegates command
                transformation and ADG generation to
                the strategy.  When ``None``, uses
                legacy hardcoded bomtrace behavior.

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

        # Final build step — delegate to strategy
        # or fall back to legacy bomtrace prefix.
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

        rc = self.runner.run(
            instrumented, cwd=str(repo_dir),
            env=env,
            description=(
                f"Instrumented build: "
                f"{instrumented[:60]}"
            ),
        )
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return False

        # Generate OmniBOR ADG documents — delegate
        # to strategy or fall back to legacy.
        if strategy:
            ok = strategy.generate_adg(
                str(repo_dir), str(bom_dir),
                omnibor_cfg,
                repo_cfg=repo_cfg,
            )
            if not ok:
                print(
                    "[ERROR] ADG generation failed"
                )
                return False
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
                    "Generating OmniBOR ADG documents"
                ),
            )
            if rc != 0:
                print(
                    "[ERROR] ADG generation failed"
                )
                return False

        print(
            "[OK] OmniBOR ADG documents "
            f"written to {bom_dir}"
        )
        return True

    def build_java(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_java_cfg,
        run_ts=None,
    ):
        """Run Java build with strace, then bomsh_create_bom_java.py.

        Java uses a different approach than C/C++/Rust/Go:
        1. Build with strace to capture file I/O (openat syscalls)
        2. Run bomsh_create_bom_java.py with strace log to create treedb

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
        bom_dir.mkdir(parents=True, exist_ok=True)
        meta_dir = bom_dir / "metadata" / "bomsh"
        meta_dir.mkdir(parents=True, exist_ok=True)

        strace_opts = omnibor_java_cfg["strace_opts"]
        strace_log = omnibor_java_cfg["strace_logfile"]
        create_bom = omnibor_java_cfg["create_bom_script"]

        # Clean stale build artifacts
        clean_cmd = repo_cfg.get("clean_cmd")
        if clean_cmd:
            self.runner.run(
                clean_cmd, cwd=str(repo_dir),
                description=f"Clean: {clean_cmd}",
            )

        # Pre-build steps (if any before final build)
        build_steps = repo_cfg["build_steps"]
        for step in build_steps[:-1]:
            rc = self.runner.run(
                step, cwd=str(repo_dir),
                description=f"Pre-build: {step[:60]}",
            )
            if rc != 0:
                print(f"[ERROR] Pre-build step failed: {step}")
                return False

        # Final build step with strace
        build_cmd = build_steps[-1]
        instrumented = (
            f"strace {strace_opts} -o {strace_log} {build_cmd}"
        )
        rc = self.runner.run(
            instrumented, cwd=str(repo_dir),
            description=(
                f"Instrumented build: strace {build_cmd[:40]}"
            ),
        )
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return False

        # Generate OmniBOR treedb by scanning entire workspace
        # The script automatically finds all .java, .class, and .jar files
        # and builds the complete dependency graph
        # See: bomsh docs/Quickstart.md - "For Java" section
        treedb_file = meta_dir / "bomsh_omnibor_treedb"
        rc = self.runner.run(
            f"{create_bom} -r {repo_dir} "
            f"-j {treedb_file}",
            cwd=str(repo_dir),
            description=(
                "Generating OmniBOR treedb for Java workspace"
            ),
        )
        if rc != 0:
            print("[ERROR] bomsh_create_bom_java.py failed")
            return False

        # Archive strace log to metadata dir so
        # AdgParser.parse_strace_openat_log() can
        # consume it — mirrors how C/C++ archives
        # the raw logfile via bomsh_create_bom.py.
        strace_archive = (
            meta_dir / "strace_java_logfile"
        )
        strace_src = Path(strace_log)
        if strace_src.exists():
            shutil.copy2(
                str(strace_src), str(strace_archive)
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

        print(
            "[OK] OmniBOR treedb written to "
            f"{treedb_file}"
        )
        return True
