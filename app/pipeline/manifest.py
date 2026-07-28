"""
Phase 1 manifest writer and reader.

The manifest is a small JSON pointer file (~1-2 KB) that records
paths to Phase 1 artifacts (treedb, raw logfile, binaries, bom_dir)
plus metadata (repo name, language, commit SHA, run timestamp).

Purpose: Sidecar Phase 1 only mode — when Phase 2 runs in a
different process or host, it reads the manifest to locate
artifacts without needing config.yaml or the source tree.

Standalone and Sidecar full modes do not use the manifest.
"""

import hashlib
import json
from pathlib import Path

from app.spdx import identity


def _sha1(file_path):
    """Compute plain SHA-1 hex digest for a file."""
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256(file_path):
    """Compute plain SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


MANIFEST_VERSION = "1.0"
MANIFEST_FILENAME = "phase1_manifest.json"

# Fields required in every manifest
_REQUIRED_FIELDS = frozenset({
    "version", "repo_name", "language", "mode", "tracer",
    "run_ts", "commit_sha", "vcs_uri",
    "artifacts", "paths",
})

# Fields required in the artifacts sub-object
_REQUIRED_ARTIFACT_FIELDS = frozenset({
    "bom_dir", "binaries",
})

# Fields required in the paths sub-object
_REQUIRED_PATH_FIELDS = frozenset({
    "repos_dir", "output_dir", "spdx_dir",
})


class ManifestError(Exception):
    """Raised when manifest validation fails."""


def write_manifest(
    manifest_dir,
    repo_name,
    language,
    mode,
    tracer,
    run_ts,
    commit_sha,
    vcs_uri,
    artifacts,
    paths,
    repo_cfg=None,
    omnibor_cfg=None,
):
    """Write phase1_manifest.json after Phase 1 completes.

    Args:
        manifest_dir: Directory to write the manifest into.
        repo_name: Repository name (e.g. ``"jsoup"``).
        language: Language string (e.g. ``"java"``).
        mode: Execution mode (``"standalone"`` or ``"sidecar"``).
        tracer: Interception method used.
        run_ts: Run timestamp string.
        commit_sha: Git commit SHA or None.
        vcs_uri: VCS download location URI.
        artifacts: Dict with artifact paths — must contain
            ``bom_dir`` (str) and ``binaries`` (list of str).
            May also contain ``treedb``, ``raw_logfile``,
            ``strace_log``, ``dep_tree_json``.
        paths: Dict with ``repos_dir``, ``output_dir``,
            ``spdx_dir``.
        repo_cfg: Optional subset of repo config needed by
            Phase 2 (output_binaries, vendored_dirs, etc.).
        omnibor_cfg: Optional resolved omnibor config section.

    Returns:
        Path to the written manifest file.

    Raises:
        ManifestError: If required fields are missing.
    """
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    _validate_artifacts(artifacts)
    _validate_paths(paths)

    data = {
        "version": MANIFEST_VERSION,
        "repo_name": repo_name,
        "language": language,
        "mode": mode,
        "tracer": tracer,
        "run_ts": run_ts,
        "commit_sha": commit_sha,
        "vcs_uri": vcs_uri,
        "artifacts": artifacts,
        "paths": paths,
    }

    if repo_cfg is not None:
        data["repo_cfg"] = repo_cfg
    if omnibor_cfg is not None:
        data["omnibor_cfg"] = omnibor_cfg

    # Compute gitoids for artifact files that exist
    data["gitoids"] = _compute_gitoids(artifacts)

    # Enrich binaries with checksums for SPDX correlation
    data["artifacts"]["binaries"] = _enrich_binaries(
        artifacts.get("binaries", []),
    )

    manifest_path = manifest_dir / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)

    return manifest_path


def read_manifest(manifest_path):
    """Read and validate a phase1_manifest.json.

    Args:
        manifest_path: Path to the manifest file.

    Returns:
        Parsed manifest dict.

    Raises:
        ManifestError: If the file is missing, malformed,
            or fails validation.
        FileNotFoundError: If the manifest file does not exist.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: {manifest_path}"
        )

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ManifestError(
            f"Malformed JSON in manifest: {e}"
        ) from e

    _validate_manifest(data)
    return data


