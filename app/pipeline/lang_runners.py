"""
Language-specific pipeline runners.

Contains the per-language orchestration functions that run
the build→SPDX→validate→collect workflow for C/C++, Rust,
Go, and Java repositories.

Each runner returns a ``TimingResult`` with per-step
metrics for Phase 1 (build interception) and Phase 2
(post-build analysis).
"""

import logging
import sys
from pathlib import Path

from app.config import lang_subdir
from app.pipeline.timing import StepTimer, TimingResult

logger = logging.getLogger(__name__)

# Java build tools recognized by _detect_java_build_tool().
_KNOWN_JAVA_BUILD_TOOLS = (
    "gradle", "maven", "ivy", "ant", "make", "bazel",
)


# ============================================================
# C/C++ pipeline
# ============================================================

def run_c_cpp_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_cfg, run_ts,
    vcs_uri="NOASSERTION",
):
    """C/C++ pipeline: apt validation, bomtrace3 build,
    OmniBOR SPDX, metadata, ADG SPDX, validation,
    binary collection.

    Returns ``TimingResult`` with per-step metrics.
    """
    tracer = omnibor_cfg.get("tracer", "bomtrace3")
    timing = TimingResult(tracer=tracer)

    # Validate apt dependencies
    deps_ok, missing = (
        pipeline.validator.validate(repo_cfg)
    )
    if not deps_ok:
        print(
            "[ERROR] Cannot proceed \u2014 "
            f"{len(missing)} missing package(s). "
            "Add them to the Dockerfile and "
            "rebuild the image."
        )
        sys.exit(1)

    # Phase 1: Build (clean + configure + build + ADG)
    build_result = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
        run_ts=run_ts,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success
    if not build_result.success:
        return timing

    # Phase 2: Post-build analysis
    timing.steps.extend(
        _run_post_build(
            pipeline, repo_name, repo_cfg,
            paths_cfg, run_ts,
            sbom_fn=lambda: pipeline.spdx_gen.generate(
                repo_name, repo_cfg,
                paths_cfg, omnibor_cfg,
                run_ts=run_ts,
                vcs_uri=vcs_uri,
            ),
            spdx_gen_fn=lambda: (
                pipeline.adg_spdx.generate(
                    repo_name, repo_cfg, paths_cfg,
                    run_ts=run_ts,
                    vcs_uri=vcs_uri,
                )
            ),
        )
    )
    return timing


# ============================================================
# Rust pipeline
# ============================================================

