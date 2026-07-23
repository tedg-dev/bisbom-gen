"""
Documentation writer for OmniBOR Analysis.

Writes build logs and runtime performance metrics to
timestamped markdown files.
"""

from datetime import datetime
from pathlib import Path

from app.config import lang_subdir, timestamp


class DocWriter:
    """Writes build logs and runtime metrics."""

    @staticmethod
    def classify_release_build(repo_cfg):
        """Classify build as release or debug.

        Returns dict with keys:
          is_release: bool
          label: str  (e.g. 'RELEASE' or 'WARNING')
          reason: str (human-readable explanation)
          warnings: list[str]
        """
        lang = repo_cfg.get("language", "c-cpp")
        steps = repo_cfg.get("build_steps", [])
        joined = " ".join(steps)
        warnings = []

        if lang == "c-cpp":
            debug_flags = [
                "--enable-debug", "CFLAGS=\"-g",
                "-O0", "DEBUG=1", "ASAN=1",
            ]
            for flag in debug_flags:
                if flag in joined:
                    warnings.append(
                        f"Debug flag detected: {flag}"
                    )
            reason = (
                "./configure + make, no debug flags"
                if "./configure" in joined
                else "make with default optimization"
            )

        elif lang == "rust":
            if "--release" not in joined:
                warnings.append(
                    "Missing --release flag in "
                    "cargo build"
                )
            reason = "cargo build --release"

        elif lang == "go":
            if "-trimpath" not in joined:
                warnings.append(
                    "Missing -trimpath in go build"
                )
            if '-ldflags' not in joined:
                warnings.append(
                    'Missing -ldflags="-s -w" '
                    "in go build"
                )
            reason = (
                "go build with -trimpath "
                '-ldflags="-s -w"'
            )

        elif lang == "java":
            profile = repo_cfg.get("build_profile") or {}
            tool = profile.get("tool")
            if tool == "gradle":
                # Gradle's `jar`/`assemble` tasks do not run tests, so a
                # release build needs no test-skipping flag. Warn only if
                # the build steps explicitly invoke a test-running task.
                test_tasks = {"test", "check", "build"}
                invoked = sorted(
                    test_tasks.intersection(joined.split())
                )
                if invoked:
                    warnings.append(
                        "Gradle build_steps invoke test task(s) "
                        f"{invoked}; use 'jar'/'assemble' for "
                        "release artifacts"
                    )
                reason = (
                    "gradle jar/assemble "
                    "(tests not bound to jar task)"
                )
            else:
                # Maven (default): a release package must skip tests.
                if "-DskipTests" not in joined:
                    warnings.append(
                        "Missing -DskipTests in mvn package"
                    )
                reason = "mvn package -DskipTests"

        else:
            reason = "unknown language"

        is_release = len(warnings) == 0
        label = "RELEASE" if is_release else "WARNING"
        return {
            "is_release": is_release,
            "label": label,
            "reason": reason,
            "warnings": warnings,
        }

    @staticmethod
    def write_build_doc(
        repo_name, repo_cfg,
        paths_cfg, success, duration_sec,
        run_ts=None, tracer=None,
        raw_logfile=None,
        commit_sha=None,
        timing=None,
    ):
        """Write build log to output/build-logs/<lang>/<repo>/<ts>/."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        docs_dir = (
            Path(paths_cfg["output_dir"])
            / "build-logs" / lang / repo_name / ts
        )
        docs_dir.mkdir(parents=True, exist_ok=True)
        doc_path = docs_dir / "build.md"

        status = "SUCCESS" if success else "FAILED"
        timing_str = (
            f"**Duration:** {duration_sec:.1f}"
            " seconds"
        )
        if timing:
            timing_str += (
                f" (build: {timing.phase1_total:.1f}s"
                f" + analysis: "
                f"{timing.phase2_total:.1f}s)"
            )
        content = (
            f"# Build Log \u2014 {repo_name}\n\n"
            f"**Date:** {datetime.now().isoformat()}\n"
            f"**Status:** {status}\n"
            f"{timing_str}\n\n"
            "## Repository\n\n"
            f"- **URL:** {repo_cfg['url']}\n"
            f"- **Branch:** "
            f"{repo_cfg.get('branch', 'master')}\n"
            f"- **Commit:** "
            f"{commit_sha or 'unknown'}\n"
            f"- **Description:** "
            f"{repo_cfg.get('description', 'N/A')}"
            "\n\n"
        )
        content += _format_build_profile(
            repo_cfg.get("build_profile")
        )
        content += "## Build Steps\n\n"
        for i, step in enumerate(
            repo_cfg["build_steps"], 1
        ):
            content += f"{i}. `{step}`\n"

        tracer_name = tracer or "unknown"
        logfile = (
            raw_logfile
            or "/tmp/bomsh_hook_raw_logfile.sha1"
        )
        content += (
            "\n## Instrumentation\n\n"
            f"- **Tracer:** {tracer_name}\n"
            f"- **Raw logfile:** {logfile}\n"
        )

        content += (
            "\n## Output Binaries\n\n"
        )
        for binary in repo_cfg.get(
            "output_binaries", []
        ):
            content += f"- `{binary}`\n"

        # Release Build Verification section
        rb = DocWriter.classify_release_build(
            repo_cfg
        )
        status_icon = (
            "RELEASE" if rb["is_release"]
            else "WARNING"
        )
        content += (
            "\n## Release Build Verification\n\n"
            f"**Classification:** {status_icon}\n"
            f"**Reason:** {rb['reason']}\n"
        )
        if rb["warnings"]:
            content += "\n**Warnings:**\n\n"
            for w in rb["warnings"]:
                content += f"- {w}\n"
        else:
            content += (
                "\nNo debug or development flags "
                "detected. Build targets "
                "production/release binaries.\n"
            )

        if timing:
            content += _format_timing_table(timing)
            content += _format_phase_summary(
                timing, None,
            )

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(f"[OK] Build doc written to {doc_path}")
        return str(doc_path)

    @staticmethod
    def write_runtime_doc(
        repo_name, repo_cfg, paths_cfg,
        duration_sec,
        run_ts=None, tracer=None,
        timing=None,
        baseline=None,
    ):
        """Write runtime performance metrics."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        runtime_dir = (
            Path(paths_cfg["output_dir"])
            / "runtime" / lang / repo_name / ts
        )
        runtime_dir.mkdir(
            parents=True, exist_ok=True
        )
        doc_path = (
            runtime_dir / "runtime.md"
        )

        tracer_name = tracer or "unknown"
        content = (
            f"# Runtime Metrics \u2014 {repo_name}\n\n"
            f"**Date:** "
            f"{datetime.now().isoformat()}\n"
            f"**Tracer:** {tracer_name}\n"
            f"**Total:** {duration_sec:.1f} seconds\n"
        )

        if timing:
            content += _format_timing_table(timing)
            content += _format_phase_summary(
                timing, baseline,
            )
            content += _format_contention_summary(
                timing,
            )

        build_cmd = repo_cfg.get(
            "build_steps", ["unknown"]
        )[-1]
        content += (
            "\n## Notes\n\n"
            f"- Measured wall-clock time for "
            f"{tracer_name}-instrumented "
            f"`{build_cmd}`\n"
            "- OmniBOR ADG + SPDX generated "
            "from build interception\n"
        )

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(
            f"[OK] Runtime doc written to {doc_path}"
        )
        return str(doc_path)


