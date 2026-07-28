"""Tests for bomsh_java_fast_classreader.py.

Creates synthetic .class files to test the pure-Python
bytecode reader without needing a real JDK.
"""
import contextlib
import io
import os
import py_compile
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent / "docker" / "patches")
)

import apply_fast_javap  # noqa: E402
from bomsh_java_fast_classreader import (  # noqa: E402
    read_source_file,
    read_source_files,
    read_source_file_data,
    read_source_files_data,
    read_class_name,
    read_class_info,
)


def _build_classfile(
    source_file="Foo.java",
    class_name="com/example/Foo",
):
    """Build a minimal valid .class file with SourceFile attr.

    Only includes the constant pool entries and attributes
    needed for testing. Follows JVM Spec §4.1.
    """
    # Constant pool entries (1-indexed):
    # 1: UTF8 "SourceFile"
    # 2: UTF8 source_file
    # 3: UTF8 class_name (internal format)
    # 4: Class -> #3
    # 5: UTF8 "java/lang/Object"
    # 6: Class -> #5
    cp_entries = []

    def utf8_entry(s):
        encoded = s.encode("utf-8")
        return struct.pack(">BH", 1, len(encoded)) + encoded

    def class_entry(name_idx):
        return struct.pack(">BH", 7, name_idx)

    cp_entries.append(utf8_entry("SourceFile"))  # #1
    cp_entries.append(utf8_entry(source_file))   # #2
    cp_entries.append(utf8_entry(class_name))    # #3
    cp_entries.append(class_entry(3))            # #4
    cp_entries.append(utf8_entry("java/lang/Object"))  # #5
    cp_entries.append(class_entry(5))            # #6

    cp_count = len(cp_entries) + 1  # 1-indexed
    cp_data = b"".join(cp_entries)

    # SourceFile attribute: name_idx=1, length=2, sf_idx=2
    source_attr = struct.pack(">HIH", 1, 2, 2)

    data = b""
    data += struct.pack(">I", 0xCAFEBABE)  # magic
    data += struct.pack(">HH", 0, 65)       # minor=0, major=65 (Java 21)
    data += struct.pack(">H", cp_count)      # constant_pool_count
    data += cp_data
    data += struct.pack(">H", 0x0021)        # access_flags: public super
    data += struct.pack(">H", 4)             # this_class -> #4
    data += struct.pack(">H", 6)             # super_class -> #6
    data += struct.pack(">H", 0)             # interfaces_count
    data += struct.pack(">H", 0)             # fields_count
    data += struct.pack(">H", 0)             # methods_count
    data += struct.pack(">H", 1)             # attributes_count
    data += source_attr
    return data


class TestReadSourceFile(unittest.TestCase):
    """Tests for read_source_file."""

    def test_valid_classfile(self):
        data = _build_classfile("Bar.java")
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        result = read_source_file(path)
        Path(path).unlink()
        self.assertEqual(result, "Bar.java")

    def test_missing_file(self):
        result = read_source_file("/nonexistent.class")
        self.assertEqual(result, "")

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            path = f.name
        result = read_source_file(path)
        Path(path).unlink()
        self.assertEqual(result, "")

    def test_not_classfile(self):
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(b"not a class file")
            path = f.name
        result = read_source_file(path)
        Path(path).unlink()
        self.assertEqual(result, "")

    def test_no_source_attr(self):
        """Class file without SourceFile attribute."""
        data = _build_classfile("Foo.java")
        # Remove the SourceFile attribute by setting
        # attributes_count to 0
        # Find last 8 bytes: attrs_count(2) + attr(6)
        # Replace attrs_count with 0 and drop attr
        truncated = data[:-8] + struct.pack(">H", 0)
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(truncated)
            path = f.name
        result = read_source_file(path)
        Path(path).unlink()
        self.assertEqual(result, "")