def verify_gitoids(manifest):
    """Verify artifact gitoids from a loaded manifest.

    Args:
        manifest: Parsed manifest dict (from read_manifest).

    Returns:
        Tuple of (passed, failed) where each is a list of
        artifact paths. Files that don't exist are skipped.
    """
    gitoids = manifest.get("gitoids", {})
    passed = []
    failed = []

    for artifact_path, expected_gitoid in gitoids.items():
        p = Path(artifact_path)
        if not p.exists():
            continue
        actual = _sha256_gitoid(p)
        if actual == expected_gitoid:
            passed.append(artifact_path)
        else:
            failed.append(artifact_path)

    return passed, failed


def _validate_manifest(data):
    """Validate a parsed manifest dict."""
    if not isinstance(data, dict):
        raise ManifestError("Manifest must be a JSON object")

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ManifestError(
            f"Missing required fields: "
            f"{', '.join(sorted(missing))}"
        )

    if data.get("version") != MANIFEST_VERSION:
        raise ManifestError(
            f"Unsupported manifest version: "
            f"{data.get('version')} "
            f"(expected {MANIFEST_VERSION})"
        )

    _validate_artifacts(data["artifacts"])
    _validate_paths(data["paths"])


def _validate_artifacts(artifacts):
    """Validate the artifacts sub-object."""
    if not isinstance(artifacts, dict):
        raise ManifestError(
            "artifacts must be a dict"
        )
    missing = _REQUIRED_ARTIFACT_FIELDS - set(
        artifacts.keys()
    )
    if missing:
        raise ManifestError(
            f"Missing required artifact fields: "
            f"{', '.join(sorted(missing))}"
        )
    binaries = artifacts.get("binaries")
    if not isinstance(binaries, list):
        raise ManifestError(
            "artifacts.binaries must be a list"
        )
    # Validate enriched format entries
    for item in binaries:
        if isinstance(item, dict) and "path" not in item:
            raise ManifestError(
                "enriched binary entry missing 'path'"
            )


def _validate_paths(paths):
    """Validate the paths sub-object."""
    if not isinstance(paths, dict):
        raise ManifestError("paths must be a dict")
    missing = _REQUIRED_PATH_FIELDS - set(paths.keys())
    if missing:
        raise ManifestError(
            f"Missing required path fields: "
            f"{', '.join(sorted(missing))}"
        )


def _enrich_binaries(binaries):
    """Enrich binary paths with checksums.

    Converts plain path strings to dicts with:
      - path: original file path
      - sha1: plain SHA-1 hex digest
      - sha256: plain SHA-256 hex digest

    Files that don't exist are kept as-is (string).
    """
    enriched = []
    for item in binaries:
        if isinstance(item, dict):
            enriched.append(item)
            continue
        p = Path(item)
        if p.is_file():
            enriched.append({
                "path": item,
                "sha1": _sha1(p),
                "sha256": _sha256(p),
            })
        else:
            enriched.append(item)
    return enriched


def _binary_paths(binaries):
    """Extract path strings from binaries list.

    Handles both old format (plain strings) and
    new format (dicts with 'path' key).
    """
    paths = []
    for item in binaries:
        if isinstance(item, dict):
            paths.append(item["path"])
        elif isinstance(item, str):
            paths.append(item)
    return paths


def _compute_gitoids(artifacts):
    """Compute SHA-256 gitoids for artifact files.

    Only computes for files that exist. Directories and
    missing files are skipped.
    """
    gitoids = {}
    # Collect all string-valued artifact paths
    for key, value in artifacts.items():
        if isinstance(value, str) and key != "bom_dir":
            p = Path(value)
            if p.is_file():
                gitoids[value] = _sha256_gitoid(p)
        elif isinstance(value, list):
            for item in value:
                # Handle both plain strings and enriched
                # dicts (with 'path' key)
                item_path = (
                    item.get("path") if isinstance(item, dict)
                    else item if isinstance(item, str)
                    else None
                )
                if item_path:
                    p = Path(item_path)
                    if p.is_file():
                        gitoids[item_path] = (
                            _sha256_gitoid(p)
                        )
    return gitoids


def _sha256_gitoid(file_path):
    """Compute the bare git-blob SHA-256 gitoid hex for a file.

    Delegates to :mod:`app.spdx.identity` so a single git-blob /
    SHA-256 implementation is shared across Phase 1 and Phase 2.
    Returns bare hex (the Phase 1 manifest stores gitoids without
    the ``gitoid:blob:sha256:`` IRI prefix).
    """
    return identity.gitoid_hex(file_path)
