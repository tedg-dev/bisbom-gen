# Patch: bomsh_create_bom_java.py — SourceFile Attribute Crash

**File:** `scripts/bomsh_create_bom_java.py`
**Upstream repo:** [omnibor/bomsh](https://github.com/omnibor/bomsh)
**Date:** 2026-03-26
**Author:** bisbom-gen project (tedg-dev/omnibor-analysis)

## Bug Description

`bomsh_create_bom_java.py` crashes with an `UnboundLocalError` when
processing JAR files that contain `.class` files without `SourceFile`
bytecode attributes.

### Error

```
Warning: Different number 0 of SourceFile attributes than number 184 of .class files
Traceback (most recent call last):
  File "/opt/bomsh/scripts/bomsh_create_bom_java.py", line 999, in <module>
    main()
  ...
  File "/opt/bomsh/scripts/bomsh_create_bom_java.py", line 780, in process_jar_file
    classfile = process_class_file(classfile, rootdir, source_file)
UnboundLocalError: local variable 'source_file' referenced before assignment
```

### Root Cause

In `process_jar_file()` (line ~776), the variable `source_file` is only
assigned inside an `if source_files:` block, but is referenced
unconditionally on the next line:

```python
for i in range(len(classfiles)):
     classfile = classfiles[i]
     if source_files:             # ← skipped when source_files is empty
         source_file = source_files[i]
     classfile = process_class_file(classfile, rootdir, source_file)
     #                                                  ^^^^^^^^^^^
     #                                         never assigned → UnboundLocalError
```

When `get_source_file_of_class_files()` returns an empty list (because
the JAR's `.class` files have no `SourceFile` attributes), the `if`
block is never entered, and `source_file` is undefined when
`process_class_file()` is called.

### Reproducer

Any JAR whose `.class` files lack `SourceFile` attributes triggers this.
Observed with [OWASP DependencyCheck](https://github.com/jeremylong/DependencyCheck)
v9.2.0, whose `dependency-check-utils-9.2.0.jar` contains generated or
stripped classes without SourceFile metadata.

## Fix

Initialize `source_file = ''` before the loop. This matches the default
parameter of `process_class_file(classfile, rootdir, source_file='')`,
so the function already handles empty strings correctly — it falls back
to strace-based or heuristic source file resolution.

### Patch

```diff
--- a/scripts/bomsh_create_bom_java.py
+++ b/scripts/bomsh_create_bom_java.py
@@ -773,6 +773,7 @@ def process_jar_file(jarfile, rootdir):
     #print(classfiles)
     record = {"outfile": (get_git_file_hash(jarfile), jarfile), "infiles": []}
     for i in range(len(classfiles)):
+         source_file = ''
          classfile = classfiles[i]
          if source_files:
              source_file = source_files[i]
```

## Impact

- **Without patch:** Any multi-module Java project with generated or
  stripped classes causes a hard crash, preventing OmniBOR treedb
  generation for the entire project.
- **With patch:** Processing continues normally. Classes without
  SourceFile attributes use strace-based or filename-heuristic resolution
  instead, which is the existing fallback path in `process_class_file()`.

## Upstream Submission

This patch should be submitted as a pull request to
[omnibor/bomsh](https://github.com/omnibor/bomsh). The fix is a single
line addition with no behavioral change for JARs that already have
SourceFile attributes.
