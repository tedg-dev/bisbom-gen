#!/usr/bin/env python3
"""Compare new SPDX output against golden baselines. Report ALL differences."""

import json
import sys
from pathlib import Path


def rel_counts(rels):
    c = {}
    for r in rels:
        t = r.get("relationshipType", "?")
        c[t] = c.get(t, 0) + 1
    return c


def compare(golden_path, new_path):
    g = json.load(open(golden_path))
    n = json.load(open(new_path))
    gp = g.get("packages", [])
    np_ = n.get("packages", [])
    gr = g.get("relationships", [])
    nr = n.get("relationships", [])

    fname = golden_path.name
    diffs = []

    # Package counts
    if len(gp) != len(np_):
        diffs.append(f"  Package count: {len(gp)} -> {len(np_)}")

    # Package names
    gn = sorted(p["name"] for p in gp)
    nn = sorted(p["name"] for p in np_)
    missing = set(gn) - set(nn)
    extra = set(nn) - set(gn)
    if missing:
        diffs.append(f"  Missing packages: {sorted(missing)}")
    if extra:
        diffs.append(f"  Extra packages: {sorted(extra)}")

    # Package versions
    gv = {p["name"]: p.get("versionInfo", "") for p in gp}
    nv = {p["name"]: p.get("versionInfo", "") for p in np_}
    for name in sorted(set(gv.keys()) & set(nv.keys())):
        if gv[name] != nv[name]:
            diffs.append(f"  Version changed [{name}]: '{gv[name]}' -> '{nv[name]}'")

    # Relationship total count
    if len(gr) != len(nr):
        diffs.append(f"  Relationship count: {len(gr)} -> {len(nr)}")

    # Relationship type counts
    grc = rel_counts(gr)
    nrc = rel_counts(nr)
    for t in sorted(set(list(grc.keys()) + list(nrc.keys()))):
        gc = grc.get(t, 0)
        nc = nrc.get(t, 0)
        if gc != nc:
            diffs.append(f"  {t}: {gc} -> {nc}")

    # Relationship endpoints (source->target pairs)
    g_pairs = sorted(
        f"{r['spdxElementId']}->{r['relatedSpdxElement']}:{r['relationshipType']}"
        for r in gr
    )
    n_pairs = sorted(
        f"{r['spdxElementId']}->{r['relatedSpdxElement']}:{r['relationshipType']}"
        for r in nr
    )
    removed_rels = set(g_pairs) - set(n_pairs)
    added_rels = set(n_pairs) - set(g_pairs)
    if removed_rels:
        diffs.append(f"  Removed relationships ({len(removed_rels)}):")
        for r in sorted(removed_rels)[:20]:
            diffs.append(f"    - {r}")
        if len(removed_rels) > 20:
            diffs.append(f"    ... and {len(removed_rels) - 20} more")
    if added_rels:
        diffs.append(f"  Added relationships ({len(added_rels)}):")
        for r in sorted(added_rels)[:20]:
            diffs.append(f"    + {r}")
        if len(added_rels) > 20:
            diffs.append(f"    ... and {len(added_rels) - 20} more")

    # External references
    for p_g in gp:
        p_n_match = [p for p in np_ if p["name"] == p_g["name"]]
        if not p_n_match:
            continue
        p_n = p_n_match[0]
        g_refs = sorted(
            json.dumps(r, sort_keys=True)
            for r in p_g.get("externalRefs", [])
        )
        n_refs = sorted(
            json.dumps(r, sort_keys=True)
            for r in p_n.get("externalRefs", [])
        )
        if g_refs != n_refs:
            diffs.append(f"  External refs changed [{p_g['name']}]")

    print(f"=== {fname} ===")
    print(f"  Packages: {len(gp)} -> {len(np_)}")
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
