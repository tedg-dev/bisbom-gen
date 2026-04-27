"""
Fast pure-Python reader for Java .class file SourceFile attribute.

Replaces javap-based extraction in bomsh_create_bom_java.py.
Reading the SourceFile attribute from .class bytecode is trivial
— the binary format is specified in JVM Spec §4.1. Each read
takes microseconds vs ~1 second for a javap subprocess (JVM
startup overhead).

Performance: 6,000 class files in <1s (vs ~100 minutes with javap).
"""

import struct


# Constant pool tag sizes (bytes after the tag byte)
# See JVM Spec §4.4
_CP_TAG_SIZES = {
    # tag: fixed_size (or -1 for variable-length Utf8)
    1: -1,   # CONSTANT_Utf8: u2 length + bytes
    3: 4,    # CONSTANT_Integer
    4: 4,    # CONSTANT_Float
    5: 8,    # CONSTANT_Long (occupies 2 slots)
    6: 8,    # CONSTANT_Double (occupies 2 slots)
    7: 2,    # CONSTANT_Class
    8: 2,    # CONSTANT_String
    9: 4,    # CONSTANT_Fieldref
    10: 4,   # CONSTANT_Methodref
    11: 4,   # CONSTANT_InterfaceMethodref
    12: 4,   # CONSTANT_NameAndType
    15: 3,   # CONSTANT_MethodHandle
    16: 2,   # CONSTANT_MethodType
    17: 4,   # CONSTANT_Dynamic
    18: 4,   # CONSTANT_InvokeDynamic
    19: 2,   # CONSTANT_Module
    20: 2,   # CONSTANT_Package
}


def read_source_file(classfile):
    """Read SourceFile attribute from a .class file.

    Returns the source filename string (e.g. "Foo.java"),
    or empty string if not found or on error.
    """
    try:
        with open(classfile, 'rb') as f:
            data = f.read()
    except (OSError, IOError):
        return ''

    if len(data) < 10:
        return ''
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic != 0xCAFEBABE:
        return ''

    try:
        return _parse_source_file(data)
    except (struct.error, IndexError, KeyError):
        return ''


def _parse_source_file(data):
    """Parse .class bytecode to extract SourceFile attribute."""
    pos = 8  # skip magic(4) + minor(2) + major(2)
    cp_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2

    # Parse constant pool — we need UTF-8 entries
    utf8 = {}
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:  # CONSTANT_Utf8
            length = struct.unpack_from('>H', data, pos)[0]
            pos += 2
            utf8[i] = data[pos:pos + length].decode(
                'utf-8', errors='replace'
            )
            pos += length
        else:
            size = _CP_TAG_SIZES.get(tag)
            if size is None:
                return ''
            pos += size
            if tag in (5, 6):  # Long/Double use 2 slots
                i += 1
        i += 1

    # Skip access_flags(2) + this_class(2) + super_class(2)
    pos += 6

    # Skip interfaces
    iface_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2 + iface_count * 2

    # Skip fields
    pos = _skip_members(data, pos)

    # Skip methods
    pos = _skip_members(data, pos)

    # Read class-level attributes — look for SourceFile
    attrs_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2
    for _ in range(attrs_count):
        name_idx = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        attr_len = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        if utf8.get(name_idx) == 'SourceFile' and attr_len == 2:
            sf_idx = struct.unpack_from('>H', data, pos)[0]
            return utf8.get(sf_idx, '')
        pos += attr_len

    return ''


def _skip_members(data, pos):
    """Skip a fields or methods table.

    Both have identical structure:
    u2 count, then count * {
        u2 access_flags, u2 name_index, u2 descriptor_index,
        u2 attributes_count, attributes_count * {
            u2 name_index, u4 length, u1 info[length]
        }
    }
    """
    count = struct.unpack_from('>H', data, pos)[0]
    pos += 2
    for _ in range(count):
        pos += 6  # access_flags + name_index + descriptor_index
        attrs_count = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        for _ in range(attrs_count):
            pos += 2  # attribute_name_index
            attr_len = struct.unpack_from('>I', data, pos)[0]
            pos += 4 + attr_len
    return pos


