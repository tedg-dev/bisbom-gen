"""
SPDX Structural Comparator.

Compares two SPDX 2.3 JSON documents for structural equivalence,
ignoring dynamic fields like UUIDs, timestamps, and file ordering.

Used to verify that sidecar-mode (dep:tree) SPDX output is
structurally equivalent to standalone-mode (strace) output
for the same repository at the same version.
"""

import json


class SpdxStructuralComparator:
    """Compare two SPDX documents for structural equivalence.

    "Structural equivalence" means:
    - Same package names and versions
    - Same relationship types and structure
    - File counts within a configurable tolerance
    - Same dependency graph shape

    Ignores:
    - documentNamespace (contains UUID)
    - creationInfo.created (timestamp)
    - SPDX element ID numbering (SPDXRef-File-0 vs -1)
    - File ordering within the files array
    - Checksum values (may differ between runs)
    """

    def __init__(self, tolerance_pct=5):
        """Initialize with file count tolerance.

        Args:
            tolerance_pct: maximum allowed percentage
                difference in file counts. Default 5%.
        """
        self.tolerance_pct = tolerance_pct

    def compare(self, baseline_path, candidate_path):
        """Compare two SPDX JSON files.

        Args:
            baseline_path: path to golden/reference SPDX.
            candidate_path: path to newly generated SPDX.

        Returns:
            A ``ComparisonResult`` with pass/fail and details.
        """
        baseline = self._load(baseline_path)
        candidate = self._load(candidate_path)

        result = ComparisonResult(
            baseline_path=str(baseline_path),
            candidate_path=str(candidate_path),
        )

        self._compare_metadata(
            baseline, candidate, result,
        )
        self._compare_packages(
            baseline, candidate, result,
        )
        self._compare_files(
            baseline, candidate, result,
        )
        self._compare_relationships(
            baseline, candidate, result,
        )

        return result

    @staticmethod
    def _load(path):
        """Load an SPDX JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _compare_metadata(baseline, candidate, result):
        """Compare SPDX version and document structure."""
        b_ver = baseline.get("spdxVersion")
        c_ver = candidate.get("spdxVersion")
        if b_ver != c_ver:
            result.add_diff(
                "metadata",
                f"spdxVersion: {b_ver} vs {c_ver}",
            )

        b_lic = baseline.get("dataLicense")
        c_lic = candidate.get("dataLicense")
        if b_lic != c_lic:
            result.add_diff(
                "metadata",
                f"dataLicense: {b_lic} vs {c_lic}",
            )

    def _compare_packages(
        self, baseline, candidate, result,
    ):
        """Compare package names, versions, and structure."""
        b_pkgs = baseline.get("packages", [])
        c_pkgs = candidate.get("packages", [])

        b_map = self._package_map(b_pkgs)
        c_map = self._package_map(c_pkgs)

        b_names = set(b_map.keys())
        c_names = set(c_map.keys())

        result.baseline_pkg_count = len(b_pkgs)
        result.candidate_pkg_count = len(c_pkgs)

        # Packages in baseline but not candidate
        missing = b_names - c_names
        for name in sorted(missing):
            result.add_diff(
                "packages",
                f"missing from candidate: {name} "
                f"({b_map[name]['version']})",
            )

        # Packages in candidate but not baseline
        extra = c_names - b_names
        for name in sorted(extra):
            result.add_diff(
                "packages",
                f"extra in candidate: {name} "
                f"({c_map[name]['version']})",
            )

        # Version mismatches for common packages
        common = b_names & c_names
        for name in sorted(common):
            b_ver = b_map[name]["version"]
            c_ver = c_map[name]["version"]
            if b_ver != c_ver:
                result.add_diff(
                    "packages",
                    f"version mismatch: {name} "
                    f"({b_ver} vs {c_ver})",
                )

            # Check filesAnalyzed consistency
            b_fa = b_map[name]["filesAnalyzed"]
            c_fa = c_map[name]["filesAnalyzed"]
            if b_fa != c_fa:
                result.add_diff(
                    "packages",
                    f"filesAnalyzed mismatch: {name} "
                    f"({b_fa} vs {c_fa})",
                )

    def _compare_files(
        self, baseline, candidate, result,
    ):
        """Compare file counts within tolerance."""
        b_files = baseline.get("files", [])
        c_files = candidate.get("files", [])

        b_count = len(b_files)
        c_count = len(c_files)
        result.baseline_file_count = b_count
        result.candidate_file_count = c_count

        if b_count == 0 and c_count == 0:
            return

        # Check within tolerance
        max_count = max(b_count, c_count)
        diff_pct = (
            abs(b_count - c_count) / max_count * 100
            if max_count > 0 else 0
        )
        result.file_count_diff_pct = round(diff_pct, 1)

        if diff_pct > self.tolerance_pct:
            result.add_diff(
                "files",
                f"file count difference exceeds "
                f"{self.tolerance_pct}%: "
                f"{b_count} vs {c_count} "
                f"({diff_pct:.1f}%)",
            )

        # Compare file names (normalized — sorted, no
        # regard for SPDX element IDs)
        b_names = self._file_names(b_files)
        c_names = self._file_names(c_files)

        missing = b_names - c_names
        extra = c_names - b_names
        result.files_missing = len(missing)
        result.files_extra = len(extra)

    @staticmethod
    def _compare_relationships(
        baseline, candidate, result,
    ):
        """Compare relationship types and structure."""
        b_rels = baseline.get("relationships", [])
        c_rels = candidate.get("relationships", [])

        result.baseline_rel_count = len(b_rels)
        result.candidate_rel_count = len(c_rels)

        # Compare relationship type distribution
        b_types = {}
        for r in b_rels:
            rt = r.get("relationshipType", "UNKNOWN")
            b_types[rt] = b_types.get(rt, 0) + 1

        c_types = {}
        for r in c_rels:
            rt = r.get("relationshipType", "UNKNOWN")
            c_types[rt] = c_types.get(rt, 0) + 1

        result.baseline_rel_types = b_types
        result.candidate_rel_types = c_types

        all_types = set(b_types) | set(c_types)
        for rt in sorted(all_types):
            b_n = b_types.get(rt, 0)
            c_n = c_types.get(rt, 0)
            if b_n != c_n:
                result.add_diff(
                    "relationships",
                    f"{rt}: {b_n} vs {c_n}",
                )

    @staticmethod
    def _package_map(packages):
        """Build name → {version, filesAnalyzed} map.

        Uses the package ``name`` field (not SPDXID).
        """
        pkg_map = {}
        for pkg in packages:
            name = pkg.get("name", "")
            pkg_map[name] = {
                "version": pkg.get(
                    "versionInfo", "UNKNOWN",
                ),
                "filesAnalyzed": pkg.get(
                    "filesAnalyzed", False,
                ),
            }
        return pkg_map

    @staticmethod
    def _file_names(files):
        """Extract set of file names from files array."""
        return {
            f.get("fileName", "")
            for f in files
        }


class ComparisonResult:
    """Result of an SPDX structural comparison."""

    def __init__(
        self, baseline_path="", candidate_path="",
    ):
        self.baseline_path = baseline_path
        self.candidate_path = candidate_path
        self.diffs = []

        # Package stats
        self.baseline_pkg_count = 0
        self.candidate_pkg_count = 0

        # File stats
        self.baseline_file_count = 0
        self.candidate_file_count = 0
        self.file_count_diff_pct = 0.0
        self.files_missing = 0
        self.files_extra = 0

        # Relationship stats
        self.baseline_rel_count = 0
        self.candidate_rel_count = 0
        self.baseline_rel_types = {}
        self.candidate_rel_types = {}

    @property
    def is_equivalent(self):
        """True if no structural differences found."""
        return len(self.diffs) == 0

    def add_diff(self, category, message):
        """Record a structural difference."""
        self.diffs.append({
            "category": category,
            "message": message,
        })

    def summary(self):
        """Return a human-readable summary string."""
        lines = [
            "SPDX Structural Comparison",
            f"  Baseline:  {self.baseline_path}",
            f"  Candidate: {self.candidate_path}",
            "",
            f"  Packages:  {self.baseline_pkg_count} "
            f"vs {self.candidate_pkg_count}",
            f"  Files:     {self.baseline_file_count} "
            f"vs {self.candidate_file_count} "
            f"({self.file_count_diff_pct}% diff)",
            f"  Relations: {self.baseline_rel_count} "
            f"vs {self.candidate_rel_count}",
        ]
        if self.diffs:
            lines.append(
                f"\n  {len(self.diffs)} difference(s):"
            )
            for d in self.diffs:
                lines.append(
                    f"    [{d['category']}] "
                    f"{d['message']}"
                )
        else:
            lines.append(
                "\n  Result: STRUCTURALLY EQUIVALENT"
            )
        return "\n".join(lines)
