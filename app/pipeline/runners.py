"""
CLI entry point for OmniBOR Analysis.

Contains main() which dispatches to language-specific
pipeline runners in app.pipeline.lang_runners.
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import (
    lang_subdir, load_config, resolve_omnibor_cfg,
    timestamp, VALID_MODES, DEFAULT_MODE,
    VALID_PHASES,
)
from app.pipeline.facade import AnalysisPipeline
from app.pipeline.lang_runners import (
    run_c_cpp_pipeline,
    run_rust_pipeline,
    run_java_pipeline,
    run_java_phase1,
    run_java_phase2,
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
    parser.add_argument(
        "--baseline", action="store_true",
        help=(
            "Run non-instrumented build to capture "
            "baseline timing. No Phase 2 analysis."
        ),
    )
    parser.add_argument(
        "--phase",
        choices=VALID_PHASES,
        default=None,
        help=(
            "Run only Phase 1 (build) or "
            "Phase 2 (spdx). Requires "
            "--mode sidecar. Omit to run both."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=str, default=None,
        help=(
            "Path to phase1_manifest.json "
            "(required with --phase spdx)"
        ),
    )
    args = parser.parse_args()

    # Validate phase isolation constraints
    if args.phase:
        _validate_phase_args(args, parser)

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
    # Phase 2-only: reuse Phase 1's timestamp so all
    # output lands in the same directory tree.
    if args.phase == "spdx" and args.manifest:
        _m = json.loads(
            Path(args.manifest).read_text()
        )
        run_ts = _m.get("run_ts", timestamp())
    else:
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

    # Resolve commit SHA for SPDX downloadLocation
    from app.pipeline.cloner import RepoCloner
    repo_dir = (
        Path(paths_cfg["repos_dir"]) / args.repo
    )
    commit_sha = RepoCloner.get_commit_sha(repo_dir)
    vcs_uri = RepoCloner.build_vcs_uri(
        repo_cfg.get("url"), commit_sha,
    )
    if commit_sha:
        print(
            f"[OK] Commit SHA: {commit_sha[:12]}..."
        )
        print(f"[OK] VCS URI: {vcs_uri}")
    else:
        print(
            "[WARN] Could not resolve commit SHA"
        )

    # Baseline mode: non-instrumented build only
    if args.baseline:
        _run_baseline(
            args.repo, repo_cfg, paths_cfg,
            run_ts, pipeline,
        )
        return

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
    # Each returns a TimingResult with per-step metrics.
    # -------------------------------------------------
    if lang == "c-cpp":
        timing = run_c_cpp_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
            vcs_uri=vcs_uri,
        )
    elif lang == "rust":
        timing = run_rust_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
            vcs_uri=vcs_uri,
        )
    elif lang == "java":
        mode = config.get("mode", DEFAULT_MODE)
        if args.phase == "build":
            timing = _run_phase1_only(
                pipeline, args.repo, repo_cfg,
                paths_cfg, omnibor_cfg, run_ts,
                mode=mode, lang=lang,
                commit_sha=commit_sha,
                vcs_uri=vcs_uri,
            )
        elif args.phase == "spdx":
            timing = _run_phase2_only(
                pipeline, args.repo,
                args.manifest, paths_cfg,
                omnibor_cfg, run_ts,
                vcs_uri=vcs_uri,
            )
        else:
            timing = run_java_pipeline(
                pipeline, args.repo, repo_cfg,
                paths_cfg, omnibor_cfg, run_ts,
                vcs_uri=vcs_uri,
                mode=mode,
                commit_sha=commit_sha,
            )
    else:
        timing = run_go_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
            vcs_uri=vcs_uri,
        )
    success = timing.success
    duration = timing.total

    # Step 7b: Validate Syft SPDX (if enabled)
    if syft_enabled:
        _validate_syft_spdx(
            pipeline, args.repo, repo_cfg,
            paths_cfg, run_ts,
        )

    # Load baseline (golden reference) for overhead calc
    from app.pipeline.timing import (
        load_baseline, save_runtime_json,
    )
    baseline = load_baseline(
        paths_cfg, args.repo, repo_cfg,
    )

    # Step 8: Write docs (all languages)
    raw_logfile = omnibor_cfg.get("raw_logfile")
    pipeline.docs.write_build_doc(
        args.repo, repo_cfg, paths_cfg,
        success, duration,
        run_ts=run_ts, tracer=timing.tracer,
        raw_logfile=raw_logfile,
        commit_sha=commit_sha,
        timing=timing,
    )
    pipeline.docs.write_runtime_doc(
        args.repo, repo_cfg, paths_cfg,
        duration, run_ts=run_ts,
        tracer=timing.tracer,
        timing=timing,
        baseline=baseline,
    )

    # Save runtime.json
    save_runtime_json(
        timing, paths_cfg, args.repo,
        repo_cfg, run_ts,
        baseline=baseline,
    )

    # Console summary — report the native CI/CD build, the
    # sidecar metadata work (create + store for Phase 2), and
    # Phase 2 SPDX generation separately so the build-stage
    # impact is never conflated with the sidecar cost.
    build_t = timing.build_total
    sidecar_t = timing.sidecar_total
    p2 = timing.phase2_total
    status = "COMPLETE" if success else "FAILED"
    print(f"\n{'#'*60}")
    print(f"  Analysis {status}: {args.repo}")
    print(
        f"  CI/CD build: {build_t:.1f}s  "
        f"Sidecar (metadata create+store): "
        f"{sidecar_t:.1f}s  "
        f"Phase 2 (SPDX): {p2:.1f}s  "
        f"Total: {duration:.1f}s"
    )
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
                print(
                    f"  Build overhead: "
                    f"{bl_wall:.1f}s → "
                    f"{inst_build.wall_sec:.1f}s "
                    f"({overhead:+.1f}%)"
                )
    print(f"{'#'*60}\n")


def _validate_phase_args(args, parser):
    """Validate --phase CLI constraints.

    Rules:
    - ``--phase`` requires ``--mode sidecar``
      (standalone does not support phase isolation).
    - ``--phase spdx`` requires ``--manifest``.
    - ``--phase build`` must not have ``--manifest``.
    """
    mode = args.mode or DEFAULT_MODE
    if mode != "sidecar":
        parser.error(
            "--phase requires --mode sidecar "
            "(standalone does not support "
            "phase isolation)"
        )
    if args.phase == "spdx" and not args.manifest:
        parser.error(
            "--phase spdx requires --manifest "
            "<path to phase1_manifest.json>"
        )
    if args.phase == "build" and args.manifest:
        parser.error(
            "--manifest is not valid with "
            "--phase build (manifest is an "
            "output of Phase 1, not an input)"
        )


def _run_phase1_only(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    mode, lang, commit_sha, vcs_uri,
):
    """Run Phase 1 only and write manifest.

    Used with ``--phase build --mode sidecar``.
    Runs the build, then writes a manifest that
    Phase 2 can consume independently.

    Returns ``TimingResult``.
    """
    from app.pipeline.manifest import write_manifest
    from app.pipeline.timing import StepTimer

    timing, _ = run_java_phase1(
        pipeline, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg, run_ts,
        mode=mode,
    )
    if not timing.success:
        return timing

    # Determine artifact paths for the manifest
    bom_dir = (
        Path(paths_cfg["output_dir"])
        / "omnibor" / lang / repo_name / run_ts
    )
    spdx_dir = (
        Path(paths_cfg["output_dir"])
        / "spdx" / lang / repo_name / run_ts
    )

    # Resolve output binary paths
    repo_dir = (
        Path(paths_cfg["repos_dir"]) / repo_name
    )
    bin_paths = []
    for pattern in repo_cfg.get(
        "output_binaries", [],
    ):
        if "*" in pattern or "?" in pattern:
            bin_paths.extend(
                str(p) for p in repo_dir.glob(pattern)
            )
        else:
            p = repo_dir / pattern
            if p.exists():
                bin_paths.append(str(p))

    artifacts = {
        "bom_dir": str(bom_dir),
        "binaries": bin_paths,
    }

    # Include strace log if present (standalone)
    strace_log = omnibor_cfg.get("strace_logfile")
    if strace_log and Path(strace_log).exists():
        artifacts["strace_log"] = strace_log

    paths = {
        "repos_dir": paths_cfg["repos_dir"],
        "output_dir": paths_cfg["output_dir"],
        "spdx_dir": str(spdx_dir),
    }

    # Time the manifest write as sidecar work: it is the
    # "store build metadata for Phase 2 access" step, distinct
    # from the native build and from Phase 2 SPDX generation.
    manifest_timer = StepTimer(
        "manifest", "phase1", category="sidecar",
    )
    with manifest_timer:
        manifest_path = write_manifest(
            manifest_dir=str(bom_dir),
            repo_name=repo_name,
            language=lang,
            mode=mode,
            tracer=timing.tracer,
            run_ts=run_ts,
            commit_sha=commit_sha,
            vcs_uri=vcs_uri,
            artifacts=artifacts,
            paths=paths,
            repo_cfg={
                k: repo_cfg[k] for k in (
                    "output_binaries", "language",
                    "build_steps",
                ) if k in repo_cfg
            },
            omnibor_cfg=omnibor_cfg,
        )
    timing.steps.append(manifest_timer.metrics)
    print(
        f"[OK] Phase 1 manifest: {manifest_path}"
    )

    return timing


def _run_phase2_only(
    pipeline, repo_name,
    manifest_path, paths_cfg,
    omnibor_cfg, run_ts,
    vcs_uri="NOASSERTION",
):
    """Run Phase 2 only from a manifest.

    Used with ``--phase spdx --manifest <path>``.
    Reads the manifest to locate Phase 1 artifacts,
    then runs SPDX generation + validation.

    Returns ``TimingResult``.
    """
    from app.pipeline.manifest import (
        read_manifest, verify_gitoids,
    )
    from app.pipeline.timing import TimingResult

    manifest = read_manifest(manifest_path)

    # Verify artifact integrity
    passed, failed = verify_gitoids(manifest)
    if failed:
        print(
            f"[WARN] {len(failed)} artifact(s) "
            f"failed gitoid verification"
        )
        for f in failed:
            print(f"  - {f}")
    if passed:
        print(
            f"[OK] {len(passed)} artifact(s) "
            f"verified via gitoid"
        )

    # Use manifest values, fall back to CLI args
    m_repo_cfg = manifest.get("repo_cfg", {})
    m_omnibor = manifest.get(
        "omnibor_cfg", omnibor_cfg,
    )
    m_vcs = manifest.get("vcs_uri", vcs_uri)
    m_ts = manifest.get("run_ts", run_ts)
    m_commit = manifest.get("commit_sha") or "NOASSERTION"
    m_mode = manifest.get("mode", "sidecar")
    tracer = manifest.get("tracer", "unknown")

    timing = TimingResult(tracer=tracer)
    timing.success = True

    phase2_steps = run_java_phase2(
        pipeline, repo_name, m_repo_cfg,
        paths_cfg, m_omnibor, m_ts,
        vcs_uri=m_vcs,
        commit_sha=m_commit,
        mode=m_mode,
    )
    timing.steps.extend(phase2_steps)
    return timing


def _run_baseline(
    repo_name, repo_cfg, paths_cfg,
    run_ts, pipeline,
):
    """Run non-instrumented build and save baseline.

    Delegates to ``BomtraceBuilder.build_baseline()``
    which runs clean + prebuild + build WITHOUT tracer.
    Each step is timed separately so the build step
    can be compared apples-to-apples against the
    instrumented build.
    """
    from app.pipeline.timing import save_baseline

    print(f"\n[BASELINE] {repo_name}: "
          "non-instrumented build")

    build_result = pipeline.builder.build_baseline(
        repo_name, repo_cfg, paths_cfg,
    )
    if build_result is None or not build_result.success:
        print(f"[ERROR] Baseline failed: {repo_name}")
        return

    save_baseline(
        build_result, paths_cfg, repo_name,
        repo_cfg, run_ts=run_ts,
    )

    # Report the build step specifically
    build_step = next(
        (s for s in build_result.steps
         if s.name == "build"),
        None,
    )
    if build_step:
        print(
            f"[BASELINE] {repo_name}: build "
            f"{build_step.wall_sec:.1f}s "
            f"(CPU eff: "
            f"{build_step.cpu_efficiency:.2f}x)"
        )
    total = sum(
        s.wall_sec for s in build_result.steps
    )
    print(
        f"[BASELINE] {repo_name}: total "
        f"{total:.1f}s"
    )
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