class TestReadClassName(unittest.TestCase):
    """Tests for read_class_name."""

    def test_valid_classfile(self):
        data = _build_classfile(
            class_name="org/bouncycastle/Foo"
        )
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        result = read_class_name(path)
        Path(path).unlink()
        self.assertEqual(
            result, "org.bouncycastle.Foo"
        )

    def test_default_package(self):
        data = _build_classfile(class_name="Main")
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        result = read_class_name(path)
        Path(path).unlink()
        self.assertEqual(result, "Main")


class TestReadClassInfo(unittest.TestCase):
    """Tests for read_class_info."""

    def test_returns_both(self):
        data = _build_classfile(
            source_file="Foo.java",
            class_name="com/example/Foo",
        )
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        sf, cn = read_class_info(path)
        Path(path).unlink()
        self.assertEqual(sf, "Foo.java")
        self.assertEqual(cn, "com.example.Foo")

    def test_missing_file(self):
        sf, cn = read_class_info("/nonexistent.class")
        self.assertEqual(sf, "")
        self.assertEqual(cn, "")


class TestReadSourceFiles(unittest.TestCase):
    """Tests for read_source_files (batch)."""

    def test_batch(self):
        paths = []
        for name in ("A.java", "B.java", "C.java"):
            data = _build_classfile(source_file=name)
            with tempfile.NamedTemporaryFile(
                suffix=".class", delete=False
            ) as f:
                f.write(data)
                paths.append(f.name)
        result = read_source_files(paths)
        for p in paths:
            Path(p).unlink()
        self.assertEqual(
            result, ["A.java", "B.java", "C.java"]
        )

    def test_empty_list(self):
        self.assertEqual(read_source_files([]), [])


class TestLongDoubleConstant(unittest.TestCase):
    """Test that Long/Double constants (2 slots) parse correctly."""

    def test_long_in_constant_pool(self):
        """Build a .class with a CONSTANT_Long in the pool."""
        cp_entries = []

        def utf8_entry(s):
            encoded = s.encode("utf-8")
            return struct.pack(">BH", 1, len(encoded)) + encoded

        def class_entry(name_idx):
            return struct.pack(">BH", 7, name_idx)

        cp_entries.append(utf8_entry("SourceFile"))  # #1
        cp_entries.append(utf8_entry("Test.java"))   # #2
        # #3: CONSTANT_Long (takes 2 slots, so #4 is unusable)
        cp_entries.append(struct.pack(">BQ", 5, 42))
        # #5: UTF8 class name
        cp_entries.append(utf8_entry("Test"))
        # #6: Class -> #5
        cp_entries.append(class_entry(5))
        # #7: UTF8 super
        cp_entries.append(utf8_entry("java/lang/Object"))
        # #8: Class -> #7
        cp_entries.append(class_entry(7))

        # cp_count: entries are #1,#2,#3(+#4),#5,#6,#7,#8 = 9
        cp_count = 9
        cp_data = b"".join(cp_entries)

        source_attr = struct.pack(">HIH", 1, 2, 2)

        data = b""
        data += struct.pack(">I", 0xCAFEBABE)
        data += struct.pack(">HH", 0, 65)
        data += struct.pack(">H", cp_count)
        data += cp_data
        data += struct.pack(">H", 0x0021)
        data += struct.pack(">H", 6)  # this_class -> #6
        data += struct.pack(">H", 8)  # super_class -> #8
        data += struct.pack(">H", 0)  # interfaces
        data += struct.pack(">H", 0)  # fields
        data += struct.pack(">H", 0)  # methods
        data += struct.pack(">H", 1)  # attributes
        data += source_attr

        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        result = read_source_file(path)
        Path(path).unlink()
        self.assertEqual(result, "Test.java")


def _utf8(s):
    encoded = s.encode("utf-8")
    return struct.pack(">BH", 1, len(encoded)) + encoded


def _class(name_idx):
    return struct.pack(">BH", 7, name_idx)


