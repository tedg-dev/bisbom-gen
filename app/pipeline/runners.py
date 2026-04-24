"""
CLI entry point and language-specific pipeline runners.

Contains main() and the three language-specific pipeline
functions that orchestrate the build→SPDX→validate→collect
workflow for C/C++, Rust, and Go repositories.
"""

import argparse
import sys
import time
from pathlib import Path

from app.config import load_config, timestamp, lang_subdir
from app.pipeline.facade import AnalysisPipeline


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
            "(no build)"
        ),
    )
    args = parser.parse_args()

    config = load_config()
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
    lang_omnibor_keys = {
        "c-cpp": "omnibor",
        "rust": "omnibor_rust",
        "java": "omnibor_java",
        "go": "omnibor_go",
    }
    lang = lang_subdir(repo_cfg)
    omnibor_key = lang_omnibor_keys.get(
        lang, "omnibor_go"
    )
    omnibor_cfg = config[omnibor_key]

    # Single timestamp for the entire run — all
    # output folders use this consistently:
    #   output/binaries/{lang}/{repo}/{run_ts}/
    #   output/spdx/{lang}/{repo}/{run_ts}/
    #   output/omnibor/{lang}/{repo}/{run_ts}/
    #   docs/build-logs/{lang}/{repo}/{run_ts}/
    #   docs/runtime/{lang}/{repo}/{run_ts}/
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

    # Step 2: Syft SBOM (manifest-based — works for
    # all languages; primary SBOM for Go repos)
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
        success, duration = _run_c_cpp_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    elif lang == "rust":
        success, duration = _run_rust_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    elif lang == "java":
        success, duration = _run_java_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )
    else:
        success, duration = _run_go_pipeline(
            pipeline, args.repo, repo_cfg,
            paths_cfg, omnibor_cfg, run_ts,
        )

    # Step 7b: Validate Syft SPDX (all languages)
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


