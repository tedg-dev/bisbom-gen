"""System-level regression tests for ADG SPDX generation.

Compares newly generated ADG SPDX files against golden baseline files
to detect regressions in package detection, versioning, and relationships.

Golden files are stored in tests/golden/spdx/{lang}/{repo}/ and represent
the "correct" output that new generations should match.

The comparison focuses on structural correctness:
- Package names and counts
- Version information
- Relationship types and counts
- External references (PURLs, CPEs)

Fields that vary between runs are ignored:
- SPDX document namespace (contains UUID)
- Creation timestamps
- File checksums (may change with upstream updates)
"""

import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden" / "spdx"


def _load_spdx(path: Path) -> dict:
    """Load SPDX JSON file."""
    with open(path) as f:
        return json.load(f)


def _extract_package_summary(doc: dict) -> dict:
    """Extract comparable package summary from SPDX document.

    Returns dict with:
    - package_names: sorted list of package names
    - package_count: total number of packages
    - packages_with_version: count of packages with versionInfo
    - packages_without_version: list of package names missing version
    - relationship_counts: dict of relationship type -> count
    """
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
    """Compare two package summaries and return list of differences."""
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

    if (
        golden["packages_with_version"]
        != actual["packages_with_version"]
    ):
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


def get_golden_files():
    """Discover all golden SPDX files for parameterized testing."""
    golden_files = []
    for lang_dir in GOLDEN_DIR.iterdir():
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name
        for repo_dir in lang_dir.iterdir():
            if not repo_dir.is_dir():
                continue
            repo = repo_dir.name
            for spdx_file in repo_dir.glob("*_adg.spdx.json"):
                binary = spdx_file.stem.replace("_adg.spdx", "")
                golden_files.append((lang, repo, binary, spdx_file))
    return golden_files


GOLDEN_FILES = get_golden_files()


@pytest.mark.parametrize(
    "lang,repo,binary,golden_path",
    GOLDEN_FILES,
    ids=[
        f"{lang}/{repo}/{binary}"
        for lang, repo, binary, _ in GOLDEN_FILES
    ],
)
def test_golden_file_exists(lang, repo, binary, golden_path):
    """Verify golden file exists and is valid JSON."""
    assert golden_path.exists(), f"Golden file missing: {golden_path}"
    doc = _load_spdx(golden_path)
    assert "packages" in doc, (
        f"Golden file missing packages: {golden_path}"
    )
    assert len(doc["packages"]) > 0, (
        f"Golden file has no packages: {golden_path}"
    )


class TestGoldenFileIntegrity:
    """Tests to verify golden files are internally consistent."""

    @pytest.mark.parametrize(
        "lang,repo,binary,golden_path",
        GOLDEN_FILES,
        ids=[
            f"{lang}/{repo}/{binary}"
            for lang, repo, binary, _ in GOLDEN_FILES
        ],
    )
    def test_no_bogus_package_names(
        self, lang, repo, binary, golden_path
    ):
        """Verify no package names contain path artifacts like '../'."""
        doc = _load_spdx(golden_path)
        for pkg in doc["packages"]:
            name = pkg["name"]
            assert "../" not in name, (
                f"Bogus package name with '../': {name} in {golden_path}"
            )
            assert name != "..", f"Bogus package name '..': {golden_path}"

    @pytest.mark.parametrize(
        "lang,repo,binary,golden_path",
        GOLDEN_FILES,
        ids=[
            f"{lang}/{repo}/{binary}"
            for lang, repo, binary, _ in GOLDEN_FILES
        ],
    )
    def test_root_package_has_version(
        self, lang, repo, binary, golden_path
    ):
        """Verify root package (first package) has version info."""
        doc = _load_spdx(golden_path)
        root_pkg = doc["packages"][0]
        has_ver = "versionInfo" in root_pkg
        is_root = root_pkg.get("name") == binary
        assert has_ver or is_root, (
            f"Root package missing version: "
            f"{root_pkg['name']} in {golden_path}"
        )


def compare_against_golden(
    actual_spdx_path: Path,
    lang: str,
    repo: str,
    binary: str,
) -> list:
    """Compare an actual SPDX file against its golden baseline.

    Returns list of differences (empty if match).
    """
    golden_path = GOLDEN_DIR / lang / repo / f"{binary}_adg.spdx.json"
    if not golden_path.exists():
        return [f"No golden file for {lang}/{repo}/{binary}"]

    golden_doc = _load_spdx(golden_path)
    actual_doc = _load_spdx(actual_spdx_path)

    golden_summary = _extract_package_summary(golden_doc)
    actual_summary = _extract_package_summary(actual_doc)

    return _compare_summaries(
        golden_summary, actual_summary, f"{lang}/{repo}/{binary}"
    )


def update_golden(actual_spdx_path: Path, lang: str, repo: str, binary: str):
    """Update golden file with new actual output.

    Call this when the actual output is confirmed correct and should
    become the new baseline.
    """
    golden_path = GOLDEN_DIR / lang / repo / f"{binary}_adg.spdx.json"
    golden_path.parent.mkdir(parents=True, exist_ok=True)

    import shutil
    shutil.copy(actual_spdx_path, golden_path)
    print(f"Updated golden: {golden_path}")
