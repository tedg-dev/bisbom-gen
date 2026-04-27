#!/usr/bin/env python3
"""Find exact source files that differ between golden and new SPDX."""

import json
import re
import sys
from pathlib import Path


def extract_filenames(doc):
    """Extract unique filenames from CONTAINS relationships."""
    files = set()
    for r in doc.get("relationships", []):
        if r.get("relationshipType") != "CONTAINS":
            continue
        ref = r.get("relatedSpdxElement", "")
        # SPDXRef-File-altsvc.c-181 -> altsvc.c
        m = re.match(r"SPDXRef-File-(.+)-\d+$", ref)
        if m:
            files.add(m.group(1))
    return files


def main():
    golden_path = Path(sys.argv[1])
    new_path = Path(sys.argv[2])

    g = json.load(open(golden_path))
    n = json.load(open(new_path))

    g_files = extract_filenames(g)
    n_files = extract_filenames(n)

    missing = sorted(g_files - n_files)
    added = sorted(n_files - g_files)

    fname = golden_path.name
    print(f"=== {fname} ===")
    print(f"  Golden files: {len(g_files)}")
    print(f"  New files: {len(n_files)}")
    if missing:
        print(f"  MISSING ({len(missing)}):")
        for f in missing:
            print(f"    - {f}")
    if added:
        print(f"  ADDED ({len(added)}):")
        for f in added:
            print(f"    + {f}")
    if not missing and not added:
        print("  Same filenames (only checksums differ)")


if __name__ == "__main__":
    main()
