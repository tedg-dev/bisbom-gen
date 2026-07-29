"""
Java inline-hashing capture log — reader and treedb assembler.

Design of record:
    ``docs/sidecar/java/reference/inline-hashing-interception-design.md``
    ``docs/sidecar/java/reference/inline-hashing-explained.md``

In sidecar mode the CI/CD build phase is **ephemeral**: the workspace is
destroyed when the build job ends, and every byte Phase 2 needs must be
captured *inside* the build job.  The ``LD_PRELOAD`` shim
(``libbisbom_java_intercept.so``) computes each artifact's git-blob
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
import re

# Environment variable the shim reads for the capture-log path.  Set by
# the interception strategy (and, in production, the CI/CD YAML) — never
# hardcoded to a repo-specific location.
CAPTURE_LOG_ENV = "BISBOM_CAPTURE_LOG"

# Event ``kind`` discriminants written by the shim.
KIND_CLASS = "class"
KIND_JAR = "jar"

# A ``.class`` physically located under a ``META-INF/versions/<N>/``
# segment is a Multi-Release JAR *packaging copy* (JEP 238), not a
# compiler-output/source location: the build copies an already-compiled
# versioned class into this staging path during JAR assembly.  Its
# filesystem path therefore must never be used to attribute source
# provenance (its directory tree sits under a different module than the
# source that produced it).  Matched to prefer the primary
# compiler-output path when the same content is captured at both.
_MRJAR_VERSION_RE = re.compile(r"/META-INF/versions/\d+/")


def _is_versioned_staging_path(path):
    """True if *path* is a Multi-Release JAR ``META-INF/versions/<N>/`` copy."""
    return bool(_MRJAR_VERSION_RE.search(path))


def _prefer_canonical(new_path, cur_path):
    """True if *new_path* should replace *cur_path* as a content's canonical.

    A non-staging (primary compiler-output) path always beats a
    ``META-INF/versions/<N>/`` staging copy; among paths of equal
    staging-ness the lexicographically-smallest wins, matching the legacy
    rescan's sorted-first content match and keeping the choice independent
    of capture order.
    """
    new_staging = _is_versioned_staging_path(new_path)
    cur_staging = _is_versioned_staging_path(cur_path)
    if new_staging != cur_staging:
        return cur_staging
    return new_path < cur_path


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
      + the class's own write path to the source ``.java`` path (by path
      similarity) and its git-blob ``SHA-1`` (a leaf entry).  When the
      source cannot be resolved the class's ``hash_tree`` is empty
      (matching bomsh's behaviour for a class with no locatable source).
    - a ``.jar`` event yields a ``{file_path, hash_tree: [member_sha1s]}``
      entry.  Each ``.class`` member carries its own git-blob ``SHA-1``
      (computed by the shim from the member's *uncompressed* bytes), so a
      member is linked purely **by content** — exactly how the legacy
      rescan correlates an extracted member to a workspace class
      (basename + byte-identical).  This is correct for every JAR layout:

      * ordinary (root) members whose bytes match a captured class;
      * Multi-Release members (``META-INF/versions/<N>/...``) whose bytes
        match a captured version-specific class, regardless of where that
        class was written on disk (Maven in-tree ``META-INF/versions`` or
        Gradle separate source-set output);
      * base/versioned pairs that share a fully-qualified name but differ
        in bytes — each member binds to its own variant by content;
      * members the build *rewrote* while packaging (e.g. a transformed
        ``module-info.class``) whose bytes match no captured class — these
        are dropped, matching the rescan (which finds no workspace file
        with identical content and excludes them from the SBOM).

    A member without a recorded ``sha1`` (legacy capture logs) falls back
    to name correlation against the class fully-qualified name.

    Two passes are used so JAR members resolve regardless of event order:
    classes/sources first (to key the treedb by content ``SHA-1`` and
    build the legacy name index), then JARs.

    Args:
        events: Iterable of capture-event dicts (see module docstring).
        resolve_source: Optional callable
            ``(source_file, class_path) -> (src_path, src_sha1)`` or
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

    class_events = [
        e for e in events
        if e.get("kind") == KIND_CLASS and e.get("sha1") and e.get("path")
    ]

    # Choose one canonical event per content ``SHA-1`` to own the treedb
    # entry's ``file_path`` and source resolution.  Identical bytes may be
    # captured at more than one path — most notably a class compiled once
    # into its module's output tree and then copied into a Multi-Release
    # JAR ``META-INF/versions/<N>/`` staging directory, or the same class
    # (e.g. a shared ``package-info``) compiled identically in sibling
    # modules.  A primary compiler-output path always wins over a staging
    # copy so source attribution reflects the class's true origin; among
    # otherwise-equal paths the lexicographically-smallest wins, matching
    # the legacy rescan (which scans a sorted file list and keeps the first
    # content match) — both are independent of capture order.
    canonical = {}
    for event in class_events:
        sha1 = event["sha1"]
        chosen = canonical.get(sha1)
        if chosen is None or _prefer_canonical(event["path"], chosen["path"]):
            canonical[sha1] = event

    # Pass 1 — create every class entry (``file_path`` only; source
    # resolution is deferred to pass 3).
    for sha1, event in canonical.items():
        _add_entry(treedb, sha1, event["path"])

    for event in class_events:
        relpath = _class_relpath(event.get("class_name", ""))
        if relpath:
            class_sha_by_relpath.setdefault(relpath, event["sha1"])

    # Pass 2 — link every JAR to its member classes by content, recording
    # which class ``SHA-1``s are actually members of some analyzed JAR.
    member_shas = set()
    for event in events:
        if event.get("kind") != KIND_JAR:
            continue
        sha1 = event.get("sha1")
        path = event.get("path")
        if not sha1 or not path:
            continue
        member_shas |= _assemble_jar(
            treedb, event, sha1, path, class_sha_by_relpath,
        )

    # Pass 3 — resolve each class's source leaf, JAR members first.  When
    # two classes compile from byte-identical source (the same source file
    # duplicated across sibling modules — e.g. a base module and its
    # Multi-Release companion), both resolve to one content-addressed leaf
    # whose ``file_path`` is kept from whichever class is resolved first.
    # Resolving members before non-members guarantees a shipped (JAR
    # member) class owns that path, exactly as bomsh — which only ever
    # walks JAR members — does, instead of a compiled-but-unshipped
    # sibling seeding it.
    ordered = [s for s in canonical if s in member_shas]
    ordered += [s for s in canonical if s not in member_shas]
    for sha1 in ordered:
        _resolve_class_source(
            treedb, canonical[sha1], sha1, resolve_source,
        )

    return treedb


def _resolve_class_source(treedb, event, sha1, resolve_source):
    """Attach a class entry's resolved source leaf to its ``hash_tree``."""
    entry = treedb[sha1]
    hash_tree = []
    if resolve_source is not None:
        resolved = resolve_source(
            event.get("source_file", ""),
            event["path"],
        )
        if resolved is not None:
            src_path, src_sha1 = resolved
            if src_sha1:
                _add_entry(treedb, src_sha1, src_path)
                hash_tree.append(src_sha1)
    entry["hash_tree"] = hash_tree


def _assemble_jar(treedb, event, sha1, path, class_sha_by_relpath):
    """Add one ``.jar`` entry linking to its member classes by content.

    Correlation is by the member's git-blob ``SHA-1`` (recorded by the
    shim from the member's uncompressed bytes), matching the legacy
    rescan's basename+content match:

    - a member whose ``sha1`` keys a captured class is linked to it;
    - a member whose ``sha1`` matches no captured class (e.g. a
      build-rewritten ``module-info.class``) is dropped, as the rescan
      finds no workspace file with identical content;
    - a member lacking a recorded ``sha1`` (legacy logs) falls back to
      matching its central-directory ``name`` to a captured class's
      fully-qualified name.

    Returns the set of member class ``SHA-1``s linked, so the caller can
    resolve JAR-member source leaves ahead of non-member ones.
    """
    entry = _add_entry(treedb, sha1, path)
    members = []
    for member in event.get("entries", []):
        member_sha1 = member.get("sha1")
        if member_sha1:
            if member_sha1 in treedb:
                members.append(member_sha1)
            continue
        name_sha1 = class_sha_by_relpath.get(member.get("name"))
        if name_sha1:
            members.append(name_sha1)
    entry["hash_tree"] = members
    return set(members)
