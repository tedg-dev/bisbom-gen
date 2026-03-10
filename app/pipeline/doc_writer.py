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
    def write_build_doc(
        repo_name, repo_cfg,
        paths_cfg, success, duration_sec,
        run_ts=None,
    ):
        """Write build log to docs/<lang>/<repo>/<ts>/."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        docs_dir = (
            Path(paths_cfg["docs_dir"])
            / lang / repo_name / ts
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

        lang = lang_subdir(repo_cfg)
        if lang == "c-cpp":
            content += (
                "\n## Instrumentation\n\n"
                "- **Tracer:** bomtrace3\n"
                "- **Raw logfile:** "
                "/tmp/bomsh_hook_raw_logfile"
                ".sha1\n"
            )
        elif lang == "rust":
            content += (
                "\n## Instrumentation\n\n"
                "- **Tracer:** bomtrace2 "
                "(default conf)\n"
                "- **Raw logfile:** "
                "/tmp/bomsh_hook_raw_logfile"
                ".sha1\n"
                "- **Watched tools:** "
                "rustc\n"
            )
        else:
            content += (
                "\n## Instrumentation\n\n"
                "- **Tracer:** bomtrace2 "
                "(Go-specific conf)\n"
                "- **Raw logfile:** "
                "/tmp/bomsh_hook_raw_logfile"
                ".sha1\n"
                "- **Watched tools:** "
                "compile, link\n"
            )

        content += (
            "\n## Output Binaries\n\n"
        )
        for binary in repo_cfg.get(
            "output_binaries", []
        ):
            content += f"- `{binary}`\n"

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
        run_ts=None,
    ):
        """Write runtime performance metrics."""
        ts = run_ts or timestamp()
        lang = lang_subdir(repo_cfg)
        runtime_dir = (
            Path(paths_cfg["docs_dir"])
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

        if lang == "c-cpp":
            build_label = "Instrumented build time"
            notes = (
                "- Measured wall-clock time for the "
                "instrumented `make` step only\n"
                "- Baseline (uninstrumented) build "
                "time should be recorded separately "
                "for comparison\n"
            )
        elif lang == "rust":
            build_label = "Instrumented build time"
            notes = (
                "- Measured wall-clock time for "
                "bomtrace2-instrumented "
                "`cargo build --release`\n"
                "- OmniBOR ADG + SPDX generated "
                "from build interception\n"
            )
        else:
            build_label = "Instrumented build time"
            notes = (
                "- Measured wall-clock time for "
                "bomtrace2-instrumented "
                "`go build -a`\n"
                "- OmniBOR ADG + SPDX generated "
                "from build interception\n"
                "- Syft manifest SBOM also "
                "generated from go.mod/go.sum\n"
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
