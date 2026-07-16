"""
Binary collection for OmniBOR Analysis.

Copies output binaries from the build tree into timestamped
output directories for preservation.
"""

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
    def _is_build_logic_jar(path):
        """Return True if *path* is a build-logic JAR — produced under a
        reserved build-logic directory (Gradle ``buildSrc``) and therefore
        build tooling rather than a shipped product component."""
        # Inspect ancestor directories only; the JAR's own filename is
        # irrelevant (a ``buildSrc`` directory is the signal, not a name).
        ancestors = Path(path).parts[:-1]
        return any(
            d in ancestors
            for d in BinaryCollector._BUILD_LOGIC_DIRS
        )

    @staticmethod
    def is_non_product_jar(path):
        """Return True if *path* is not a shippable product JAR.

        Combines the filename-classified auxiliary artifacts
        (tests/sources/javadoc/shade copies) with path-classified
        build-logic JARs (Gradle ``buildSrc``).  Used everywhere the
        ``output_binaries`` globs are expanded so every mode
        (standalone, sidecar) applies one consistent product-JAR
        definition.
        """
        p = Path(path)
        return (
            BinaryCollector._is_auxiliary_jar(p.name)
            or BinaryCollector._is_build_logic_jar(p)
        )

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

        collected = []
        for rel_path in bins:
            # Handle glob patterns (e.g., target/jsoup-*.jar)
            if '*' in rel_path or '?' in rel_path:
                matches = [
                    m for m in repo_dir.glob(rel_path)
                    if not BinaryCollector.is_non_product_jar(
                        m
                    )
                ]
                skipped = len(
                    list(repo_dir.glob(rel_path))
                ) - len(matches)
                if skipped:
                    print(
                        f"[INFO] Skipped {skipped} "
                        f"non-product JAR(s) "
                        f"(tests/sources/javadoc/build-logic)"
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
