"""
CLI entry point for OmniBOR Analysis.

Contains main() which dispatches to language-specific
pipeline runners in app.pipeline.lang_runners.
"""

import argparse
import sys
from pathlib import Path

from app.config import (
    lang_subdir, load_config, resolve_omnibor_cfg,
    timestamp, VALID_MODES, DEFAULT_MODE,
)
from app.pipeline.facade import AnalysisPipeline
from app.pipeline.lang_runners import (
    run_c_cpp_pipeline,
    run_rust_pipeline,
    run_java_pipeline,
    run_go_pipeline,
    generate_java_adg_spdx,
)


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "OmniBOR Analysis — Build interception "
            "and SBOM generation"
        )
    )
    parser.add_argument(
        "--repo",
        help="Repository name from config.yaml",
    )
    parser.add_argument(
        "--skip-clone", action="store_true",
        help="Skip cloning (repo already exists)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available repositories",
    )
    parser.add_argument(
        "--syft-only", action="store_true",
        help=(
            "Only generate Syft manifest SBOM "
            "(no build). Overrides pipeline."
            "syft_enabled config."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default=None,
        help=(
            "Pipeline mode: standalone (ptrace) "
            "or sidecar (wrappers/dep-tree). "
            "Overrides config.yaml 'mode' key. "
            f"Default: {DEFAULT_MODE}"
        ),
    )
    args = parser.parse_args()

    config = load_config()
    # CLI --mode overrides config file
    if args.mode:
        config["mode"] = args.mode
    pipeline = AnalysisPipeline()

    if args.list:
        pipeline.list_repos(config)
        return

    if not args.repo:
        print(
            "[ERROR] --repo is required. "
            "Use --list to see options."
        )
        sys.exit(1)

    if args.repo not in config["repos"]:
        print(
            f"[ERROR] Unknown repo '{args.repo}'. "
            "Use --list to see options."
        )
        sys.exit(1)

    repo_cfg = config["repos"][args.repo]
    paths_cfg = config["paths"]

    # Language-aware omnibor config lookup
    lang = lang_subdir(repo_cfg)
    omnibor_cfg = resolve_omnibor_cfg(config, lang)

    # Single timestamp for the entire run — all
    # output folders use this consistently:
    #   output/binaries/{lang}/{repo}/{run_ts}/
    #   output/spdx/{lang}/{repo}/{run_ts}/
    #   output/omnibor/{lang}/{repo}/{run_ts}/
    #   output/build-logs/{lang}/{repo}/{run_ts}/
    #   output/runtime/{lang}/{repo}/{run_ts}/
    run_ts = timestamp()

    print(f"\n{'#'*60}")
    print(f"  OmniBOR Analysis: {args.repo}")
    desc = repo_cfg.get("description", "")
    print(f"  {desc}")
    print(f"{'#'*60}\n")

    # Release build verification (console)
    from app.pipeline.doc_writer import DocWriter
    rb = DocWriter.classify_release_build(repo_cfg)
    status_msg = (
        "release build confirmed"
        if rb["is_release"]
        else "release build issue"
    )
    print(
        f"[{rb['label']}] {args.repo}: "
        f"{status_msg} ({rb['reason']})"
    )
    for w in rb["warnings"]:
        print(f"[WARNING] {args.repo}: {w}")

    # Step 1: Clone
    if not args.skip_clone:
        pipeline.cloner.clone(
            args.repo, repo_cfg, paths_cfg
        )

    # Step 2: Syft SBOM (manifest-based — optional,
    # disabled by default in config.yaml).
    # --syft-only CLI flag overrides config.
    syft_enabled = config.get(
        "pipeline", {}
    ).get("syft_enabled", False) or args.syft_only
    if syft_enabled:
        pipeline.syft_gen.generate(
            args.repo, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    if args.syft_only:
        print(
            "\n[DONE] Syft-only mode — "
            "skipping build."
        )
        return

    # -------------------------------------------------
    # Language-specific pipeline branch
    # -------------------------------------------------
    if lang == "c-cpp":
        success, duration = run_c_cpp_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    elif lang == "rust":
        success, duration = run_rust_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    elif lang == "java":
        success, duration = run_java_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    else:
        success, duration = run_go_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )

    # Step 7b: Validate Syft SPDX (if enabled)
    if syft_enabled:
        _validate_syft_spdx(
            pipeline, args.repo, repo_cfg,
            paths_cfg, run_ts,
        )

    # Step 8: Write docs (all languages)
    tracer = omnibor_cfg.get("tracer")
    raw_logfile = omnibor_cfg.get("raw_logfile")
    pipeline.docs.write_build_doc(
        args.repo, repo_cfg, paths_cfg,
        success, duration,
        run_ts=run_ts, tracer=tracer,
        raw_logfile=raw_logfile,
    )
    pipeline.docs.write_runtime_doc(
        args.repo, repo_cfg, paths_cfg,
        duration, run_ts=run_ts,
        tracer=tracer,
    )

    status = "COMPLETE" if success else "FAILED"
    print(f"\n{'#'*60}")
    print(f"  Analysis {status}: {args.repo}")
    print(f"  Duration: {duration:.1f}s")
    print(f"{'#'*60}\n")


def _validate_syft_spdx(
    pipeline, repo_name, repo_cfg,
    paths_cfg, run_ts,
):
    """Validate Syft SPDX if it exists (all languages)."""
    lang = lang_subdir(repo_cfg)
    syft_spdx = (
        Path(paths_cfg["output_dir"])
        / "spdx" / lang / repo_name / run_ts
        / f"{repo_name}_syft.spdx.json"
    )
    if syft_spdx.exists():
        pipeline.spdx_validator.validate(
            str(syft_spdx)
        )


# Backward-compatible aliases for test imports
_run_c_cpp_pipeline = run_c_cpp_pipeline
_run_rust_pipeline = run_rust_pipeline
_run_java_pipeline = run_java_pipeline
_run_go_pipeline = run_go_pipeline
_generate_java_adg_spdx = generate_java_adg_spdx