def run_rust_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_rust_cfg, run_ts,
    vcs_uri="NOASSERTION",
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

    Returns ``TimingResult`` with per-step metrics.
    """
    tracer = omnibor_rust_cfg.get(
        "tracer", "bomtrace2",
    )
    timing = TimingResult(tracer=tracer)

    # Phase 1: Build
    build_result = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_rust_cfg,
        run_ts=run_ts,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success
    if not build_result.success:
        return timing

    # Phase 2: Post-build analysis
    timing.steps.extend(
        _run_post_build(
            pipeline, repo_name, repo_cfg,
            paths_cfg, run_ts,
            sbom_fn=lambda: pipeline.spdx_gen.generate(
                repo_name, repo_cfg,
                paths_cfg, omnibor_rust_cfg,
                run_ts=run_ts,
                vcs_uri=vcs_uri,
            ),
            spdx_gen_fn=lambda: (
                pipeline.adg_spdx.generate(
                    repo_name, repo_cfg, paths_cfg,
                    run_ts=run_ts,
                    vcs_uri=vcs_uri,
                )
            ),
        )
    )
    return timing


# ============================================================
# Java pipeline
# ============================================================

def _extract_maven_modules(build_steps):
    """Extract ``-pl`` value from Maven build steps.

    Scans the build command strings for ``-pl <modules>``
    to support multi-module projects where dep:tree must
    target the same module(s) as the build.

    Returns:
        The modules string (e.g. ``"crawler4j"``) or None.
    """
    import shlex
    for step in (build_steps or []):
        if not step.startswith("mvn"):
            continue
        tokens = shlex.split(step)
        for i, tok in enumerate(tokens):
            if tok == "-pl" and i + 1 < len(tokens):
                return tokens[i + 1]
    return None


def _detect_java_build_tool(repo_dir, repo_cfg=None):
    """Detect the Java build tool for a repository.

    Returns one of ``gradle`` / ``maven`` / ``ivy`` / ``ant`` /
    ``make`` / ``bazel``, or ``unknown`` when no signal matches.

    A ``java_build_tool`` field in the repo config overrides
    detection (config-driven, never repo-name-keyed). Otherwise
    detection is a pure function over the repo's top-level build
    files, using this precedence: ``gradle`` > ``maven`` >
    ``ivy`` > ``ant`` > ``make`` > ``bazel``. Maven and Gradle
    are checked first because their build files unambiguously
    identify the primary build; ``bazel`` is last because its
    Java share is tiny and a native strategy is deferred.

    Raises:
        ValueError: if ``java_build_tool`` is set to an
            unrecognized value.
    """
    override = (repo_cfg or {}).get("java_build_tool")
    if override:
        tool = str(override).strip().lower()
        if tool not in _KNOWN_JAVA_BUILD_TOOLS:
            raise ValueError(
                f"Unknown java_build_tool '{override}'; expected "
                f"one of {_KNOWN_JAVA_BUILD_TOOLS}"
            )
        return tool

    from app.spdx.gradle_parser import is_gradle_project

    repo_path = Path(repo_dir)
    if is_gradle_project(str(repo_path)):
        return "gradle"
    if (repo_path / "pom.xml").exists():
        return "maven"
    if (repo_path / "ivy.xml").exists():
        return "ivy"
    if (repo_path / "build.xml").exists():
        return "ant"
    if any(
        (repo_path / f).exists()
        for f in ("Makefile", "makefile", "GNUmakefile")
    ):
        return "make"
    if any(
        (repo_path / f).exists()
        for f in ("WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel")
    ):
        return "bazel"
    return "unknown"


def _select_java_strategy(
    repo_name, repo_cfg, paths_cfg, mode,
):
    """Select interception strategy for Java builds.

    In sidecar mode, uses dep:tree strategies that avoid
    strace entirely.  Detects the build tool via
    ``_detect_java_build_tool``.

    In standalone mode, returns None (legacy strace path).
    """
    if mode != "sidecar":
        return None

    repo_dir = (
        Path(paths_cfg["repos_dir"]) / repo_name
    )
    tool = _detect_java_build_tool(str(repo_dir), repo_cfg)

    if tool == "gradle":
        from app.pipeline.interception import (
            GradleDepTreeStrategy,
        )
        return GradleDepTreeStrategy()

    if tool not in ("maven", "unknown"):
        logger.info(
            "Java build tool '%s' detected for %s; native "
            "dependency capture is not yet implemented \u2014 "
            "falling back to the Maven dep:tree strategy",
            tool, repo_name,
        )

    from app.pipeline.interception import (
        MavenDepTreeStrategy,
    )
    maven_modules = _extract_maven_modules(
        repo_cfg.get("build_steps"),
    )
    return MavenDepTreeStrategy(
        maven_modules=maven_modules,
    )


def run_java_phase1(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_java_cfg, run_ts,
    mode="standalone",
):
    """Java Phase 1: build interception only.

    In standalone mode: strace + bomsh_create_bom_java.py.
    In sidecar mode: dep:tree strategy (no strace needed).

    Returns ``(TimingResult, strategy)`` tuple.
    The strategy is needed by Phase 2 dispatch but is
    a Phase 1 decision, so it is returned here.
    """
    strategy = _select_java_strategy(
        repo_name, repo_cfg, paths_cfg, mode,
    )
    tracer = strategy.name if strategy else "strace"
    timing = TimingResult(tracer=tracer)

    if strategy:
        build_result = pipeline.builder.build(
            repo_name, repo_cfg,
            paths_cfg, omnibor_java_cfg,
            run_ts=run_ts,
            strategy=strategy,
        )
    else:
        build_result = pipeline.builder.build_java(
            repo_name, repo_cfg,
            paths_cfg, omnibor_java_cfg,
            run_ts=run_ts,
        )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success

    # Persist the SHA-256 identity index while build intermediates
    # (.class) still exist, so an offline Phase 2 can surface
    # identity for files removed by workspace cleanup (design of
    # record: project/artifact-identity.md, Java caveats).  bomsh's
    # SHA-1 treedb is used only to enumerate node paths (topology).
    if timing.success:
        _persist_identity_index(
            repo_name, repo_cfg, paths_cfg, run_ts,
        )

    return timing, strategy


def _persist_identity_index(
    repo_name, repo_cfg, paths_cfg, run_ts,
):
    """Write the Phase-1 identity index for a Java run.

    Generic across standalone and sidecar modes: both write the
    bomsh treedb to the same ``bom_dir``.  Failure to persist the
    index is non-fatal (logged, not raised) so it never breaks a
    successful build.
    """
    from app.spdx.parser import AdgParser

    lang = lang_subdir(repo_cfg)
    bom_dir = (
        Path(paths_cfg["output_dir"])
        / "omnibor" / lang / repo_name / run_ts
    )
    try:
        count = AdgParser(
            str(bom_dir), paths_cfg["repos_dir"],
        ).persist_identity_index()
    except (OSError, ValueError) as exc:
        print(
            f"[WARN] identity index not written for "
            f"{repo_name}: {exc}"
        )
        return
    print(
        f"[OK] identity index: {count} artifacts "
        f"({bom_dir}/metadata/bomsh/"
        f"bomsh_identity_index.json)"
    )


def run_java_phase2(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_java_cfg, run_ts,
    vcs_uri="NOASSERTION",
):
    """Java Phase 2: SPDX generation + validation.

    Runs post-build analysis: OmniBOR SBOM, metadata,
    per-binary SPDX, validation, binary collection.

    Returns list of ``StepMetrics``.
    """
    return _run_post_build(
        pipeline, repo_name, repo_cfg,
        paths_cfg, run_ts,
        sbom_fn=lambda: (
            pipeline.spdx_gen.generate_java(
                repo_name, repo_cfg,
                paths_cfg, omnibor_java_cfg,
                run_ts=run_ts,
            )
        ),
        spdx_gen_fn=lambda: (
            generate_java_adg_spdx(
                repo_name, repo_cfg,
                paths_cfg, run_ts,
                vcs_uri=vcs_uri,
            )
        ),
    )


def run_java_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_java_cfg, run_ts,
    vcs_uri="NOASSERTION",
    mode="standalone",
):
    """Java pipeline: build + SPDX generation.

    In standalone mode (default): strace + bomsh_create_bom_java.py.
    In sidecar mode: dep:tree strategy (no strace needed).

    Backward-compatible: calls Phase 1 then Phase 2
    sequentially. For phase isolation, use
    ``run_java_phase1`` / ``run_java_phase2`` directly.

    Returns ``TimingResult`` with per-step metrics.
    """
    timing, _ = run_java_phase1(
        pipeline, repo_name, repo_cfg,
        paths_cfg, omnibor_java_cfg, run_ts,
        mode=mode,
    )
    if not timing.success:
        return timing

    timing.steps.extend(
        run_java_phase2(
            pipeline, repo_name, repo_cfg,
            paths_cfg, omnibor_java_cfg, run_ts,
            vcs_uri=vcs_uri,
        )
    )
    return timing


def _find_module_dir(jar_path):
    """Find the build-module directory for an output JAR.

    Walks up from the JAR's build-output directory to the nearest
    ancestor containing a build file (``pom.xml`` /
    ``build.gradle`` / ``build.gradle.kts``). Used only by the
    co-located dev/test live-resolution fallback; the enterprise
    path never reads the source tree.

    Returns the module directory as a string, or None if not found.
    """
    jar_dir = jar_path.parent
    build_files = (
        "pom.xml", "build.gradle", "build.gradle.kts",
    )
    for parent in [
        jar_dir, jar_dir.parent, jar_dir.parent.parent,
    ]:
        if any(
            (parent / bf).exists() for bf in build_files
        ):
            return str(parent)
    return None


def generate_java_adg_spdx(
    repo_name, repo_cfg, paths_cfg, run_ts,
    vcs_uri="NOASSERTION",
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
    from app.pipeline.maven_plugin_detector import (
        detect_repackaging_plugins,
    )
    from app.spdx.dep_capture_reader import (
        get_module_deps,
        load_capture,
    )
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

    # OmniBOR artifact identity per JAR is computed by reading the
    # built JAR itself in the generator (raw SHA-256 + SHA-256
    # gitOID); bomsh's SHA-1 treedb is topology only and is not
    # surfaced (see project/artifact-identity.md).

    # Topology completeness: warn when a JAR's .class files do not
    # trace back to a .java source (strace capture gap).  Design of
    # record Java caveat (project/artifact-identity.md).
    for rel, stats in parser.validate_jar_topology().items():
        missing = stats["classes_without_source"]
        if missing:
            print(
                f"[WARN] {rel}: {missing}/{stats['classes']} "
                f".class files have no traced .java source "
                f"(strace capture gap — topology incomplete)"
            )

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

    # Detect shade/assembly plugins for SPDX annotation
    plugin_result = detect_repackaging_plugins(
        str(repo_dir),
    )
    if plugin_result.is_uber_jar:
        for det in plugin_result.detections:
            print(f"[WARN] {repo_name}: {det.warning}")

    gen = JavaSpdxGenerator(
        bom_dir=str(bom_dir),
        repos_dir=repos_dir,
        repo_name=repo_name,
        strace_accessed=strace_accessed,
        vcs_uri=vcs_uri,
    )

    # Phase 2 generates _build SBOMs from the Phase 1 dependency
    # capture (no source-tree access).  ``source_present`` marks a
    # co-located dev/test run, where a live-resolution fallback is
    # permitted if the capture is missing; the enterprise path
    # (no source tree) fails loudly instead.
    capture = load_capture(bom_dir)
    source_present = repo_dir.exists()

    results = []
    for jar_path in jar_paths:
        jar_name = jar_path.stem  # e.g. jsoup-1.22.1
        bin_name = jar_path.name  # e.g. jsoup-1.22.1.jar

        # Find matching treedb entry by JAR path.
        # Try exact path first, then fall back to
        # matching by JAR filename (Gradle maven-publish
        # puts JARs in build/maven-repository/ while
        # the output_binaries glob finds build/libs/).
        rel_jar = str(
            jar_path.relative_to(repo_dir)
        )
        lookup_key = f"{repo_name}/{rel_jar}"
        jar_files = jar_map.get(lookup_key)
        if jar_files is None:
            # Fallback: match by JAR filename
            for key in jar_map:
                if key.endswith(f"/{bin_name}"):
                    jar_files = jar_map[key]
                    print(
                        f"[OK] Matched {bin_name} "
                        f"via filename (treedb path "
                        f"differs from glob path)"
                    )
                    break
        if jar_files is None:
            print(
                f"[ERROR] No treedb entry for "
                f"{bin_name} — skipping SPDX "
                f"generation (looked up: "
                f"{lookup_key})"
            )
            continue

        # Resolve this JAR's dependency subtree from the Phase 1
        # capture (no source-tree access).  The module is identified
        # from artifact metadata that travels with the JAR: its
        # artifactId / subproject name and its build-output path.
        artifact_name = (
            JavaSpdxGenerator.extract_artifact_name(bin_name)
        )
        build_deps = None
        if capture is not None:
            build_deps = get_module_deps(
                capture, artifact_name, rel_jar,
            )

        # Decide the _build dependency source.  Per design, the
        # enterprise path (no source tree) fails loudly when the
        # capture lacks this module; a co-located dev/test run may
        # fall back to live resolution from the source tree.
        pom_dir = None
        build_ok = True
        if build_deps is None:
            if source_present:
                print(
                    f"[WARN] {bin_name}: no Phase 1 dependency "
                    f"metadata; falling back to live resolution "
                    f"(co-located dev/test path)"
                )
                pom_dir = _find_module_dir(jar_path)
            else:
                print(
                    f"[ERROR] {bin_name}: no Phase 1 dependency "
                    f"metadata and no source tree — cannot "
                    f"generate _build SBOM (enterprise Phase 2 "
                    f"requires the capture); skipping _build"
                )
                build_ok = False

        # Analyzed: only source files in this JAR.  It never needs
        # dependencies, so pass deps=[] to keep it off the source
        # tree entirely.
        analyzed_path = (
            spdx_dir
            / f"{jar_name}_analyzed.spdx.json"
        )
        result = gen.generate(
            output_path=str(analyzed_path),
            binary_name=bin_name,
            sbom_type="analyzed",
            jar_files=jar_files,
            deps=[],
            plugin_detection=plugin_result,
            jar_path=str(jar_path),
        )
        if result:
            results.append(result)

        # Build: full dependency graph for this module, from the
        # captured metadata (build_deps) or the co-located live
        # fallback (build_deps is None with pom_dir set).
        if build_ok:
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
                deps=build_deps,
                plugin_detection=plugin_result,
                jar_path=str(jar_path),
            )
            if result:
                results.append(result)

    return results


# ============================================================
# Go pipeline
# ============================================================

def run_go_pipeline(
    pipeline, repo_name, repo_cfg,
    paths_cfg, omnibor_go_cfg, run_ts,
    vcs_uri="NOASSERTION",
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

    Returns ``TimingResult`` with per-step metrics.
    """
    tracer = omnibor_go_cfg.get(
        "tracer", "bomtrace2",
    )
    timing = TimingResult(tracer=tracer)

    # Phase 1: Build
    build_result = pipeline.builder.build(
        repo_name, repo_cfg,
        paths_cfg, omnibor_go_cfg,
        run_ts=run_ts,
    )
    timing.steps.extend(build_result.steps)
    timing.success = build_result.success
    if not build_result.success:
        return timing

    # Phase 2: Post-build analysis
    timing.steps.extend(
        _run_post_build(
            pipeline, repo_name, repo_cfg,
            paths_cfg, run_ts,
            sbom_fn=lambda: pipeline.spdx_gen.generate(
                repo_name, repo_cfg,
                paths_cfg, omnibor_go_cfg,
                run_ts=run_ts,
                vcs_uri=vcs_uri,
            ),
            spdx_gen_fn=lambda: (
                pipeline.adg_spdx.generate(
                    repo_name, repo_cfg, paths_cfg,
                    run_ts=run_ts,
                    vcs_uri=vcs_uri,
                )
            ),
        )
    )
    return timing


