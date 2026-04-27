"""Tests for bomsh_java_fast_classreader.py.

Creates synthetic .class files to test the pure-Python
bytecode reader without needing a real JDK.
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent / "docker" / "patches")
)

from bomsh_java_fast_classreader import (
    read_source_file,
    read_source_files,
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


if __name__ == "__main__":
    unittest.main()
