# In-Memory JAR Class Processing — Deep Dive (A8 / #11055)

| | |
|---|---|
| **Work item** | Main A / Sub **A8** — build efficiency: fully in-memory JAR class processing (no extract-to-disk) |
| **Tracker** | `CiscoSecurityServices/gambit#11055` (parentless; detached from `#11005`) |
| **User story** | US-4 in `docs/planning/java/phase1-build-speed-subissues.md` |
| **Local PR branch** | `feat/a8-inmemory-jar-11055` (this repo) |
| **Upstream target** | `omnibor/bomsh` `scripts/bomsh_create_bom_java.py` |
| **Author** | Cascade |
| **Status** | Implemented + unit-proven locally; **gated on EC2 golden validation** before merge |

---

## 1. Summary

The Java Phase 1 component processor extracts every `.jar` to a temp
directory, walks the tree for `.class` files, hashes them on disk, then
deletes the directory. For JAR-heavy builds this extract → walk → delete
lifecycle dominates the post-build reporting step.

A8 replaces that lifecycle with **reading each `.class` entry's bytes
directly from the archive in memory** and hashing the bytes. The change
is a pure build-speed optimization: the emitted treedb — and therefore
the SPDX SBOM — must be **byte-for-byte identical** to today's output.

The non-obvious part (and the reason careful analysis of the upstream
source was required) is that the treedb does **not** key entries by the
extracted temp path. It content-matches each extracted class against the
build **workspace** `.class` files and records the **workspace** path,
falling back to a **synthetic** temp path for classes with no workspace
match. Reproducing those exact keys without extracting to disk is the
whole problem.

---

## 2. Motivation & problem

The upstream JAR processor, per JAR, performs:

1. `jar -xf` (or our `safe_extract_jar`) into
   `<g_tmp_unbundle_dir>/<jar-basename>/`.
2. `find` for `*.class` under that directory.
3. A `git hash-object` per class (replaced by our fast-IO pure-Python
   `git_blob_hash`).
4. `shutil.rmtree` of the temp directory.

For a build with many JARs (e.g. a Maven multi-module project resolving
hundreds of dependency JARs), steps 1 and 4 are pure disk churn: write
every class to disk only to hash it and immediately delete it. Estimated
savings are on the order of seconds to tens of seconds for JAR-heavy
builds, entirely in the Phase 1 build window where the guiding
constraint is **lowest possible impact on the CI/CD build cycle**.

Reading class bytes straight from the ZIP (a JAR is a ZIP) removes the
entire unbundle → find → `rmtree` cycle. The git blob id of a class is a
pure function of its bytes, so the fingerprints are unchanged.

---

## 3. How we consume bomsh (pin + build-time appliers)

We do **not** fork or vendor `omnibor/bomsh`. The Dockerfile clones it at
a pinned commit and monkey-patches it at build time:

- `docker/Dockerfile`: `ARG BOMSH_COMMIT=5823f7db7e5bd958e4ff868ae6ea79a7d871bb07`
  (2024-10-31), `git clone` + `git checkout "$BOMSH_COMMIT"`.
- Patches live in `docker/patches/` as **appliers** that rewrite specific
  functions of the pinned script via regex on the `def` signature,
  fail-fast on upstream drift, and are idempotent. Existing examples:
  `apply_fast_javap.py` (javap → pure-Python bytecode reader) and
  `apply_fast_io.py` (`git hash-object`/`diff`/`find`/`jar`/`file` →
  pure-Python helpers in `bomsh_java_fast_io.py`).

Upstream status (verified 2026-07-14):

| Check | Result |
|---|---|
| Pinned commit date | 2024-10-31 |
| `omnibor/bomsh` default branch `main` HEAD | same commit `5823f7db…` |
| Commits since our pin (`compare pin...main`) | **0** — upstream is dormant |
| Our open upstream issues | `#80`, `#81`, `#82`, `#83` (libtool/Go/QEMU) |
| Our open upstream PRs | `#84`, `#85` (Go/bomtrace2), open ~2 months |

None of our open upstream items touch the Java JAR processor, and none
have been merged. Consequently A8 ships as **another build-time applier
in our repo** — the same proven mechanism — with no dependency on an
unresponsive upstream. The upstream sections below (§9) exist so the same
change can *also* be proposed upstream if desired.

---

## 4. Upstream code analysis (the crux)

Source read from `omnibor/bomsh@5823f7db` `scripts/bomsh_create_bom_java.py`
(999 lines). The two functions A8 rewrites, verbatim:

### 4.1 `process_jar_file` — the extract-to-disk lifecycle

```python
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
```

### 4.2 `process_class_file` — content-match → workspace path

```python
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
```

`find_matching_file_in_dict` matches by **basename + identical content**
(`is_same_file_content`, a byte-for-byte compare) against `g_class_files`
(a `basename -> [workspace paths]` dict built by walking the build tree).

