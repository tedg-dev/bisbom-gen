#!/usr/bin/env python3
"""Compare the latest Java sidecar SPDX output against golden baselines.

For each requested repo, finds the newest output/spdx/java/<repo>/<ts>/
directory and compares every *_build.spdx.json and *_analyzed.spdx.json
file against the golden file of the SAME name (exact suffix match, unlike
compare_against_golden which always prefers _analyzed).

Exit code 0 if all match, 1 if any differences (never updates golden).
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT_SPDX = PROJECT / "output" / "spdx" / "java"
GOLDEN_DIR = PROJECT / "tests" / "golden" / "spdx"


def _normalize_branding(text: str) -> str:
    """Mask the ``omnibor`` -> ``bisbom`` project rename.

    The rename is a branding change, not a content change.  Applying the
    SAME substitution to BOTH the golden baseline and the new candidate
    can only mask that rename in names (repo/package/path) -- it can never
    hide a real content difference, because any genuine divergence survives
    the identical substitution on both sides.  Golden files that predate
    the rename keep the ``omnibor`` spelling; new output uses ``bisbom``.
    """
    return text.replace("omnibor", "bisbom")


def _load_spdx(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.loads(_normalize_branding(f.read()))


def _extract_package_summary(doc: dict) -> dict:
    packages = doc.get("packages", [])
    relationships = doc.get("relationships", [])
    pkg_names = sorted(p["name"] for p in packages)
    with_version = [p for p in packages if p.get("versionInfo")]
    without_version = sorted(
        p["name"] for p in packages if not p.get("versionInfo")
    )
    rel_counts = {}
    for r in relationships:
        rtype = r.get("relationshipType", "UNKNOWN")
        rel_counts[rtype] = rel_counts.get(rtype, 0) + 1
    return {
        "package_names": pkg_names,
        "package_count": len(packages),
        "packages_with_version": len(with_version),
        "packages_without_version": without_version,
        "relationship_counts": rel_counts,
    }


def _compare_summaries(golden: dict, actual: dict, name: str) -> list:
    diffs = []
    if golden["package_count"] != actual["package_count"]:
        diffs.append(
            f"{name}: package count mismatch: "
            f"golden={golden['package_count']}, "
            f"actual={actual['package_count']}"
        )
    golden_names = set(golden["package_names"])
    actual_names = set(actual["package_names"])
    missing = golden_names - actual_names
    if missing:
        diffs.append(f"{name}: missing packages: {sorted(missing)}")
    extra = actual_names - golden_names
    if extra:
        diffs.append(f"{name}: extra packages: {sorted(extra)}")
    if golden["packages_with_version"] != actual["packages_with_version"]:
        diffs.append(
            f"{name}: versioned package count mismatch: "
            f"golden={golden['packages_with_version']}, "
            f"actual={actual['packages_with_version']}"
        )
    golden_unversioned = set(golden["packages_without_version"])
    actual_unversioned = set(actual["packages_without_version"])
    new_unversioned = actual_unversioned - golden_unversioned
    if new_unversioned:
        diffs.append(
            f"{name}: newly unversioned packages: "
            f"{sorted(new_unversioned)}"
        )
    for rtype in set(
        list(golden["relationship_counts"].keys())
        + list(actual["relationship_counts"].keys())
    ):
        g_count = golden["relationship_counts"].get(rtype, 0)
        a_count = actual["relationship_counts"].get(rtype, 0)
        if g_count != a_count:
            diffs.append(
                f"{name}: {rtype} relationship count mismatch: "
                f"golden={g_count}, actual={a_count}"
            )
    return diffs


def latest_output_dir(repo: str) -> Path | None:
    base = OUTPUT_SPDX / repo
    dirs = sorted(
        (d for d in base.glob("*") if d.is_dir()),
        key=lambda d: d.name,
    )
    return dirs[-1] if dirs else None


def compare_repo(repo: str) -> list:
    diffs = []
    out_dir = latest_output_dir(repo)
    if out_dir is None:
        return [f"{repo}: no output dir under {OUTPUT_SPDX / repo}"]
    golden_repo = GOLDEN_DIR / "java" / repo
    golden_files = sorted(golden_repo.glob("*.spdx.json"))
    if not golden_files:
        return [f"{repo}: no golden files under {golden_repo}"]
    for golden in golden_files:
        actual = out_dir / golden.name
        if not actual.exists():
            diffs.append(f"{repo}: missing actual {golden.name}")
            continue
        g = _extract_package_summary(_load_spdx(golden))
        a = _extract_package_summary(_load_spdx(actual))
        d = _compare_summaries(g, a, f"java/{repo}/{golden.name}")
        if d:
            diffs.extend(d)
        else:
            print(f"[MATCH] java/{repo}/{golden.name} "
                  f"(<- {out_dir.name})")
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", required=True)
    args = ap.parse_args()
    all_diffs = []
    for repo in args.repos:
        all_diffs.extend(compare_repo(repo))
    if all_diffs:
        print("\n=== DIFFERENCES ===")
        for d in all_diffs:
            print(f"[DIFF] {d}")
        print(f"\nTOTAL DIFFS: {len(all_diffs)}")
        sys.exit(1)
    print("\nALL JAVA GOLDEN FILES MATCH")


if __name__ == "__main__":
    main()