def read_class_name(classfile):
    """Read the fully-qualified class name from a .class file.

    Returns dotted name (e.g. "com.example.Foo") or empty string.
    """
    try:
        with open(classfile, 'rb') as f:
            data = f.read()
    except (OSError, IOError):
        return ''

    if len(data) < 10:
        return ''
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic != 0xCAFEBABE:
        return ''

    try:
        return _parse_class_name(data)
    except (struct.error, IndexError, KeyError):
        return ''


def read_class_info(classfile):
    """Read both SourceFile and class name from a .class file.

    Drop-in replacement for get_javap_info_of_class_file().
    Returns (source_file, class_name) tuple.
    """
    try:
        with open(classfile, 'rb') as f:
            data = f.read()
    except (OSError, IOError):
        return ('', '')

    if len(data) < 10:
        return ('', '')
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic != 0xCAFEBABE:
        return ('', '')

    try:
        return _parse_class_info(data)
    except (struct.error, IndexError, KeyError):
        return ('', '')


def read_source_files(classfiles):
    """Read SourceFile for a list of .class files.

    Drop-in replacement for
    get_source_file_of_class_files_internal().
    """
    return [read_source_file(f) for f in classfiles]


def _parse_class_name(data):
    """Parse .class bytecode to extract class name."""
    pos = 8
    cp_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2

    utf8 = {}
    class_names = {}  # index -> name_index
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:  # CONSTANT_Utf8
            length = struct.unpack_from('>H', data, pos)[0]
            pos += 2
            utf8[i] = data[pos:pos + length].decode(
                'utf-8', errors='replace'
            )
            pos += length
        elif tag == 7:  # CONSTANT_Class
            name_idx = struct.unpack_from('>H', data, pos)[0]
            class_names[i] = name_idx
            pos += 2
        else:
            size = _CP_TAG_SIZES.get(tag)
            if size is None:
                return ''
            pos += size
            if tag in (5, 6):
                i += 1
        i += 1

    # this_class is right after constant pool
    pos += 2  # access_flags
    this_class = struct.unpack_from('>H', data, pos)[0]
    name_idx = class_names.get(this_class, 0)
    internal = utf8.get(name_idx, '')
    return internal.replace('/', '.')


def _parse_class_info(data):
    """Parse .class bytecode to extract both SourceFile and class name."""
    pos = 8
    cp_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2

    utf8 = {}
    class_names = {}
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            length = struct.unpack_from('>H', data, pos)[0]
            pos += 2
            utf8[i] = data[pos:pos + length].decode(
                'utf-8', errors='replace'
            )
            pos += length
        elif tag == 7:
            name_idx = struct.unpack_from('>H', data, pos)[0]
            class_names[i] = name_idx
            pos += 2
        else:
            size = _CP_TAG_SIZES.get(tag)
            if size is None:
                return ('', '')
            pos += size
            if tag in (5, 6):
                i += 1
        i += 1

    # Read access_flags + this_class
    pos += 2  # access_flags
    this_class = struct.unpack_from('>H', data, pos)[0]
    pos += 2
    name_idx = class_names.get(this_class, 0)
    class_name = utf8.get(name_idx, '').replace('/', '.')

    # Skip super_class
    pos += 2

    # Skip interfaces
    iface_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2 + iface_count * 2

    # Skip fields and methods
    pos = _skip_members(data, pos)
    pos = _skip_members(data, pos)

    # Find SourceFile attribute
    source_file = ''
    attrs_count = struct.unpack_from('>H', data, pos)[0]
    pos += 2
    for _ in range(attrs_count):
        attr_name_idx = struct.unpack_from('>H', data, pos)[0]
        pos += 2
        attr_len = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        if utf8.get(attr_name_idx) == 'SourceFile' and attr_len == 2:
            sf_idx = struct.unpack_from('>H', data, pos)[0]
            source_file = utf8.get(sf_idx, '')
        pos += attr_len

    return (source_file, class_name)