def _assemble(cp_entries, cp_count, this_class, super_class,
              fields=b"", fields_count=0,
              methods=b"", methods_count=0,
              attrs=b"", attrs_count=0):
    """Assemble a .class file from raw constant-pool/member bytes."""
    data = struct.pack(">I", 0xCAFEBABE)
    data += struct.pack(">HH", 0, 65)
    data += struct.pack(">H", cp_count)
    data += b"".join(cp_entries)
    data += struct.pack(">H", 0x0021)        # access_flags
    data += struct.pack(">H", this_class)
    data += struct.pack(">H", super_class)
    data += struct.pack(">H", 0)             # interfaces_count
    data += struct.pack(">H", fields_count) + fields
    data += struct.pack(">H", methods_count) + methods
    data += struct.pack(">H", attrs_count) + attrs
    return data


def _member_with_attr(name_idx, desc_idx, attr_name_idx, info):
    """A field/method entry carrying a single attribute."""
    member = struct.pack(">HHH", 0x0001, name_idx, desc_idx)
    member += struct.pack(">H", 1)  # attributes_count
    member += struct.pack(">HI", attr_name_idx, len(info)) + info
    return member


def _write_class(data):
    with tempfile.NamedTemporaryFile(
        suffix=".class", delete=False
    ) as f:
        f.write(data)
        return f.name


# magic + minor/major + cp_count=50 but no entries -> parse overruns.
_MALFORMED = (
    struct.pack(">I", 0xCAFEBABE)
    + struct.pack(">HH", 0, 65)
    + struct.pack(">H", 50)
)


