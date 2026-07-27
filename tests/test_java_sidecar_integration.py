"""
Docker integration tests for Java sidecar pipeline (#110 B5).

Runs the full jsoup Maven sidecar pipeline inside the Docker
container and compares the output SPDX against the golden
(strace-generated) baseline.

Requirements:
  - Docker daemon running
  - bisbom-env:standalone image built
  - Network access (Maven downloads dependencies)

Run::

    pytest tests/test_java_sidecar_integration.py -v

Skip in normal test runs::

    pytest tests/ -m "not docker_integration"
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

from app.spdx.structural_comparator import (
    SpdxStructuralComparator,
)

# ── Skip conditions ──────────────────────────────────

_has_docker = shutil.which("docker") is not None


def _image_exists(tag="bisbom-env:standalone"):
    """Check if the Docker image exists locally."""
    if not _has_docker:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", tag],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


_has_image = _image_exists()

skip_no_docker = pytest.mark.skipif(
    not _has_docker,
    reason="Docker not available",
)
skip_no_image = pytest.mark.skipif(
    not _has_image,
    reason=(
        "bisbom-env:standalone image not built. "
        "Run: docker compose -f docker/"
        "docker-compose.yml build"
    ),
)

# Golden file paths
GOLDEN_DIR = Path(
    "tests/golden/spdx/java/jsoup"
)
GOLDEN_BUILD = (
    GOLDEN_DIR / "jsoup-1.22.1_build.spdx.json"
)
GOLDEN_ANALYZED = (
    GOLDEN_DIR / "jsoup-1.22.1_analyzed.spdx.json"
)

# Project root (for Docker volume mounts)
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.docker_integration
@skip_no_docker
@skip_no_image
class TestJsoupMavenSidecar(unittest.TestCase):
    """Integration test: jsoup Maven sidecar pipeline.

    Builds jsoup 1.22.1 using dep:tree strategy
    (sidecar mode, no SYS_PTRACE) and compares the
    resulting SPDX against the strace golden file.

    Acceptance criteria (from issue #110):
    - SPDX structurally equivalent: same dependency
      names, same relationship types
    - Package count within ±5%
    - No SYS_PTRACE required
    """

    _output_dir = None

    @classmethod
    def setUpClass(cls):
        """Run the sidecar pipeline once for all tests."""
        cls._output_dir = tempfile.mkdtemp(
            prefix="omnibor_sidecar_test_"
        )
        cls._repos_dir = tempfile.mkdtemp(
            prefix="omnibor_sidecar_repos_"
        )

        # Run pipeline inside Docker container.
        # Volume mounts:
        #   app/ (read-only) — pipeline code
        #   output/ (write) — SPDX output
        #   repos/ (write) — cloned repo
        # No SYS_PTRACE — this is the sidecar test.
        cmd = [
            "docker", "run", "--rm",
            "--platform", "linux/amd64",
            "-v", f"{PROJECT_ROOT}/app:/workspace/app:ro",
            "-v", f"{cls._output_dir}:/workspace/output",
            "-v", f"{cls._repos_dir}:/workspace/repos",
            "-v", (
                f"{PROJECT_ROOT}/app/config.yaml"
                ":/workspace/app/config.yaml:ro"
            ),
            "-w", "/workspace",
            "bisbom-env:standalone",
            "python3", "/workspace/app/analyze.py",
            "--repo", "jsoup",
            "--mode", "sidecar",
        ]
        cls._run_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Find the generated SPDX files
        spdx_java_dir = (
            Path(cls._output_dir) / "spdx" / "java"
            / "jsoup"
        )
        cls._build_spdx = None
        cls._analyzed_spdx = None
        if spdx_java_dir.exists():
            # Find the timestamp directory
            ts_dirs = sorted(spdx_java_dir.iterdir())
            if ts_dirs:
                ts_dir = ts_dirs[-1]
                build = (
                    ts_dir
                    / "jsoup-1.22.1_build.spdx.json"
                )
                analyzed = (
                    ts_dir
                    / "jsoup-1.22.1_analyzed.spdx.json"
                )
                if build.exists():
                    cls._build_spdx = build
                if analyzed.exists():
                    cls._analyzed_spdx = analyzed

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary directories."""
        if cls._output_dir:
            shutil.rmtree(
                cls._output_dir, ignore_errors=True,
            )
        if cls._repos_dir:
            shutil.rmtree(
                cls._repos_dir, ignore_errors=True,
            )

    def test_pipeline_exits_zero(self):
        """Pipeline should complete successfully."""
        self.assertEqual(
            self._run_result.returncode, 0,
            f"Pipeline failed:\n"
            f"STDOUT:\n{self._run_result.stdout[-2000:]}\n"
            f"STDERR:\n{self._run_result.stderr[-2000:]}",
        )

    def test_no_sys_ptrace_in_command(self):
        """No SYS_PTRACE capability used."""
        # The docker run command has no --cap-add SYS_PTRACE
        # Verify strace was NOT used in the output
        stdout = self._run_result.stdout
        self.assertNotIn(
            "strace -f", stdout,
            "strace should not be used in sidecar mode",
        )

    def test_build_spdx_generated(self):
        """Build SPDX file should be created."""
        self.assertIsNotNone(
            self._build_spdx,
            "jsoup-1.22.1_build.spdx.json not found "
            f"in output. Pipeline output:\n"
            f"{self._run_result.stdout[-1000:]}",
        )

    def test_analyzed_spdx_generated(self):
        """Analyzed SPDX file should be created."""
        self.assertIsNotNone(
            self._analyzed_spdx,
            "jsoup-1.22.1_analyzed.spdx.json not found",
        )

    @unittest.skipUnless(
        GOLDEN_BUILD.exists(),
        "Golden build SPDX not present",
    )
    def test_build_spdx_structurally_equivalent(self):
        """Sidecar build SPDX ≈ strace golden file."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        cmp = SpdxStructuralComparator(
            tolerance_pct=5,
        )
        result = cmp.compare(
            GOLDEN_BUILD, self._build_spdx,
        )

        # Report details regardless of pass/fail
        print(f"\n{result.summary()}")

        self.assertTrue(
            result.is_equivalent,
            f"Structural differences found:\n"
            f"{result.summary()}",
        )

    @unittest.skipUnless(
        GOLDEN_ANALYZED.exists(),
        "Golden analyzed SPDX not present",
    )
    def test_analyzed_spdx_structurally_equivalent(
        self,
    ):
        """Sidecar analyzed SPDX ≈ strace golden file."""
        if not self._analyzed_spdx:
            self.skipTest("Analyzed SPDX not generated")

        cmp = SpdxStructuralComparator(
            tolerance_pct=5,
        )
        result = cmp.compare(
            GOLDEN_ANALYZED, self._analyzed_spdx,
        )

        print(f"\n{result.summary()}")

        self.assertTrue(
            result.is_equivalent,
            f"Structural differences found:\n"
            f"{result.summary()}",
        )

    def test_build_spdx_valid_json(self):
        """Build SPDX should be valid JSON."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx) as f:
            doc = json.load(f)

        self.assertEqual(
            doc["spdxVersion"], "SPDX-2.3"
        )
        self.assertIn("packages", doc)
        self.assertIn("files", doc)
        self.assertIn("relationships", doc)

    def test_build_has_maven_dependencies(self):
        """Build SPDX should include Maven deps."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx) as f:
            doc = json.load(f)

        pkgs = doc.get("packages", [])
        dep_pkgs = [
            p for p in pkgs
            if not p.get("filesAnalyzed", True)
        ]
        # jsoup has at least jspecify and re2j
        self.assertGreaterEqual(
            len(dep_pkgs), 1,
            "Expected at least 1 Maven dependency "
            "package with filesAnalyzed=false",
        )

    def test_analyzed_has_no_dependencies(self):
        """Analyzed SPDX should have only the root pkg."""
        if not self._analyzed_spdx:
            self.skipTest("Analyzed SPDX not generated")

        with open(self._analyzed_spdx) as f:
            doc = json.load(f)

        pkgs = doc.get("packages", [])
        # Analyzed = only source files, no deps
        self.assertEqual(
            len(pkgs), 1,
            f"Expected 1 package (root only), "
            f"got {len(pkgs)}",
        )

    def test_package_count_within_tolerance(self):
        """Package count should be within ±5%."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")
        if not GOLDEN_BUILD.exists():
            self.skipTest("Golden file not present")

        with open(GOLDEN_BUILD) as f:
            golden = json.load(f)
        with open(self._build_spdx) as f:
            candidate = json.load(f)

        g_count = len(golden.get("packages", []))
        c_count = len(candidate.get("packages", []))
        max_count = max(g_count, c_count)
        if max_count == 0:
            return

        diff_pct = (
            abs(g_count - c_count) / max_count * 100
        )
        self.assertLessEqual(
            diff_pct, 5.0,
            f"Package count differs by {diff_pct:.1f}%: "
            f"golden={g_count}, candidate={c_count}",
        )

    def test_dep_tree_strategy_logged(self):
        """Pipeline output should mention dep:tree strategy."""
        stdout = self._run_result.stdout
        # Should see Maven dep:tree execution
        self.assertTrue(
            "dep:tree" in stdout.lower()
            or "maven dep" in stdout.lower()
            or "MavenDepTreeStrategy" in stdout,
            "Expected dep:tree strategy in pipeline "
            f"output:\n{stdout[-1000:]}",
        )


if __name__ == "__main__":
    unittest.main()