# ============================================================
# Formatting helpers (module-level, used by both doc methods)
# ============================================================

_STEP_LABELS = {
    "clean": "Clean",
    "prebuild": "Pre-Build",
    "build": "Build",
    "adg": "ADG Generation",
    "omnibor_sbom": "OmniBOR SBOM",
    "metadata": "Metadata",
    "spdx_gen": "SPDX Generation",
    "validate": "Validation",
    "collect": "Binary Collection",
}

_PHASE_LABELS = {
    "phase1": "Phase 1: Build Interception",
    "phase2": "Phase 2: Post-Build Analysis",
}


def _format_build_profile(profile):
    """Render a repo's build_profile as a headerless metadata table.

    Returns an empty string when no profile is present so callers can
    concatenate unconditionally. Optional fields (dsl, tool_version,
    traits) are only shown when set.
    """
    if not isinstance(profile, dict) or not profile:
        return ""
    rows = [
        ("Tool", profile.get("tool", "")),
        ("Structure", profile.get("structure", "")),
    ]
    if profile.get("dsl"):
        rows.append(("DSL", profile["dsl"]))
    if profile.get("tool_version"):
        rows.append(
            ("Tool version", profile["tool_version"])
        )
    traits = profile.get("traits") or []
    if traits:
        rows.append(("Traits", ", ".join(traits)))

    out = "## Build Profile\n\n|  |  |\n| --- | --- |\n"
    for key, val in rows:
        out += f"| **{key}** | {val} |\n"
    out += "\n"
    return out


