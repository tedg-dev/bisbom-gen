#!/usr/bin/env python3
"""Diagnostic: list file-name differences between a golden and actual
SPDX file (by fileName), to reveal which .class members the inline
capture path dropped relative to the rescan golden baseline.

Usage: diff_spdx_files.py <lang>/<repo>/<basename>.spdx.json
Compares tests/golden/spdx/<arg> against the newest matching file under
output/spdx/<lang>/<repo>/<ts>/<basename>.
"""
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def file_names(doc):
    return sorted(f.get("fileName", f.get("name", "?"))
                  for f in doc.get("files", []))


def main():
    rel = sys.argv[1]  # e.g. java/jsoup/jsoup-1.22.1_build.spdx.json
    golden = PROJECT / "tests" / "golden" / "spdx" / rel
    parts = Path(rel).parts  # (lang, repo, basename)
    lang, repo, base = parts[0], parts[1], parts[2]
    out_repo = PROJECT / "output" / "spdx" / lang / repo
    ts_dirs = sorted(d for d in out_repo.glob("*") if d.is_dir())
    actual = ts_dirs[-1] / base
    g = set(file_names(load(golden)))
    a = set(file_names(load(actual)))
    print(f"golden={len(g)} actual={len(a)}")
    print(f"actual dir: {ts_dirs[-1].name}")
    missing = sorted(g - a)
    extra = sorted(a - g)
    print(f"\nMISSING in actual ({len(missing)}):")
    for m in missing:
        print(f"  - {m}")
    print(f"\nEXTRA in actual ({len(extra)}):")
    for e in extra:
        print(f"  + {e}")


if __name__ == "__main__":
    main()
