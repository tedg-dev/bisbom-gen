#!/usr/bin/env python3
"""Apply fast javap replacement to bomsh_create_bom_java.py.

Replaces javap subprocess calls with pure-Python .class bytecode
reader imports. Uses regex patterns for robust matching.
"""
import re
import sys

# Default target is the container path; tests pass an explicit fixture path.
DEFAULT_TARGET = "/opt/bomsh/scripts/bomsh_create_bom_java.py"

# Import injected after 'import subprocess' in the upstream script.
IMPORT_LINE = (
    "from bomsh_java_fast_classreader import "
    "read_source_file as _fast_read_sf, "
    "read_source_files as _fast_read_sfs, "
    "read_class_info as _fast_read_ci"
)

# Body for the get_source_file_of_class_files wrapper (no bash length limit).
_WRAPPER_BODY = (
    "bundle_files = _fast_read_sfs(afiles)\n"
    '    verbose("Total number of SourceFile attributes found: "'
    ' + str(len(bundle_files)))\n'
    "    return bundle_files"
)

# (name, params, new_body, docstring) for each upstream function rewritten.
REPLACEMENTS = [
    ("get_source_file_of_class_file", "classfile",
     "return _fast_read_sf(classfile)",
     "Get SourceFile attribute. Pure-Python bytecode reader (no JVM)."),
    ("get_source_file_of_class_files_internal", "classfiles",
     "return _fast_read_sfs(classfiles)",
     "Get SourceFile for a list of .class files. No JVM needed."),
    ("get_source_file_of_class_files", "afiles",
     _WRAPPER_BODY,
     "Get SourceFile for .class files. No bash length limits needed."),
    ("get_class_name_of_class_file", "classfile",
     "_, class_name = _fast_read_ci(classfile)\n    return class_name",
     "Get full class name. Pure-Python bytecode reader (no JVM)."),
    ("get_javap_info_of_class_file", "classfile",
     "return _fast_read_ci(classfile)",
     "Get SourceFile and class name. Pure-Python reader (no JVM)."),
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

    if "bomsh_java_fast_classreader" in content:
        pass  # already patched (idempotent re-run)
    elif "import subprocess\n" in content:
        content = content.replace(
            "import subprocess\n",
            "import subprocess\n" + IMPORT_LINE + "\n",
        )
        print("[OK] Added fast classreader import")
        applied += 1
    else:
        missing.append("import subprocess (import anchor)")

    # Remove the now-unused bash command length limit (non-fatal cleanup).
    content = re.sub(r"\nbash_cmd_line_maxlimit = \d+\n", "\n", content)

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
            "apply_fast_javap: upstream drift, functions not found: "
            + ", ".join(missing)
        )

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(content)
    print(f"[DONE] {applied} replacements applied")
    return applied


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
