"""
Build interception strategies for OmniBOR Analysis.

Defines the ``InterceptionStrategy`` ABC and concrete
implementations for different build interception methods.

Each strategy provides two operations:

1. ``instrument_command()`` — modify a build command to
   enable OmniBOR tracing (e.g. prepend bomtrace3, set
   environment variables, or pass through unmodified).
2. ``generate_adg()`` — produce the OmniBOR Artifact
   Dependency Graph from tracer output or build-tool
   dependency information.

Design reference:
    Implementation Design §4.4 — Interception Strategy
"""

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.pipeline.java_capture import (
    CAPTURE_LOG_ENV,
    assemble_treedb,
    read_capture_log,
)


def build_inline_hash_env(shim_path, capture_log, extra=None):
    """Return the env additions that enable inline hashing.

    The only build-visible change in inline mode: load the ``LD_PRELOAD``
    shim and point it at a capture log.  The native build command,
    ``pom.xml``/``build.gradle``, and ``settings.gradle`` are untouched
    (sidecar constraint C2/C3).

    Args:
        shim_path: Absolute path to ``libomnibor_java_intercept.so``.
        capture_log: Absolute path the shim appends capture events to.
        extra: Optional extra env vars (e.g. Gradle daemon disable).

    Returns:
        Dict of environment variables to set for the build.
    """
    env = {"LD_PRELOAD": shim_path, CAPTURE_LOG_ENV: capture_log}
    if extra:
        env.update(extra)
    return env


def prepare_capture_log(capture_log):
    """Create the capture-log directory and clear any stale log.

    The shim opens the log with ``O_CREAT | O_APPEND`` but does not create
    parent directories, and a stale log from a previous run would pollute
    the assembled treedb.  Called before the build so every run starts
    from a clean, writable capture log.
    """
    parent = os.path.dirname(capture_log)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.remove(capture_log)
    except FileNotFoundError:
        pass


def _git_blob_sha1(path):
    """Git-blob ``SHA-1`` of a file: ``SHA-1("blob <len>\\0" + data)``.

    Matches ``docker/patches/bomsh_java_fast_io.py:git_blob_hash`` so the
    assembled treedb keys are identical to the legacy rescan's.
    """
    data = Path(path).read_bytes()
    sha = hashlib.sha1()
    sha.update(b"blob %d\0" % len(data))
    sha.update(data)
    return sha.hexdigest()


def make_source_resolver(repo_dir):
    """Build a class -> source ``.java`` resolver over *repo_dir*.

    Indexes source files once (a cheap walk — sources are far fewer than
    ``.class`` files and are never zipped), then resolves each class's
    ``SourceFile`` attribute + fully-qualified name to the matching
    ``.java`` path and its git-blob ``SHA-1``.  This is the only
    filesystem read the inline path performs, and it touches sources
    only — never the ``.class``/``.jar`` bytes the shim already hashed.

    Returns:
        A ``(source_file, class_name) -> (path, sha1) | None`` callable.
    """
    index = {}
    for root, _dirs, files in os.walk(repo_dir):
        for name in files:
            if name.endswith(".java"):
                index.setdefault(name, []).append(
                    os.path.join(root, name)
                )

    def resolve(source_file, class_name):
        if not source_file:
            return None
        candidates = index.get(source_file)
        if not candidates:
            return None
        if class_name and "." in class_name:
            pkg = class_name.rsplit(".", 1)[0].replace(".", "/")
            wanted = pkg + "/" + source_file
            for path in candidates:
                norm = path.replace(os.sep, "/")
                if norm.endswith(wanted):
                    return path, _git_blob_sha1(path)
        if len(candidates) == 1:
            return candidates[0], _git_blob_sha1(candidates[0])
        return None

    return resolve


def assemble_treedb_from_capture(
    capture_log, repo_dir, meta_dir, substeps, resolver=None,
):
    """Assemble the bomsh treedb from the inline capture log.

    Replaces the post-build workspace rescan: reads the shim's capture
    events and writes ``bomsh_omnibor_treedb`` in the exact bomsh schema.
    Fails loudly (returns False) if the capture log is missing or empty —
    in the enterprise inline path there is no silent rescan fallback
    (design C4/C5).

    Appends a ``treedb`` timing entry to *substeps*.
    """
    t0 = time.monotonic()
    events = read_capture_log(capture_log)
    if not events:
        substeps.append({
            "name": "treedb",
            "tool": "inline-assemble",
            "wall_sec": round(time.monotonic() - t0, 2),
        })
        print(
            "[ERROR] inline capture log missing or empty: "
            f"{capture_log}"
        )
        return False
    if resolver is None:
        resolver = make_source_resolver(repo_dir)
    treedb = assemble_treedb(events, resolve_source=resolver)
    treedb_file = Path(meta_dir) / "bomsh_omnibor_treedb"
    with open(treedb_file, "w", encoding="utf-8") as handle:
        json.dump(treedb, handle)
    treedb_sec = time.monotonic() - t0
    substeps.append({
        "name": "treedb",
        "tool": "inline-assemble",
        "wall_sec": round(treedb_sec, 2),
    })
    print(
        f"[OK] OmniBOR treedb assembled from {len(events)} "
        f"capture events \u2192 {treedb_file} "
        f"({treedb_sec:.1f}s)"
    )
    return True


