#!/usr/bin/env python3
"""Compare new SPDX output against golden baselines. Report ALL differences."""

import json
import sys
from pathlib import Path


def _normalize_ref(ref):
    """Normalize an external ref for comparison.

    gitoid refs for compiled binaries change every build
    (binaries are not reproducible).  Normalize the hash
    portion so structural comparison ignores per-build
    gitoid variance.
    """
    loc = ref.get("referenceLocator", "")
    if loc.startswith("gitoid:"):
        # gitoid:blob:sha1:<hash> -> gitoid:blob:sha1:NORMALIZED
        parts = loc.split(":")
        if len(parts) >= 4:
            parts[-1] = "NORMALIZED"
            ref = dict(ref)
            ref["referenceLocator"] = ":".join(parts)
    return ref


def rel_counts(rels):
    c = {}
    for r in rels:
        t = r.get("relationshipType", "?")
        c[t] = c.get(t, 0) + 1
    return c


def compare(golden_path, new_path):
    with open(golden_path, encoding="utf-8") as fh:
        g = json.load(fh)
    with open(new_path, encoding="utf-8") as fh:
        n = json.load(fh)
    gp = g.get("packages", [])
    np_ = n.get("packages", [])
    gf = g.get("files", [])
    nf = n.get("files", [])
    gr = g.get("relationships", [])
    nr = n.get("relationships", [])

    fname = golden_path.name
    diffs = []

    # Package counts
    if len(gp) != len(np_):
        diffs.append(f"  Package count: {len(gp)} -> {len(np_)}")

    # Package identity — keyed by SPDXID (unique per document)
    g_by_id = {p["SPDXID"]: p for p in gp}
    n_by_id = {p["SPDXID"]: p for p in np_}
    missing_ids = set(g_by_id) - set(n_by_id)
    extra_ids = set(n_by_id) - set(g_by_id)
    if missing_ids:
        labels = sorted(
            f"{sid} ({g_by_id[sid]['name']})"
            for sid in missing_ids
        )
        diffs.append(f"  Missing packages: {labels}")
    if extra_ids:
        labels = sorted(
            f"{sid} ({n_by_id[sid]['name']})"
            for sid in extra_ids
        )
        diffs.append(f"  Extra packages: {labels}")

    # Package versions — matched by SPDXID
    for sid in sorted(set(g_by_id) & set(n_by_id)):
        gv = g_by_id[sid].get("versionInfo", "")
        nv = n_by_id[sid].get("versionInfo", "")
        if gv != nv:
            name = g_by_id[sid]["name"]
            diffs.append(
                f"  Version changed [{name} "
                f"({sid})]: '{gv}' -> '{nv}'"
            )

    # File counts
    if len(gf) != len(nf):
        diffs.append(
            f"  File count: {len(gf)} -> {len(nf)}"
        )

    # Relationship total count
    if len(gr) != len(nr):
        diffs.append(
            f"  Relationship count: "
            f"{len(gr)} -> {len(nr)}"
        )

    # Relationship type counts
    grc = rel_counts(gr)
    nrc = rel_counts(nr)
    for t in sorted(set(list(grc.keys()) + list(nrc.keys()))):
        gc = grc.get(t, 0)
        nc = nrc.get(t, 0)
        if gc != nc:
            diffs.append(f"  {t}: {gc} -> {nc}")

    # Relationship endpoints (source->target pairs)
    def _rel_key(r):
        src = r["spdxElementId"]
        tgt = r["relatedSpdxElement"]
        typ = r["relationshipType"]
        return f"{src}->{tgt}:{typ}"

    g_pairs = sorted(_rel_key(r) for r in gr)
    n_pairs = sorted(_rel_key(r) for r in nr)
    removed_rels = set(g_pairs) - set(n_pairs)
    added_rels = set(n_pairs) - set(g_pairs)
    if removed_rels:
        n = len(removed_rels)
        diffs.append(f"  Removed relationships ({n}):")
        for r in sorted(removed_rels)[:20]:
            diffs.append(f"    - {r}")
        if n > 20:
            diffs.append(f"    ... and {n - 20} more")
    if added_rels:
        n = len(added_rels)
        diffs.append(f"  Added relationships ({n}):")
        for r in sorted(added_rels)[:20]:
            diffs.append(f"    + {r}")
        if n > 20:
            diffs.append(f"    ... and {n - 20} more")

    # External references — matched by SPDXID
    # Normalize gitoid refs (compiled binary hashes
    # change every build — not reproducible).
    for sid in sorted(set(g_by_id) & set(n_by_id)):
        g_refs = sorted(
            json.dumps(
                _normalize_ref(r), sort_keys=True
            )
            for r in g_by_id[sid].get(
                "externalRefs", []
            )
        )
        n_refs = sorted(
            json.dumps(
                _normalize_ref(r), sort_keys=True
            )
            for r in n_by_id[sid].get(
                "externalRefs", []
            )
        )
        if g_refs != n_refs:
            name = g_by_id[sid]["name"]
            diffs.append(
                f"  External refs changed "
                f"[{name} ({sid})]"
            )

    print(f"=== {fname} ===")
    print(f"  Packages: {len(gp)} -> {len(np_)}")
    print(f"  Files: {len(gf)} -> {len(nf)}")
    print(f"  Relationships: {len(gr)} -> {len(nr)}")
    if diffs:
        print("  ** DIFFERENCES FOUND **")
        for d in diffs:
            print(d)
    else:
        print("  IDENTICAL (structural match)")
    print()
    return len(diffs) > 0


def main():
    golden_dir = Path(sys.argv[1])
    new_dir = Path(sys.argv[2])

    any_diff = False
    for gf in sorted(golden_dir.glob("*.spdx.json")):
        nf = new_dir / gf.name
        if not nf.exists():
            print(f"MISSING: {gf.name} not in new output")
            any_diff = True
            continue
        if compare(gf, nf):
            any_diff = True

    # Check for new files not in golden
    for nf in sorted(new_dir.glob("*.spdx.json")):
        gf = golden_dir / nf.name
        if not gf.exists():
            print(f"NEW FILE (no golden): {nf.name}")
            any_diff = True

    if any_diff:
        print("RESULT: DIFFERENCES FOUND — requires user review")
        sys.exit(1)
    else:
        print("RESULT: All files identical — no changes")
        sys.exit(0)


if __name__ == "__main__":
    main()
