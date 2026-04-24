#!/usr/bin/env python3
"""Merge sibling SPDX modules into a single combined visualization.

Replaces sibling stub nodes in the parent SPDX with the actual
packages/relationships from child SPDX docs, deduplicates shared
dependencies, and generates one HTML visualization.

Usage:
    # Auto-detect siblings from parent's "Sibling module. See:" comments:
    python3 scripts/combine_spdx_viz.py parent_build.spdx.json

    # Explicit children:
    python3 scripts/combine_spdx_viz.py parent.spdx.json child1.spdx.json child2.spdx.json
"""

import json
import re
import sys
from pathlib import Path

# Add project root to path so we can import app modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.spdx_visualize import generate_html  # noqa: E402


def _rewrite_ids(doc, prefix):
    """Rewrite all SPDXRef IDs in a doc to avoid collisions.

    Prefixes every SPDXRef (except SPDXRef-DOCUMENT) with the given
    prefix string, e.g. SPDXRef-Dep-0 -> SPDXRef-utils-Dep-0.
    """
    def _rewrite(ref):
        if ref == "SPDXRef-DOCUMENT":
            return ref
        return ref.replace("SPDXRef-", f"SPDXRef-{prefix}-", 1)

    for p in doc.get("packages", []):
        p["SPDXID"] = _rewrite(p["SPDXID"])

    for f in doc.get("files", []):
        f["SPDXID"] = _rewrite(f["SPDXID"])

    for r in doc.get("relationships", []):
        r["spdxElementId"] = _rewrite(r["spdxElementId"])
        r["relatedSpdxElement"] = _rewrite(r["relatedSpdxElement"])

    return doc


def merge_spdx(parent_path, child_paths):
    """Merge child SPDX docs into parent, replacing sibling stubs.

    Args:
        parent_path: Path to the parent SPDX JSON
        child_paths: dict of {sibling_name_fragment: (path, id_prefix)}

    Returns:
        Combined SPDX document dict
    """
    with open(parent_path) as f:
        parent = json.load(f)

    # Identify sibling stub package IDs in parent
    sibling_ids = {}
    for p in parent["packages"]:
        comment = p.get("comment", "").lower()
        if "sibling module" in comment:
            for frag, (path, prefix) in child_paths.items():
                if frag in p["name"].lower():
                    sibling_ids[p["SPDXID"]] = (frag, path, prefix)

    print(f"Parent: {len(parent['packages'])} packages, "
          f"{len(parent['relationships'])} relationships")
    print(f"Sibling stubs found: {list(sibling_ids.keys())}")

    # Remove sibling stub packages from parent
    parent["packages"] = [
        p for p in parent["packages"]
        if p["SPDXID"] not in sibling_ids
    ]

    # Remove relationships pointing to/from sibling stubs
    parent["relationships"] = [
        r for r in parent["relationships"]
        if r["spdxElementId"] not in sibling_ids
        and r["relatedSpdxElement"] not in sibling_ids
    ]

    # Load and merge each child
    for _stub_id, (frag, child_path, prefix) in sibling_ids.items():
        with open(child_path) as f:
            child = json.load(f)

        child = _rewrite_ids(child, prefix)

        print(f"\n  Merging {frag} ({prefix}): "
              f"{len(child['packages'])} packages, "
              f"{len(child['relationships'])} relationships, "
              f"{len(child.get('files', []))} files")

        # Find the child root package (APPLICATION purpose)
        child_root_id = None
        for p in child["packages"]:
            if p.get("primaryPackagePurpose") == "APPLICATION":
                child_root_id = p["SPDXID"]
                # Change purpose to LIBRARY since it's a sub-module
                p["primaryPackagePurpose"] = "LIBRARY"
                break

        # Add child packages (skip DOCUMENT)
        parent["packages"].extend(child["packages"])

        # Add child files
        if "files" not in parent:
            parent["files"] = []
        parent.get("files", []).extend(child.get("files", []))

        # Add child relationships (skip DOCUMENT-level ones)
        for r in child["relationships"]:
            if "SPDXRef-DOCUMENT" in (
                r["spdxElementId"], r["relatedSpdxElement"]
            ):
                continue
            parent["relationships"].append(r)

        # Connect parent root to child root via DEPENDS_ON
        if child_root_id:
            parent_root = parent["packages"][0]["SPDXID"]
            parent["relationships"].append({
                "spdxElementId": parent_root,
                "relatedSpdxElement": child_root_id,
                "relationshipType": "DEPENDS_ON",
            })

    # Dedup packages by name+version — keep first occurrence,
    # rewrite relationships to point to canonical SPDX ID.
    seen = {}  # (name, version) -> canonical SPDXID
    id_remap = {}  # duplicate SPDXID -> canonical SPDXID
    deduped_pkgs = []
    for p in parent["packages"]:
        key = (p["name"], p.get("versionInfo", ""))
        if key in seen:
            id_remap[p["SPDXID"]] = seen[key]
        else:
            seen[key] = p["SPDXID"]
            deduped_pkgs.append(p)
    parent["packages"] = deduped_pkgs

    if id_remap:
        print(f"\n  Deduped {len(id_remap)} duplicate packages:")
        for dup_id, canon_id in id_remap.items():
            print(f"    {dup_id} -> {canon_id}")

    # Rewrite relationships and remove self-loops
    remapped_rels = []
    for r in parent["relationships"]:
        r["spdxElementId"] = id_remap.get(
            r["spdxElementId"], r["spdxElementId"])
        r["relatedSpdxElement"] = id_remap.get(
            r["relatedSpdxElement"], r["relatedSpdxElement"])
        # Skip self-loops created by dedup
        if r["spdxElementId"] != r["relatedSpdxElement"]:
            remapped_rels.append(r)
    # Remove duplicate relationships
    seen_rels = set()
    unique_rels = []
    for r in remapped_rels:
        key = (r["spdxElementId"], r["relatedSpdxElement"],
               r["relationshipType"])
        if key not in seen_rels:
            seen_rels.add(key)
            unique_rels.append(r)
    parent["relationships"] = unique_rels

    print(f"\nCombined: {len(parent['packages'])} packages, "
          f"{len(parent['relationships'])} relationships, "
          f"{len(parent.get('files', []))} files")

    # Update document name
    base_name = parent.get("name", "combined")
    parent["name"] = base_name + "-combined"

    return parent


