#!/usr/bin/env python3
"""Pure-Python fast-IO replacements for bomsh_create_bom_java.py.

The upstream bomsh JAR processor shells out to external commands for
operations that have trivial, faster pure-Python equivalents. For a JAR
with N ``.class`` files this spawns ~3N subprocesses (two
``git hash-object`` + one ``diff -q`` per file) plus ``find`` and
``jar -xf`` per JAR. This module provides drop-in replacements that
eliminate those subprocess spawns.

Functions here are intentionally free of any bomsh global state so they
can be unit-tested in isolation (mirrors bomsh_java_fast_classreader.py).
``apply_fast_io.py`` monkey-patches the upstream script to call them.

Replacements provided:

- ``git_blob_hash``        -> replaces ``git hash-object`` (SHA-1 blob id)
- ``git_blob_hash_data``   -> in-memory blob id (for future in-memory JAR
                              processing; see project memory / deep-dive)
- ``build_hash_cache``     -> parallel pre-hash pass populating the memo
                              cache used by ``git_blob_hash``
- ``files_have_same_content`` -> replaces ``diff -q``
- ``find_suffix_files``    -> replaces ``find -type f -name '*<suffix>'``
                              (deterministic, sorted output)
- ``safe_extract_jar``     -> replaces ``jar -xf`` (with Zip-Slip guard)
- ``is_zip_file``          -> replaces ``file`` archive-type detection
"""
import filecmp
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor

__all__ = [
    "git_blob_hash",
    "git_blob_hash_data",
    "build_hash_cache",
    "clear_cache",
    "files_have_same_content",
    "find_suffix_files",
    "safe_extract_jar",
    "is_zip_file",
    "iter_jar_class_entries",
    "bytes_same_as_file",
    "find_matching_class",
]

# Read files in 1 MiB chunks so large JARs do not load fully into memory.
_CHUNK_SIZE = 1 << 20

# Memoization cache: {(abspath, size, mtime_ns): sha1_hex}. The upstream
# script hashes the same file more than once (e.g. a class file in both
# process_class_file and process_jar_file), so memoizing avoids redundant
# work. Keyed by (path, size, mtime) so a changed file is never served a
# stale digest. A cache miss only costs a recompute, never correctness.
_HASH_CACHE = {}


def clear_cache():
    """Empty the hash memoization cache (used for test isolation)."""
    _HASH_CACHE.clear()


def _stat_key(path):
    """Return ((abspath, size, mtime_ns), size) for ``path``.

    Raises OSError if the path cannot be stat-ed.
    """
    st = os.stat(path)
    return (os.path.abspath(path), st.st_size, st.st_mtime_ns), st.st_size


def _hash_blob_stream(path, size):
    """Compute the git blob SHA-1 of ``path`` by streaming its bytes.

    The git object id of a blob is ``SHA-1("blob " + size + "\\0" + data)``.
    """
    sha = hashlib.sha1()
    sha.update(b"blob %d\0" % size)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            sha.update(chunk)
    return sha.hexdigest()


def git_blob_hash(path):
    """Return the git blob hash of a file (replaces ``git hash-object``).

    Returns an empty string on any I/O error, matching the upstream
    ``git hash-object <file> || true`` behaviour. Results are memoized.
    """
    try:
        key, size = _stat_key(path)
    except OSError:
        return ""
    cached = _HASH_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        digest = _hash_blob_stream(path, size)
    except OSError:
        return ""
    _HASH_CACHE[key] = digest
    return digest


def git_blob_hash_data(data):
    """Return the git blob hash of an in-memory ``bytes`` object.

    Enables hashing class bytes read directly from a JAR without writing
    them to disk (reserved for the deferred in-memory JAR optimization).
    """
    sha = hashlib.sha1()
    sha.update(b"blob %d\0" % len(data))
    sha.update(data)
    return sha.hexdigest()


def _hash_for_cache(path):
    """Worker for build_hash_cache: compute (key, digest) off-thread.

    Returns None when the file is missing, unreadable, or already cached.
    Never mutates the shared cache (that happens on the main thread).
    """
    try:
        key, size = _stat_key(path)
    except OSError:
        return None
    if key in _HASH_CACHE:
        return None
    try:
        return key, _hash_blob_stream(path, size)
    except OSError:
        return None


def build_hash_cache(paths, max_workers=None):
    """Pre-hash ``paths`` in parallel and populate the memo cache.

    Hashing of each file is independent and releases the GIL during file
    I/O, so a thread pool yields real speedup. Results are merged into the
    shared cache on the calling thread only, so there is no data race.

    :returns: number of newly cached entries.
    """
    if not paths:
        return 0
    unique = list(dict.fromkeys(paths))
    count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for result in pool.map(_hash_for_cache, unique):
            if result is not None:
                key, digest = result
                _HASH_CACHE[key] = digest
                count += 1
    return count


def files_have_same_content(afile, bfile):
    """Return True if two files have identical content (replaces ``diff -q``).

    ``filecmp.cmp(shallow=False)`` does a byte-for-byte comparison and
    short-circuits on a size mismatch. Returns False if either file is
    missing or unreadable (more correct than the upstream
    ``diff -q ... || true``, which reports missing files as identical).
    """
    try:
        return filecmp.cmp(afile, bfile, shallow=False)
    except OSError:
        return False


