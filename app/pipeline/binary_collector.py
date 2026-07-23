"""
Binary collection for OmniBOR Analysis.

Copies output binaries from the build tree into timestamped
output directories for preservation.
"""

import re
from pathlib import Path

from app.config import lang_subdir, timestamp


class BinaryCollector:
    """Copies output binaries from the build tree into
    output/binaries/<lang>/<repo>/<timestamp>/ so each run is
    preserved in a datetime-stamped folder.

    Uses the ``output_binaries`` list from config.yaml,
    which contains paths relative to the repo root
    (e.g. ``src/.libs/curl``).
    """

    # Maven classifier suffixes to skip when
    # collecting production JARs
    _JAR_SKIP_SUFFIXES = (
        "-tests.jar",
        "-test-sources.jar",
        "-sources.jar",
        "-javadoc.jar",
        "-examples.jar",
    )

    # Maven prefixes that indicate non-production JARs
    _JAR_SKIP_PREFIXES = (
        "original-",  # Maven shade pre-shade copy
    )

    # Reserved build-logic directories whose compiled output configures
    # the build itself and is never part of a published artifact.  Gradle
    # reserves ``buildSrc`` for exactly this purpose, so a JAR produced
    # under it (e.g. ``buildSrc/build/libs/buildSrc.jar``) is build tooling
    # — not a shippable component — and must not be a product SBOM target.
    _BUILD_LOGIC_DIRS = (
        "buildSrc",
    )

    # Gradle ``includeBuild(...)`` declares a composite/included build —
    # a separate Gradle build (commonly convention-plugin "build logic",
    # e.g. caffeine's ``gradle/plugins``).  Its outputs are produced by a
    # different build and are never a product of the main build, so any
    # JAR under an included-build directory is build tooling.  Detected
    # from the repo's own settings file so the rule stays generic — no
    # hardcoded module names.
    _INCLUDE_BUILD_RE = re.compile(
        r"""includeBuild\s*\(?\s*['"]([^'"]+)['"]"""
    )

    @staticmethod
    def _is_auxiliary_jar(filename):
        """Return True if JAR is a test/sources/javadoc
        auxiliary artifact, not the production JAR."""
        name = filename.lower()
        return (
            any(
                name.endswith(s)
                for s in
                BinaryCollector._JAR_SKIP_SUFFIXES
            )
            or any(
                name.startswith(p)
                for p in
                BinaryCollector._JAR_SKIP_PREFIXES
            )
        )

    @staticmethod
    def included_build_dirs(repo_dir):
        """Return the repo-relative dirs of Gradle included builds.

        Parses the repo's ``settings.gradle`` / ``settings.gradle.kts``
        for ``includeBuild(...)`` declarations.  An included build is a
        separate Gradle build (typically convention-plugin build logic);
        its outputs are never products of the main build.  Returns an
        empty set when *repo_dir* is falsy or no settings file exists, so
        callers without repo context simply skip this check.
        """
        dirs = set()
        if not repo_dir:
            return dirs
        repo = Path(repo_dir)
        for name in ("settings.gradle", "settings.gradle.kts"):
            settings = repo / name
            if not settings.is_file():
                continue
            try:
                text = settings.read_text(
                    encoding="utf-8", errors="replace",
                )
            except OSError:
                continue
            for m in BinaryCollector._INCLUDE_BUILD_RE.finditer(
                text
            ):
                dirs.add(m.group(1).strip().strip("/"))
        return dirs

    @staticmethod
    def _ancestors_contain(ancestors, sub_parts):
        """True if *sub_parts* is a contiguous run within *ancestors*."""
        ancestors = tuple(ancestors)
        sub_parts = tuple(sub_parts)
        n = len(sub_parts)
        if n == 0:
            return False
        for i in range(len(ancestors) - n + 1):
            if ancestors[i:i + n] == sub_parts:
                return True
        return False

    @staticmethod
    def _is_build_logic_jar(path, included_dirs=()):
        """Return True if *path* is a build-logic JAR — build tooling
        rather than a shipped product component.

        Two generic signals, neither hardcoding a module name:

        - the JAR is produced under a reserved build-logic directory
          (Gradle ``buildSrc``); or
        - the JAR is produced under a directory declared as an
          ``includeBuild(...)`` composite/included build (passed in
          *included_dirs*, e.g. caffeine's ``gradle/plugins``).
        """
        # Inspect ancestor directories only; the JAR's own filename is
        # irrelevant (the directory is the signal, not a name).
        ancestors = Path(path).parts[:-1]
        if any(
            d in ancestors
            for d in BinaryCollector._BUILD_LOGIC_DIRS
        ):
            return True
        for inc in included_dirs:
            if BinaryCollector._ancestors_contain(
                ancestors, Path(inc).parts,
            ):
                return True
        return False

    @staticmethod
    def is_non_product_jar(path, repo_dir=None):
        """Return True if *path* is not a shippable product JAR.

        Combines the filename-classified auxiliary artifacts
        (tests/sources/javadoc/shade copies) with path-classified
        build-logic JARs (Gradle ``buildSrc`` and ``includeBuild(...)``
        composite/included builds).  Used everywhere the
        ``output_binaries`` globs are expanded so every mode
        (standalone, sidecar) applies one consistent product-JAR
        definition.  Pass *repo_dir* so included-build outputs are
        recognised from the repo's own Gradle settings.
        """
        p = Path(path)
        if BinaryCollector._is_auxiliary_jar(p.name):
            return True
        included = BinaryCollector.included_build_dirs(repo_dir)
        return BinaryCollector._is_build_logic_jar(p, included)

    @staticmethod
    def excluded_binaries(repo_dir, exclude_globs):
        """Resolve ``exclude_binaries`` globs to a set of paths.

        ``exclude_binaries`` (repo config) lists repo-relative glob
        patterns for build artifacts that the ``output_binaries``
        globs would match but that are not shippable products -- e.g.
        an internal build-tooling subproject JAR that is a normal
        Gradle subproject (so it is neither ``buildSrc`` nor an
        included build and cannot be classified generically).  The
        specific patterns live in ``config.yaml``, keeping product
        selection config-driven with no repo names in code.
        """
        excluded = set()
        if not repo_dir or not exclude_globs:
            return excluded
        base = Path(repo_dir)
        for pattern in exclude_globs:
            excluded.update(base.glob(pattern))
        return excluded

    @staticmethod
    def collect(repo_name, repo_cfg, paths_cfg,
                run_ts=None):
        """Copy each listed binary to a timestamped dir.

        Returns a list of (src, dst) tuples for binaries
        that were successfully copied.
        """
        import shutil

        ts = run_ts or timestamp()
        bins = repo_cfg.get("output_binaries", [])
        if not bins:
            print(
                "[WARN] No output_binaries defined "
                f"for {repo_name}"
            )
            return []

        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        lang = lang_subdir(repo_cfg)
        out_dir = (
            Path(paths_cfg["output_dir"])
            / "binaries" / lang / repo_name / ts
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        excluded = BinaryCollector.excluded_binaries(
            repo_dir, repo_cfg.get("exclude_binaries", []),
        )

        collected = []
        for rel_path in bins:
            # Handle glob patterns (e.g., target/jsoup-*.jar)
            if '*' in rel_path or '?' in rel_path:
                matches = [
                    m for m in repo_dir.glob(rel_path)
                    if not BinaryCollector.is_non_product_jar(
                        m, repo_dir,
                    )
                    and m not in excluded
                ]
                skipped = len(
                    list(repo_dir.glob(rel_path))
                ) - len(matches)
                if skipped:
                    print(
                        f"[INFO] Skipped {skipped} "
                        f"non-product JAR(s) (tests/sources/"
                        f"javadoc/build-logic/config-excluded)"
                    )
                if not matches:
                    print(
                        f"[WARN] No files match: {rel_path}"
                    )
                    continue
                for src in matches:
                    dst = out_dir / src.name
                    shutil.copy2(str(src), str(dst))
                    size = dst.stat().st_size
                    print(
                        f"[OK] Collected {dst.name} "
                        f"({size:,} bytes)"
                    )
                    collected.append((str(src), str(dst)))
            else:
                src = repo_dir / rel_path
                dst = out_dir / Path(rel_path).name
                if not src.exists():
                    print(
                        f"[WARN] Binary not found: {src}"
                    )
                    continue
                if not src.is_file():
                    print(
                        f"[WARN] Not a file (directory?): "
                        f"{src}"
                    )
                    continue
                shutil.copy2(str(src), str(dst))
                size = dst.stat().st_size
                print(
                    f"[OK] Collected {dst.name} "
                    f"({size:,} bytes)"
                )
                collected.append((str(src), str(dst)))

        if collected:
            print(
                f"[OK] {len(collected)} binary(ies) "
                f"saved to {out_dir}"
            )
        else:
            print(
                f"[WARN] No binaries found for "
                f"{repo_name}"
            )
        return collected