def auto_detect(parent_path):
    """Auto-detect sibling SPDX files referenced in parent's comments.

    Scans the parent doc for packages with "Sibling module. See: <file>"
    comments and builds the child_paths dict automatically.
    """
    parent_dir = Path(parent_path).parent
    with open(parent_path) as f:
        parent = json.load(f)

    child_paths = {}
    for p in parent.get("packages", []):
        comment = p.get("comment", "")
        if "sibling module" not in comment.lower():
            continue
        # Extract filename from "See: <filename>"
        match = re.search(r"See:\s*(\S+\.spdx\.json)", comment)
        if not match:
            continue
        child_file = match.group(1)
        child_full = parent_dir / child_file
        if not child_full.exists():
            print(f"  [WARN] Sibling file not found: {child_full}")
            continue
        # Use the package name as the key and prefix
        name = p.get("name", "unknown")
        # Short prefix from name (last segment)
        prefix = name.split("-")[-1] if "-" in name else name
        child_paths[name] = (child_full, prefix)

    return child_paths


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Merge sibling SPDX modules into a single "
                    "combined visualization.",
    )
    ap.add_argument(
        "parent",
        help="Path to the parent SPDX JSON (e.g. foo_build.spdx.json)",
    )
    ap.add_argument(
        "children", nargs="*",
        help="Paths to child SPDX JSON files. If omitted, "
             "auto-detects siblings from parent's comments.",
    )
    ap.add_argument(
        "-o", "--output", default=None,
        help="Output base name (default: <parent>_combined)",
    )
    args = ap.parse_args()

    parent_path = Path(args.parent).resolve()

    if args.children:
        child_paths = {}
        for cp in args.children:
            cp = Path(cp).resolve()
            name = cp.stem.replace("_build.spdx", "")
            prefix = name.split("-")[-1] if "-" in name else name
            child_paths[name] = (cp, prefix)
    else:
        child_paths = auto_detect(parent_path)
        if not child_paths:
            print("[ERROR] No sibling modules found. "
                  "Pass child files explicitly.")
            sys.exit(1)

    print(f"Parent: {parent_path.name}")
    print(f"Children: {', '.join(child_paths.keys())}")

    combined = merge_spdx(parent_path, child_paths)

    # Determine output paths
    if args.output:
        base_name = args.output
    else:
        stem = parent_path.stem.replace("_build.spdx", "")
        base_name = str(parent_path.parent / f"{stem}_combined.spdx")

    combined_json = Path(base_name + ".json")
    with open(combined_json, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n[OK] Combined SPDX: {combined_json}")

    output_html = Path(base_name + ".html")
    generate_html(combined, str(output_html))


if __name__ == "__main__":
    main()
