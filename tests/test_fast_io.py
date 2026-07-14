"""Tests for bomsh_java_fast_io.py and apply_fast_io.py.

Verifies the pure-Python fast-IO replacements produce results identical
to the shell commands they replace (git hash-object, diff -q, find,
jar -xf, file), and that the applier rewrites the upstream script
correctly. No JDK or network access required.
"""
import contextlib
import io
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PATCHES_DIR = Path(__file__).parent.parent / "docker" / "patches"
sys.path.insert(0, str(PATCHES_DIR))

import apply_fast_io  # noqa: E402
from bomsh_java_fast_io import (  # noqa: E402
    git_blob_hash,
    git_blob_hash_data,
    build_hash_cache,
    clear_cache,
    files_have_same_content,
    find_suffix_files,
    safe_extract_jar,
    is_zip_file,
    iter_jar_class_entries,
    bytes_same_as_file,
    find_matching_class,
)

# Well-known git blob object ids (independent of any local git config).
EMPTY_BLOB_SHA1 = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
HELLO_BLOB_SHA1 = "ce013625030ba8dba906f756967f9e9ca394464a"  # b"hello\n"

GIT_AVAILABLE = shutil.which("git") is not None


def _write(path, data=b""):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class TestGitBlobHash(unittest.TestCase):
    """git_blob_hash parity with git hash-object."""

    def setUp(self):
        clear_cache()

    def test_empty_file_known_constant(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "empty"), b"")
            self.assertEqual(git_blob_hash(p), EMPTY_BLOB_SHA1)

    def test_hello_known_constant(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "hello"), b"hello\n")
            self.assertEqual(git_blob_hash(p), HELLO_BLOB_SHA1)

    def test_missing_file_returns_empty(self):
        self.assertEqual(git_blob_hash("/no/such/file"), "")

    def test_read_error_after_stat_returns_empty(self):
        # File vanishes between stat and read (TOCTOU): return "".
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"data")
            with mock.patch(
                "bomsh_java_fast_io._hash_blob_stream",
                side_effect=OSError,
            ):
                self.assertEqual(git_blob_hash(p), "")

    @unittest.skipUnless(GIT_AVAILABLE, "git not installed")
    def test_parity_with_real_git_hash_object(self):
        payloads = [b"", b"hello\n", b"\x00\x01\x02binary", b"x" * 5000]
        with tempfile.TemporaryDirectory() as td:
            for i, payload in enumerate(payloads):
                p = _write(os.path.join(td, f"f{i}"), payload)
                expected = subprocess.check_output(
                    ["git", "hash-object", p],
                    universal_newlines=True,
                ).strip()
                clear_cache()
                self.assertEqual(git_blob_hash(p), expected)

    def test_large_file_streams_in_chunks(self):
        # Larger than the 1 MiB chunk to exercise the streaming loop.
        data = os.urandom(3 * (1 << 20))
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "big"), data)
            self.assertEqual(git_blob_hash(p), git_blob_hash_data(data))


class TestGitBlobHashData(unittest.TestCase):
    """git_blob_hash_data parity with git_blob_hash."""

    def setUp(self):
        clear_cache()

    def test_matches_known_constants(self):
        self.assertEqual(git_blob_hash_data(b""), EMPTY_BLOB_SHA1)
        self.assertEqual(git_blob_hash_data(b"hello\n"), HELLO_BLOB_SHA1)

    def test_matches_file_hash(self):
        with tempfile.TemporaryDirectory() as td:
            data = b"some content\nspanning lines\n"
            p = _write(os.path.join(td, "f"), data)
            self.assertEqual(git_blob_hash(p), git_blob_hash_data(data))