def find_suffix_files(builddir, suffix):
    """Find regular files ending with ``suffix`` under ``builddir``.

    Replaces ``find <builddir> -type f -name '*<suffix>'``. Symlinks are
    excluded (matching ``find -type f``) and symlinked directories are not
    followed. Output is sorted for deterministic, reproducible results
    (the shell ``find`` returns filesystem-dependent ordering).
    """
    matches = []
    for root, _dirs, files in os.walk(builddir, followlinks=False):
        for name in files:
            if not name.endswith(suffix):
                continue
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            matches.append(full)
    matches.sort()
    return matches


def _jar_extract_fallback(jarfile, destdir):
    """Fallback extraction via ``jar -xf`` for non-standard archives."""
    subprocess.run(
        ["jar", "-xf", os.path.abspath(jarfile)],
        cwd=destdir,
        check=False,
    )


def safe_extract_jar(jarfile, destdir):
    """Extract a JAR into ``destdir`` (replaces ``rm -rf; mkdir; jar -xf``).

    Recreates ``destdir`` then extracts via the stdlib ``zipfile`` module
    (JARs are ZIP archives). Guards against Zip-Slip path traversal by
    verifying every member resolves inside ``destdir`` before extracting.
    Falls back to ``jar -xf`` only for archives ``zipfile`` cannot read.
    """
    shutil.rmtree(destdir, ignore_errors=True)
    os.makedirs(destdir, exist_ok=True)
    dest_abs = os.path.abspath(destdir)
    try:
        with zipfile.ZipFile(jarfile) as archive:
            for member in archive.namelist():
                target = os.path.abspath(os.path.join(destdir, member))
                if target != dest_abs and not target.startswith(
                    dest_abs + os.sep
                ):
                    raise ValueError(
                        "Refusing to extract unsafe path %r from %s"
                        % (member, jarfile)
                    )
            archive.extractall(destdir)
    except zipfile.BadZipFile:
        _jar_extract_fallback(jarfile, destdir)


def is_zip_file(path):
    """Return True if ``path`` is a ZIP-based archive (replaces ``file``).

    ``zipfile.is_zipfile`` reads the archive's magic bytes and returns
    False for missing or non-archive files. JAR/WAR/EAR files are ZIP
    archives, so this is equivalent to the upstream ``is_jar_file`` check
    for the Java build artifacts this tool processes.
    """
    return zipfile.is_zipfile(path)


def _iter_class_entries_fallback(jarfile):
    """Extract-to-temp fallback for archives ``zipfile`` cannot read.

    Preserves parity with the upstream ``jar -xf`` behaviour for the rare
    non-standard archive: extract to a temp dir, read every ``.class`` as
    bytes, then remove the temp dir. Member names are the archive-relative
    paths (POSIX separators) so callers get identical keys to the
    zip-based path.
    """
    destdir = tempfile.mkdtemp(prefix="bomsh_inmem_jar_")
    try:
        safe_extract_jar(jarfile, destdir)
        entries = []
        for path in find_suffix_files(destdir, ".class"):
            member = os.path.relpath(path, destdir).replace(os.sep, "/")
            with open(path, "rb") as handle:
                entries.append((member, handle.read()))
        entries.sort(key=lambda item: item[0])
        return entries
    finally:
        shutil.rmtree(destdir, ignore_errors=True)


def iter_jar_class_entries(jarfile):
    """Return sorted ``(member_name, data)`` for every ``.class`` in a JAR.

    Reads each ``.class`` entry's bytes directly from the archive with no
    extraction to disk (replaces the ``jar -xf`` + walk + ``rmtree``
    lifecycle). Entries are sorted by member name, which matches the
    ordering of ``find_suffix_files`` over an extracted tree (a shared
    prefix does not change the sort). Falls back to extract-to-temp only
    for archives ``zipfile`` cannot parse.
    """
    try:
        with zipfile.ZipFile(jarfile) as archive:
            names = sorted(
                name for name in archive.namelist()
                if name.endswith(".class") and not name.endswith("/")
            )
            return [(name, archive.read(name)) for name in names]
    except zipfile.BadZipFile:
        return _iter_class_entries_fallback(jarfile)


def bytes_same_as_file(data, path):
    """Return True if the file at ``path`` has content equal to ``data``.

    Byte-for-byte comparison of in-memory ``data`` against a workspace
    file. Returns False if the file is missing or unreadable (matching the
    conservative behaviour of :func:`files_have_same_content`). Compares
    size first to short-circuit the common mismatch cheaply.
    """
    try:
        if os.path.getsize(path) != len(data):
            return False
        with open(path, "rb") as handle:
            return handle.read() == data
    except OSError:
        return False


def find_matching_class(classfile, adict, class_data=None):
    """Find the workspace ``.class`` file matching a JAR entry.

    Mirrors the upstream ``find_matching_file_in_dict``: candidates share
    the basename of ``classfile`` and must have identical content. When
    ``class_data`` is provided the comparison is made against the
    in-memory JAR bytes; otherwise it falls back to a file/file compare
    (preserving the original path-based behaviour). Returns the matching
    workspace path or an empty string.
    """
    candidates = adict.get(os.path.basename(classfile)) or []
    for afile in candidates:
        if class_data is not None:
            if bytes_same_as_file(class_data, afile):
                return afile
        elif files_have_same_content(afile, classfile):
            return afile
    return ""
