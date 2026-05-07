"""
Docker integration tests for checkstyle shade plugin (#111 B6).

Runs the full checkstyle Maven sidecar pipeline inside the
Docker container. Verifies:
  - Shade plugin warning is emitted
  - SPDX comment mentions shade plugin
  - SPDX is otherwise valid

Requirements:
  - Docker daemon running
  - omnibor-env:standalone image built
  - Network access (Maven downloads dependencies)

Run::

    pytest tests/test_checkstyle_sidecar_integration.py -v

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


def _image_exists(tag="omnibor-env:standalone"):
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
        "omnibor-env:standalone image not built. "
        "Run: docker compose -f docker/"
        "docker-compose.yml build"
    ),
)

# Golden file paths
GOLDEN_DIR = Path(
    "tests/golden/spdx/java/checkstyle"
)
GOLDEN_BUILD = (
    GOLDEN_DIR / "checkstyle-13.3.0_build.spdx.json"
)
GOLDEN_ANALYZED = (
    GOLDEN_DIR / "checkstyle-13.3.0_analyzed.spdx.json"
)

# Project root (for Docker volume mounts)
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.docker_integration
@skip_no_docker
@skip_no_image
class TestCheckstyleShadeSidecar(unittest.TestCase):
    """Integration test: checkstyle shade plugin pipeline.

    Builds checkstyle 13.3.0 using dep:tree strategy
    (sidecar mode, no SYS_PTRACE) and verifies:
    - Shade plugin warning is logged
    - SPDX comment annotates shade plugin
    - SPDX is otherwise structurally valid

    Acceptance criteria (from issue #111):
    - Warning logged for shade plugin
    - SPDX comment mentions shade plugin
    - SPDX otherwise valid
    """

    _output_dir = None

    @classmethod
    def setUpClass(cls):
        """Run the sidecar pipeline once for all tests."""
        cls._output_dir = tempfile.mkdtemp(
            prefix="omnibor_checkstyle_test_"
        )
        cls._repos_dir = tempfile.mkdtemp(
            prefix="omnibor_checkstyle_repos_"
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
            "omnibor-env:standalone",
            "python3", "-m", "app.pipeline.runners",
            "--repo", "checkstyle",
            "--mode", "sidecar",
        ]
        cls._run_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,
        )

        # Find the generated SPDX files
        spdx_java_dir = (
            Path(cls._output_dir) / "spdx" / "java"
            / "checkstyle"
        )
        cls._build_spdx = None
        cls._analyzed_spdx = None
        if spdx_java_dir.exists():
            ts_dirs = sorted(spdx_java_dir.iterdir())
            if ts_dirs:
                ts_dir = ts_dirs[-1]
                build = (
                    ts_dir
                    / "checkstyle-13.3.0_build.spdx.json"
                )
                analyzed = (
                    ts_dir
                    / "checkstyle-13.3.0_analyzed"
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

    # ── Core pipeline tests ──────────────────────────

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
        stdout = self._run_result.stdout
        self.assertNotIn(
            "strace -f", stdout,
            "strace should not be used in sidecar mode",
        )

    # ── Shade plugin tests (issue #111 criteria) ─────

    def test_shade_plugin_warning_logged(self):
        """Pipeline should log a warning for shade plugin."""
        stdout = self._run_result.stdout
        self.assertIn(
            "[WARN]", stdout,
            "Expected [WARN] in pipeline output for "
            f"shade plugin:\n{stdout[-1000:]}",
        )
        self.assertTrue(
            "shade" in stdout.lower(),
            "Expected 'shade' mention in pipeline "
            f"output:\n{stdout[-1000:]}",
        )

    def test_build_spdx_creation_comment_mentions_shade(
        self,
    ):
        """creationInfo comment should mention shade plugin."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx) as f:
            doc = json.load(f)

        creation = doc.get("creationInfo", {})
        comment = creation.get("comment", "")
        self.assertTrue(
            "shade" in comment.lower(),
            f"Expected 'shade' in creationInfo.comment, "
            f"got: {comment!r}",
        )

    def test_build_spdx_root_package_comment_mentions_shade(
        self,
    ):
        """Root package comment should mention shade plugin."""
        if not self._build_spdx:
            self.skipTest("Build SPDX not generated")

        with open(self._build_spdx) as f:
            doc = json.load(f)

        root = doc["packages"][0]
        comment = root.get("comment", "")
        self.assertTrue(
            "shade" in comment.lower(),
            f"Expected 'shade' in root package comment, "
            f"got: {comment!r}",
        )

    # ── SPDX validity tests ──────────────────────────

    def test_build_spdx_generated(self):
        """Build SPDX file should be created."""
        self.assertIsNotNone(
            self._build_spdx,
            "checkstyle-13.3.0_build.spdx.json not "
            f"found in output. Pipeline output:\n"
            f"{self._run_result.stdout[-1000:]}",
        )

    def test_analyzed_spdx_generated(self):
        """Analyzed SPDX file should be created."""
        self.assertIsNotNone(
            self._analyzed_spdx,
            "checkstyle-13.3.0_analyzed.spdx.json "
            "not found",
        )

    def test_build_spdx_valid_json(self):
        """Build SPDX should be valid SPDX 2.3 JSON."""
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
        # checkstyle has picocli, antlr4-runtime, etc.
        self.assertGreaterEqual(
            len(dep_pkgs), 5,
            "Expected at least 5 Maven dependency "
            f"packages, got {len(dep_pkgs)}",
        )

    def test_analyzed_has_no_dependencies(self):
        """Analyzed SPDX should have only the root pkg."""
        if not self._analyzed_spdx:
            self.skipTest("Analyzed SPDX not generated")

        with open(self._analyzed_spdx) as f:
            doc = json.load(f)

        pkgs = doc.get("packages", [])
        self.assertEqual(
            len(pkgs), 1,
            f"Expected 1 package (root only), "
            f"got {len(pkgs)}",
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

        print(f"\n{result.summary()}")

        self.assertTrue(
            result.is_equivalent,
            f"Structural differences found:\n"
            f"{result.summary()}",
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
        self.assertTrue(
            "dep:tree" in stdout.lower()
            or "maven dep" in stdout.lower()
            or "MavenDepTreeStrategy" in stdout,
            "Expected dep:tree strategy in pipeline "
            f"output:\n{stdout[-1000:]}",
        )


if __name__ == "__main__":
    unittest.main()