def build_java_treedb(
    inline_hash, capture_log, runner, repo_dir,
    meta_dir, omnibor_cfg, substeps,
):
    """Build the Java treedb via inline assembly or legacy rescan.

    Shared by the Maven and Gradle sidecar strategies so both pick the
    treedb source identically (DRY).  Inline assembly is used when the
    strategy was configured for inline hashing and a capture-log path is
    known; otherwise the legacy post-build rescan runs.
    """
    if inline_hash and capture_log:
        return assemble_treedb_from_capture(
            capture_log, repo_dir, meta_dir, substeps,
        )
    return _generate_java_treedb(
        runner, repo_dir, meta_dir, omnibor_cfg, substeps,
    )


def _write_adg_substeps(bom_path, substeps):
    """Write ADG sub-step timings to ``adg_substeps.json``.

    Called by ``generate_adg()`` implementations to persist
    the wall-clock breakdown (treedb vs dep:tree) for
    performance analysis.

    Args:
        bom_path: ``Path`` to the OmniBOR output directory.
        substeps: List of timing dicts with ``name``,
            ``tool``, and ``wall_sec`` keys.
    """
    out = bom_path / "adg_substeps.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(substeps, f, indent=2)


def _generate_java_treedb(
    runner, repo_dir, meta_dir, omnibor_cfg, substeps,
):
    """Generate the OmniBOR treedb for a Java workspace.

    Runs ``bomsh_create_bom_java.py`` to map JAR -> class ->
    source from the built workspace.  This step is
    **build-tool-agnostic** (it inspects compiled artifacts,
    not build files) and is shared by every Java sidecar
    strategy.  Appends a ``treedb`` timing entry to *substeps*.

    Args:
        runner: ``CommandRunner`` used to invoke the script.
        repo_dir: Path to the built repository workspace.
        meta_dir: ``Path`` to the bomsh metadata directory
            where the treedb is written.
        omnibor_cfg: The ``omnibor`` config section.
        substeps: Mutable list of timing dicts; a ``treedb``
            entry is appended.

    Returns:
        True on success, False if the script fails.
    """
    create_bom = omnibor_cfg.get(
        "create_bom_script",
        "bomsh_create_bom_java.py",
    )
    treedb_file = meta_dir / "bomsh_omnibor_treedb"
    t0 = time.monotonic()
    rc = runner.run(
        f"{create_bom} -r {repo_dir} -j {treedb_file} "
        f"-b {meta_dir} -m",
        cwd=str(repo_dir),
        description=(
            "Generating OmniBOR treedb for Java workspace"
        ),
    )
    treedb_sec = time.monotonic() - t0
    substeps.append({
        "name": "treedb",
        "tool": "bomsh_create_bom_java.py",
        "wall_sec": round(treedb_sec, 2),
    })
    if rc != 0:
        print("[ERROR] bomsh_create_bom_java.py failed")
        return False
    print(
        f"[OK] OmniBOR treedb written to "
        f"{treedb_file} ({treedb_sec:.1f}s)"
    )
    return True


