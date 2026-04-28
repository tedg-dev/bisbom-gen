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
            if "-DskipTests" not in joined:
                warnings.append(
                    "Missing -DskipTests in "
                    "mvn package"
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
        content = (
            f"# Build Log — {repo_name}\n\n"
            f"**Date:** {datetime.now().isoformat()}\n"
            f"**Status:** {status}\n"
            f"**Duration:** {duration_sec:.1f}"
            " seconds\n\n"
            "## Repository\n\n"
            f"- **URL:** {repo_cfg['url']}\n"
            f"- **Branch:** "
            f"{repo_cfg.get('branch', 'master')}\n"
            f"- **Description:** "
            f"{repo_cfg.get('description', 'N/A')}"
            "\n\n"
            "## Build Steps\n\n"
        )
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

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(f"[OK] Build doc written to {doc_path}")
        return str(doc_path)

    @staticmethod
    def write_runtime_doc(
        repo_name, repo_cfg, paths_cfg,
        duration_sec, baseline_sec=None,
        run_ts=None, tracer=None,
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

        overhead_pct = ""
        if baseline_sec and baseline_sec > 0:
            pct = (
                (duration_sec - baseline_sec)
                / baseline_sec * 100
            )
            overhead_pct = (
                f"\n**Bomtrace3 overhead:** "
                f"{pct:.1f}%"
            )

        build_cmd = repo_cfg.get(
            "build_steps", ["unknown"]
        )[-1]
        tracer_name = tracer or "unknown"
        build_label = "Instrumented build time"
        notes = (
            f"- Measured wall-clock time for "
            f"{tracer_name}-instrumented "
            f"`{build_cmd}`\n"
            "- OmniBOR ADG + SPDX generated "
            "from build interception\n"
        )

        content = (
            f"# Runtime Metrics — {repo_name}\n\n"
            f"**Date:** "
            f"{datetime.now().isoformat()}\n"
            f"**{build_label}:** "
            f"{duration_sec:.1f} seconds\n"
            f"{overhead_pct}\n\n"
            "## Notes\n\n"
            f"{notes}"
        )

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(
            f"[OK] Runtime doc written to {doc_path}"
        )
        return str(doc_path)
