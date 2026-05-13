"""Tests for phase isolation (--phase build / --phase spdx).

Covers CLI validation, Phase 1 manifest write,
Phase 2 manifest read, and the round-trip flow.
"""

import json
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    read_manifest,
)
from app.pipeline.runners import (
    _run_phase1_only,
    _run_phase2_only,
    _validate_phase_args,
)
from app.pipeline.builder import BuildResult


# ── Fixtures ─────────────────────────────────────────────


def _make_pipeline():
    """Create a mock AnalysisPipeline."""
    p = MagicMock()
    p.builder.build.return_value = BuildResult(
        success=True,
    )
    p.builder.build_java.return_value = BuildResult(
        success=True,
    )
    p.spdx_gen.generate_java.return_value = (
        "/tmp/spdx.json"
    )
    p.metadata_collector.collect.return_value = None
    p.spdx_validator.validate.return_value = None
    p.binary_collector.collect.return_value = None
    return p


def _make_cfg(td):
    """Create test config dicts in a temp dir."""
    paths_cfg = {
        "output_dir": str(Path(td) / "output"),
        "repos_dir": str(Path(td) / "repos"),
    }
    repo_cfg = {
        "language": "java",
        "url": "https://github.com/test/test.git",
        "build_steps": ["mvn package -DskipTests -q"],
        "output_binaries": ["**/target/*.jar"],
    }
    omnibor_cfg = {
        "strace_opts": "-f",
        "create_bom_script": "bomsh_bom_java.py",
        "strace_logfile": "/tmp/strace.log",
    }
    return paths_cfg, repo_cfg, omnibor_cfg


# ── _validate_phase_args ─────────────────────────────────


class TestValidatePhaseArgs:
    """Tests for _validate_phase_args."""

    def _make_parser(self):
        """Minimal mock parser with error method."""
        parser = MagicMock()
        parser.error.side_effect = SystemExit(2)
        return parser

    def test_phase_requires_sidecar(self):
        parser = self._make_parser()
        args = Namespace(
            phase="build", mode=None, manifest=None,
        )
        with pytest.raises(SystemExit):
            _validate_phase_args(args, parser)
        parser.error.assert_called_once()
        assert "sidecar" in str(
            parser.error.call_args
        )

    def test_phase_build_with_standalone_fails(self):
        parser = self._make_parser()
        args = Namespace(
            phase="build", mode="standalone",
            manifest=None,
        )
        with pytest.raises(SystemExit):
            _validate_phase_args(args, parser)

    def test_phase_spdx_requires_manifest(self):
        parser = self._make_parser()
        args = Namespace(
            phase="spdx", mode="sidecar",
            manifest=None,
        )
        with pytest.raises(SystemExit):
            _validate_phase_args(args, parser)
        assert "manifest" in str(
            parser.error.call_args
        ).lower()

    def test_phase_build_rejects_manifest(self):
        parser = self._make_parser()
        args = Namespace(
            phase="build", mode="sidecar",
            manifest="/tmp/m.json",
        )
        with pytest.raises(SystemExit):
            _validate_phase_args(args, parser)

    def test_phase_build_sidecar_passes(self):
        parser = self._make_parser()
        args = Namespace(
            phase="build", mode="sidecar",
            manifest=None,
        )
        _validate_phase_args(args, parser)
        parser.error.assert_not_called()

    def test_phase_spdx_with_manifest_passes(self):
        parser = self._make_parser()
        args = Namespace(
            phase="spdx", mode="sidecar",
            manifest="/tmp/m.json",
        )
        _validate_phase_args(args, parser)
        parser.error.assert_not_called()


# ── _run_phase1_only ─────────────────────────────────────