class InterceptionStrategy(ABC):
    """Defines how a build is instrumented for OmniBOR tracing.

    Concrete strategies implement distro-specific or
    language-specific instrumentation. The pipeline
    selects a strategy based on ``config.yaml`` settings.
    """

    @property
    @abstractmethod
    def name(self):
        """Human-readable instrumentation method name.

        Used in build docs and runtime reports to
        identify the interception technique.
        """

    @abstractmethod
    def instrument_command(self, build_cmd, repo_dir):
        """Modify a build command for OmniBOR tracing.

        Args:
            build_cmd: The original build command string.
            repo_dir: Path to the repository root.

        Returns:
            A ``(command, env)`` tuple where *command* is
            the (possibly modified) build command string
            and *env* is a dict of environment variables
            to set during the build (empty dict if none).
        """

    @abstractmethod
    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Generate the OmniBOR Artifact Dependency Graph.

        Args:
            repo_dir: Path to the repository root.
            bom_dir: Path to the OmniBOR output directory.
            omnibor_cfg: The ``omnibor`` config section.

        Returns:
            True on success, False on failure.
        """


class PtraceStrategy(InterceptionStrategy):
    """Standalone mode: bomtrace3/bomtrace2 prefix.

    Encapsulates the current default behavior where the
    build command is prefixed with the tracer binary
    (e.g. ``bomtrace3 make -j4``).  The tracer uses
    ptrace to intercept compiler/linker invocations.

    This is the only strategy that requires ``SYS_PTRACE``
    capability in Docker.
    """

    def __init__(self, tracer="bomtrace3"):
        self._tracer = tracer

    @property
    def name(self):
        """Return the tracer binary name."""
        return self._tracer

    def instrument_command(self, build_cmd, repo_dir):
        """Prepend the tracer to the build command.

        Returns:
            ``("{tracer} {build_cmd}", {})``
        """
        return f"{self._tracer} {build_cmd}", {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``bomsh_create_bom.py`` on tracer output.

        The tracer writes a raw logfile during the build.
        ``bomsh_create_bom.py`` reads it to produce the
        OmniBOR treedb and ADG documents.

        Returns:
            True on success, False on failure.
        """
        from app.runner import CommandRunner

        runner = CommandRunner()
        create_bom = omnibor_cfg.get(
            "create_bom_script", "bomsh_create_bom.py",
        )
        raw_logfile = omnibor_cfg.get(
            "raw_logfile",
            "/tmp/bomsh_hook_raw_logfile.sha1",
        )
        rc = runner.run(
            f"{create_bom} -r {raw_logfile} "
            f"-b {bom_dir}",
            cwd=str(repo_dir),
            description=(
                "Generating OmniBOR ADG documents"
            ),
        )
        return rc == 0


class CcWrapperStrategy(InterceptionStrategy):
    """Sidecar C/C++: CC=/CXX=/AR=/LD= environment variables.

    Instead of ptrace, sets compiler environment variables
    to point at OmniBOR wrapper scripts that intercept
    compilation without ``SYS_PTRACE``.
    """

    def __init__(self, wrapper_dir="/opt/bomsh/bin"):
        self._wrapper_dir = wrapper_dir

    @property
    def name(self):
        """Return the instrumentation method."""
        return "cc-wrapper"

    def instrument_command(self, build_cmd, repo_dir):
        """Return the build command with CC/CXX wrappers.

        Returns:
            ``(build_cmd, {"CC": ..., "CXX": ..., ...})``
        """
        d = self._wrapper_dir
        env = {
            "CC": f"{d}/bomsh_cc_wrapper.sh",
            "CXX": f"{d}/bomsh_cxx_wrapper.sh",
            "AR": f"{d}/bomsh_ar_wrapper.sh",
            "LD": f"{d}/bomsh_ld_wrapper.sh",
        }
        return build_cmd, env

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``bomsh_create_bom.py`` on wrapper output.

        Same as ``PtraceStrategy`` — both produce the same
        raw logfile format.
        """
        strategy = PtraceStrategy()
        return strategy.generate_adg(
            repo_dir, bom_dir, omnibor_cfg,
        )


class GoToolexecStrategy(InterceptionStrategy):
    """Sidecar Go: ``-toolexec`` flag injection.

    Go's ``-toolexec`` flag runs each tool invocation
    through a wrapper, avoiding ptrace entirely.
    """

    def __init__(
        self, wrapper="/opt/bomsh/bin/bomsh_hook.sh",
    ):
        self._wrapper = wrapper

    @property
    def name(self):
        """Return the instrumentation method."""
        return "go-toolexec"

    def instrument_command(self, build_cmd, repo_dir):
        """Insert ``-toolexec`` into the go build command.

        Replaces ``go build`` with
        ``go build -toolexec={wrapper}``.

        Returns:
            ``(modified_cmd, {})``
        """
        cmd = build_cmd.replace(
            "go build",
            f"go build -toolexec={self._wrapper}",
            1,
        )
        return cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``bomsh_create_bom.py`` on wrapper output."""
        strategy = PtraceStrategy()
        return strategy.generate_adg(
            repo_dir, bom_dir, omnibor_cfg,
        )


