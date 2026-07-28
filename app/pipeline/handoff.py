"""
Phase 2 SBOM hand-off manifest writer, reader, and verifier.

The hand-off manifest (``sbom_handoff_manifest.json``) is a small,
consumer-agnostic JSON index written at the root of a Phase 2 output
run directory. It enumerates every SPDX document Phase 2 generated
(one ``build`` / ``analyzed`` pair per production artifact) and makes
the set independently verifiable via per-file digests, so any
downstream consumer can ingest it without reading the source tree,
the artifacts, or any bisbom-gen internals.

This module is deliberately **language-agnostic** (Java today,
reusable by the C/C++ flow) and **config-driven** (no hardcoded
paths). The producer-side output contract it implements is specified
in ``docs/sidecar/java/phase2-handoff-contract.md``.

Digest conventions (see the contract):

  * ``sha256`` -- plain ``SHA-256`` hex over the file bytes.
  * ``gitoid`` -- OmniBOR GitOID IRI ``gitoid:blob:sha256:<hex>``.

Artifact digests are supplied by the caller (sourced from Phase 1
metadata -- Phase 2 does not re-read the build workspace to compute
them). SBOM-file digests are computed here over the files Phase 2
just wrote. All hashing delegates to :mod:`app.spdx.identity` so
there is a single identity/digest implementation across phases.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.spdx import identity


HANDOFF_VERSION = "1.0"
HANDOFF_FILENAME = "sbom_handoff_manifest.json"

# Producer identity constants (this tool, this phase).
PRODUCER_TOOL = "bisbom-gen"
PRODUCER_PHASE = "phase2"

_REQUIRED_FIELDS = frozenset({
    "version", "generated_ts", "producer", "repo_name",
    "language", "commit_sha", "vcs_uri", "build_id", "sboms",
})
_REQUIRED_PRODUCER_FIELDS = frozenset({"tool", "phase", "mode"})
_REQUIRED_SBOM_FIELDS = frozenset({"artifact", "build", "analyzed"})
_REQUIRED_ARTIFACT_FIELDS = frozenset({"name", "sha256", "gitoid"})
_REQUIRED_FILE_FIELDS = frozenset({"path", "sha256", "gitoid"})


class HandoffError(Exception):
    """Raised when hand-off manifest construction or validation fails."""


def _relpath(target, base_dir):
    """Return ``target`` as a path relative to ``base_dir``."""
    return os.path.relpath(str(target), str(base_dir))


def _file_record(file_path, manifest_dir):
    """Build a ``{path, sha256, gitoid}`` record for an SBOM file.

    The file must exist -- an offline enterprise run that produced no
    SBOM must fail loudly rather than emit an unverifiable manifest.
    """
    p = Path(file_path)
    if not p.is_file():
        raise HandoffError(
            f"SBOM file not found (cannot compute digest): {p}"
        )
    return {
        "path": _relpath(p, manifest_dir),
        "sha256": identity.raw_hash(p),
        "gitoid": identity.gitoid(p),
    }


def _validate_artifact(artifact):
    """Validate a caller-supplied ``artifact`` record."""
    if not isinstance(artifact, dict):
        raise HandoffError("sboms[].artifact must be a dict")
    missing = _REQUIRED_ARTIFACT_FIELDS - set(artifact.keys())
    if missing:
        raise HandoffError(
            f"artifact missing required fields: "
            f"{', '.join(sorted(missing))}"
        )
    return {
        "name": artifact["name"],
        "sha256": artifact["sha256"],
        "gitoid": artifact["gitoid"],
    }


def _build_sbom_entry(entry, manifest_dir):
    """Build one validated ``sboms[]`` entry from a caller spec.

    Expected input spec::

        {
          "artifact": {"name", "sha256", "gitoid"},  # from Phase 1
          "build": <path to *_build.spdx.json>,
          "analyzed": <path to *_analyzed.spdx.json>,
        }
    """
    if not isinstance(entry, dict):
        raise HandoffError("each sboms[] entry must be a dict")
    missing = _REQUIRED_SBOM_FIELDS - set(entry.keys())
    if missing:
        raise HandoffError(
            f"sboms[] entry missing required fields: "
            f"{', '.join(sorted(missing))}"
        )
    return {
        "artifact": _validate_artifact(entry["artifact"]),
        "build": _file_record(entry["build"], manifest_dir),
        "analyzed": _file_record(entry["analyzed"], manifest_dir),
    }


def write_handoff_manifest(
    manifest_dir,
    *,
    repo_name,
    language,
    mode,
    commit_sha,
    vcs_uri,
    build_id,
    sboms,
    source_manifest=None,
    generated_ts=None,
):
    """Write ``sbom_handoff_manifest.json`` for a Phase 2 output run.

    Args:
        manifest_dir: Run directory; the manifest is written here and
            all SBOM paths are recorded relative to it.
        repo_name: Repository name.
        language: Language string (e.g. ``"java"``).
        mode: Execution mode (``"sidecar"`` or ``"standalone"``).
        commit_sha: Source commit SHA.
        vcs_uri: VCS location the source was obtained from.
        build_id: Config-driven build / release identifier.
        sboms: Iterable of entry specs, each with an ``artifact``
            record (``name``/``sha256``/``gitoid`` from Phase 1) and
            ``build`` / ``analyzed`` SBOM file paths.
        source_manifest: Optional relative path to the
            ``phase1_manifest.json`` this run consumed.
        generated_ts: Optional ISO-8601 UTC timestamp; defaults to now.

    Returns:
        Path to the written manifest file.

    Raises:
        HandoffError: If ``sboms`` is empty or any entry is invalid or
            references a missing SBOM file.
    """
    manifest_dir = Path(manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    entries = [_build_sbom_entry(e, manifest_dir) for e in sboms]
    if not entries:
        raise HandoffError("no SBOMs to record in hand-off manifest")

    if generated_ts is None:
        generated_ts = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    data = {
        "version": HANDOFF_VERSION,
        "generated_ts": generated_ts,
        "producer": {
            "tool": PRODUCER_TOOL,
            "phase": PRODUCER_PHASE,
            "mode": mode,
        },
        "repo_name": repo_name,
        "language": language,
        "commit_sha": commit_sha,
        "vcs_uri": vcs_uri,
        "build_id": build_id,
        "sboms": entries,
    }
    if source_manifest is not None:
        data["source_manifest"] = source_manifest

    manifest_path = manifest_dir / HANDOFF_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
    return manifest_path


def read_handoff_manifest(manifest_path):
    """Read and validate a ``sbom_handoff_manifest.json``.

    Args:
        manifest_path: Path to the manifest file.

    Returns:
        Parsed manifest dict.

    Raises:
        FileNotFoundError: If the manifest file does not exist.
        HandoffError: If the file is malformed or fails validation.
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Hand-off manifest not found: {manifest_path}"
        )
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise HandoffError(
            f"Malformed JSON in hand-off manifest: {e}"
        ) from e

    _validate_manifest(data)
    return data


