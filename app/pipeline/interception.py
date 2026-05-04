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

from abc import ABC, abstractmethod


class InterceptionStrategy(ABC):
    """Defines how a build is instrumented for OmniBOR tracing.

    Concrete strategies implement distro-specific or
    language-specific instrumentation. The pipeline
    selects a strategy based on ``config.yaml`` settings.
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
    """Java Maven: ``mvn dependency:tree`` instead of strace.

    In sidecar mode, Java builds do not need ``SYS_PTRACE``.
    Instead of intercepting file I/O via strace, this strategy:

    1. Runs the build command unmodified (no strace prefix).
    2. Runs ``mvn dependency:tree -DoutputType=dot`` to
       capture the declared dependency graph.
    3. Parses the DOT output into treedb-compatible format.

    Accuracy caveat: ``mvn dependency:tree`` reports the
    *declared* dependency graph, which may diverge from the
    *actual* runtime classpath when shade/assembly plugins
    repackage transitive dependencies.
    """

    def __init__(self, runner=None):
        from app.runner import CommandRunner
        self._runner = runner or CommandRunner()

    def instrument_command(self, build_cmd, repo_dir):
        """Return the build command unmodified — no strace.

        Returns:
            ``(build_cmd, {})`` — no env vars needed.
        """
        return build_cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``mvn dependency:tree -DoutputType=dot`` and parse.

        Writes parsed dependency data to
        ``{bom_dir}/maven_deps.json``.

        Returns:
            True on success, False on failure.
        """
        import json
        from pathlib import Path

        from app.pipeline.maven_dep_tree_parser import (
            parse_dot_output,
            run_maven_dep_tree,
        )

        bom_path = Path(bom_dir)
        bom_path.mkdir(parents=True, exist_ok=True)

        dot_output = run_maven_dep_tree(
            repo_dir, runner=self._runner,
        )
        if dot_output is None:
            return False

        deps = parse_dot_output(dot_output)
        if not deps:
            print(
                "[WARN] No dependencies found in "
                "mvn dependency:tree output"
            )

        out_file = bom_path / "maven_deps.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(deps, f, indent=2)

        print(
            f"[OK] Maven dep:tree: "
            f"{len(deps)} dependencies → {out_file}"
        )
        return True


class GradleDepTreeStrategy(InterceptionStrategy):
    """Java Gradle: ``./gradlew dependencies`` instead of strace.

    Like ``MavenDepTreeStrategy``, this avoids ``SYS_PTRACE``
    for Gradle-based Java builds:

    1. Runs the build command unmodified.
    2. Runs ``./gradlew dependencies`` per subproject.
    3. Parses the indented tree output into structured data.

    Handles multi-project builds by iterating subprojects
    discovered from ``settings.gradle``.
    """

    def __init__(self, runner=None):
        from app.runner import CommandRunner
        self._runner = runner or CommandRunner()

    def instrument_command(self, build_cmd, repo_dir):
        """Return the build command unmodified — no strace.

        Returns:
            ``(build_cmd, {})`` — no env vars needed.
        """
        return build_cmd, {}

    def generate_adg(self, repo_dir, bom_dir, omnibor_cfg):
        """Run ``./gradlew dependencies`` and parse output.

        Writes parsed dependency data to
        ``{bom_dir}/gradle_deps.json``.

        Returns:
            True on success, False on failure.
        """
        import json
        from pathlib import Path

        from app.pipeline.gradle_dep_tree_parser import (
            get_all_gradle_deps,
        )

        bom_path = Path(bom_dir)
        bom_path.mkdir(parents=True, exist_ok=True)

        deps = get_all_gradle_deps(repo_dir)
        if not deps:
            print(
                "[WARN] No dependencies found in "
                "Gradle dependency tree"
            )

        out_file = bom_path / "gradle_deps.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(deps, f, indent=2)

        print(
            f"[OK] Gradle dep:tree: "
            f"{len(deps)} dependencies → {out_file}"
        )
        return True
