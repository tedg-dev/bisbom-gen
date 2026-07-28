"""Unit tests for app.pipeline.manifest module."""

import json
from pathlib import Path

import pytest

from app.pipeline.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ManifestError,
    read_manifest,
    verify_gitoids,
    write_manifest,
    _sha256_gitoid,
)


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def manifest_dir(tmp_path):
    """Temporary directory for manifest output."""
    return tmp_path / "bom_dir"


@pytest.fixture
def sample_artifacts(tmp_path):
    """Sample artifact paths with real files."""
    treedb = tmp_path / "treedb"
    treedb.write_text("treedb-content")
    binary = tmp_path / "app.jar"
    binary.write_text("jar-content")
    return {
        "bom_dir": str(tmp_path / "bom"),
        "treedb": str(treedb),
        "binaries": [str(binary)],
    }


@pytest.fixture
def sample_paths(tmp_path):
    """Sample paths config."""
    return {
        "repos_dir": str(tmp_path / "repos"),
        "output_dir": str(tmp_path / "output"),
        "spdx_dir": str(tmp_path / "spdx"),
    }


@pytest.fixture
def sample_kwargs(
    manifest_dir, sample_artifacts, sample_paths,
):
    """Common kwargs for write_manifest."""
    return {
        "manifest_dir": str(manifest_dir),
        "repo_name": "jsoup",
        "language": "java",
        "mode": "sidecar",
        "tracer": "maven-dep-tree",
        "run_ts": "2026-05-12_0900",
        "commit_sha": "abc123def456",
        "vcs_uri": "https://github.com/jhy/jsoup.git@abc123",
        "artifacts": sample_artifacts,
        "paths": sample_paths,
    }


# ── write_manifest ───────────────────────────────────────