def _format_timing_table(timing):
    """Format per-step timing as a markdown table.

    Each row shows step name, phase, wall time,
    expected parallelism, actual CPU efficiency,
    and contention severity.
    """
    lines = [
        "\n## Per-Step Timing\n",
        "| Step | Phase | Wall (s) "
        "| Expected | CPU Eff | Contention |",
        "|------|-------|----------"
        "|----------|---------|------------|",
    ]
    for step in timing.steps:
        label = _STEP_LABELS.get(
            step.name, step.name,
        )
        phase = _PHASE_LABELS.get(
            step.phase, step.phase,
        )
        exp = f"{step.expected_parallelism}x"
        eff = f"{step.cpu_efficiency:.2f}x"
        if step.contention:
            sev = step.contention_severity
            flag = f"\u26a0 {sev:.0f}% below"
        else:
            flag = "\u2014"
        lines.append(
            f"| {label} | {phase} "
            f"| {step.wall_sec:.1f} "
            f"| {exp} | {eff} | {flag} |"
        )
    lines.append("")
    return "\n".join(lines)


def _format_phase_summary(timing, baseline=None):
    """Format phase totals and baseline comparison."""
    p1 = timing.phase1_total
    p2 = timing.phase2_total
    total = p1 + p2

    lines = [
        "\n## Phase Summary\n",
        f"- **Phase 1 (Build Interception):** "
        f"{p1:.1f}s",
        f"- **Phase 2 (Post-Build Analysis):** "
        f"{p2:.1f}s",
        f"- **Total:** {total:.1f}s",
    ]

    if baseline:
        from app.pipeline.timing import (
            baseline_build_step,
        )
        bl_build = baseline_build_step(baseline)
        if bl_build:
            bl_wall = bl_build.get("wall_sec", 0)
            # Find instrumented build step
            inst_build = next(
                (s for s in timing.steps
                 if s.name == "build"),
                None,
            )
            if bl_wall > 0 and inst_build:
                overhead = (
                    (inst_build.wall_sec - bl_wall)
                    / bl_wall * 100
                )
                lines.append(
                    "\n### Baseline Comparison "
                    "(Build Step Only)\n"
                )
                lines.append(
                    "- **Baseline build:** "
                    f"{bl_wall:.1f}s"
                )
                lines.append(
                    "- **Instrumented build:** "
                    f"{inst_build.wall_sec:.1f}s"
                )
                lines.append(
                    f"- **Overhead:** "
                    f"{overhead:+.1f}%"
                )
    lines.append("")
    return "\n".join(lines)


def _format_contention_summary(timing):
    """Format aggregate contention analysis section.

    Reports how many steps had contention, total time
    under contention, percentage of pipeline time, and
    the most severe step.
    """
    flagged = timing.contention_steps
    total_steps = len(timing.steps)
    if not flagged:
        return (
            "\n## Contention Analysis\n\n"
            f"No contention detected across "
            f"{total_steps} steps.\n"
        )

    dur = timing.contention_total_sec
    pct = timing.contention_pct
    lines = [
        "\n## Contention Analysis\n",
        f"- **Steps with contention:** "
        f"{len(flagged)} of {total_steps}",
        f"- **Total contention duration:** "
        f"{dur:.1f}s of {timing.total:.1f}s "
        f"({pct:.1f}%)",
    ]

    # Most severe step
    worst = max(
        flagged, key=lambda s: s.contention_severity,
    )
    worst_label = _STEP_LABELS.get(
        worst.name, worst.name,
    )
    lines.append(
        f"- **Most severe:** {worst_label} "
        f"\u2014 {worst.cpu_efficiency:.2f}x actual "
        f"vs {worst.expected_parallelism}x expected "
        f"({worst.contention_severity:.0f}% below "
        f"threshold)"
    )
    lines.append("")
    return "\n".join(lines)
