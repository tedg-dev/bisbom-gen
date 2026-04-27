#!/usr/bin/env python3
"""Apply fast javap replacement to bomsh_create_bom_java.py.

Replaces javap subprocess calls with pure-Python .class bytecode
reader imports. Uses regex patterns for robust matching.
"""
import re

TARGET = "/opt/bomsh/scripts/bomsh_create_bom_java.py"

with open(TARGET, "r") as f:
    content = f.read()

changes = 0

# 1. Add import after 'import subprocess'
IMPORT_LINE = (
    "from bomsh_java_fast_classreader import "
    "read_source_file as _fast_read_sf, "
    "read_source_files as _fast_read_sfs, "
    "read_class_info as _fast_read_ci"
)
if IMPORT_LINE not in content:
    content = content.replace(
        "import subprocess\n",
        "import subprocess\n" + IMPORT_LINE + "\n",
    )
    print("[OK] Added fast classreader import")
    changes += 1

# Helper: replace a function body by matching its def line
def replace_func(name, params, new_body, docstring=None):
    global content, changes
    # Match from def line through to next def or class at same indent
    pattern = re.compile(
        r"(def " + re.escape(name) + r"\(" + re.escape(params) + r"\):\n)"
        r"(.*?)(?=\ndef |\nclass |\n####|\Z)",
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        print(f"[WARN] {name} not found")
        return
    doc = docstring or f"Fast bytecode reader replacement for {name}."
    replacement = (
        f"def {name}({params}):\n"
        f'    """\n    {doc}\n    """\n'
        f"    {new_body}\n"
    )
    content = content[:m.start()] + replacement + content[m.end():]
    print(f"[OK] Replaced {name}")
    changes += 1

# 2. get_source_file_of_class_file
replace_func(
    "get_source_file_of_class_file", "classfile",
    "return _fast_read_sf(classfile)",
    "Get SourceFile attribute. Pure-Python bytecode reader (no JVM).",
)

# 3. get_source_file_of_class_files_internal
replace_func(
    "get_source_file_of_class_files_internal", "classfiles",
    "return _fast_read_sfs(classfiles)",
    "Get SourceFile for a list of .class files. No JVM needed.",
)

# 4. get_source_file_of_class_files (wrapper — also remove bash_cmd_line_maxlimit)
# Remove the bash limit constant first
content = re.sub(
    r"\nbash_cmd_line_maxlimit = \d+\n",
    "\n",
    content,
)
replace_func(
    "get_source_file_of_class_files", "afiles",
    (
        "bundle_files = _fast_read_sfs(afiles)\n"
        '    verbose("Total number of SourceFile attributes found: "'
        ' + str(len(bundle_files)))\n'
        "    return bundle_files"
    ),
    "Get SourceFile for .class files. No bash length limits needed.",
)

# 5. get_class_name_of_class_file
replace_func(
    "get_class_name_of_class_file", "classfile",
    "_, class_name = _fast_read_ci(classfile)\n    return class_name",
    "Get full class name. Pure-Python bytecode reader (no JVM).",
)

# 6. get_javap_info_of_class_file
replace_func(
    "get_javap_info_of_class_file", "classfile",
    "return _fast_read_ci(classfile)",
    "Get SourceFile and class name. Pure-Python bytecode reader (no JVM).",
)

with open(TARGET, "w") as f:
    f.write(content)

print(f"[DONE] {changes} replacements applied")
