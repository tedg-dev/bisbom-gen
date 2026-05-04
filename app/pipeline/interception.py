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
