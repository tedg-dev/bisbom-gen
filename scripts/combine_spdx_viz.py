#!/usr/bin/env python3
"""One-off: merge three dependency-check SPDX files into a single
combined visualization.

Replaces the sibling stub nodes in the parent SPDX with the actual
packages/relationships from the child SPDX docs, then generates
one HTML visualization via spdx_visualize.generate_html().
"""

import json
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
    for stub_id, (frag, child_path, prefix) in sibling_ids.items():
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

    print(f"\nCombined: {len(parent['packages'])} packages, "
          f"{len(parent['relationships'])} relationships, "
          f"{len(parent.get('files', []))} files")

    # Update document name
    parent["name"] = "dependency-check-9.2.0-combined"

    return parent


def main():
    base = (PROJECT_ROOT / "output" / "spdx" / "java"
            / "dependency-check" / "2026-04-23_2352")

    parent_path = base / "dependency-check-9.2.0_build.spdx.json"

    child_paths = {
        "utils": (
            base / "dependency-check-utils-9.2.0_build.spdx.json",
            "utils",
        ),
        "core": (
            base / "dependency-check-core-9.2.0_build.spdx.json",
            "core",
        ),
    }

    combined = merge_spdx(parent_path, child_paths)

    # Save combined SPDX
    combined_json = base / "dependency-check-9.2.0_combined.spdx.json"
    with open(combined_json, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n[OK] Combined SPDX: {combined_json}")

    # Generate visualization
    output_html = base / "dependency-check-9.2.0_combined.spdx.html"
    generate_html(combined, str(output_html))


if __name__ == "__main__":
    main()
