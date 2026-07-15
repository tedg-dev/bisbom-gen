"""
Java inline-hashing capture log — reader and treedb assembler.

Design of record:
    ``docs/sidecar/java/inline-hashing-interception-design.md``
    ``docs/sidecar/java/inline-hashing-explained.md``

In sidecar mode the CI/CD build phase is **ephemeral**: the workspace is
destroyed when the build job ends, and every byte Phase 2 needs must be
captured *inside* the build job.  The ``LD_PRELOAD`` shim
(``libomnibor_java_intercept.so``) computes each artifact's git-blob
``SHA-1`` (treedb topology) and ``SHA-256`` gitoid (SBOM identity) inline,
as the build writes each ``.class``/``.jar``, and appends one event per
finalized artifact to a capture log (JSONL, one JSON object per line).

This module turns that capture log into the exact bomsh treedb structure
(``{git_blob_sha1: {"file_path": ..., "hash_tree": [...]}}``) so
``generate_adg()`` becomes an in-memory *assembly* step instead of a
post-build workspace rescan (no ``find``, no ``jar -xf``, no re-hash).

The module holds **no** bomsh global state and performs no I/O beyond the
optional source-file resolution it is explicitly handed, so every function
is unit-testable in isolation.
"""

import json

# Environment variable the shim reads for the capture-log path.  Set by
# the interception strategy (and, in production, the CI/CD YAML) — never
# hardcoded to a repo-specific location.
CAPTURE_LOG_ENV = "OMNIBOR_CAPTURE_LOG"

# Event ``kind`` discriminants written by the shim.
KIND_CLASS = "class"
KIND_JAR = "jar"


def read_capture_log(path):
    """Read a capture log into a list of event dicts.

    The log is JSONL (one JSON object per line).  Blank lines are
    skipped.  A malformed final line — which can occur if the build was
    killed mid-write — is tolerated and skipped rather than aborting the
    whole assembly; every other line must parse.

    Args:
        path: Filesystem path to the capture log.

    Returns:
        List of event dicts in file order.  Returns an empty list if the
        file does not exist.
    """
    events = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return events
    last = len(lines) - 1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            events.append(json.loads(stripped))
        except ValueError:
            # Only the final line may be a torn write; a malformed
            # interior line means the log is corrupt.
            if idx == last:
                continue
            raise
    return events


def load_hash_index(events):
    """Map absolute artifact path -> its captured hashes.

    Used both to surface SHA-256 identity for intermediates that no
    longer exist after workspace cleanup, and (optionally) to accelerate
    the legacy bomsh treedb build by serving pre-computed git-blob
    ``SHA-1`` values instead of re-reading each file.

    Args:
        events: Iterable of capture-event dicts.

    Returns:
        ``{path: {"sha1": str, "gitoid": str}}``.  Later events win on
        duplicate paths (the last finalized write is authoritative).
    """
    index = {}
    for event in events:
        path = event.get("path")
        if not path:
            continue
        index[path] = {
            "sha1": event.get("sha1", ""),
            "gitoid": event.get("gitoid", ""),
        }
    return index


def _add_entry(treedb, sha1, file_path):
    """Insert or return a treedb entry for ``sha1``.

    bomsh keys every entry by its git-blob ``SHA-1``.  Two artifacts with
    identical bytes collapse to one entry (git de-duplication); the first
    ``file_path`` seen is kept, matching bomsh's dict-insertion order.
    """
    entry = treedb.get(sha1)
    if entry is None:
        entry = {"file_path": file_path}
        treedb[sha1] = entry
    return entry


def _class_relpath(class_name):
    """Zip-entry-style relative path for a fully-qualified class name.

    ``com.example.App`` -> ``com/example/App.class``.  Inner classes keep
    their ``$`` suffix (``com.example.App$1`` -> ``com/example/App$1.class``)
    so the key matches the JAR central-directory entry name exactly.
    Returns ``None`` when the class name is empty.
    """
    if not class_name:
        return None
    return class_name.replace(".", "/") + ".class"


def assemble_treedb(events, resolve_source=None):
    """Assemble the bomsh treedb from inline capture events.

    Reproduces the structure ``bomsh_create_bom_java.py`` produces by a
    post-build rescan, using only data captured inline:

    - a ``.class`` event yields a ``{file_path, hash_tree: [src_sha1]}``
      entry; ``resolve_source`` maps the class's ``SourceFile`` attribute
      + fully-qualified name to the source ``.java`` path and its git-blob
      ``SHA-1`` (a leaf entry).  When the source cannot be resolved the
      class's ``hash_tree`` is empty (matching bomsh's behaviour for a
      class with no locatable source).
    - a ``.jar`` event yields a ``{file_path, hash_tree: [member_sha1s]}``
      entry.  A member is linked by its ``sha1`` when the shim recorded
      one, else by matching the central-directory entry ``name`` to a
      captured class's git-blob ``SHA-1`` — either way no re-hash and no
      unzip are needed (the member bytes equal the on-disk ``.class``
      bytes already captured).

    Two passes are used so JAR members resolve regardless of event order:
    classes/sources first (to build the name index), then JARs.

    Args:
        events: Iterable of capture-event dicts (see module docstring).
        resolve_source: Optional callable
            ``(source_file, class_name) -> (src_path, src_sha1)`` or
            ``None``.  Injected so the caller owns all filesystem access
            and this function stays pure/testable.  When omitted, classes
            get an empty ``hash_tree``.

    Returns:
        The treedb dict: ``{git_blob_sha1: {"file_path": str,
        "hash_tree"?: [str, ...]}}``.
    """
    events = list(events)
    treedb = {}
    class_sha_by_relpath = {}

    for event in events:
        if event.get("kind") != KIND_CLASS:
            continue
        sha1 = event.get("sha1")
        path = event.get("path")
        if not sha1 or not path:
            continue
        _assemble_class(treedb, event, sha1, path, resolve_source)
        relpath = _class_relpath(event.get("class_name", ""))
        if relpath:
            class_sha_by_relpath.setdefault(relpath, sha1)

    for event in events:
        if event.get("kind") != KIND_JAR:
            continue
        sha1 = event.get("sha1")
        path = event.get("path")
        if not sha1 or not path:
            continue
        _assemble_jar(treedb, event, sha1, path, class_sha_by_relpath)

    return treedb


def _assemble_class(treedb, event, sha1, path, resolve_source):
    """Add one ``.class`` entry (and its resolved source leaf)."""
    entry = _add_entry(treedb, sha1, path)
    hash_tree = []
    if resolve_source is not None:
        resolved = resolve_source(
            event.get("source_file", ""),
            event.get("class_name", ""),
        )
        if resolved is not None:
            src_path, src_sha1 = resolved
            if src_sha1:
                _add_entry(treedb, src_sha1, src_path)
                hash_tree.append(src_sha1)
    entry["hash_tree"] = hash_tree


def _assemble_jar(treedb, event, sha1, path, class_sha_by_relpath):
    """Add one ``.jar`` entry linking to its member classes.

    Each member is linked by its recorded ``sha1`` when present, else by
    matching its central-directory ``name`` to a captured class hash.
    """
    entry = _add_entry(treedb, sha1, path)
    members = []
    for member in event.get("entries", []):
        member_sha1 = member.get("sha1")
        if not member_sha1:
            member_sha1 = class_sha_by_relpath.get(
                member.get("name"),
            )
        if member_sha1:
            members.append(member_sha1)
    entry["hash_tree"] = members
