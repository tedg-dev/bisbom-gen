"""
Artifact identity layer (OmniBOR core).

Design of record: ``.windsurf/rules/project/artifact-identity.md``.

For any artifact -- a leaf source file, an intermediate object
(``.o`` / ``.class``), or a built package (executable, shared
library, JAR, wheel, module) -- this module computes its two
distinct SHA-256 identity values:

  * **raw hash**       -- ``SHA-256`` of the raw file bytes.
  * **artifact gitOID** -- ``gitoid:blob:sha256`` (git-blob
    framing + ``SHA-256``).

These are different values, not two encodings of one: the gitOID
hashes ``"blob <len>\\0" + content`` while the raw hash hashes the
content alone.

The computation is language-agnostic and parameterized by hash
algorithm (default ``sha256``), mirroring OmniBOR's own
``HashAlgorithm`` design so a future migration is a config change,
not a rewrite.

bomsh's ``SHA-1`` treedb is used only to capture graph *topology*
(which inputs feed which output).  *Identity* is computed here by
reading each artifact and is never surfaced from bomsh's ``SHA-1``
values.  See the topology-vs-identity split in the design of record.

Note: the OmniBOR Input Manifest gitOID (OMID) -- the third
identity value, for built packages only -- is intentionally not
computed here yet.  Per the design of record it must be produced
canonically per the OmniBOR spec and validated against a reference
library; that is a distinct follow-up.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ALGO = "sha256"

# Git object type used for OmniBOR artifact IDs.
_GIT_OBJECT_TYPE = "blob"

# Filename of the Phase-1 identity index (raw SHA-256 + gitOID per
# artifact path).  Written next to the bomsh treedb so an offline
# Phase 2 can surface identity for intermediates (.class / .o) that
# no longer exist on disk after workspace cleanup.
IDENTITY_INDEX_FILENAME = "bomsh_identity_index.json"


def raw_hash(path, algo=DEFAULT_ALGO):
    """Return the raw hex digest of a file's bytes.

    No git framing -- this is what ``sha256sum`` would produce, so
    it belongs in an SPDX ``checksums`` entry.
    """
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gitoid_hex(path, algo=DEFAULT_ALGO):
    """Return the bare git-blob gitOID hex of a file.

    ``gitOID = <algo>("blob " + <byte-length> + "\\0" + <content>)``.
    """
    content = Path(path).read_bytes()
    return _gitoid_hex_of_bytes(content, algo)


def _gitoid_hex_of_bytes(content, algo=DEFAULT_ALGO):
    """Return the git-blob gitOID hex for an in-memory byte string."""
    header = f"{_GIT_OBJECT_TYPE} {len(content)}\0".encode("ascii")
    h = hashlib.new(algo)
    h.update(header)
    h.update(content)
    return h.hexdigest()


def gitoid(path, algo=DEFAULT_ALGO):
    """Return the canonical OmniBOR gitOID IRI for a file.

    Form: ``gitoid:blob:<algo>:<hex>``.
    """
    return _iri(gitoid_hex(path, algo), algo)


def _iri(hex_digest, algo=DEFAULT_ALGO):
    """Assemble a ``gitoid:blob:<algo>:<hex>`` IRI."""
    return f"gitoid:{_GIT_OBJECT_TYPE}:{algo}:{hex_digest}"


@dataclass(frozen=True)
class ArtifactIdentity:
    """The version-agnostic identity of a single artifact.

    Attributes:
        path:   absolute path the identity was computed from.
        algo:   hash algorithm used (e.g. ``"sha256"``).
        raw:    raw hex digest of the file bytes (for
                SPDX ``checksums``).
        gitoid: canonical ``gitoid:blob:<algo>:<hex>`` IRI (the
                artifact's own OmniBOR Artifact ID).
    """

    path: str
    algo: str
    raw: str
    gitoid: str

    @property
    def gitoid_hex(self):
        """Return the bare hex of the gitOID (IRI suffix)."""
        return self.gitoid.rsplit(":", 1)[-1]

    @property
    def checksum_algorithm(self):
        """Return the SPDX ``checksums`` algorithm label.

        SPDX uppercases hash names (``sha256`` -> ``SHA256``).
        """
        return self.algo.upper()

    def as_spdx_checksum(self):
        """Return an SPDX 2.3 ``checksums`` entry for the raw hash."""
        return {
            "algorithm": self.checksum_algorithm,
            "checksumValue": self.raw,
        }

    def as_spdx_gitoid_ref(self):
        """Return an SPDX 2.3 ``externalRefs`` gitoid entry."""
        return {
            "referenceCategory": "PERSISTENT-ID",
            "referenceType": "gitoid",
            "referenceLocator": self.gitoid,
        }

    @classmethod
    def from_file(cls, path, algo=DEFAULT_ALGO):
        """Compute identity by reading ``path`` exactly once."""
        p = str(path)
        content = Path(p).read_bytes()
        raw = hashlib.new(algo, content).hexdigest()
        goid_hex = _gitoid_hex_of_bytes(content, algo)
        return cls(
            path=p,
            algo=algo,
            raw=raw,
            gitoid=_iri(goid_hex, algo),
        )


def try_from_file(path, algo=DEFAULT_ALGO):
    """Return :class:`ArtifactIdentity` or ``None`` if unreadable.

    Offline Phase 2 may run after the build workspace is gone; in
    that case the artifact cannot be read and identity is unknown.
    Callers should treat ``None`` as "identity unavailable" rather
    than emitting a wrong value.
    """
    try:
        return ArtifactIdentity.from_file(path, algo)
    except (OSError, ValueError):
        return None


# SPDX 2.3 mandates exactly one SHA-1 checksum per ``File`` (Clause
# 8.4, Table 39: cardinality ``1..1`` for SHA1, ``0..*`` for other
# algorithms).  This is a legacy corruption-detection checksum, NOT
# an identity value -- artifact identity remains SHA-256 (raw +
# gitOID) per the design of record.  SPDX 3.0.1 removes this mandate
# (``verifiedUsing`` accepts ``sha256`` alone), so the 3.x emitter
# reuses the SHA-256 raw hash directly and skips this helper.
SPDX_2_3_FILE_LEGACY_ALGO = "sha1"


def spdx_2_3_file_checksums(path, algo=DEFAULT_ALGO):
    """Return the SPDX 2.3 ``File.checksums`` list for ``path``.

    SPDX 2.3 requires every ``File`` to carry a raw ``SHA-1``
    checksum (spec conformance only -- see
    ``SPDX_2_3_FILE_LEGACY_ALGO``).  This helper reads the file
    once and returns both the mandated raw ``SHA-1`` entry and the
    raw identity-hash entry (``SHA-256`` by default), in spec order.

    The ``SHA-1`` here is the plain hash of the file bytes (what
    ``sha1sum`` produces), never a git-blob value and never an
    identity claim.  When ``algo`` is already ``sha1`` (unusual),
    only a single ``SHA-1`` entry is returned to avoid duplication.

    Returns an empty list if the file cannot be read, so an offline
    Phase 2 emits a ``File`` with no checksums rather than a wrong
    one; callers decide how to surface that gap.
    """
    try:
        content = Path(path).read_bytes()
    except OSError:
        return []
    checksums = []
    if algo != SPDX_2_3_FILE_LEGACY_ALGO:
        checksums.append({
            "algorithm": SPDX_2_3_FILE_LEGACY_ALGO.upper(),
            "checksumValue": hashlib.new(
                SPDX_2_3_FILE_LEGACY_ALGO, content
            ).hexdigest(),
        })
    checksums.append({
        "algorithm": algo.upper(),
        "checksumValue": hashlib.new(algo, content).hexdigest(),
    })
    return checksums


def write_identity_index(paths, out_path, algo=DEFAULT_ALGO):
    """Persist identities for ``paths`` to a JSON index.

    Written during Phase 1 (while intermediates still exist) so an
    offline Phase 2 can surface identity for files that no longer
    exist on the analysis host.  Files that cannot be read are
    skipped.

    Args:
        paths:    iterable of absolute file paths.
        out_path: destination JSON file.
        algo:     hash algorithm (default ``sha256``).

    Returns:
        Number of artifacts written to the index.
    """
    import json

    index = {}
    for path in paths:
        ident = try_from_file(path, algo)
        if ident is None:
            continue
        index[ident.path] = {
            "algo": ident.algo,
            "raw": ident.raw,
            "gitoid": ident.gitoid,
        }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(index, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return len(index)