class TestRunPhase1Only:
    """Tests for _run_phase1_only."""

    @patch(
        "app.pipeline.lang_runners"
        "._select_java_strategy",
    )
    def test_writes_manifest(self, mock_strategy):
        mock_strategy.return_value = None
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, omnibor = _make_cfg(td)

            # Create a fake JAR so binary resolution works
            repo_dir = Path(td) / "repos" / "myapp"
            target_dir = repo_dir / "target"
            target_dir.mkdir(parents=True)
            jar = target_dir / "myapp-1.0.jar"
            jar.write_text("fake-jar")

            timing = _run_phase1_only(
                pipeline, "myapp", repo_cfg,
                paths, omnibor, "ts1",
                mode="sidecar", lang="java",
                commit_sha="abc123",
                vcs_uri="https://example.com",
            )

            assert timing.success

            # Manifest should exist in bom_dir
            bom_dir = (
                Path(td) / "output" / "omnibor"
                / "java" / "myapp" / "ts1"
            )
            manifest_path = bom_dir / MANIFEST_FILENAME
            assert manifest_path.exists()

            data = json.loads(
                manifest_path.read_text()
            )
            assert data["version"] == MANIFEST_VERSION
            assert data["repo_name"] == "myapp"
            assert data["language"] == "java"
            assert data["mode"] == "sidecar"
            assert data["commit_sha"] == "abc123"
            assert len(data["artifacts"]["binaries"]) == 1
            assert "repo_cfg" in data
            assert "omnibor_cfg" in data

    @patch(
        "app.pipeline.lang_runners"
        "._select_java_strategy",
    )
    def test_build_failure_skips_manifest(
        self, mock_strategy,
    ):
        mock_strategy.return_value = None
        pipeline = _make_pipeline()
        pipeline.builder.build_java.return_value = (
            BuildResult(success=False)
        )

        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, omnibor = _make_cfg(td)

            timing = _run_phase1_only(
                pipeline, "myapp", repo_cfg,
                paths, omnibor, "ts1",
                mode="sidecar", lang="java",
                commit_sha="abc123",
                vcs_uri="https://example.com",
            )

            assert not timing.success

            # No manifest should be written
            bom_dir = (
                Path(td) / "output" / "omnibor"
                / "java" / "myapp" / "ts1"
            )
            assert not (
                bom_dir / MANIFEST_FILENAME
            ).exists()


# ── _run_phase2_only ─────────────────────────────────────


class TestRunPhase2Only:
    """Tests for _run_phase2_only."""

    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
    )
    def test_reads_manifest_and_runs(self, mock_adg):
        mock_adg.return_value = ["/tmp/adg.spdx.json"]
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, omnibor = _make_cfg(td)

            # Write a valid manifest
            manifest_dir = Path(td) / "manifest"
            manifest_dir.mkdir()
            manifest_file = (
                manifest_dir / MANIFEST_FILENAME
            )
            manifest_data = {
                "version": MANIFEST_VERSION,
                "repo_name": "myapp",
                "language": "java",
                "mode": "sidecar",
                "tracer": "maven-dep-tree",
                "run_ts": "ts1",
                "commit_sha": "abc123",
                "vcs_uri": "https://example.com",
                "artifacts": {
                    "bom_dir": str(td),
                    "binaries": [],
                },
                "paths": {
                    "repos_dir": paths["repos_dir"],
                    "output_dir": paths["output_dir"],
                    "spdx_dir": str(td),
                },
                "repo_cfg": repo_cfg,
                "omnibor_cfg": omnibor,
                "gitoids": {},
            }
            manifest_file.write_text(
                json.dumps(manifest_data)
            )

            timing = _run_phase2_only(
                pipeline, "myapp",
                str(manifest_file), paths,
                omnibor, "ts1",
                vcs_uri="https://example.com",
            )

            assert timing.success
            assert timing.tracer == "maven-dep-tree"
            # Phase 2 steps should be present
            assert len(timing.steps) > 0

    def test_missing_manifest_raises(self):
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, _, omnibor = _make_cfg(td)

            with pytest.raises(FileNotFoundError):
                _run_phase2_only(
                    pipeline, "myapp",
                    "/nonexistent/manifest.json",
                    paths, omnibor, "ts1",
                )

    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
    )
    def test_tampered_artifact_warns(self, mock_adg):
        mock_adg.return_value = []
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, _, omnibor = _make_cfg(td)

            # Create an artifact file and record its gitoid
            artifact = Path(td) / "treedb"
            artifact.write_text("original")

            from app.pipeline.manifest import (
                _sha256_gitoid,
            )
            original_gitoid = _sha256_gitoid(artifact)

            manifest_dir = Path(td) / "manifest"
            manifest_dir.mkdir()
            manifest_file = (
                manifest_dir / MANIFEST_FILENAME
            )
            manifest_data = {
                "version": MANIFEST_VERSION,
                "repo_name": "myapp",
                "language": "java",
                "mode": "sidecar",
                "tracer": "maven-dep-tree",
                "run_ts": "ts1",
                "commit_sha": "abc123",
                "vcs_uri": "https://example.com",
                "artifacts": {
                    "bom_dir": str(td),
                    "treedb": str(artifact),
                    "binaries": [],
                },
                "paths": {
                    "repos_dir": paths["repos_dir"],
                    "output_dir": paths["output_dir"],
                    "spdx_dir": str(td),
                },
                "gitoids": {
                    str(artifact): original_gitoid,
                },
            }
            manifest_file.write_text(
                json.dumps(manifest_data)
            )

            # Tamper with the artifact
            artifact.write_text("tampered!")

            timing = _run_phase2_only(
                pipeline, "myapp",
                str(manifest_file), paths,
                omnibor, "ts1",
            )

            # Should still succeed (warning, not error)
            assert timing.success


