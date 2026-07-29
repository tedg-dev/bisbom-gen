"""
Docker integration tests for Java on RHEL (#112 B7).

Runs the Java sidecar pipeline inside the RHEL (Rocky Linux 9)
container to validate that dep:tree + RpmResolver work together
and produce valid SPDX with pkg:rpm PURLs.

Requirements:
  - Docker daemon running
  - bisbom-env:rhel9 image built
  - Network access (Maven downloads dependencies)

Run::

    docker compose -f docker/docker-compose.yml run --rm \\
        bisbom-rhel python3 -m pytest \\
        tests/test_java_rhel_integration.py -v

Skip in normal test runs::

    pytest tests/ -m "not docker_integration"
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

# ── Skip conditions ──────────────────────────────────

_has_docker = shutil.which("docker") is not None


def _image_exists(tag="bisbom-env:rhel9"):
    """Check if the Docker image exists locally."""
    if not _has_docker:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", tag],
            capture_output=True, timeout=10,
            check=False,
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
        "bisbom-env:rhel9 image not built. "
        "Run: docker compose -f docker/"
        "docker-compose.yml build bisbom-rhel"
    ),
)

# Project root (for Docker volume mounts)
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.docker_integration
@skip_no_docker
@skip_no_image
class TestJavaOnRhel(unittest.TestCase):
    """Integration test: Java sidecar pipeline on RHEL.

    Builds crawler4j 4.4.0 using dep:tree strategy inside
    the RHEL container (sidecar mode, no SYS_PTRACE).
    Uses a complex multi-module Maven project with
    BUILD_TOOL_OF dependencies.

    Acceptance criteria (from issue #112):
    - Valid SPDX on RHEL
    - No strace, no SYS_PTRACE, no dpkg in logs
    - PURLs use pkg:rpm/
    - BUILD_TOOL_OF relationships present
    - Structurally equivalent to standalone golden files
    """

    _output_dir = None

    @classmethod
    def setUpClass(cls):
        """Run the sidecar pipeline once for all tests."""
        cls._output_dir = tempfile.mkdtemp(
            prefix="omnibor_java_rhel_test_"
        )
        cls._repos_dir = tempfile.mkdtemp(
            prefix="omnibor_java_rhel_repos_"
        )

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
            "bisbom-env:rhel9",
            "python3", "/workspace/app/analyze.py",
            "--repo", "crawler4j",
            "--mode", "sidecar",
        ]
        cls._run_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

        # Find the generated SPDX files
        spdx_java_dir = (
            Path(cls._output_dir) / "spdx" / "java"
            / "crawler4j"
        )
        cls._build_spdx = None
        cls._analyzed_spdx = None
        if spdx_java_dir.exists():
            ts_dirs = sorted(spdx_java_dir.iterdir())
            if ts_dirs:
                ts_dir = ts_dirs[-1]
                build = (
                    ts_dir
                    / "crawler4j-4.4.0_build.spdx.json"
                )
                analyzed = (
                    ts_dir
                    / "crawler4j-4.4.0_analyzed"
                    ".spdx.json"
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

    # ── Pipeline execution ──────────────────────────

    def test_pipeline_exits_zero(self):
        """Pipeline should complete successfully on RHEL."""
        self.assertEqual(
            self._run_result.returncode, 0,
            f"Pipeline failed on RHEL:\n"
            f"STDOUT:\n{self._run_result.stdout[-2000:]}\n"
            f"STDERR:\n{self._run_result.stderr[-2000:]}",
        )

    def test_no_sys_ptrace(self):
        """No SYS_PTRACE capability used."""
        stdout = self._run_result.stdout
        self.assertNotIn(
            "strace -f", stdout,
            "strace should not be used in sidecar mode",
        )

    def test_no_dpkg_in_logs(self):
        """No dpkg references on RHEL."""
        stdout = self._run_result.stdout
        stderr = self._run_result.stderr
        combined = stdout + stderr
        # dpkg-query is Ubuntu-specific
        self.assertNotIn(
            "dpkg-query", combined,
            "dpkg-query should not appear on RHEL",
        )

    # ── SPDX validity ──────────────────────────────

    def test_build_spdx_generated(self):
        """Build SPDX file should be created on RHEL."""
        self.assertIsNotNone(
            self._build_spdx,
            "crawler4j-4.4.0_build.spdx.json not "
            "found in output. Pipeline output:\n"
            f"{self._run_result.stdout[-1000:]}",
        )

    def test_build_spdx_valid_json(self):
        """Build SPDX should be valid JSON with SPDX-2.3."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx, encoding="utf-8") as f:
            doc = json.load(f)

        self.assertEqual(
            doc["spdxVersion"], "SPDX-2.3"
        )
        self.assertIn("packages", doc)
        self.assertIn("relationships", doc)

    def test_build_has_maven_dependencies(self):
        """Build SPDX should include Maven deps."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx, encoding="utf-8") as f:
            doc = json.load(f)

        pkgs = doc.get("packages", [])
        dep_pkgs = [
            p for p in pkgs
            if not p.get("filesAnalyzed", True)
        ]
        self.assertGreaterEqual(
            len(dep_pkgs), 1,
            "Expected at least 1 Maven dependency",
        )

    # ── PURL verification ───────────────────────────

    def test_system_purls_use_rpm(self):
        """System library PURLs should use pkg:rpm/.

        If the pipeline resolves any system libraries on
        RHEL, their PURLs must use the rpm scheme, not deb.
        """
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx, encoding="utf-8") as f:
            doc = json.load(f)

        for pkg in doc.get("packages", []):
            for ref in pkg.get("externalRefs", []):
                locator = ref.get("referenceLocator", "")
                if locator.startswith("pkg:"):
                    # Java deps use pkg:maven — that's fine
                    # System deps should NOT use pkg:deb
                    self.assertFalse(
                        locator.startswith("pkg:deb/"),
                        f"Found deb PURL on RHEL: "
                        f"{locator}",
                    )

    def test_dep_tree_strategy_logged(self):
        """Pipeline should use dep:tree strategy."""
        stdout = self._run_result.stdout
        self.assertTrue(
            "dep:tree" in stdout.lower()
            or "maven dep" in stdout.lower()
            or "MavenDepTreeStrategy" in stdout,
            "Expected dep:tree strategy in pipeline "
            f"output:\n{stdout[-1000:]}",
        )

    # ── BUILD_TOOL_OF ────────────────────────────────

    def test_build_tool_of_present(self):
        """Build SPDX should have BUILD_TOOL_OF rels."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx, encoding="utf-8") as f:
            doc = json.load(f)

        bt_rels = [
            r for r in doc.get("relationships", [])
            if r["relationshipType"] == "BUILD_TOOL_OF"
        ]
        self.assertGreaterEqual(
            len(bt_rels), 1,
            "Expected BUILD_TOOL_OF relationships "
            "in crawler4j build SPDX",
        )

    # ── Golden file comparison ───────────────────────

    def test_build_spdx_matches_golden(self):
        """Build SPDX must be structurally equivalent
        to the standalone-generated golden file."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        golden = (
            PROJECT_ROOT / "tests" / "golden"
            / "spdx" / "java" / "crawler4j"
            / "crawler4j-4.4.0_build.spdx.json"
        )
        if not golden.exists():
            self.skipTest(
                f"Golden file not found: {golden}"
            )

        sys.path.insert(0, str(PROJECT_ROOT))
        from app.spdx.structural_comparator import (
            SpdxStructuralComparator,
        )
        comparator = SpdxStructuralComparator(
            tolerance_pct=0,
        )
        result = comparator.compare(
            str(golden), str(self._build_spdx),
        )
        self.assertTrue(
            result.is_equivalent,
            f"RHEL build SPDX differs from golden:\n"
            f"{result.summary()}",
        )

    def test_analyzed_spdx_matches_golden(self):
        """Analyzed SPDX must be structurally equivalent
        to the standalone-generated golden file."""
        if not self._analyzed_spdx:
            self.skipTest(
                "Analyzed SPDX not generated"
            )

        golden = (
            PROJECT_ROOT / "tests" / "golden"
            / "spdx" / "java" / "crawler4j"
            / "crawler4j-4.4.0_analyzed.spdx.json"
        )
        if not golden.exists():
            self.skipTest(
                f"Golden file not found: {golden}"
            )

        sys.path.insert(0, str(PROJECT_ROOT))
        from app.spdx.structural_comparator import (
            SpdxStructuralComparator,
        )
        comparator = SpdxStructuralComparator(
            tolerance_pct=0,
        )
        result = comparator.compare(
            str(golden),
            str(self._analyzed_spdx),
        )
        self.assertTrue(
            result.is_equivalent,
            "RHEL analyzed SPDX differs from "
            f"golden:\n{result.summary()}",
        )


if __name__ == "__main__":
    unittest.main()
