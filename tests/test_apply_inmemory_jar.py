"""Tests for apply_inmemory_jar.py.

Verifies the applier rewrites the upstream JAR processor correctly and,
most importantly, that the rewritten in-memory ``process_jar_file`` /
``process_class_file`` produce treedb records **byte-for-byte identical**
to the original extract-to-disk versions -- for both classes that match a
workspace file and classes that do not. No JDK or network required.
"""
import importlib.util
import os
import py_compile
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PATCHES_DIR = Path(__file__).parent.parent / "docker" / "patches"
sys.path.insert(0, str(PATCHES_DIR))

import apply_inmemory_jar  # noqa: E402


# A self-contained fixture that mirrors the upstream bomsh functions the
# applier rewrites, plus the minimum dependencies to run them end to end.
# ``update_hash_tree_db_and_gitbom`` captures every record into g_records
# so the original and patched runs can be compared.
FIXTURE = '''\
import os
import shutil
import subprocess
from bomsh_java_fast_io import (
    git_blob_hash,
    files_have_same_content,
    find_suffix_files,
    safe_extract_jar,
)
from bomsh_java_fast_classreader import read_source_file

g_tmp_unbundle_dir = "/tmp/bomjdir"
g_class_files = {}
g_java_files = {}
g_treedb = {}
g_classfile_records = {}
g_records = []


def verbose(*args, **kwargs):
    pass


def get_git_file_hash(afile):
    return git_blob_hash(afile)


def is_same_file_content(afile, bfile):
    return files_have_same_content(afile, bfile)


def find_all_suffix_files(builddir, suffix):
    return find_suffix_files(builddir, suffix)


def get_source_file_of_class_file(classfile):
    return read_source_file(classfile)


def get_source_file_of_class_files(afiles):
    return [get_source_file_of_class_file(f) for f in afiles]


def find_matching_file_in_dict(in_file, adict):
    basename = os.path.basename(in_file)
    afiles = adict.get(basename) or []
    for afile in afiles:
        if is_same_file_content(afile, in_file):
            return afile
    return ''


def find_java_file_for_classfile(classfile, source_file):
    if not source_file:
        source_file = get_source_file_of_class_file(classfile)
    if source_file:
        matches = g_java_files.get(os.path.basename(source_file)) or []
        if matches:
            return matches[0]
    return ''


def get_java_file_for_classfile_from_strace(classfile, d_records, rootdir):
    if classfile[0] != "/":
        classfile = os.path.abspath(classfile)
    if classfile not in d_records:
        return ''
    return d_records[classfile]


def update_hash_tree_db_and_gitbom(db, record):
    checksum, outfile = record["outfile"]
    infiles = record.get("infiles", [])
    g_records.append((outfile, checksum, list(infiles)))
    db[checksum] = outfile


def unbundle_jar_file(jarfile, destdir):
    safe_extract_jar(jarfile, destdir)


def process_class_file(classfile, rootdir, source_file=''):
    if not os.path.isfile(classfile):
        return
    match_classfile = find_matching_file_in_dict(classfile, g_class_files)
    if not match_classfile:
        verbose("Warning: Cannot find this .class file: " + classfile)
        return classfile
    classfile = match_classfile
    strace_source_file = ''
    if g_classfile_records:
        strace_source_file = get_java_file_for_classfile_from_strace(
            match_classfile, g_classfile_records, rootdir)
    if strace_source_file:
        source_file = strace_source_file
    else:
        source_file = find_java_file_for_classfile(classfile, source_file)
    record = {"outfile": (get_git_file_hash(classfile), classfile)}
    if source_file:
        record["infiles"] = [(get_git_file_hash(source_file), source_file),]
    update_hash_tree_db_and_gitbom(g_treedb, record)
    return classfile


def process_jar_file(jarfile, rootdir):
    if not os.path.isfile(jarfile):
        return
    jarfile_abspath = jarfile
    if jarfile[0] != "/":
        jarfile_abspath = os.path.abspath(jarfile)
    destdir = os.path.join(g_tmp_unbundle_dir, os.path.basename(jarfile))
    unbundle_jar_file(jarfile_abspath, destdir)
    classfiles = find_all_suffix_files(destdir, ".class")
    source_files = get_source_file_of_class_files(classfiles)
    record = {"outfile": (get_git_file_hash(jarfile), jarfile), "infiles": []}
    for i in range(len(classfiles)):
         classfile = classfiles[i]
         if source_files:
             source_file = source_files[i]
         classfile = process_class_file(classfile, rootdir, source_file)
         record["infiles"].append( (get_git_file_hash(classfile), classfile) )
    update_hash_tree_db_and_gitbom(g_treedb, record)
    shutil.rmtree(destdir, True)
'''


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestApplier(unittest.TestCase):
    """Structural checks on the applier itself."""

    def _apply(self, target):
        return apply_inmemory_jar.main(target)

    def test_rewrites_and_compiles(self):
        with tempfile.TemporaryDirectory() as td:
            target = _write(os.path.join(td, "bomsh_create_bom_java.py"),
                            FIXTURE)
            applied = self._apply(target)
            # import + 2 function rewrites
            self.assertEqual(applied, 3)
            py_compile.compile(target, doraise=True)
            patched = Path(target).read_text(encoding="utf-8")
            self.assertIn("_fast_iter_jar_classes", patched)
            self.assertIn("class_data=None", patched)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            target = _write(os.path.join(td, "bomsh_create_bom_java.py"),
                            FIXTURE)
            self._apply(target)
            first = Path(target).read_text(encoding="utf-8")
            self.assertEqual(self._apply(target), 0)
            self.assertEqual(Path(target).read_text(encoding="utf-8"), first)

    def test_fails_fast_on_missing_function(self):
        fixture = FIXTURE.replace(
            "def process_jar_file(jarfile, rootdir):",
            "def renamed_jar(jarfile, rootdir):",
        )
        with tempfile.TemporaryDirectory() as td:
            target = _write(os.path.join(td, "bomsh_create_bom_java.py"),
                            fixture)
            with self.assertRaises(SystemExit) as ctx:
                self._apply(target)
            self.assertIn("process_jar_file", str(ctx.exception))

    def test_fails_fast_on_missing_import_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            target = _write(
                os.path.join(td, "bomsh_create_bom_java.py"),
                "def process_class_file(classfile, rootdir, source_file=''):\n"
                "    pass\n\n\ndef process_jar_file(jarfile, rootdir):\n"
                "    pass\n",
            )
            with self.assertRaises(SystemExit):
                self._apply(target)

    def test_default_target_constant(self):
        self.assertTrue(
            apply_inmemory_jar.DEFAULT_TARGET.endswith(
                "bomsh_create_bom_java.py"
            )
        )


