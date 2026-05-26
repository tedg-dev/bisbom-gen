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
    _enrich_binaries,
    _binary_paths,
    _sha1,
    _sha256,
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

    def test_optional_omnibor_cfg(self, sample_kwargs):
        sample_kwargs["omnibor_cfg"] = {
            "strace_opts": "-f -e trace=openat",
        }
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "omnibor_cfg" in data

    def test_no_optional_fields_by_default(
        self, sample_kwargs,
    ):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        assert "repo_cfg" not in data
        assert "omnibor_cfg" not in data

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


class TestEnrichBinaries:
    """Tests for _enrich_binaries."""

    def test_enriches_existing_file(self, tmp_path):
        jar = tmp_path / "app.jar"
        jar.write_bytes(b"jar-bytes")
        result = _enrich_binaries([str(jar)])
        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, dict)
        assert entry["path"] == str(jar)
        assert len(entry["sha1"]) == 40
        assert len(entry["sha256"]) == 64

    def test_keeps_missing_file_as_string(self):
        result = _enrich_binaries(["/no/such/file.jar"])
        assert result == ["/no/such/file.jar"]

    def test_passes_through_existing_dict(self):
        entry = {"path": "/x.jar", "sha1": "a", "sha256": "b"}
        result = _enrich_binaries([entry])
        assert result == [entry]

    def test_empty_list(self):
        assert _enrich_binaries([]) == []

    def test_checksums_are_correct(self, tmp_path):
        jar = tmp_path / "test.jar"
        jar.write_bytes(b"content")
        result = _enrich_binaries([str(jar)])
        entry = result[0]
        assert entry["sha1"] == _sha1(jar)
        assert entry["sha256"] == _sha256(jar)


class TestBinaryPaths:
    """Tests for _binary_paths."""

    def test_plain_strings(self):
        paths = _binary_paths(["/a.jar", "/b.jar"])
        assert paths == ["/a.jar", "/b.jar"]

    def test_enriched_dicts(self):
        entries = [
            {"path": "/a.jar", "sha1": "x"},
            {"path": "/b.jar", "sha1": "y"},
        ]
        assert _binary_paths(entries) == ["/a.jar", "/b.jar"]

    def test_mixed(self):
        entries = [
            {"path": "/a.jar", "sha1": "x"},
            "/b.jar",
        ]
        assert _binary_paths(entries) == ["/a.jar", "/b.jar"]

    def test_empty(self):
        assert _binary_paths([]) == []


class TestManifestEnrichedRoundTrip:
    """Tests for write/read with enriched binaries."""

    def test_binaries_enriched_on_write(
        self, sample_kwargs,
    ):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        binaries = data["artifacts"]["binaries"]
        # The JAR file exists, so it should be enriched
        for entry in binaries:
            if isinstance(entry, dict):
                assert "path" in entry
                assert "sha1" in entry
                assert "sha256" in entry

    def test_enriched_manifest_reads_ok(
        self, sample_kwargs,
    ):
        path = write_manifest(**sample_kwargs)
        data = read_manifest(path)
        binaries = data["artifacts"]["binaries"]
        assert isinstance(binaries, list)
        assert len(binaries) > 0

    def test_enriched_entry_missing_path_raises(
        self, tmp_path,
    ):
        bad = tmp_path / MANIFEST_FILENAME
        data = {
            "version": MANIFEST_VERSION,
            "repo_name": "x", "language": "java",
            "mode": "sidecar", "tracer": "t",
            "run_ts": "ts", "commit_sha": None,
            "vcs_uri": "NOASSERTION",
            "artifacts": {
                "bom_dir": "/tmp/bom",
                "binaries": [{"sha1": "abc"}],
            },
            "paths": {
                "repos_dir": "/r",
                "output_dir": "/o",
                "spdx_dir": "/s",
            },
        }
        bad.write_text(json.dumps(data))
        with pytest.raises(
            ManifestError, match="missing 'path'",
        ):
            read_manifest(bad)

    def test_gitoids_work_with_enriched_binaries(
        self, sample_kwargs,
    ):
        path = write_manifest(**sample_kwargs)
        data = json.loads(path.read_text())
        # Gitoids should still be keyed by path strings
        for key in data.get("gitoids", {}):
            assert isinstance(key, str)


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