# ── Round-trip ───────────────────────────────────────────


class TestPhaseRoundTrip:
    """End-to-end: Phase 1 writes manifest,
    Phase 2 reads it."""

    @patch(
        "app.pipeline.lang_runners"
        "._select_java_strategy",
    )
    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
    )
    def test_round_trip(
        self, mock_adg, mock_strategy,
    ):
        mock_strategy.return_value = None
        mock_adg.return_value = ["/tmp/adg.spdx.json"]
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, omnibor = _make_cfg(td)

            # Create fake JAR
            repo_dir = Path(td) / "repos" / "myapp"
            target_dir = repo_dir / "target"
            target_dir.mkdir(parents=True)
            jar = target_dir / "myapp-1.0.jar"
            jar.write_text("fake-jar")

            # Phase 1: build + manifest
            timing1 = _run_phase1_only(
                pipeline, "myapp", repo_cfg,
                paths, omnibor, "ts1",
                mode="sidecar", lang="java",
                commit_sha="abc123",
                vcs_uri="https://example.com",
            )
            assert timing1.success

            # Find the manifest
            bom_dir = (
                Path(td) / "output" / "omnibor"
                / "java" / "myapp" / "ts1"
            )
            manifest_path = bom_dir / MANIFEST_FILENAME
            assert manifest_path.exists()

            # Phase 2: read manifest + SPDX
            timing2 = _run_phase2_only(
                pipeline, "myapp",
                str(manifest_path), paths,
                omnibor, "ts1",
                vcs_uri="https://example.com",
            )
            assert timing2.success
            assert len(timing2.steps) > 0

            # Verify manifest was read correctly
            manifest = read_manifest(manifest_path)
            assert manifest["repo_name"] == "myapp"
            assert manifest["language"] == "java"
            assert manifest["mode"] == "sidecar"

    @patch(
        "app.pipeline.lang_runners"
        "._select_java_strategy",
    )
    @patch(
        "app.pipeline.lang_runners"
        ".generate_java_adg_spdx",
    )
    def test_phase2_uses_phase1_run_ts(
        self, mock_adg, mock_strategy,
    ):
        """Phase 2 must reuse Phase 1's run_ts so all
        output (SPDX, docs, runtime) lands in the same
        directory tree."""
        mock_strategy.return_value = None
        mock_adg.return_value = ["/tmp/adg.spdx.json"]
        pipeline = _make_pipeline()

        with tempfile.TemporaryDirectory() as td:
            paths, repo_cfg, omnibor = _make_cfg(td)

            repo_dir = Path(td) / "repos" / "myapp"
            target_dir = repo_dir / "target"
            target_dir.mkdir(parents=True)
            (target_dir / "myapp.jar").write_text("x")

            # Phase 1: uses a specific run_ts
            phase1_ts = "2026-05-12_1200"
            timing1 = _run_phase1_only(
                pipeline, "myapp", repo_cfg,
                paths, omnibor, phase1_ts,
                mode="sidecar", lang="java",
                commit_sha="abc", vcs_uri="https://x",
            )
            assert timing1.success

            # Read manifest — verify run_ts stored
            bom_dir = (
                Path(td) / "output" / "omnibor"
                / "java" / "myapp" / phase1_ts
            )
            manifest_path = bom_dir / MANIFEST_FILENAME
            manifest = read_manifest(manifest_path)
            assert manifest["run_ts"] == phase1_ts

            # Phase 2 with a DIFFERENT run_ts arg
            phase2_ts = "2026-05-12_9999"
            timing2 = _run_phase2_only(
                pipeline, "myapp",
                str(manifest_path), paths,
                omnibor, phase2_ts,
            )
            assert timing2.success

            # _run_phase2_only uses manifest's run_ts
            # (phase1_ts), not the phase2_ts arg,
            # for the actual SPDX generation calls.
            assert mock_adg.called
            # Phase 1 ts must appear in the call args
            call_str = str(mock_adg.call_args)
            assert phase1_ts in call_str, (
                f"Expected {phase1_ts} in Phase 2 "
                f"call, got: {call_str}"
            )
