#!/usr/bin/env python3
"""Print/write the Java build / sidecar / Phase 2 timing tally.

Aggregates the latest ``runtime.json`` for every Java repo under
``output/runtime/java`` and reports, per repo, the native CI/CD
build time, the sidecar metadata work (treedb, dep-tree, identity
index, manifest — i.e. creating and storing Phase 2's inputs), and
the Phase 2 SPDX time, plus a TOTAL line.

Usage:
    python3 scripts/java_timing_tally.py \
        --output-dir output --markdown output/java_timing_tally.md
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.timing_tally import (  # noqa: E402
    collect_rows,
    format_console,
    format_markdown,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Consolidated build/sidecar/Phase 2 timing tally"
        )
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Pipeline output directory (default: output)",
    )
    parser.add_argument(
        "--lang", default="java",
        help="Language subdirectory (default: java)",
    )
    parser.add_argument(
        "--markdown", default=None,
        help="Optional path to also write a markdown table",
    )
    args = parser.parse_args(argv)

    rows = collect_rows(args.output_dir, args.lang)
    if not rows:
        print(
            f"No runtime.json found under "
            f"{args.output_dir}/runtime/{args.lang}"
        )
        return 1

    print(format_console(rows))
    if args.markdown:
        Path(args.markdown).write_text(
            format_markdown(rows) + "\n", encoding="utf-8",
        )
        print(f"\nWrote markdown tally to {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
