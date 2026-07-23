#!/usr/bin/env python3
"""Apply in-memory JAR class processing to bomsh_create_bom_java.py.

The upstream JAR processor extracts every ``.jar`` to a temp directory
(``jar -xf``), walks the tree to find ``.class`` files, hashes them on
disk, then ``rmtree``s the directory. For JAR-heavy builds this
per-JAR extract -> walk -> delete lifecycle dominates the reporting step.

This applier rewrites ``process_jar_file`` and ``process_class_file`` so
that ``.class`` bytes are read straight from the archive in memory and
hashed with ``git_blob_hash_data`` -- no extraction to disk. The treedb
output is unchanged: each class is still content-matched against the
workspace ``.class`` files (``g_class_files``) and recorded under its
workspace path, and unmatched classes still record the synthetic
``<tmp_unbundle_dir>/<jar>/<entry>`` path, byte-for-byte as before.

Like ``apply_fast_io.py`` it matches ``def <name>(<params>):`` via regex
so it is resilient to surrounding upstream changes, is idempotent, and
exits non-zero on upstream drift (a missing target function).
"""
import re
import sys

# Default target is the container path; tests pass an explicit fixture path.
DEFAULT_TARGET = "/opt/bomsh/scripts/bomsh_create_bom_java.py"

# Marker used for idempotency: presence means the file is already patched.
MARKER = "_fast_iter_jar_classes"

# Imports injected after 'import subprocess' in the upstream script.
IMPORT_LINE = (
    "from bomsh_java_fast_io import (\n"
    "    iter_jar_class_entries as _fast_iter_jar_classes,\n"
    "    git_blob_hash_data as _fast_git_hash_data,\n"
    "    find_matching_class as _fast_find_match,\n"
    ")\n"
    "from bomsh_java_fast_classreader import (\n"
    "    read_source_files_data as _fast_read_source_files_data,\n"
    ")"
)

# Rewritten process_class_file: accepts optional in-memory ``class_data``
# and matches against the workspace via the byte-aware helper. Behaviour
# is identical to upstream when class_data is None.
_CLASS_FILE = '''\
def process_class_file(classfile, rootdir, source_file='', class_data=None):
    """
    Process a single .class file (in-memory aware; identical treedb output).
    """
    if class_data is None and not os.path.isfile(classfile):
        return
    match_classfile = _fast_find_match(classfile, g_class_files, class_data)
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
'''

# Rewritten process_jar_file: reads .class bytes from the archive in
# memory instead of extracting to disk. The synthetic per-entry path
# (destdir + entry) and per-class hashing reproduce the upstream treedb.
_JAR_FILE = '''\
def process_jar_file(jarfile, rootdir):
    """
    Process a single .jar file, reading .class bytes in memory (no extract).
    """
    if not os.path.isfile(jarfile):
        return
    jarfile_abspath = jarfile
    if jarfile[0] != "/":
        jarfile_abspath = os.path.abspath(jarfile)
    destdir = os.path.join(g_tmp_unbundle_dir, os.path.basename(jarfile))
    entries = _fast_iter_jar_classes(jarfile_abspath)
    classfiles = [os.path.join(destdir, name) for name, _data in entries]
    datas = [_data for _name, _data in entries]
    source_files = _fast_read_source_files_data(datas)
    record = {"outfile": (get_git_file_hash(jarfile), jarfile), "infiles": []}
    for i in range(len(classfiles)):
        source_file = source_files[i] if source_files else ''
        classfile = process_class_file(classfiles[i], rootdir, source_file, datas[i])
        if os.path.isfile(classfile):
            ahash = get_git_file_hash(classfile)
        else:
            ahash = _fast_git_hash_data(datas[i])
        record["infiles"].append((ahash, classfile))
    update_hash_tree_db_and_gitbom(g_treedb, record)
'''

# (name, params, replacement_text) for each upstream function rewritten.
REPLACEMENTS = [
    ("process_class_file", "classfile, rootdir, source_file=''", _CLASS_FILE),
    ("process_jar_file", "jarfile, rootdir", _JAR_FILE),
]


def _replace_func(content, name, params, new_text):
    """Replace a whole function, matched by its ``def`` line, via regex.

    Returns (new_content, replaced); replaced is False when the signature
    is not found (signals upstream drift).
    """
    pattern = re.compile(
        r"(def " + re.escape(name) + r"\(" + re.escape(params) + r"\):\n)"
        r"(.*?)(?=\ndef |\nclass |\n####|\Z)",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return content, False
    return content[:match.start()] + new_text + content[match.end():], True


def main(target=DEFAULT_TARGET):
    """Rewrite ``target`` in place. Exits non-zero on upstream drift."""
    with open(target, "r", encoding="utf-8") as handle:
        content = handle.read()

    if MARKER in content:
        print("[SKIP] in-memory JAR patch already applied")
        return 0

    applied = 0
    missing = []

    if "import subprocess\n" in content:
        content = content.replace(
            "import subprocess\n",
            "import subprocess\n" + IMPORT_LINE + "\n",
        )
        print("[OK] Added in-memory JAR imports")
        applied += 1
    else:
        missing.append("import subprocess (import anchor)")

    for name, params, new_text in REPLACEMENTS:
        content, replaced = _replace_func(content, name, params, new_text)
        if replaced:
            print(f"[OK] Rewrote {name}")
            applied += 1
        else:
            print(f"[ERROR] {name} not found")
            missing.append(name)

    if missing:
        raise SystemExit(
            "apply_inmemory_jar: upstream drift, not found: "
            + ", ".join(missing)
        )

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)
    print(f"[DONE] {applied} changes applied")
    return applied


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
