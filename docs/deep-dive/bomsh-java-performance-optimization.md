# `bomsh_create_bom_java.py` Performance Optimization

> **Superseded (2026-06-24):** This delivered optimization is summarized in
> the consolidated reference `docs/deep-dive/phase1-build-speed-design.md`
> (Section 3.1). This document is retained for the full root-cause analysis,
> optimization detail, and EC2 validation measurements.

| **Status** | VALIDATED — golden-clean on EC2 (June 22, 2026) — see EC2 Validation Results |
|---|---|
| **Date** | June 16, 2026 (analysis); June 18, 2026 (implementation); June 22, 2026 (EC2 validation) |
| **Author** | OmniBOR Analysis project |
| **Related** | `docs/deep-dive/phase-isolation-build-time-analysis.md` |

> **Implementation status (June 18, 2026):** Optimizations #1–#5 are
> implemented in `docker/patches/bomsh_java_fast_io.py` and applied via
> `docker/patches/apply_fast_io.py` (mirrors the existing
> `bomsh_java_fast_classreader.py` + `apply_fast_javap.py` pattern). The
> fully in-memory JAR variant (read `.class` bytes from the zip, hash with
> `git_blob_hash_data`, never extract to disk) is **deferred** to a
> follow-up PR after the extract-to-disk variant is validated against
> golden files on EC2. The appliers fail-fast on upstream drift, and
> `omnibor/bomsh` is now pinned by commit SHA in the Dockerfile
> (`ARG BOMSH_COMMIT`).

> **Validation status (June 22, 2026):** EC2-validated and golden-clean
> across all re-run Java repos (`jsoup`, `crawler4j`, `checkstyle`,
> `logging-log4j2`, `bc-java`); `dependency-check` and `spring-boot` were
> validated in a prior session. See **Section 9** for measured timings.

---

## 1. Problem Statement

Split timing data from EC2 runs (June 16, 2026) revealed that
`bomsh_create_bom_java.py` is the dominant bottleneck in the Phase 1
post-build `adg` step — not the JVM dep:tree commands as originally
hypothesized.

| Repo | `bomsh_create_bom_java.py` | dep:tree | % treedb |
|------|---------------------------|----------|----------|
| dependency-check (Maven) | 240.85s | 3.47s | **98.6%** |
| spring-boot (Gradle) | 486.09s | 139.64s | **77.7%** |

The script processes 55,673 treedb entries for dependency-check and
113,524 for spring-boot.

---

## 2. Script Architecture

