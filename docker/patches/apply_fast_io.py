#!/usr/bin/env python3
"""Apply fast-IO replacements to bomsh_create_bom_java.py.

Replaces subprocess-spawning helpers (git hash-object, diff -q, find,
jar -xf, file) with pure-Python equivalents from bomsh_java_fast_io.py,
and adds a parallel pre-hash pass that warms the hash memo cache. Uses
regex matching on ``def <name>(<params>):`` like apply_fast_javap.py so
it is resilient to surrounding upstream changes.
"""
import re
import sys

# Default target is the container path; tests pass an explicit fixture path.
DEFAULT_TARGET = "/opt/bomsh/scripts/bomsh_create_bom_java.py"

# Import injected after 'import subprocess' in the upstream script.
IMPORT_LINE = (
    "from bomsh_java_fast_io import (\n"
    "    git_blob_hash as _fast_git_hash,\n"
    "    files_have_same_content as _fast_same_content,\n"
    "    find_suffix_files as _fast_find_suffix,\n"
    "    safe_extract_jar as _fast_extract_jar,\n"
    "    is_zip_file as _fast_is_zip,\n"
    "    build_hash_cache as _fast_build_cache,\n"
    ")"
)

# Body for find_all_java_and_class_files: original behaviour plus a parallel
# pre-hash pass that warms the git-hash memo cache.
_NEW_FIND_BODY = "\n    ".join([
    'javafiles = find_all_suffix_files(rootdir, ".java")',
    'classfiles = find_all_suffix_files(rootdir, ".class")',
    "add_files_to_dict(g_java_files, javafiles)",
    "add_files_to_dict(g_class_files, classfiles)",
    "_fast_build_cache(javafiles + classfiles)",
    'print("Found " + str(len(javafiles)) + " .java files and "'
    ' + str(len(classfiles)) + " .class files in rootdir " + rootdir)',
    "return (javafiles, classfiles)",
])

# (name, params, new_body, docstring) for each upstream function rewritten.
REPLACEMENTS = [
    ("get_git_file_hash", "afile",
     "return _fast_git_hash(afile)",
     "Git blob hash via pure-Python SHA-1 (no git subprocess)."),
    ("is_same_file_content", "afile, bfile",
     "return _fast_same_content(afile, bfile)",
     "Byte-for-byte content compare via filecmp (no diff subprocess)."),
    ("find_all_suffix_files", "builddir, suffix",
     "return _fast_find_suffix(builddir, suffix)",
     "Find suffix files via os.walk, sorted (no find subprocess)."),
    ("unbundle_jar_file", "jarfile, destdir",
     "_fast_extract_jar(jarfile, destdir)",
     "Extract JAR via zipfile with Zip-Slip guard (no jar subprocess)."),
    ("is_jar_file", "afile",
     "return _fast_is_zip(afile)",
     "Archive detection via zipfile.is_zipfile (no file subprocess)."),
    ("find_all_java_and_class_files", "rootdir",
     _NEW_FIND_BODY,
     "Find .java/.class files, register them, and parallel pre-hash."),
]


def _replace_func(content, name, params, new_body, docstring):
    """Replace a function body by matching its def line via regex.

    Returns (new_content, replaced) where replaced is False if the
    function signature was not found (signals upstream drift).
    """
    pattern = re.compile(
        r"(def " + re.escape(name) + r"\(" + re.escape(params) + r"\):\n)"
        r"(.*?)(?=\ndef |\nclass |\n####|\Z)",
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return content, False
    replacement = (
        f"def {name}({params}):\n"
        f'    """\n    {docstring}\n    """\n'
        f"    {new_body}\n"
    )
    return content[:match.start()] + replacement + content[match.end():], True


def main(target=DEFAULT_TARGET):
    """Rewrite ``target`` in place. Exits non-zero on upstream drift."""
    with open(target, "r", encoding="utf-8") as handle:
        content = handle.read()

    applied = 0
    missing = []

    if "bomsh_java_fast_io" in content:
        pass  # already patched (idempotent re-run)
    elif "import subprocess\n" in content:
        content = content.replace(
            "import subprocess\n",
            "import subprocess\n" + IMPORT_LINE + "\n",
        )
        print("[OK] Added fast-IO import")
        applied += 1
    else:
        missing.append("import subprocess (import anchor)")

    for name, params, body, doc in REPLACEMENTS:
        content, replaced = _replace_func(content, name, params, body, doc)
        if replaced:
            print(f"[OK] Replaced {name}")
            applied += 1
        else:
            print(f"[ERROR] {name} not found")
            missing.append(name)

    if missing:
        raise SystemExit(
            "apply_fast_io: upstream drift, functions not found: "
            + ", ".join(missing)
        )

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)
    print(f"[DONE] {applied} replacements applied")
    return applied


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