def verify_handoff_manifest(manifest, base_dir):
    """Verify every SBOM file digest recorded in a loaded manifest.

    Args:
        manifest: Parsed manifest dict (from read_handoff_manifest).
        base_dir: Directory the manifest's relative paths resolve
            against (normally the manifest's own directory).

    Returns:
        Tuple ``(passed, failed)`` of relative SBOM paths. A path whose
        file is missing is reported as failed.
    """
    base_dir = Path(base_dir)
    passed = []
    failed = []
    for entry in manifest.get("sboms", []):
        for role in ("build", "analyzed"):
            record = entry.get(role, {})
            rel = record.get("path")
            if rel is None:
                continue
            fp = base_dir / rel
            if not fp.is_file() or (
                identity.raw_hash(fp) != record.get("sha256")
            ):
                failed.append(rel)
            else:
                passed.append(rel)
    return passed, failed


def _validate_manifest(data):
    """Validate a parsed hand-off manifest dict."""
    if not isinstance(data, dict):
        raise HandoffError("Hand-off manifest must be a JSON object")

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise HandoffError(
            f"Missing required fields: {', '.join(sorted(missing))}"
        )
    if data.get("version") != HANDOFF_VERSION:
        raise HandoffError(
            f"Unsupported hand-off manifest version: "
            f"{data.get('version')} (expected {HANDOFF_VERSION})"
        )

    producer = data["producer"]
    if not isinstance(producer, dict):
        raise HandoffError("producer must be a dict")
    prod_missing = _REQUIRED_PRODUCER_FIELDS - set(producer.keys())
    if prod_missing:
        raise HandoffError(
            f"producer missing required fields: "
            f"{', '.join(sorted(prod_missing))}"
        )

    sboms = data["sboms"]
    if not isinstance(sboms, list) or not sboms:
        raise HandoffError("sboms must be a non-empty list")
    for entry in sboms:
        _validate_sbom_entry(entry)


def _validate_sbom_entry(entry):
    """Validate one ``sboms[]`` entry from a loaded manifest."""
    if not isinstance(entry, dict):
        raise HandoffError("each sboms[] entry must be a dict")
    missing = _REQUIRED_SBOM_FIELDS - set(entry.keys())
    if missing:
        raise HandoffError(
            f"sboms[] entry missing required fields: "
            f"{', '.join(sorted(missing))}"
        )
    art_missing = _REQUIRED_ARTIFACT_FIELDS - set(entry["artifact"])
    if art_missing:
        raise HandoffError(
            f"artifact missing required fields: "
            f"{', '.join(sorted(art_missing))}"
        )
    for role in ("build", "analyzed"):
        rec = entry[role]
        if not isinstance(rec, dict):
            raise HandoffError(f"sboms[].{role} must be a dict")
        file_missing = _REQUIRED_FILE_FIELDS - set(rec.keys())
        if file_missing:
            raise HandoffError(
                f"sboms[].{role} missing required fields: "
                f"{', '.join(sorted(file_missing))}"
            )