class TestClassReaderEdgeCases(unittest.TestCase):
    """Cover error paths and rarer bytecode shapes."""

    def _read_all(self, data):
        path = _write_class(data)
        try:
            return (
                read_source_file(path),
                read_class_name(path),
                read_class_info(path),
            )
        finally:
            Path(path).unlink()

    def test_unknown_cp_tag(self):
        # First CP entry has an unrecognized tag -> all readers bail out.
        data = _assemble([b"\x63"], cp_count=2,
                         this_class=0, super_class=0)
        sf, cn, info = self._read_all(data)
        self.assertEqual(sf, "")
        self.assertEqual(cn, "")
        self.assertEqual(info, ("", ""))

    def test_known_nonutf8_tag_methodref(self):
        # A Methodref (tag 10) exercises the fixed-size skip branch.
        cp = [
            _utf8("SourceFile"),          # 1
            _utf8("Test.java"),           # 2
            struct.pack(">BI", 10, 0),    # 3 Methodref
            _utf8("Test"),                # 4
            _class(4),                    # 5
            _utf8("java/lang/Object"),    # 6
            _class(6),                    # 7
        ]
        attrs = struct.pack(">HIH", 1, 2, 2)  # SourceFile -> #2
        data = _assemble(cp, cp_count=8, this_class=5, super_class=7,
                         attrs=attrs, attrs_count=1)
        sf, cn, info = self._read_all(data)
        self.assertEqual(sf, "Test.java")
        self.assertEqual(cn, "Test")
        self.assertEqual(info, ("Test.java", "Test"))

    def test_long_constant_in_name_parsers(self):
        # CONSTANT_Long occupies two slots in the name/info parsers too.
        cp = [
            _utf8("SourceFile"),       # 1
            _utf8("Test.java"),        # 2
            struct.pack(">BQ", 5, 42),  # 3 Long (+ unusable slot 4)
            _utf8("Test"),             # 5
            _class(5),                 # 6
            _utf8("java/lang/Object"),  # 7
            _class(7),                 # 8
        ]
        attrs = struct.pack(">HIH", 1, 2, 2)
        data = _assemble(cp, cp_count=9, this_class=6, super_class=8,
                         attrs=attrs, attrs_count=1)
        _, cn, info = self._read_all(data)
        self.assertEqual(cn, "Test")
        self.assertEqual(info, ("Test.java", "Test"))

    def test_non_sourcefile_attribute_then_none(self):
        # A class-level attribute that is not SourceFile is skipped.
        cp = [
            _utf8("Deprecated"),       # 1
            _utf8("Test"),             # 2
            _class(2),                 # 3
            _utf8("java/lang/Object"),  # 4
            _class(4),                 # 5
        ]
        attrs = struct.pack(">HI", 1, 0)  # Deprecated, length 0
        data = _assemble(cp, cp_count=6, this_class=3, super_class=5,
                         attrs=attrs, attrs_count=1)
        path = _write_class(data)
        try:
            self.assertEqual(read_source_file(path), "")
        finally:
            Path(path).unlink()

    def test_fields_and_methods_with_attributes(self):
        # Exercises _skip_members for both tables with attributes.
        cp = [
            _utf8("SourceFile"),       # 1
            _utf8("Test.java"),        # 2
            _utf8("ConstantValue"),    # 3 field attr name
            _utf8("Code"),             # 4 method attr name
            _utf8("Test"),             # 5
            _class(5),                 # 6
            _utf8("java/lang/Object"),  # 7
            _class(7),                 # 8
            _utf8("x"),                # 9 field name
            _utf8("I"),                # 10 field desc
            _utf8("m"),                # 11 method name
            _utf8("()V"),              # 12 method desc
        ]
        field = _member_with_attr(9, 10, 3, b"\x00\x05")
        method = _member_with_attr(11, 12, 4, b"\x00\x00\x00\x01")
        attrs = struct.pack(">HIH", 1, 2, 2)
        data = _assemble(
            cp, cp_count=13, this_class=6, super_class=8,
            fields=field, fields_count=1,
            methods=method, methods_count=1,
            attrs=attrs, attrs_count=1,
        )
        path = _write_class(data)
        try:
            self.assertEqual(read_source_file(path), "Test.java")
        finally:
            Path(path).unlink()

    def test_parse_exception_returns_empty(self):
        sf, cn, info = self._read_all(_MALFORMED)
        self.assertEqual(sf, "")
        self.assertEqual(cn, "")
        self.assertEqual(info, ("", ""))

    def test_read_class_name_missing_file(self):
        self.assertEqual(read_class_name("/nonexistent.class"), "")

    def test_read_class_name_short_and_bad_magic(self):
        short = _write_class(b"\xca\xfe\xba")
        bad = _write_class(b"\x00" * 12)
        try:
            self.assertEqual(read_class_name(short), "")
            self.assertEqual(read_class_name(bad), "")
        finally:
            Path(short).unlink()
            Path(bad).unlink()

    def test_read_class_info_short_and_bad_magic(self):
        short = _write_class(b"\xca\xfe\xba")
        bad = _write_class(b"\x00" * 12)
        try:
            self.assertEqual(read_class_info(short), ("", ""))
            self.assertEqual(read_class_info(bad), ("", ""))
        finally:
            Path(short).unlink()
            Path(bad).unlink()


# Minimal fixture mirroring the exact upstream signatures that
# apply_fast_javap rewrites.
_JAVAP_FIXTURE = '''\
import subprocess

bash_cmd_line_maxlimit = 1000


def get_source_file_of_class_file(classfile):
    cmd = "javap " + classfile
    return get_shell_cmd_output(cmd)


def get_source_file_of_class_files_internal(classfiles):
    return [get_source_file_of_class_file(c) for c in classfiles]


def get_source_file_of_class_files(afiles):
    return get_source_file_of_class_files_internal(afiles)


def get_class_name_of_class_file(classfile):
    return "javap parse"


def get_javap_info_of_class_file(classfile):
    return ("a", "b")
'''


