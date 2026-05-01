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
                    if not BinaryCollector._is_auxiliary_jar(
                        m.name
                    )
                ]
                skipped = len(
                    list(repo_dir.glob(rel_path))
                ) - len(matches)
                if skipped:
                    print(
                        f"[INFO] Skipped {skipped} "
                        f"auxiliary JAR(s) "
                        f"(tests/sources/javadoc)"
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