class TestWriteManifest:
    """Tests for write_manifest."""

    def test_creates_manifest_file(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        assert path.exists()
        assert path.name == MANIFEST_FILENAME

    def test_creates_parent_dirs(self, sample_kwargs):
        sample_kwargs["manifest_dir"] = str(
            Path(sample_kwargs["manifest_dir"]) / "deep" / "nested"
        )
        path = write_manifest(**sample_kwargs)
        assert path.exists()

    def test_manifest_content(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert data["version"] == MANIFEST_VERSION
        assert data["repo_name"] == "jsoup"
        assert data["language"] == "java"
        assert data["mode"] == "sidecar"
        assert data["tracer"] == "maven-dep-tree"
        assert data["run_ts"] == "2026-05-12_0900"
        assert data["commit_sha"] == "abc123def456"
        assert data["vcs_uri"].startswith("https://")

    def test_artifacts_preserved(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "bom_dir" in data["artifacts"]
        assert isinstance(
            data["artifacts"]["binaries"], list,
        )

    def test_paths_preserved(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "repos_dir" in data["paths"]
        assert "output_dir" in data["paths"]
        assert "spdx_dir" in data["paths"]

    def test_gitoids_computed(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "gitoids" in data
        # treedb file exists, so it should have a gitoid
        treedb_path = sample_kwargs["artifacts"]["treedb"]
        assert treedb_path in data["gitoids"]

    def test_optional_repo_cfg(self, sample_kwargs):
        sample_kwargs["repo_cfg"] = {
            "output_binaries": ["**/target/*.jar"],
        }
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "repo_cfg" in data

    def test_optional_bisbom_cfg(self, sample_kwargs):
        sample_kwargs["bisbom_cfg"] = {
            "strace_opts": "-f -e trace=openat",
        }
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "bisbom_cfg" in data

    def test_no_optional_fields_by_default(
        self, sample_kwargs,
    ):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "repo_cfg" not in data
        assert "bisbom_cfg" not in data

    def test_missing_bom_dir_raises(self, sample_kwargs):
        del sample_kwargs["artifacts"]["bom_dir"]
        with pytest.raises(ManifestError, match="bom_dir"):
            write_manifest(**sample_kwargs)

    def test_missing_binaries_raises(self, sample_kwargs):
        del sample_kwargs["artifacts"]["binaries"]
        with pytest.raises(
            ManifestError, match="binaries",
        ):
            write_manifest(**sample_kwargs)

    def test_binaries_not_list_raises(self, sample_kwargs):
        sample_kwargs["artifacts"]["binaries"] = "not-a-list"
        with pytest.raises(
            ManifestError, match="must be a list",
        ):
            write_manifest(**sample_kwargs)

    def test_missing_repos_dir_raises(self, sample_kwargs):
        del sample_kwargs["paths"]["repos_dir"]
        with pytest.raises(
            ManifestError, match="repos_dir",
        ):
            write_manifest(**sample_kwargs)

    def test_null_commit_sha(self, sample_kwargs):
        sample_kwargs["commit_sha"] = None
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert data["commit_sha"] is None


# ── read_manifest ────────────────────────────────────────


class TestReadManifest:
    """Tests for read_manifest."""

    def test_round_trip(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = read_manifest(path)
        assert data["repo_name"] == "jsoup"
        assert data["version"] == MANIFEST_VERSION

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_manifest(tmp_path / "nonexistent.json")

    def test_malformed_json(self, tmp_path):
        bad_file = tmp_path / MANIFEST_FILENAME
        bad_file.write_text("{not valid json")
        with pytest.raises(ManifestError, match="Malformed"):
            read_manifest(bad_file)

    def test_missing_required_field(self, tmp_path):
        bad_file = tmp_path / MANIFEST_FILENAME
        bad_file.write_text(json.dumps({"version": "1.0"}))
        with pytest.raises(
            ManifestError, match="Missing required",
        ):
            read_manifest(bad_file)

    def test_wrong_version(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        data["version"] = "99.0"
        path.write_text(json.dumps(data))
        with pytest.raises(
            ManifestError, match="Unsupported.*version",
        ):
            read_manifest(path)

    def test_not_a_dict(self, tmp_path):
        bad_file = tmp_path / MANIFEST_FILENAME
        bad_file.write_text(json.dumps([1, 2, 3]))
        with pytest.raises(
            ManifestError, match="must be a JSON object",
        ):
            read_manifest(bad_file)


# ── verify_gitoids ───────────────────────────────────────


class TestVerifyGitoids:
    """Tests for verify_gitoids."""

    def test_verification_passes(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        manifest = read_manifest(path)
        passed, failed = verify_gitoids(manifest)
        assert len(passed) > 0
        assert len(failed) == 0

    def test_tampered_file_fails(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        manifest = read_manifest(path)

        # Tamper with a file after manifest was written
        treedb_path = sample_kwargs["artifacts"]["treedb"]
        Path(treedb_path).write_text(
            "tampered!", encoding="utf-8",
        )

        _passed, failed = verify_gitoids(manifest)
        assert treedb_path in failed

    def test_missing_file_skipped(self, sample_kwargs):
        path = write_manifest(**sample_kwargs)
        manifest = read_manifest(path)

        # Remove a file after manifest was written
        treedb_path = sample_kwargs["artifacts"]["treedb"]
        Path(treedb_path).unlink()

        passed, failed = verify_gitoids(manifest)
        assert treedb_path not in passed
        assert treedb_path not in failed

    def test_no_gitoids_key(self):
        manifest = {
            "gitoids": {},
        }
        passed, failed = verify_gitoids(manifest)
        assert passed == []
        assert failed == []


# ── _sha256_gitoid ───────────────────────────────────────


class TestSha256Gitoid:
    """Tests for gitoid computation."""

    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        g1 = _sha256_gitoid(f)
        g2 = _sha256_gitoid(f)
        assert g1 == g2

    def test_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")
        f2 = tmp_path / "b.txt"
        f2.write_text("world")
        assert _sha256_gitoid(f1) != _sha256_gitoid(f2)

    def test_hex_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        gitoid = _sha256_gitoid(f)
        assert len(gitoid) == 64
        assert all(c in "0123456789abcdef" for c in gitoid)