### 4.3 The treedb key convention (why naive in-memory would break)

`update_hash_tree_db_and_gitbom` keys the treedb by **git blob checksum**
and records a **filepath** per node. Tracing the paths that actually land
in the treedb:

| Case | Path recorded in treedb | Hash recorded |
|---|---|---|
| Class **matches** a workspace file | the **workspace** path (`match_classfile`) | `git_blob_hash(workspace_file)` |
| Class has **no** workspace match | the **synthetic** temp path `<g_tmp_unbundle_dir>/<jar>/<entry>` | `git_blob_hash(extracted_temp_file)` |

Two consequences that any correct in-memory rewrite must honor:

1. **Matched classes** must still be found by content against
   `g_class_files` and recorded under the workspace path — so the
   comparison operand (previously the extracted temp file) becomes the
   in-memory bytes.
2. **Unmatched classes** must still record the exact synthetic string
   `os.path.join(g_tmp_unbundle_dir, basename(jar), entry_name)` and a
   hash equal to the class bytes' blob id. Since the extracted temp file
   had identical bytes, `git_blob_hash(temp_file)` equals
   `git_blob_hash_data(bytes)` — so hashing the in-memory bytes
   reproduces the value without ever writing the file.

Ordering also matters: the JAR's `infiles` list order comes from
`find_all_suffix_files`, which (after `apply_fast_io`) returns **sorted
full paths**. Sorting ZIP member names is equivalent because the
`<destdir>/` prefix is common to every entry and does not change relative
order.

---

## 5. Design

### 5.1 Primitives (unit-testable, no pipeline wiring)

Added to `docker/patches/bomsh_java_fast_classreader.py`:

- `read_source_file_data(data)` / `read_source_files_data(datas)` — read
  the `SourceFile` attribute from in-memory `.class` bytes. The existing
  `_parse_source_file` already operated on bytes; these are thin public
  wrappers with the same magic/length guards as the path-based readers.

Added to `docker/patches/bomsh_java_fast_io.py`:

- `iter_jar_class_entries(jarfile)` — returns sorted `(member_name, data)`
  for every `.class` in the archive, read via `zipfile` with no
  extraction. Excludes directory entries. Falls back to extract-to-temp
  (`_iter_class_entries_fallback`, itself using `safe_extract_jar`) only
  for archives `zipfile` cannot parse, preserving parity with the
  upstream `jar -xf` behavior for non-standard archives.
- `bytes_same_as_file(data, path)` — byte-for-byte compare of in-memory
  bytes to a workspace file (size check first; conservative `False` on
  `OSError`, matching `files_have_same_content`).
- `find_matching_class(classfile, adict, class_data=None)` — the
  byte-aware analogue of `find_matching_file_in_dict`. With `class_data`
  it compares bytes to candidates; without it, it falls back to the
  original file/file compare (so the None path is behavior-identical).
- `git_blob_hash_data(data)` — already present; reserved for exactly this.

### 5.2 The applier

`docker/patches/apply_inmemory_jar.py` rewrites two functions in the
pinned script (regex on the `def` line, idempotent via a marker,
fail-fast on drift), wired into **both** Docker stages after
`apply_fast_io`:

- `process_class_file(classfile, rootdir, source_file='', class_data=None)`
  — adds the optional `class_data` param and uses `_fast_find_match`
  (`find_matching_class`). When `class_data is None` the behavior is
  identical to upstream.
- `process_jar_file(jarfile, rootdir)` — reads entries via
  `_fast_iter_jar_classes`, builds the same `classfiles` list as
  `os.path.join(destdir, member)`, reads source files from bytes via
  `_fast_read_source_files_data`, and for the JAR `infiles` hash uses the
  matched workspace file when present, else `_fast_git_hash_data(bytes)`.
  No extraction, no `rmtree`.

### 5.3 Parity guarantees

| Aspect | How parity is preserved |
|---|---|
| **Class fingerprints** | `git_blob_hash_data(bytes)` == `git_blob_hash(extracted_file)` (same bytes) |
| **Matched path** | same `g_class_files` content-match → same workspace path |
| **Unmatched path** | synthesized `os.path.join(destdir, member)` == old extracted path string |
| **Iteration order** | ZIP members sorted; equivalent to sorted extracted full paths (common prefix) |
| **Source files** | `read_source_file_data(bytes)` == `read_source_file(file)` (proven in tests) |
| **JAR outfile hash** | unchanged (`get_git_file_hash(jarfile)`) |
| **Non-standard archives** | extract-to-temp fallback preserves old `jar -xf` behavior |

---

## 6. Testing & equivalence proof

Local unit tests (no JDK, no network, no Docker):

- `tests/test_fast_classreader.py` — byte-based readers, incl. parity
  with the path-based readers, empty/short/bad-magic/truncated inputs.
- `tests/test_fast_io.py` — `iter_jar_class_entries` (sorting, directory
  exclusion, empty, bad-zip fallback, forced-fallback read),
  `bytes_same_as_file`, `find_matching_class` (data/path modes).