class TestHashCache(unittest.TestCase):
    """Memoization cache and parallel pre-hash."""

    def setUp(self):
        clear_cache()

    def test_build_cache_counts_unique(self):
        with tempfile.TemporaryDirectory() as td:
            paths = [
                _write(os.path.join(td, f"f{i}"), f"data{i}".encode())
                for i in range(5)
            ]
            self.assertEqual(build_hash_cache(paths), 5)
            # Re-running finds everything already cached.
            self.assertEqual(build_hash_cache(paths), 0)

    def test_build_cache_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"dup")
            self.assertEqual(build_hash_cache([p, p, p]), 1)

    def test_build_cache_empty(self):
        self.assertEqual(build_hash_cache([]), 0)

    def test_build_cache_skips_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"ok")
            self.assertEqual(build_hash_cache([p, "/no/such/file"]), 1)

    def test_build_cache_skips_read_error(self):
        # Stat succeeds but the read fails: entry is skipped, not cached.
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"data")
            with mock.patch(
                "bomsh_java_fast_io._hash_blob_stream",
                side_effect=OSError,
            ):
                self.assertEqual(build_hash_cache([p]), 0)

    def test_cached_value_matches_direct(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"hello\n")
            build_hash_cache([p])
            # Served from cache; must equal the authoritative value.
            self.assertEqual(git_blob_hash(p), HELLO_BLOB_SHA1)

    def test_cache_invalidated_on_change(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "f")
            _write(p, b"")
            self.assertEqual(git_blob_hash(p), EMPTY_BLOB_SHA1)
            # Rewrite with new content + bump mtime; key changes.
            _write(p, b"hello\n")
            os.utime(p, (0, 0))
            self.assertEqual(git_blob_hash(p), HELLO_BLOB_SHA1)