The upstream script (`/opt/bomsh/scripts/bomsh_create_bom_java.py`,
918 lines, from [omnibor/bomsh](https://github.com/omnibor/bomsh))
processes each JAR file through the following pipeline:

1. **Extract JAR** — `jar -xf` to `/tmp/bomjdir/<jar>/`
2. **Find `.class` files** — `find ... -name "*.class"`
3. **Read `SourceFile` attributes** — already optimized (pure-Python
   bytecode reader, see `docker/patches/bomsh_java_fast_classreader.py`)
4. **Per `.class` file loop**:
   - Match against built `.class` files via `diff -q` (subprocess)
   - Compute `git hash-object` for the `.class` file (subprocess)
   - Resolve source `.java` file via path similarity
   - Compute `git hash-object` for the `.java` file (subprocess)
   - Update treedb and gitBOM doc structures
5. **Serialize treedb** — `json.dump()` with `indent=4, sort_keys=True`

---

## 3. Root Cause: Subprocess Spawning Per File

The script shells out to external commands for operations that have
trivial pure-Python equivalents. For a project with N `.class` files,
this creates **~3N subprocess spawns** (two `git hash-object` + one
`diff -q` per file), plus overhead from `find` and `jar -xf`.

### Subprocess Call Inventory

| Function | Line | Command | Calls per JAR | Purpose |
|----------|------|---------|---------------|---------|
| `get_git_file_hash` | 761 | `git hash-object <file>` | 2 × N `.class` files | SHA-1 hash of class + source |
| `is_same_file_content` | 204 | `diff -q <a> <b>` | N `.class` files | Match unbundled to built |
| `find_all_suffix_files` | 217 | `find <dir> -name "*.class"` | 1 per JAR | List extracted classes |
| `unbundle_jar_file` | 669 | `rm -rf; mkdir; jar -xf` | 1 per JAR | Extract JAR contents |
| `get_filetype` | 146 | `file <jar>` | 1 per JAR | Check if file is archive |

### Cost Model

Each `fork+exec` costs ~3-5ms on Linux. For dependency-check:

- ~6,000 `.class` files × 3 subprocess calls = **~18,000 subprocesses**
- At 5ms each = **~90 seconds** in process creation alone
- Remaining time: disk I/O (extract, read, hash) + JSON serialization

For spring-boot (113K treedb entries), the subprocess count is
proportionally higher.

---

## 4. Optimization Plan

All optimizations use the same Docker patch pattern established by
`docker/patches/apply_fast_javap.py` — monkey-patching upstream
functions at Docker build time without modifying the upstream repo.

### 4.1 Pure-Python `git hash-object` (Highest Impact)

**Eliminates: ~12,000+ subprocess spawns**

Git's object hash is `SHA-1("blob <size>\0<content>")`. This is a
one-line Python replacement:

```python
import hashlib

def get_git_file_hash(afile):
    with open(afile, 'rb') as f:
        data = f.read()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()
```

Python's `hashlib.sha1` uses OpenSSL's hardware-accelerated
implementation. Each call takes ~10μs vs ~5ms for `git hash-object`.

**Estimated savings: 60–120s** (dependency-check), proportionally
more for spring-boot.

### 4.2 Python `filecmp.cmp()` Instead of `diff -q` (High Impact)

**Eliminates: ~6,000 subprocess spawns**

`is_same_file_content` (line 204) shells out to `diff -q` to compare
file contents. Python's `filecmp.cmp(shallow=False)` does a
byte-for-byte comparison without forking:

```python
import filecmp

def is_same_file_content(afile, bfile):
    return filecmp.cmp(afile, bfile, shallow=False)
```

**Estimated savings: 30–60s.**

### 4.3 Python `os.walk()` Instead of `find` (Medium Impact)

**Eliminates: ~10 subprocess spawns + avoids shell quoting issues**

`find_all_suffix_files` (line 217) shells out to `find`. Python's
`os.walk` is faster for small-to-medium directory trees and avoids
shell injection risks from filenames with special characters:

```python
def find_all_suffix_files(builddir, suffix):
    result = []
    for root, _dirs, files in os.walk(builddir):
        for f in files:
            if f.endswith(suffix):
                result.append(os.path.join(root, f))
    return result
```

**Estimated savings: <1s** (few calls), but improves correctness.

### 4.4 Python `zipfile` Instead of `jar -xf` (Medium Impact)

**Eliminates: disk I/O for extraction + subprocess spawns**

JARs are ZIP files. Python's `zipfile` can extract them, or better,
read `.class` file contents **in-memory** without writing to disk:

```python
import zipfile

def process_jar_file_fast(jarfile, rootdir):
    with zipfile.ZipFile(jarfile) as zf:
        classfiles = [n for n in zf.namelist()
                      if n.endswith('.class')]
        for name in classfiles:
            data = zf.read(name)
            # Parse SourceFile from data (already have bytecode reader)
            # Compute git hash from data (no disk write needed)
```

This eliminates the entire `unbundle_jar_file` → `find` →
`shutil.rmtree` cycle. However, this is a deeper refactor since the
current `process_class_file` function expects file paths, not
in-memory data. A simpler first step is to just replace `jar -xf`
with `zipfile.extractall()`.

**Estimated savings: 5–10s** (eliminates temp dir lifecycle).

### 4.5 Parallel File Hashing (Medium Impact)

**CPU parallelism for I/O-bound + hash-bound workload**

Even with pure-Python hashing, processing 12,000+ files sequentially
has I/O latency. Thread-based parallelism helps because file reads
release the GIL:

```python
from concurrent.futures import ThreadPoolExecutor

def hash_files_parallel(files, max_workers=4):
    with ThreadPoolExecutor(max_workers) as pool:
        return dict(zip(files, pool.map(get_git_file_hash, files)))
```

**Estimated savings: 30–50% of remaining time** after patches 4.1–4.4.

### 4.6 Faster JSON Serialization (Low Impact)

`save_json_db` (line 173) uses `json.dump(db, f, indent=4,
sort_keys=True)`. For 113K entries, this is measurable. Options:

- Drop `indent=4` (compact JSON) — saves string allocation
- Use `orjson` or `ujson` if available (3–5x faster)
- Use MessagePack/CBOR for binary format (not human-readable)

**Estimated savings: 2–5s** for spring-boot scale.

---

## 5. Implementation Priority

| Priority | Optimization | Patch file | Subprocess calls eliminated | Est. savings |
|----------|-------------|------------|---------------------------|-------------|
| **P0** | Pure-Python `git hash-object` | `apply_fast_hashing.py` | ~12,000+ | 60–120s |
| **P1** | Python `filecmp.cmp()` | `apply_fast_hashing.py` | ~6,000 | 30–60s |
| **P2** | Python `os.walk()` | `apply_fast_hashing.py` | ~10 | <1s |
| **P3** | Python `zipfile.extractall()` | `apply_fast_hashing.py` | ~10 | 5–10s |
| **P4** | Parallel file hashing | `apply_fast_hashing.py` | 0 (parallelism) | 30–50% |
| **P5** | Faster JSON serialization | `apply_fast_hashing.py` | 0 | 2–5s |

P0 + P1 alone should reduce the treedb step from **240s → ~30-60s**
for dependency-check and from **486s → ~100-150s** for spring-boot.

---

## 6. Implementation Approach

All patches will be applied via a new Docker patch script following
the established pattern:

```text
docker/patches/
├── apply_fast_javap.py          # existing: javap → bytecode reader
├── apply_fast_hashing.py        # new: git/diff/find → pure Python
└── bomsh_java_fast_classreader.py  # existing: bytecode reader module
```

The Dockerfile will add a step after the existing `apply_fast_javap.py`:

```dockerfile
COPY docker/patches/apply_fast_hashing.py /tmp/
RUN python3 /tmp/apply_fast_hashing.py && rm /tmp/apply_fast_hashing.py
```

### Validation

After implementing each patch:

1. Run dependency-check + spring-boot on EC2
2. Verify `adg_substeps.json` shows reduced treedb time
3. Compare SPDX output against golden files (must be identical)
4. Verify treedb entry counts match previous runs

---

## 7. Previously Completed Optimization

The `javap` → pure-Python bytecode reader optimization was implemented
in a prior session and is already deployed:

| Before | After |
|--------|-------|
| `javap` subprocess per `.class` file (~1s each) | Pure-Python `.class` parser (~10μs each) |
| 6,000 class files: ~100 minutes | 6,000 class files: <1 second |

**Patch**: `docker/patches/apply_fast_javap.py`

**Module**: `docker/patches/bomsh_java_fast_classreader.py`

This optimization eliminated the `javap` bottleneck completely, which
is what exposed `git hash-object` and `diff -q` as the next-largest
costs.

---

## 8. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Pure-Python SHA-1 produces different hash than `git hash-object` | Unit test: hash known files, compare against `git hash-object` output |
| `filecmp.cmp` has different semantics than `diff -q` | Both do byte-for-byte comparison; `shallow=False` ensures no stat-only shortcut |
| `zipfile` cannot read corrupted/non-standard JARs | Fall back to `jar -xf` on `BadZipFile` exception |
| Parallel hashing introduces race conditions in treedb | Hash in parallel, update treedb sequentially (collect results first) |
| Upstream bomsh updates may conflict with patches | `apply_fast_hashing.py` uses regex matching like `apply_fast_javap.py`; pin bomsh commit in Dockerfile |

---

## 9. EC2 Validation Results (June 22, 2026)

The optimized appliers were re-run on the EC2 build host
(`c6i.xlarge`, 4 vCPU) in sidecar mode. All re-run Java repos produced
**golden-clean** SPDX (no structural differences beyond the intended
`packageSourceInfo` → `sourceInfo` rename and the `javac` JDK patch
bump `21.0.10` → `21.0.11`).

### Measured timings

`Build` is the Phase 1 instrumented build wall time; `Analysis` is the
Phase 2 post-build step that runs the optimized
`bomsh_create_bom_java.py` (the treedb step this optimization targets).

| Repo | Build (P1) | Analysis (P2) | Total |
|------|-----------|---------------|-------|
| `jsoup` | 18.7s | 8.4s | 27.1s |
| `crawler4j` | 9.6s | 7.6s | 17.2s |
| `checkstyle` | 26.9s | 13.2s | 40.1s |
| `logging-log4j2` | 98.2s | 18.6s | 116.7s |
| `bc-java` | 166.8s | 224.0s | 390.8s |

### Build-interception overhead (baseline → instrumented)

The pipeline also reports build overhead as the stored baseline build
wall vs the instrumented build wall.

| Repo | Baseline → Instrumented | Reported delta |
|------|--------------------------|----------------|
| `jsoup` | 25.1s → 17.0s | −32.2% |
| `crawler4j` | 98.9s → 8.2s | −91.8% |
| `checkstyle` | 41.8s → 24.9s | −40.4% |
| `logging-log4j2` | 120.9s → 96.1s | −20.5% |
| `bc-java` | 140.7s → 142.3s | +1.1% |

> **Caveat — cache warmth confound:** these overhead deltas are not a
> clean measure of the treedb optimization. The instrumented re-runs use
> the persistent Maven/Gradle cache volumes (`maven-cache`,
> `gradle-cache`), while the stored baselines were captured cold. Large
> negative deltas (e.g., `crawler4j` −91.8%) primarily reflect avoided
> cold-cache dependency downloads, not interception speedups. The
> optimization's true impact is in the Phase 2 `Analysis` column above.

### Interpretation

- The optimized treedb step (`Analysis`) is now a minor cost for
  small/medium repos (`jsoup` 8.4s, `crawler4j` 7.6s, `checkstyle`
  13.2s, `logging-log4j2` 18.6s).
- `bc-java` Phase 2 (224.0s) remains dominated by its large multi-module
  Gradle output volume; the per-file pure-Python hashing still applies,
  but the sheer number of `.class` files keeps the absolute time high.
- All re-run repos are golden-clean, confirming the pure-Python
  appliers produce byte-identical hashes and file matching versus the
  original subprocess-based upstream behavior.