# ============================================================
# Shared post-build helper (Phase 2 steps)
# ============================================================

def _run_post_build(
    pipeline, repo_name, repo_cfg,
    paths_cfg, run_ts,
    sbom_fn=None,
    spdx_gen_fn=None,
):
    """Run Phase 2 post-build steps (generic, all languages).

    Callers inject two callbacks to vary behavior:

    - ``sbom_fn``: generates the OmniBOR SBOM
      (``bomsh_sbom.py`` for C/Rust/Go, no-op for Java).
    - ``spdx_gen_fn``: generates per-binary SPDX
      (``AdgSpdxGenerator`` for C/Rust/Go,
      ``JavaSpdxGenerator`` for Java).

    Returns list of ``StepMetrics`` for each step.
    """
    steps = []

    # OmniBOR SBOM
    spdx_file = None
    timer = StepTimer("omnibor_sbom", "phase2")
    with timer:
        if sbom_fn:
            spdx_file = sbom_fn()
    steps.append(timer.metrics)

    # Metadata collection
    timer = StepTimer("metadata", "phase2")
    with timer:
        pipeline.metadata_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )
    steps.append(timer.metrics)

    # SPDX generation
    adg_files = []
    timer = StepTimer("spdx_gen", "phase2")
    with timer:
        if spdx_gen_fn:
            adg_files = spdx_gen_fn()
    steps.append(timer.metrics)

    # Validation
    timer = StepTimer("validate", "phase2")
    with timer:
        if spdx_file:
            pipeline.spdx_validator.validate(
                spdx_file,
            )
        for adg_file in adg_files:
            pipeline.spdx_validator.validate(
                adg_file,
            )
    steps.append(timer.metrics)

    # Binary collection
    timer = StepTimer("collect", "phase2")
    with timer:
        pipeline.binary_collector.collect(
            repo_name, repo_cfg, paths_cfg,
            run_ts=run_ts,
        )
    steps.append(timer.metrics)

    return steps