class RustcWrapperStrategy(InterceptionStrategy):
    """Sidecar Rust: ``RUSTC_WRAPPER`` environment variable.

    Rust's ``RUSTC_WRAPPER`` runs each ``rustc`` invocation
    through a wrapper binary, avoiding ptrace.
    """

    def __init__(
        self, wrapper="/opt/bomsh/bin/bomsh_hook.sh",
    ):
        self._wrapper = wrapper

    @property
    def name(self):
        """Return the instrumentation method."""
        return "rustc-wrapper"

    def instrument_command(self, build_cmd, repo_dir):
        """Set ``RUSTC_WRAPPER`` for cargo build.

        Returns:
            ``(build_cmd, {"RUSTC_WRAPPER": ...})``
        """
        return build_cmd, {
            "RUSTC_WRAPPER": self._wrapper,
        }

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``bomsh_create_bom.py`` on wrapper output."""
        strategy = PtraceStrategy()
        return strategy.generate_adg(
            repo_dir, bom_dir, omnibor_cfg,
        )


class MavenDepTreeStrategy(InterceptionStrategy):
    """Java Maven: sidecar mode without ``SYS_PTRACE``.

    In sidecar mode, Java builds do not need strace or
    ptrace.  This strategy:

    1. Runs the build command unmodified (no strace prefix).
    2. Generates OmniBOR treedb via
       ``bomsh_create_bom_java.py`` — the same script used
       in standalone mode.  Without a strace log, it uses
       the ``SourceFile`` bytecode attribute + path
       similarity to trace JAR → class → source.
    3. Runs ``mvn dependency:tree -DoutputType=dot`` to
       capture the declared dependency graph.

    Both data sources feed into the same downstream SPDX
    pipeline as standalone mode.
    """

    def __init__(
        self, runner=None, maven_modules=None,
        inline_hash=False, shim_path=None, capture_log=None,
    ):
        from app.runner import CommandRunner
        self._runner = runner or CommandRunner()
        self._maven_modules = maven_modules
        self._inline_hash = inline_hash
        self._shim_path = shim_path
        self._capture_log = capture_log

    @property
    def name(self):
        """Return the instrumentation method."""
        if self._inline_hash:
            return "maven-inline-hash"
        return "maven-dep-tree"

    def instrument_command(self, build_cmd, repo_dir):
        """Return the build command with optional inline-hash env.

        In inline mode the command is still unchanged; only the
        ``LD_PRELOAD`` shim + capture-log env are added (sidecar C2/C3).

        Returns:
            ``(build_cmd, env)`` — *env* is empty unless inline hashing
            is enabled.
        """
        if self._inline_hash and self._shim_path and self._capture_log:
            prepare_capture_log(self._capture_log)
            return build_cmd, build_inline_hash_env(
                self._shim_path, self._capture_log,
            )
        return build_cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Generate OmniBOR treedb and Maven dependency graph.

        Two data sources for SPDX generation:

        1. ``bomsh_create_bom_java.py`` scans the build
           workspace to produce the OmniBOR treedb
           (JAR → class → source file provenance).
           Uses the same SourceFile bytecode attribute
           + path similarity as standalone mode.
        2. ``mvn dependency:tree`` captures the declared
           Maven dependency graph.

        Sub-step wall-clock timings are written to
        ``adg_substeps.json`` in *bom_dir* for
        performance analysis.

        Returns:
            True on success, False on failure.
        """
        from app.pipeline.maven_dep_tree_parser import (
            parse_text_output,
            run_maven_dep_tree,
        )

        substeps = []
        bom_path = Path(bom_dir)
        bom_path.mkdir(parents=True, exist_ok=True)
        meta_dir = bom_path / "metadata" / "bomsh"
        meta_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Build the OmniBOR treedb — inline assembly from the
        # shim's capture log when inline hashing is enabled, else the
        # legacy post-build rescan.  Shared by all Java sidecar
        # strategies (DRY) and build-tool-agnostic.
        if not build_java_treedb(
            self._inline_hash, self._capture_log,
            self._runner, repo_dir, meta_dir,
            omnibor_cfg, substeps,
        ):
            _write_adg_substeps(bom_path, substeps)
            return False

        # Step 2: Capture Maven dependency graph (per-module).
        # Default text output is parsed into per-module subtrees so
        # Phase 2 can generate per-module ``_build`` SBOMs from this
        # metadata alone, with no source-tree access.
        t0 = time.monotonic()
        tree_output = run_maven_dep_tree(
            repo_dir, runner=self._runner,
            maven_modules=self._maven_modules,
        )
        deptree_sec = time.monotonic() - t0
        substeps.append({
            "name": "dep_tree",
            "tool": "mvn dependency:tree",
            "wall_sec": round(deptree_sec, 2),
        })
        if tree_output is None:
            _write_adg_substeps(bom_path, substeps)
            return False

        modules = parse_text_output(tree_output)
        capture = {"tool": "maven", "modules": modules}
        if not modules:
            print(
                "[WARN] No modules found in "
                "mvn dependency:tree output"
            )

        out_file = bom_path / "maven_deps.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(capture, f, indent=2)

        dep_total = sum(len(m["deps"]) for m in modules)
        print(
            f"[OK] Maven dep:tree: {len(modules)} modules, "
            f"{dep_total} dependencies → {out_file}"
            f" ({deptree_sec:.1f}s)"
        )
        _write_adg_substeps(bom_path, substeps)
        return True