class TestFilesHaveSameContent(unittest.TestCase):
    """files_have_same_content parity with diff -q."""

    def test_identical(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(os.path.join(td, "a"), b"same\n")
            b = _write(os.path.join(td, "b"), b"same\n")
            self.assertTrue(files_have_same_content(a, b))

    def test_different(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(os.path.join(td, "a"), b"one\n")
            b = _write(os.path.join(td, "b"), b"two\n")
            self.assertFalse(files_have_same_content(a, b))

    def test_different_size_short_circuit(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(os.path.join(td, "a"), b"short")
            b = _write(os.path.join(td, "b"), b"a much longer body")
            self.assertFalse(files_have_same_content(a, b))

    def test_missing_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(os.path.join(td, "a"), b"x")
            self.assertFalse(
                files_have_same_content(a, "/no/such/file")
            )


class TestFindSuffixFiles(unittest.TestCase):
    """find_suffix_files parity with find -type f -name '*<suffix>'."""

    def test_finds_nested_sorted(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "b", "c"))
            _write(os.path.join(td, "Z.class"))
            _write(os.path.join(td, "b", "A.class"))
            _write(os.path.join(td, "b", "c", "M.class"))
            _write(os.path.join(td, "skip.java"))
            result = find_suffix_files(td, ".class")
            self.assertEqual(len(result), 3)
            self.assertEqual(result, sorted(result))
            self.assertTrue(all(p.endswith(".class") for p in result))

    def test_missing_dir_returns_empty(self):
        self.assertEqual(find_suffix_files("/no/such/dir", ".class"), [])

    def test_excludes_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            real = _write(os.path.join(td, "real.class"))
            link = os.path.join(td, "link.class")
            os.symlink(real, link)
            result = find_suffix_files(td, ".class")
            self.assertEqual(result, [real])

    def test_does_not_follow_symlinked_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            outside = os.path.join(td, "outside")
            os.makedirs(outside)
            _write(os.path.join(outside, "X.class"))
            inside = os.path.join(td, "inside")
            os.makedirs(inside)
            os.symlink(outside, os.path.join(inside, "ldir"))
            result = find_suffix_files(inside, ".class")
            self.assertEqual(result, [])


class TestSafeExtractJar(unittest.TestCase):
    """safe_extract_jar parity with jar -xf, plus Zip-Slip guard."""

    def _make_jar(self, path, entries):
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return path

    def test_extracts_entries(self):
        with tempfile.TemporaryDirectory() as td:
            jar = self._make_jar(
                os.path.join(td, "a.jar"),
                {"com/Foo.class": b"foo", "META-INF/MANIFEST.MF": b"x"},
            )
            dest = os.path.join(td, "out")
            safe_extract_jar(jar, dest)
            self.assertTrue(
                os.path.isfile(os.path.join(dest, "com", "Foo.class"))
            )

    def test_recreates_destdir(self):
        with tempfile.TemporaryDirectory() as td:
            jar = self._make_jar(
                os.path.join(td, "a.jar"), {"A.class": b"a"}
            )
            dest = os.path.join(td, "out")
            os.makedirs(dest)
            _write(os.path.join(dest, "stale.txt"), b"old")
            safe_extract_jar(jar, dest)
            self.assertFalse(
                os.path.exists(os.path.join(dest, "stale.txt"))
            )
            self.assertTrue(os.path.isfile(os.path.join(dest, "A.class")))

    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            jar = os.path.join(td, "evil.jar")
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("../escape.txt", b"pwned")
            dest = os.path.join(td, "out")
            with self.assertRaises(ValueError):
                safe_extract_jar(jar, dest)

    def test_bad_zip_falls_back_to_jar(self):
        with tempfile.TemporaryDirectory() as td:
            not_a_jar = _write(os.path.join(td, "bad.jar"), b"not a zip")
            dest = os.path.join(td, "out")
            with mock.patch(
                "bomsh_java_fast_io.subprocess.run"
            ) as run:
                safe_extract_jar(not_a_jar, dest)
                run.assert_called_once()


class TestIsZipFile(unittest.TestCase):
    """is_zip_file parity with the is_jar_file archive check."""

    def test_real_zip(self):
        with tempfile.TemporaryDirectory() as td:
            jar = os.path.join(td, "a.jar")
            with zipfile.ZipFile(jar, "w") as zf:
                zf.writestr("A.class", b"a")
            self.assertTrue(is_zip_file(jar))

    def test_non_zip(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f.txt"), b"plain text")
            self.assertFalse(is_zip_file(p))

    def test_missing(self):
        self.assertFalse(is_zip_file("/no/such/file"))


# Minimal fixture mirroring the exact upstream signatures the applier
# rewrites (omnibor/bomsh scripts/bomsh_create_bom_java.py).
UPSTREAM_FIXTURE = '''\
import subprocess


def is_same_file_content(afile, bfile):
    cmd = 'diff -q ' + afile + ' ' + bfile + ' || true'
    output = get_shell_cmd_output(cmd)
    if output:
        return False
    return True


def find_all_suffix_files(builddir, suffix):
    findcmd = "find " + builddir + ' -name "*' + suffix + '" || true'
    output = subprocess.check_output(findcmd, shell=True)
    return output.splitlines()

############################################################
#### Start of gitbom routines ####
############################################################

def add_files_to_dict(d, afiles):
    for afile in afiles:
        d[afile] = afile


def find_all_java_and_class_files(rootdir):
    javafiles = find_all_suffix_files(rootdir, ".java")
    classfiles = find_all_suffix_files(rootdir, ".class")
    add_files_to_dict(g_java_files, javafiles)
    add_files_to_dict(g_class_files, classfiles)
    return (javafiles, classfiles)


def unbundle_jar_file(jarfile, destdir):
    cmd = "rm -rf " + destdir + "; jar -xf " + jarfile + " || true"
    get_shell_cmd_output(cmd)


def get_git_file_hash(afile):
    cmd = 'git hash-object ' + afile + ' || true'
    output = get_shell_cmd_output(cmd)
    if output:
        return output.strip()
    return ''


def is_jar_file(afile):
    return " archive data" in get_filetype(afile)
'''


class TestApplier(unittest.TestCase):
    """apply_fast_io.main() rewrites the upstream script correctly."""

    def _apply(self, target):
        # Call in-process so coverage measures the applier.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            count = apply_fast_io.main(target)
        return count, buf.getvalue()

    def test_applier_rewrites_and_compiles(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "bomsh_create_bom_java.py")
            _write(target, UPSTREAM_FIXTURE.encode())
            count, stdout = self._apply(target)
            # Import + six function replacements.
            self.assertEqual(count, 7)

            patched = Path(target).read_text()
            self.assertIn("from bomsh_java_fast_io import", patched)
            self.assertIn("return _fast_git_hash(afile)", patched)
            self.assertIn(
                "return _fast_same_content(afile, bfile)", patched
            )
            self.assertIn(
                "return _fast_find_suffix(builddir, suffix)", patched
            )
            self.assertIn(
                "_fast_extract_jar(jarfile, destdir)", patched
            )
            self.assertIn("return _fast_is_zip(afile)", patched)
            self.assertIn(
                "_fast_build_cache(javafiles + classfiles)", patched
            )
            # No subprocess shell-outs remain in the rewritten helpers.
            self.assertNotIn("git hash-object", patched)
            self.assertNotIn("diff -q", patched)
            self.assertNotIn("jar -xf", patched)
            # Result is valid Python.
            py_compile.compile(target, doraise=True)
            self.assertIn("replacements applied", stdout)

    def test_applier_idempotent_import(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "bomsh_create_bom_java.py")
            _write(target, UPSTREAM_FIXTURE.encode())
            self._apply(target)
            self._apply(target)
            patched = Path(target).read_text()
            # Import inserted exactly once across re-runs.
            self.assertEqual(
                patched.count("from bomsh_java_fast_io import"), 1
            )

    def test_applier_fails_fast_on_missing_function(self):
        # Drop a target function to simulate upstream drift.
        fixture = UPSTREAM_FIXTURE.replace(
            "def get_git_file_hash(afile):",
            "def renamed_hash(afile):",
        )
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "bomsh_create_bom_java.py")
            _write(target, fixture.encode())
            with self.assertRaises(SystemExit) as ctx:
                self._apply(target)
            self.assertIn("get_git_file_hash", str(ctx.exception))
            # File must be left unmodified when drift is detected.
            self.assertEqual(Path(target).read_text(), fixture)

    def test_applier_fails_fast_on_missing_import_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "bomsh_create_bom_java.py")
            _write(target, b"def get_git_file_hash(afile):\n    pass\n")
            with self.assertRaises(SystemExit):
                self._apply(target)

    def test_applier_default_target_constant(self):
        self.assertTrue(
            apply_fast_io.DEFAULT_TARGET.endswith(
                "bomsh_create_bom_java.py"
            )
        )


def _make_jar(path, members):
    """Create a JAR (zip) with the given {member_name: bytes} mapping."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


class TestIterJarClassEntries(unittest.TestCase):
    """iter_jar_class_entries reads .class bytes in sorted member order."""

    def test_returns_sorted_class_entries_with_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            jar = _make_jar(os.path.join(td, "a.jar"), {
                "b/B.class": b"BB",
                "a/A.class": b"AA",
                "META-INF/MANIFEST.MF": b"Manifest\n",
                "a/notes.txt": b"text",
            })
            entries = iter_jar_class_entries(jar)
            self.assertEqual(
                [name for name, _ in entries],
                ["a/A.class", "b/B.class"],
            )
            self.assertEqual(dict(entries), {
                "a/A.class": b"AA", "b/B.class": b"BB",
            })

    def test_excludes_directory_entries(self):
        with tempfile.TemporaryDirectory() as td:
            jar = os.path.join(td, "d.jar")
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("pkg/", b"")
                archive.writestr("pkg/C.class", b"CC")
            self.assertEqual(
                iter_jar_class_entries(jar), [("pkg/C.class", b"CC")]
            )

    def test_empty_jar(self):
        with tempfile.TemporaryDirectory() as td:
            jar = _make_jar(os.path.join(td, "e.jar"), {})
            self.assertEqual(iter_jar_class_entries(jar), [])

    def test_bad_zip_uses_extract_fallback(self):
        # A non-zip file triggers the extract-to-temp fallback, which in
        # turn falls back to `jar -xf`; with jar unavailable it yields [].
        with tempfile.TemporaryDirectory() as td:
            bogus = _write(os.path.join(td, "bad.jar"), b"not a zip")
            with mock.patch(
                "bomsh_java_fast_io._jar_extract_fallback"
            ) as fallback:
                result = iter_jar_class_entries(bogus)
            self.assertEqual(result, [])
            fallback.assert_called_once()

    def test_fallback_reads_extracted_classes(self):
        with tempfile.TemporaryDirectory() as td:
            real = _make_jar(os.path.join(td, "r.jar"), {
                "x/Y.class": b"YY", "x/Z.class": b"ZZ",
            })
            with open(real, "rb") as fh:
                payload = fh.read()
            # Force the BadZipFile branch even though payload is valid.
            orig = zipfile.ZipFile

            def _raise(path, *a, **k):
                if os.path.abspath(path) == os.path.abspath(real):
                    raise zipfile.BadZipFile("forced")
                return orig(path, *a, **k)

            with mock.patch.object(zipfile, "ZipFile", _raise):
                with mock.patch(
                    "bomsh_java_fast_io._jar_extract_fallback",
                    lambda jarfile, destdir: orig(real).extractall(destdir),
                ):
                    entries = iter_jar_class_entries(real)
            self.assertEqual(payload[:2], b"PK")  # sanity: it was a real zip
            self.assertEqual(
                [name for name, _ in entries],
                ["x/Y.class", "x/Z.class"],
            )


class TestBytesSameAsFile(unittest.TestCase):
    """bytes_same_as_file compares in-memory bytes to a file."""

    def test_identical(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"hello\n")
            self.assertTrue(bytes_same_as_file(b"hello\n", p))

    def test_size_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"hello\n")
            self.assertFalse(bytes_same_as_file(b"hell", p))

    def test_same_size_different_content(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(os.path.join(td, "f"), b"aaaaa")
            self.assertFalse(bytes_same_as_file(b"bbbbb", p))

    def test_missing_file(self):
        self.assertFalse(bytes_same_as_file(b"x", "/no/such/file"))


class TestFindMatchingClass(unittest.TestCase):
    """find_matching_class mirrors upstream find_matching_file_in_dict."""

    def _dict(self, td, mapping):
        adict = {}
        for rel, data in mapping.items():
            path = os.path.join(td, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, data)
            adict.setdefault(os.path.basename(rel), []).append(path)
        return adict

    def test_data_match_returns_workspace_path(self):
        with tempfile.TemporaryDirectory() as td:
            adict = self._dict(td, {"a/Foo.class": b"FOO"})
            match = find_matching_class(
                "/tmp/x/Foo.class", adict, class_data=b"FOO"
            )
            self.assertEqual(match, adict["Foo.class"][0])

    def test_data_no_content_match(self):
        with tempfile.TemporaryDirectory() as td:
            adict = self._dict(td, {"a/Foo.class": b"FOO"})
            self.assertEqual(
                find_matching_class(
                    "/tmp/x/Foo.class", adict, class_data=b"BAR"
                ),
                "",
            )

    def test_no_basename_candidate(self):
        self.assertEqual(
            find_matching_class("/tmp/x/Nope.class", {}, class_data=b"X"),
            "",
        )

    def test_path_mode_matches_file_content(self):
        with tempfile.TemporaryDirectory() as td:
            adict = self._dict(td, {"a/Foo.class": b"FOO"})
            os.makedirs(os.path.join(td, "probe"))
            probe = _write(os.path.join(td, "probe/Foo.class"), b"FOO")
            self.assertEqual(
                find_matching_class(probe, adict),
                adict["Foo.class"][0],
            )

    def test_picks_first_content_match(self):
        with tempfile.TemporaryDirectory() as td:
            adict = self._dict(td, {"a/Foo.class": b"FOO"})
            # A second same-basename candidate with matching content.
            second = os.path.join(td, "b", "Foo.class")
            os.makedirs(os.path.dirname(second))
            _write(second, b"FOO")
            adict["Foo.class"].append(second)
            match = find_matching_class(
                "/tmp/x/Foo.class", adict, class_data=b"FOO"
            )
            self.assertEqual(match, adict["Foo.class"][0])


if __name__ == "__main__":
    unittest.main()