def _run_c_cpp_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
):
    """C/C++ pipeline: apt validation, bomtrace3 build,
    OmniBOR SPDX, metadata, ADG SPDX, validation,
    binary collection.

    Returns (success, duration_sec).
    """
    # Step 3: Validate apt dependencies
    deps_ok, missing = (
        pipeline.validator.validate(repo_cfg)
    )
    if not deps_ok:
        print(
            "[ERROR] Cannot proceed — "
            f"{len(missing)} missing package(s). "
            "Add them to the Dockerfile and "
            "rebuild the image."
        )
        sys.exit(1)

    # Step 4: Instrumented build
    start = time.time()
    success = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate(
            repo_name, repo_cfg,
            paths_cfg, omnibor_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata + dynamic libs
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX
    adg_files = []
    if success:
        adg_files = pipeline.adg_spdx.generate(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Step 7: Collect output binaries
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration


def _run_rust_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
):
    """Rust pipeline: bomtrace2 instrumented build,
    OmniBOR ADG, SPDX generation, metadata, ADG SPDX,
    validation, binary collection.

    Uses bomtrace2 with the default bomtrace.conf.
    bomsh_hook2.py has a dedicated rustc command parser
    (get_all_subfiles_in_rustc_cmdline) that extracts
    input .rs files and output .rlib / binary files.

    See: https://github.com/omnibor/bomsh
    #software-vulnerability-cve-search-for-rust-packages

    Returns (success, duration_sec).
    """
    # Step 4: Instrumented build (bomtrace2)
    start = time.time()
    success = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_rust_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate(
            repo_name, repo_cfg,
            paths_cfg, omnibor_rust_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX
    adg_files = []
    if success:
        adg_files = pipeline.adg_spdx.generate(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Step 7: Collect output binaries
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration


def _run_java_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_java_cfg, run_ts,
):
    """Java pipeline: strace-instrumented Maven build,
    bomsh_create_bom_java.py for OmniBOR ADG, SPDX generation,
    metadata, ADG SPDX, validation, JAR collection.

    Java uses a different approach than C/C++/Rust/Go:
    1. Build with strace to capture file I/O
    2. Run bomsh_create_bom_java.py with strace log
       to create the OmniBOR treedb

    See: https://github.com/omnibor/bomsh
    #software-vulnerability-cve-search-for-java-packages

    Returns (success, duration_sec).
    """
    # Step 4: Instrumented build (strace + Maven)
    start = time.time()
    success = pipeline.builder.build_java(
        repo_name, repo_cfg,
        paths_cfg, omnibor_java_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    # (Java uses bomsh_create_bom_java.py output)
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate_java(
            repo_name, repo_cfg,
            paths_cfg, omnibor_java_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX (Java-specific)
    adg_files = []
    if success:
        adg_files = _generate_java_adg_spdx(
            repo_name, repo_cfg, paths_cfg, run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Step 7: Collect output JARs
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration


def _generate_java_adg_spdx(
    repo_name, repo_cfg, paths_cfg, run_ts,
):
    """Generate per-binary Java SPDX.

    Produces two SBOMs per JAR (CISA taxonomy):
      - _analyzed: only source files in the JAR
      - _build: full Maven dependency graph

    For multi-module Maven projects, each output JAR
    gets its own SPDX pair with only the files that
    were compiled into that specific JAR (traced via
    bomsh treedb hash_tree).
    """
    from app.spdx.java_generator import JavaSpdxGenerator
    from app.spdx.parser import AdgParser

    lang = lang_subdir(repo_cfg)
    bom_dir = (
        Path(paths_cfg["output_dir"])
        / "omnibor" / lang / repo_name / run_ts
    )
    repos_dir = paths_cfg["repos_dir"]
    repo_dir = Path(repos_dir) / repo_name
    spdx_dir = (
        Path(paths_cfg["output_dir"])
        / "spdx" / lang / repo_name / run_ts
    )
    spdx_dir.mkdir(parents=True, exist_ok=True)

    # Get per-JAR source file mapping from treedb
    parser = AdgParser(str(bom_dir), repos_dir)
    try:
        jar_map = parser.get_jar_source_files()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return []

    # Parse strace openat log — the set of files
    # actually opened during the build.  Mirrors
    # how C/C++ uses load_raw_logfile_hashes() to
    # consume tracer output.
    strace_accessed = parser.parse_strace_openat_log()
    if strace_accessed:
        print(
            f"[OK] strace log: "
            f"{len(strace_accessed)} files "
            f"accessed during build"
        )

    # Resolve output_binaries globs to actual JARs
    bins = repo_cfg.get("output_binaries", [])
    jar_paths = []
    for pattern in bins:
        if "*" in pattern or "?" in pattern:
            jar_paths.extend(repo_dir.glob(pattern))
        else:
            p = repo_dir / pattern
            if p.exists():
                jar_paths.append(p)

    # Filter to production JARs only
    from app.pipeline.binary_collector import (
        BinaryCollector,
    )
    jar_paths = [
        p for p in jar_paths
        if not BinaryCollector._is_auxiliary_jar(
            p.name
        )
    ]

    if not jar_paths:
        print(
            f"[WARN] No output JARs found for "
            f"{repo_name}"
        )
        return []

    gen = JavaSpdxGenerator(
        bom_dir=str(bom_dir),
        repos_dir=repos_dir,
        repo_name=repo_name,
        strace_accessed=strace_accessed,
    )

    results = []
    for jar_path in jar_paths:
        jar_name = jar_path.stem  # e.g. jsoup-1.22.1
        bin_name = jar_path.name  # e.g. jsoup-1.22.1.jar

        # Find matching treedb entry by JAR path
        rel_jar = str(
            jar_path.relative_to(repo_dir)
        )
        jar_files = jar_map.get(
            f"{repo_name}/{rel_jar}"
        )
        if jar_files is None:
            print(
                f"[WARN] No treedb entry for "
                f"{rel_jar}, using all project files"
            )

        # Determine module pom_dir for per-module
        # Maven deps (e.g. cli/pom.xml, core/pom.xml)
        pom_dir = None
        jar_dir = jar_path.parent
        # Walk up from target/ to find module pom.xml
        for parent in [jar_dir, jar_dir.parent]:
            if (parent / "pom.xml").exists():
                pom_dir = str(parent)
                break

        # Analyzed: only source files in this JAR
        analyzed_path = (
            spdx_dir
            / f"{jar_name}_analyzed.spdx.json"
        )
        result = gen.generate(
            output_path=str(analyzed_path),
            binary_name=bin_name,
            sbom_type="analyzed",
            jar_files=jar_files,
            pom_dir=pom_dir,
        )
        if result:
            results.append(result)

        # Build: full dependency graph for this module
        build_path = (
            spdx_dir
            / f"{jar_name}_build.spdx.json"
        )
        result = gen.generate(
            output_path=str(build_path),
            binary_name=bin_name,
            sbom_type="build",
            jar_files=jar_files,
            pom_dir=pom_dir,
        )
        if result:
            results.append(result)

    return results


def _run_go_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
):
    """Go pipeline: bomtrace2 instrumented build,
    OmniBOR ADG, SPDX generation, metadata, ADG SPDX,
    validation, binary collection.

    Uses bomtrace2 with a Go-specific bomtrace.conf
    that watches the Go compiler tools (compile, link)
    and traces the openat syscall.  ``go build -a`` is
    required to bypass the Go build cache so bomtrace2
    captures all compilation steps.

    See: https://github.com/omnibor/bomsh
    #software-vulnerability-cve-search-for-golang-packages

    Returns (success, duration_sec).
    """
    # Step 4: Instrumented build (bomtrace2)
    start = time.time()
    success = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_go_cfg,
        run_ts=run_ts,
    )
    duration = time.time() - start

    # Step 5a: Generate SPDX from OmniBOR
    spdx_file = None
    if success:
        spdx_file = pipeline.spdx_gen.generate(
            repo_name, repo_cfg,
            paths_cfg, omnibor_go_cfg,
            run_ts=run_ts,
        )

    # Step 5b: Collect component metadata
    if success:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 5c: Generate per-binary ADG SPDX
    adg_files = []
    if success:
        adg_files = pipeline.adg_spdx.generate(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    # Step 6: Validate SPDX documents
    if spdx_file:
        pipeline.spdx_validator.validate(spdx_file)
    for adg_file in adg_files:
        pipeline.spdx_validator.validate(adg_file)

    # Step 7: Collect output binaries
    if success:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )

    return success, duration