class GradleDepTreeStrategy(InterceptionStrategy):
    """Java Gradle: sidecar mode without ``SYS_PTRACE``.

    Like ``MavenDepTreeStrategy``, this avoids strace/ptrace
    for Gradle-based Java builds:

    1. Runs the build command unmodified.
    2. Generates OmniBOR treedb via
       ``bomsh_create_bom_java.py`` (same as standalone).
    3. Runs ``./gradlew dependencies`` per subproject.
    4. Parses the indented tree output into structured data.

    Both data sources feed into the same downstream SPDX
    pipeline as standalone mode.
    """

    def __init__(
        self, runner=None,
        inline_hash=False, shim_path=None, capture_log=None,
    ):
        from app.runner import CommandRunner
        self._runner = runner or CommandRunner()
        self._inline_hash = inline_hash
        self._shim_path = shim_path
        self._capture_log = capture_log

    @property
    def name(self):
        """Return the instrumentation method."""
        if self._inline_hash:
            return "gradle-inline-hash"
        return "gradle-dep-tree"

    def instrument_command(self, build_cmd, repo_dir):
        """Return the build command with optional inline-hash env.

        In inline mode the command is unchanged; the ``LD_PRELOAD`` shim,
        capture-log path, and a Gradle-daemon-disable flag are added via
        env only so every compiling JVM inherits the preload (sidecar
        C2/C3).

        Returns:
            ``(build_cmd, env)`` — *env* is empty unless inline hashing
            is enabled.
        """
        if self._inline_hash and self._shim_path and self._capture_log:
            prepare_capture_log(self._capture_log)
            return build_cmd, build_inline_hash_env(
                self._shim_path, self._capture_log,
                extra={"GRADLE_OPTS": "-Dorg.gradle.daemon=false"},
            )
        return build_cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Generate OmniBOR treedb and Gradle dependency graph.

        Two data sources for SPDX generation:

        1. ``bomsh_create_bom_java.py`` scans the build
           workspace to produce the OmniBOR treedb
           (JAR → class → source file provenance).
        2. ``./gradlew dependencies`` captures the declared
           Gradle dependency graph per subproject.

        Sub-step wall-clock timings are written to
        ``adg_substeps.json`` in *bom_dir* for
        performance analysis.

        Returns:
            True on success, False on failure.
        """
        from app.pipeline.gradle_dep_tree_parser import (
            get_all_gradle_deps,
        )

        substeps = []
        bom_path = Path(bom_dir)
        bom_path.mkdir(parents=True, exist_ok=True)
        meta_dir = bom_path / "metadata" / "bomsh"
        meta_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Build the OmniBOR treedb — inline assembly from the
        # shim's capture log when inline hashing is enabled, else the
        # legacy post-build rescan.  Shared by all Java sidecar
        # strategies (DRY) and build-tool-agnostic.
        if not build_java_treedb(
            self._inline_hash, self._capture_log,
            self._runner, repo_dir, meta_dir,
            omnibor_cfg, substeps,
        ):
            _write_adg_substeps(bom_path, substeps)
            return False

        # Step 2: Capture Gradle dependency graph (per-subproject).
        # Captured per subproject so Phase 2 can generate per-module
        # ``_build`` SBOMs from this metadata alone, with no
        # source-tree access.
        t0 = time.monotonic()
        modules = get_all_gradle_deps(repo_dir)
        capture = {"tool": "gradle", "modules": modules}
        deptree_sec = time.monotonic() - t0
        substeps.append({
            "name": "dep_tree",
            "tool": "gradlew dependencies",
            "wall_sec": round(deptree_sec, 2),
        })
        if not modules:
            print(
                "[WARN] No subprojects found in "
                "Gradle dependency tree"
            )

        out_file = bom_path / "gradle_deps.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(capture, f, indent=2)

        dep_total = sum(len(m["deps"]) for m in modules)
        print(
            f"[OK] Gradle dep:tree: {len(modules)} subprojects, "
            f"{dep_total} dependencies → {out_file}"
            f" ({deptree_sec:.1f}s)"
        )
        _write_adg_substeps(bom_path, substeps)
        return True
