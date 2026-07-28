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


def _file_checksum(f):
    """Return a file's SHA1 checksum (or first available)."""
    checksums = f.get("checksums", [])
    for c in checksums:
        if c.get("algorithm") == "SHA1":
            return c.get("checksumValue", "")
    return checksums[0].get("checksumValue", "") if checksums else ""


def _capped_list(diffs, label, items, marker, cap=20):
    """Append a capped, labeled list of items to ``diffs``."""
    n = len(items)
    diffs.append(f"  {label} ({n}):")
    for item in sorted(items)[:cap]:
        diffs.append(f"    {marker} {item}")
    if n > cap:
        diffs.append(f"    ... and {n - cap} more")


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

    # Other scalar package fields (name, license, supplier,
    # download location, purpose, filesAnalyzed, sourceInfo,
    # comment).  A change in any of these is a real difference
    # that version/ref comparison alone would miss.  sourceInfo
    # and the legacy packageSourceInfo key are both compared so
    # a rename between them is reported, not silently ignored.
    _pkg_fields = (
        "name", "downloadLocation", "supplier",
        "primaryPackagePurpose", "filesAnalyzed",
        "licenseConcluded", "licenseDeclared",
        "copyrightText", "sourceInfo", "comment",
        "packageSourceInfo",
    )
    for sid in sorted(set(g_by_id) & set(n_by_id)):
        for field in _pkg_fields:
            gvf = g_by_id[sid].get(field)
            nvf = n_by_id[sid].get(field)
            if gvf != nvf:
                name = g_by_id[sid]["name"]
                diffs.append(
                    f"  Field '{field}' changed "
                    f"[{name} ({sid})]: "
                    f"{gvf!r} -> {nvf!r}"
                )

    # Files — identity (by fileName) and content (checksum).
    # fileName is stable across runs; comparing checksums
    # catches content changes (and file swaps) that an equal
    # file COUNT would otherwise hide.
    if len(gf) != len(nf):
        diffs.append(
            f"  File count: {len(gf)} -> {len(nf)}"
        )
    g_files = {f["fileName"]: _file_checksum(f) for f in gf}
    n_files = {f["fileName"]: _file_checksum(f) for f in nf}
    missing_files = set(g_files) - set(n_files)
    added_files = set(n_files) - set(g_files)
    if missing_files:
        _capped_list(diffs, "Missing files", missing_files, "-")
    if added_files:
        _capped_list(diffs, "Added files", added_files, "+")
    changed_files = [
        fn for fn in (set(g_files) & set(n_files))
        if g_files[fn] != n_files[fn]
    ]
    if changed_files:
        n_chg = len(changed_files)
        diffs.append(f"  Changed file checksums ({n_chg}):")
        for fn in sorted(changed_files)[:20]:
            diffs.append(
                f"    ~ {fn}: {g_files[fn][:12]} -> "
                f"{n_files[fn][:12]}"
            )
        if n_chg > 20:
            diffs.append(f"    ... and {n_chg - 20} more")

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
        _capped_list(
            diffs, "Removed relationships", removed_rels, "-",
        )
    if added_rels:
        _capped_list(
            diffs, "Added relationships", added_rels, "+",
        )

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