class TestInMemoryEquivalence(unittest.TestCase):
    """The rewritten path must reproduce the extract-to-disk treedb."""

    def _setup_workspace(self, td):
        """Create workspace .class/.java files and the dicts for them."""
        rootdir = os.path.join(td, "ws")
        # Two classes present in the workspace (will match by content),
        # one class that only exists inside the JAR (unmatched).
        matched = {
            "com/x/Alpha.class": b"ALPHA-CLASS-BYTES",
            "com/x/Beta.class": b"BETA-CLASS-BYTES",
        }
        class_files = {}
        for rel, data in matched.items():
            path = os.path.join(rootdir, "target", "classes", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            class_files.setdefault(os.path.basename(rel), []).append(path)
        return rootdir, class_files, matched

    def _build_jar(self, td, matched):
        jar = os.path.join(td, "artifact.jar")
        with zipfile.ZipFile(jar, "w") as archive:
            for rel, data in matched.items():
                archive.writestr(rel, data)
            # An extra class not present in the workspace (unmatched).
            archive.writestr("com/x/Gamma.class", b"GAMMA-ONLY-IN-JAR")
            archive.writestr("META-INF/MANIFEST.MF", b"Manifest-Version: 1\n")
        return jar

    def _run(self, module, td, rootdir, class_files, jar):
        module.g_tmp_unbundle_dir = os.path.join(td, "unbundle")
        module.g_class_files = class_files
        module.g_java_files = {}
        module.g_treedb = {}
        module.g_classfile_records = {}
        module.g_records = []
        module.process_jar_file(jar, rootdir)
        return module.g_records

    def test_records_identical(self):
        with tempfile.TemporaryDirectory() as td:
            rootdir, class_files, matched = self._setup_workspace(td)
            jar = self._build_jar(td, matched)

            orig_path = _write(os.path.join(td, "orig.py"), FIXTURE)
            orig = _load_module(orig_path, "bomsh_orig")
            orig_records = self._run(orig, td, rootdir, class_files, jar)

            patched_path = _write(os.path.join(td, "patched.py"), FIXTURE)
            apply_inmemory_jar.main(patched_path)
            patched = _load_module(patched_path, "bomsh_patched")
            patched_records = self._run(
                patched, td, rootdir, class_files, jar
            )

            self.assertEqual(orig_records, patched_records)

    def test_matched_classes_use_workspace_paths(self):
        with tempfile.TemporaryDirectory() as td:
            rootdir, class_files, matched = self._setup_workspace(td)
            jar = self._build_jar(td, matched)
            patched_path = _write(os.path.join(td, "patched.py"), FIXTURE)
            apply_inmemory_jar.main(patched_path)
            patched = _load_module(patched_path, "bomsh_patched2")
            records = self._run(patched, td, rootdir, class_files, jar)

            # The JAR record is last; its infiles reference the two matched
            # workspace paths plus the synthetic temp path for Gamma.
            jar_infiles = records[-1][2]
            paths = [p for _h, p in jar_infiles]
            self.assertTrue(
                any(p.endswith("target/classes/com/x/Alpha.class")
                    for p in paths)
            )
            gamma = [p for p in paths if p.endswith("Gamma.class")][0]
            self.assertIn("unbundle", gamma)
            self.assertIn("artifact.jar", gamma)

    def test_no_extraction_dir_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            rootdir, class_files, matched = self._setup_workspace(td)
            jar = self._build_jar(td, matched)
            patched_path = _write(os.path.join(td, "patched.py"), FIXTURE)
            apply_inmemory_jar.main(patched_path)
            patched = _load_module(patched_path, "bomsh_patched3")
            self._run(patched, td, rootdir, class_files, jar)
            # In-memory path must never create the unbundle directory.
            self.assertFalse(os.path.exists(os.path.join(td, "unbundle")))


if __name__ == "__main__":
    unittest.main()