class TestJavapApplier(unittest.TestCase):
    """apply_fast_javap.main() rewrites the upstream script correctly."""

    def _apply(self, target):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            count = apply_fast_javap.main(target)
        return count, buf.getvalue()

    def _write(self, td, text):
        target = os.path.join(td, "bomsh_create_bom_java.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        return target

    def test_rewrites_and_compiles(self):
        with tempfile.TemporaryDirectory() as td:
            target = self._write(td, _JAVAP_FIXTURE)
            count, stdout = self._apply(target)
            self.assertEqual(count, 6)  # import + 5 functions

            with open(target, encoding="utf-8") as f:
                patched = f.read()
            self.assertIn(
                "from bomsh_java_fast_classreader import", patched
            )
            self.assertIn("return _fast_read_sf(classfile)", patched)
            self.assertIn("return _fast_read_sfs(classfiles)", patched)
            self.assertIn("_fast_read_ci(classfile)", patched)
            # bash length limit removed; no javap shell-out remains.
            self.assertNotIn("bash_cmd_line_maxlimit", patched)
            self.assertNotIn('"javap ', patched)
            py_compile.compile(target, doraise=True)
            self.assertIn("replacements applied", stdout)

    def test_idempotent_import(self):
        with tempfile.TemporaryDirectory() as td:
            target = self._write(td, _JAVAP_FIXTURE)
            self._apply(target)
            self._apply(target)
            with open(target, encoding="utf-8") as f:
                patched = f.read()
            self.assertEqual(
                patched.count(
                    "from bomsh_java_fast_classreader import"
                ),
                1,
            )

    def test_fails_fast_on_missing_function(self):
        fixture = _JAVAP_FIXTURE.replace(
            "def get_javap_info_of_class_file(classfile):",
            "def renamed_info(classfile):",
        )
        with tempfile.TemporaryDirectory() as td:
            target = self._write(td, fixture)
            with self.assertRaises(SystemExit) as ctx:
                self._apply(target)
            self.assertIn("get_javap_info_of_class_file", str(ctx.exception))
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read(), fixture)

    def test_fails_fast_on_missing_import_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            target = self._write(
                td, "def get_source_file_of_class_file(classfile):\n"
                    "    pass\n",
            )
            with self.assertRaises(SystemExit):
                self._apply(target)

    def test_default_target_constant(self):
        self.assertTrue(
            apply_fast_javap.DEFAULT_TARGET.endswith(
                "bomsh_create_bom_java.py"
            )
        )


class TestReadSourceFileData(unittest.TestCase):
    """Tests for the in-memory (bytes) SourceFile readers."""

    def test_valid_bytes_match_path_reader(self):
        data = _build_classfile("Bar.java")
        self.assertEqual(read_source_file_data(data), "Bar.java")

    def test_parity_with_path_reader(self):
        data = _build_classfile("Baz.java")
        with tempfile.NamedTemporaryFile(
            suffix=".class", delete=False
        ) as f:
            f.write(data)
            path = f.name
        try:
            self.assertEqual(
                read_source_file_data(data), read_source_file(path)
            )
        finally:
            Path(path).unlink()

    def test_empty_bytes(self):
        self.assertEqual(read_source_file_data(b""), "")

    def test_too_short(self):
        self.assertEqual(read_source_file_data(b"\x00\x01\x02"), "")

    def test_bad_magic(self):
        self.assertEqual(read_source_file_data(b"\x00" * 32), "")

    def test_truncated_after_magic(self):
        data = _build_classfile("Foo.java")[:12]
        self.assertEqual(read_source_file_data(data), "")

    def test_list_wrapper_parity(self):
        datas = [
            _build_classfile("A.java"),
            _build_classfile("B.java"),
        ]
        self.assertEqual(
            read_source_files_data(datas), ["A.java", "B.java"]
        )

    def test_list_wrapper_empty(self):
        self.assertEqual(read_source_files_data([]), [])


if __name__ == "__main__":
    unittest.main()