- `tests/test_apply_inmemory_jar.py` — the **equivalence proof**: a
  self-contained fixture mirroring the upstream functions is run in its
  original extract-to-disk form and again after applying
  `apply_inmemory_jar`, against the same JAR + workspace (two matched
  classes + one unmatched `Gamma`). It asserts the captured treedb
  records are **identical**, that matched classes use workspace paths
  while the unmatched class uses the synthetic `…/unbundle/…jar/…`
  path, and that the in-memory path **never creates** the unbundle dir.
  Also covers applier structure: rewrite-and-compile, idempotency,
  fail-fast on missing function, fail-fast on missing import anchor.

Result: **91 passed** across the three files; `flake8` clean on all six
files.

---

## 7. Final results

Files changed on `feat/a8-inmemory-jar-11055`:

| File | Change |
|---|---|
| `docker/patches/bomsh_java_fast_classreader.py` | + `read_source_file_data`, `read_source_files_data` |
| `docker/patches/bomsh_java_fast_io.py` | + `iter_jar_class_entries`, `bytes_same_as_file`, `find_matching_class`, `tempfile` import |
| `docker/patches/apply_inmemory_jar.py` | new applier (rewrites `process_jar_file`, `process_class_file`) |
| `docker/Dockerfile` | wire applier after `apply_fast_io` in standalone + sidecar stages |
| `tests/test_fast_classreader.py` | + byte-reader tests |
| `tests/test_fast_io.py` | + in-memory primitive tests |
| `tests/test_apply_inmemory_jar.py` | new equivalence + applier tests |

---

## 8. Remaining gate (EC2 golden validation) — mandatory

A8 changes treedb generation, so per the `regression-gate` rule it
requires a system-level golden run before the PR is declared ready:

- **Pipeline impact:** Yes (treedb → SPDX).
- **Regression repos:** Java golden set including multi-module
  `dependency-check`, plus a Gradle repo; must be golden-clean.
- **Policy:** golden files are never updated by Cascade; any diff stops
  the effort and is reported for user review.

Local unit tests prove *structural* byte-identity of the treedb records;
the EC2 run proves it end-to-end against the real bomsh script and real
JAR-heavy builds.

---

## 9. Upstream applicability (`omnibor/bomsh`)

The same change is a clean, self-contained improvement to
`bomsh_create_bom_java.py` and could be proposed upstream. Our applier is
a regex overlay of the exact edits an upstream patch would make directly.

### 9.1 Why it is upstream-worthy

- Removes real disk churn from every JAR the tool processes.
- Requires no new dependencies (`zipfile`, `hashlib` are stdlib).
- Output-preserving: same treedb, same gitBOM docs.
- Backward compatible: `process_class_file` keeps its old behavior when
  called without `class_data`.

### 9.2 Proposed upstream issue (draft)

> **Title:** `bomsh_create_bom_java.py` extracts every JAR to disk just to
> hash `.class` files
>
> **Body:** For each JAR, `process_jar_file` runs `jar -xf` into a temp
> directory, walks it for `.class` files, hashes each, then `rmtree`s the
> directory. The git blob id of a class depends only on its bytes, which
> can be read directly from the archive with `zipfile`. For JAR-heavy
> builds the extract/delete lifecycle is a measurable, avoidable cost in
> the build window. Proposal: read `.class` bytes in memory and hash them
> directly, preserving the existing treedb keys (workspace path on a
> content match; the current synthetic temp path otherwise).

### 9.3 Proposed upstream PR (draft)

- Add byte-based helpers (or inline equivalents): read `SourceFile` from
  bytes; iterate `.class` entries from the archive; compare bytes to a
  workspace file; hash bytes as a git blob.
- Rewrite `process_jar_file` to iterate archive entries in sorted member
  order (no extraction, no `rmtree`).
- Extend `process_class_file` with an optional in-memory bytes parameter
  used for the content match and hashing; unchanged when omitted.
- Keep an extract-to-temp fallback for archives `zipfile` cannot parse.

### 9.4 Risks / caveats for upstream

- **Ordering:** upstream `find` output is filesystem-ordered; if upstream
  has not adopted sorted enumeration, member-name sort must be reconciled
  with however upstream orders `infiles` to avoid a treedb diff.
- **Non-standard archives:** the `zipfile` fast path must fall back to
  `jar -xf` for archives it cannot read.
- **Encoding of member names:** POSIX `/` separators; on non-POSIX hosts
  the synthetic path join must match the platform separator used by the
  extracted-walk path.

---

## 10. Open questions / future work

- Measure the actual per-build saving on a representative multi-JAR build
  during the EC2 golden run and record it in the build doc.
- If upstream ever revives, decide whether to raise §9's issue/PR and, if
  merged, bump `BOMSH_COMMIT` and retire the applier (only after golden
  re-validation).
