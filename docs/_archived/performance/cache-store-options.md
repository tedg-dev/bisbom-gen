# Cache Store Options for OmniBOR Pre-Hash Cache

This document evaluates storage backends for the pre-hash cache described in
[Strategy 1: Out-of-Band Pre-Hash Cache](strategy-1-pre-hash-cache.md). Options
are scored from best to worst for the OmniBOR use case.

---

## Requirements

From the [Performance Optimization Proposal](omnibor-performance-optimization-proposal.md#strategy-1-pre-hash-cache)
and the [Strategy 1 breakout](strategy-1-pre-hash-cache.md):

- **O(1) lookup at ~50–100 ns** per read (per-operation cost table)
- **Shared across processes** — bomtrace3 spawns per-process hooks via ptrace
- **Concurrent readers** — parallel `make -j16` means 16+ processes reading simultaneously
- **Single writer** — the `bomsh_hashd` daemon or pre-build step populates the cache
- **Fixed schema** — key is `(dev, ino, mtime, size)`, value is 64-char hex SHA256
- **~10,000–50,000 entries** for large builds
- **Persistent** — cache must survive between CI runs and be saveable as a CI artifact
- **Self-contained** — the omnibor-analysis Docker container must not depend on external services

---

## Summary

| Rank | Option | Lookup Latency | Dependencies | Persistent? | Cross-Platform? |
|------|--------|---------------|-------------|-------------|-----------------|
| ★★★★★ | **Custom mmap'd hash table** | ~50–100 ns | None | Yes (file-backed) | Yes (all platforms) |
| ★★★★ | **LMDB** | ~200–500 ns | 1 C file (12K lines) | Yes (ACID) | Yes (all platforms) |
| ★★★ | **POSIX shm_open + hash table** | ~50–100 ns | None | No (tmpfs) | No (not on Windows) |
| ★★ | **SQLite WAL** | ~5–20 μs | 1 C file (250K lines) | Yes (ACID) | Yes (all platforms) |
| ★ | **Redis / external server** | ~50–100 μs | Server + client lib | Optional | Yes (all platforms) |
| ☆ | **MongoDB** | ~500 µs–5 ms | External server + C driver | Yes | Yes (all platforms) |

---

## Option 1: Custom mmap'd Open-Addressing Hash Table — ★★★★★ Best

*Reference implementations: [ShareHashFile](https://github.com/simonhf/sharedhashfile), [Robin Hood hashing](https://github.com/martinus/robin-hood-hashing)*

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~50–100 ns — direct pointer arithmetic into mmap'd region, no syscalls |
| **Concurrent readers** | Unlimited — `mmap(MAP_SHARED, PROT_READ)` requires no locks for readers |
| **Writer model** | Single writer rebuilds the file; readers see updates after `msync()` or remap |
| **Dependency** | None — pure C, no external library |
| **Persistence** | File-backed, survives process restarts, cacheable as CI artifact |
| **Precedent** | ccache 4.0+ uses exactly this: an mmap'd shared file with fixed-size entries keyed by `(dev, ino, mtime, size)`. Sharded across 256 files to reduce lock contention. *(Source: [ccache manual](https://ccache.dev/manual/latest.html), `inode_cache` option)* |
| **Footprint** | ~100 bytes/entry × 50,000 entries = ~5 MB |

**Why it's best for OmniBOR:** This is what the proposal already describes
("shared, mmap'd hash table"). The schema is fixed and tiny — there's no need for
a query engine, transactions, or B-tree overhead. bomsh is a C codebase; a custom
hash table keeps the dependency footprint at zero and achieves the lowest possible
latency. Open-addressing (Robin Hood or linear probing) gives cache-line-friendly
access patterns — a single cacheline (64 bytes) can hold an entire entry, so
lookups hit L1/L2 cache after the first access.

**Risk:** You own the code — bugs in hash table resizing or collision handling
are yours to fix. Mitigated by the fixed-size, rebuild-on-change design (no
dynamic resizing during reads).

---

## Option 2: [LMDB](http://www.lmdb.tech/doc/) (Lightning Memory-Mapped Database) — ★★★★ Very Good

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~200–500 ns — B+ tree traversal through mmap'd pages, 2–3 page touches for 50K entries |
| **Concurrent readers** | Unlimited — LMDB's MVCC design allows any number of concurrent read transactions with zero locking. Reads are a direct mmap pointer dereference. *(Source: [LMDB tech docs](http://www.lmdb.tech/doc/))* |
| **Writer model** | Single writer with copy-on-write. Write transactions don't block readers. |
| **Dependency** | Single C file (`lmdb.c` + `lmdb.h`, ~12,000 lines). Can be vendored. |
| **Persistence** | File-backed, ACID-compliant, crash-safe |
| **Precedent** | Used by OpenLDAP, Monero, Caffe. Designed for exactly this pattern: many concurrent readers, one writer, memory-mapped access. |
| **Footprint** | Slightly larger due to B+ tree overhead (~1.5–2x raw data size) |

**Why it's very good:** LMDB gives all the benefits of mmap with proper crash
safety and a tested API. The read path is literally an mmap pointer traversal —
no copies, no locks, no syscalls. The ~200–500 ns lookup is still well within
budget (vs ~60–170 μs for a full hash computation). The single-file vendoring
makes it easy to integrate into bomsh's build.

**Why it's not #1:** The B+ tree adds ~3–5x latency over a flat hash table for
this use case. For 50K fixed-schema entries with no range queries needed, a B+
tree is overengineered. Also adds a dependency (albeit tiny) to a project that
currently has zero external deps beyond libc and OpenSSL.

---

## Option 3: POSIX Shared Memory ([shm_open](https://man7.org/linux/man-pages/man3/shm_open.3.html) + custom hash table) — ★★★ Good

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~50–100 ns — same as option 1, it's just a different backing for the mmap |
| **Concurrent readers** | Unlimited — same `MAP_SHARED` semantics |
| **Writer model** | Single writer, readers see updates via shared mapping |
| **Dependency** | None (POSIX APIs) |
| **Persistence** | **Not persistent** — `/dev/shm` is tmpfs, lost on reboot |
| **Precedent** | Common in HFT and real-time systems for inter-process shared state |

**Why it's good:** Same raw performance as option 1. The `shm_open()` API is
cleaner than managing file paths for the mmap'd file.

**Why it's not higher:** The lack of persistence is a significant drawback. The
cache must survive between CI runs (saved as a CI cache artifact), between
container restarts, and between daemon restarts. A file-backed mmap (option 1)
naturally provides this. With `shm_open`, you'd need to serialize/deserialize the
cache to disk separately, adding complexity. Also, `shm_open` is not available on
Windows (see [cross-platform applicability](cross-platform-applicability.md)).

---

## Option 4: [SQLite](https://sqlite.org/) with [WAL Mode](https://sqlite.org/wal.html) — ★★ Adequate

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~5–20 μs — SQL parse + query plan + B-tree traversal + row deserialization |
| **Concurrent readers** | Unlimited in WAL mode — readers don't block writers and vice versa. *(Source: [SQLite WAL docs](https://sqlite.org/wal.html))* |
| **Writer model** | Single writer, WAL allows concurrent reads during writes |
| **Dependency** | Single C file (`sqlite3.c`, ~250,000 lines). Heavy but self-contained. |
| **Persistence** | Excellent — crash-safe, widely tested, trivially portable |
| **Precedent** | Used by Firefox, Chrome, iOS, Android for local storage. |

**Why it's adequate:** SQLite is the safe, boring choice. WAL mode handles
concurrency well. It's trivially queryable for debugging
(`sqlite3 hashcache.db "SELECT * FROM hashes WHERE path LIKE '%stdio.h%'"`).
Cross-platform with no issues.

**Why it's not higher:** The ~5–20 μs lookup latency is 10–200x slower than an
mmap'd hash table. For 34,000 cache lookups per build (per the strategy doc),
that's ~170–680 ms in SQLite vs ~68 ms with mmap. Still a net win over the
4.5-second no-cache baseline, but leaves performance on the table. The 250K-line
`sqlite3.c` amalgamation is a heavy dependency for a simple key-value cache. SQL
parsing overhead is wasted on a fixed-schema, single-table lookup.

---

## Option 5: [Redis](https://redis.io/) / External Key-Value Server — ★ Worst

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~50–100 μs — TCP/IP round-trip to localhost, even with Unix sockets ~10–30 μs |
| **Concurrent readers** | Unlimited — Redis is single-threaded but handles concurrent clients via event loop |
| **Writer model** | Single writer or multiple writers — Redis handles serialization |
| **Dependency** | External server process, Redis client library in C (`hiredis`) |
| **Persistence** | Optional (RDB snapshots, AOF) — adds operational complexity |
| **Precedent** | Used everywhere for web caching, but not for build tool hot paths |

**Why it's worst for OmniBOR:** The network round-trip (~50–100 μs per lookup,
~10–30 μs with Unix socket) is comparable to the full hash computation it's
trying to avoid (~60–170 μs). For 34,000 lookups, that's 340 ms–3.4 seconds of
pure IPC overhead — potentially eliminating the entire benefit of caching. It
also requires running and managing a separate server process inside the build
container, adding operational complexity. The bomsh codebase is self-contained C;
adding a Redis dependency and client library is architecturally incongruent.

---

## Option 6: [MongoDB](https://www.mongodb.com/) / External Document Database — ☆ Not Recommended

| Attribute | Detail |
|-----------|--------|
| **Lookup latency** | ~500 µs–5 ms — BSON serialization + network round-trip + query planning + document deserialization |
| **Concurrent readers** | Unlimited — MongoDB handles concurrency via WiredTiger storage engine |
| **Writer model** | Multiple writers supported with document-level locking |
| **Dependency** | External `mongod` server process + [MongoDB C Driver](https://mongoc.org/) (`libmongoc` + `libbson`) |
| **Persistence** | Excellent — journaled, crash-safe, replicated |
| **Precedent** | Widely used for application-level document storage and lookup services |

**Why it doesn't fit the OmniBOR pre-hash cache:**

1. **Latency mismatch.** Even a local MongoDB query is ~500 µs–5 ms (network +
   BSON deserialization). That's **5,000–50,000x slower** than an mmap'd hash
   table (~50–100 ns). For 34,000 cache lookups per build, MongoDB would add
   **17–170 seconds** of pure query overhead — far worse than the 4.5 seconds
   of hashing it's trying to eliminate.

2. **Container isolation.** omnibor-analysis runs as a self-contained Docker
   container. Reaching out to an external MongoDB instance during a build
   introduces a network dependency, authentication requirements, and a failure
   mode that could break builds. The container must be able to run air-gapped.

3. **Cache keys are host-local.** The pre-hash cache key is `(dev, ino, mtime,
   size)` — filesystem identity metadata that is **local to the build host**.
   Inode numbers and device IDs are meaningless on another machine or container.
   A shared MongoDB instance serving multiple CI pipelines would contain entries
   that are valid only on the host that wrote them.

4. **Per-pipeline scope.** Each product team's CI/CD pipeline builds different
   source trees with different filesystem layouts. The cache is inherently
   per-build-host and per-repository. A centralized database adds complexity
   without enabling meaningful sharing, because the cache entries cannot be
   reused across different hosts or containers.

5. **Dependency weight.** The MongoDB C Driver (`libmongoc` + `libbson`) is a
   substantial dependency (~100K+ lines of code). The bomsh codebase is pure C
   with minimal dependencies (libc + OpenSSL). Adding a MongoDB client library
   and requiring a running `mongod` instance is architecturally incongruent
   with a build-time interception tool.

6. **Designed for a different problem.** MongoDB excels as an application-level
   knowledge store — for example, a ComponentStore that maps file hashes to
   metadata ("here is a hash, here's what we know about it"). That is a
   **post-build, query-at-human-speed** use case. The pre-hash cache is a
   **build-time, query-at-nanosecond-speed** use case. These are fundamentally
   different access patterns with different optimal storage backends.

---

## Recommendation

**Option 1 (custom mmap'd hash table)** — consistent with what the
[proposal](omnibor-performance-optimization-proposal.md#strategy-1-pre-hash-cache)
already describes, what ccache uses for the same problem, and what delivers the
~50–100 ns lookup that makes the 96% hashing reduction possible.

**LMDB** is the strong runner-up if crash safety or avoiding custom hash table
code is a priority.

---

## Central Hash Store Integration

The options above (1–6) address the **build-time cache** — the hot-path,
in-process lookup that eliminates redundant SHA-256 computations. This section
addresses a separate but related question: can OmniBOR's hash results be shared
with other Security Team applications, and can a central hash database help
pre-populate or enrich the local cache?

### Two Fundamentally Different Hash Roles

Before evaluating options, it is critical to distinguish the two types of hashes
OmniBOR produces:

| Aspect | Build-Time Cache Key | Content Hash (gitoid) |
|--------|---------------------|-----------------------|
| **Format** | `(dev, ino, mtime, size)` tuple | `SHA256("blob " + size + "\0" + content)` |
| **Purpose** | Index for fast local lookup | Universal content identifier |
| **Portable?** | **No** — inode numbers and device IDs are local to the build host | **Yes** — identical content on any machine produces the same gitoid |
| **Shareable?** | **No** — meaningless on another host or container | **Yes** — this is the value other tools can consume |
| **Precedent** | ccache inode cache | Git object store, OmniBOR spec, Bazel CAS |

The build-time cache key is host-local and ephemeral. The gitoid (the cache
**value**) is a universal content fingerprint that is shareable, portable, and
useful to any tool that understands content-addressable hashing.

**Bottom line:** The local mmap'd cache is the performance layer.
The central hash store is the knowledge-sharing layer. They operate at different
timescales and serve different purposes. The architecture must keep them
completely decoupled so that the central store is **never** on the build
critical path.

---

### Architecture Options

#### Architecture A: Post-Build Export Pipeline Step — ★★★★★ Recommended

```
                       BUILD TIME (hot path)                    POST-BUILD (async)
                       ──────────────────────                   ──────────────────
                       ┌─────────────────────┐                  ┌──────────────────┐
  bomtrace3 ──────────►│ Local mmap'd cache   │──── build ────►│ Export Manifest   │
  (per-process hooks)  │ (50-100 ns lookup)   │    completes    │ (JSON/NDJSON)    │
                       └─────────────────────┘                  └───────┬──────────┘
                                                                        │
                                                                        ▼
                                                                ┌──────────────────┐
                                                                │ Central Hash DB  │
                                                                │ (Mongo, Postgres,│
                                                                │  or any store)   │
                                                                └──────────────────┘
```

**How it works:**

1. During the build, bomtrace3 uses the local mmap'd cache exactly as described
   in [Strategy 1](strategy-1-pre-hash-cache.md) — zero changes to the hot path.
2. After the build completes, a new pipeline step exports all gitoid→path
   mappings as a JSON manifest file (the `bomsh_omnibor_treedb` already is this).
3. An external process (Python script, CI step, or queue consumer) pushes the
   manifest to the central hash database.

**Export manifest format** (already exists as `bomsh_omnibor_treedb`):

```json
{
  "gitoid:sha256:a1b2c3d4...": {
    "file_path": "/workspace/repos/curl/src/main.c",
    "file_size": 4096,
    "build_timestamp": "2026-04-23T21:00:00Z",
    "repo": "curl",
    "language": "c-cpp"
  }
}
```

| Attribute | Detail |
|-----------|--------|
| **Build-time impact** | **Zero** — export happens after the build completes |
| **Complexity** | Low — the treedb JSON already exists; just push it |
| **Central DB requirements** | Any document store — MongoDB, PostgreSQL JSONB, even S3+Athena |
| **Partner compatibility** | Partner app's ComponentStore can ingest gitoids directly |
| **Failure mode** | If central DB is down, the build succeeds; export retries later |
| **Precedent** | Bazel remote cache write-back, GitHub Actions cache save step |

**Why it's best:** This is the simplest architecture that achieves cross-team
hash sharing with zero risk to build performance. The export step is already
implicitly part of the pipeline (the treedb is already generated). Adding a
push-to-central-DB step is ~10 lines of Python.

---

#### Architecture B: Two-Tier Cache (Local Hot + Central Warm) — ★★★★★ Recommended (with A)

```
  OUT-OF-BAND (PR listener / pre-hash daemon)       BUILD TIME              POST-BUILD
  ─────────────────────────────────────────────      ──────────              ──────────
  ┌─────────────┐      ┌──────────────────┐         ┌──────────────┐        ┌──────────────┐
  │ Git webhook │─────►│ Pre-hash daemon  │────────►│ Local mmap'd │        │ Local cache  │
  │ (PR event)  │      │ (already running)│         │ cache (L1)   │──────►│ → Central DB │
  └─────────────┘      └───────┬──────────┘         └──────────────┘ async  └──────────────┘
                               │                          ▲             export
                    ┌──────────┴──────────┐               │
                    │                     │               │  bomtrace3 reads
                    ▼                     ▼               │  at 50-100 ns
              ┌───────────┐        ┌─────────────┐        │
              │ Hash local│        │ Pull known  │        │
              │ files     │        │ hashes from │────────┘
              │ (as today)│        │ Central DB  │  stat() + insert
              └───────────┘        └─────────────┘
```

**How it works:**

1. **Out-of-band pre-warm (on PR event):** The same daemon or CI listener that
   already watches for pull requests and pre-computes local file hashes
   (Strategy 1's pre-hash step) **also** queries the central DB: "for
   repository X, what gitoid hashes are known?" For each file that still
   exists locally with the same `(size)`, the daemon inserts the gitoid into
   the local mmap'd cache, keyed by the file's current `(dev, ino, mtime,
   size)`. This happens on the same trigger and in the same process that
   already does local hashing — it is **not** an extra build step.

2. **Build time:** Identical to Architecture A — local mmap'd cache only.
   The cache is already warm from both local hashing and central DB pull.

3. **Post-build:** New gitoids (cache misses that were computed during the
   build) are exported to the central DB via Architecture A's export step.

**Pre-warm matching strategy:**

The central DB stores `{gitoid, repo, file_path, file_size}`. The pre-warm
script matches by `(repo, file_path, file_size)`:

```
For each file F in the local workspace:
  1. stat(F) → get (dev, ino, mtime, size)
  2. Query central DB: WHERE repo = "curl" AND path = "src/main.c" AND size = 4096
  3. If match found AND local file has same size → insert (dev, ino, mtime, size) → gitoid
  4. If no match → file will be hashed normally during build (cache miss)
```

| Attribute | Detail |
|-----------|--------|
| **Build-time impact** | **Zero** — pre-warm runs out-of-band on the PR listener, not in the build pipeline |
| **Pre-warm benefit** | First build on a new CI runner can skip hashing for known-unchanged files |
| **Complexity** | Medium — requires matching logic and central DB schema design |
| **Incremental cost** | **Near-zero** — the pre-hash daemon is already running and already `stat()`-ing every file. Adding a central DB query is one bulk fetch per PR event. |
| **Risk** | Size-only matching could produce false positives (same size, different content). Mitigated by the fact that a wrong gitoid for an input file only affects SBOM accuracy, not the build itself, and is detectable during validation. |
| **Precedent** | ccache remote storage (local + remote, with read-through on miss), Bazel remote cache |

**Why it's recommended (alongside A):** This is Architecture A plus one
addition: the pre-hash daemon that already runs on PR events also pulls
known hashes from the central DB in the same pass. Since the daemon is
already `stat()`-ing every file and building the local cache, the marginal
cost of also checking the central DB is a single bulk query — seconds of
network I/O that happen **out-of-band**, not on the build critical path.

This eliminates the one scenario where the pre-hash cache provides no
benefit: the first build on a new CI runner (cold cache). With the central
DB pull, even a brand-new runner has a warm cache for any file that has been
seen before by any other runner.

The Bazel remote cache architecture validates this pattern at scale —
Bazel's "local disk cache" is L1, and the "remote cache" is L2, with the
same miss-then-populate flow.

**Remaining complexity:** The matching logic (by `repo, file_path, file_size`)
and the central DB schema design. These are straightforward but not trivial.

---

#### Architecture C: Write-Behind with Background Thread — ★★★ Good

**How it works:** During the build, a background thread in `bomsh_hashd`
(the hash daemon from the
[proposal](omnibor-performance-optimization-proposal.md#strategy-4-git-aware-hash-daemon))
drains newly-computed hashes to the central DB asynchronously.

| Attribute | Detail |
|-----------|--------|
| **Build-time impact** | Near-zero — writes are buffered in a lock-free queue, drained by a separate thread |
| **Latency** | Central DB sees new hashes within seconds of computation, not at build end |
| **Complexity** | High — requires thread-safe queue in C, connection management, error handling |
| **Risk** | Thread contention could cause micro-stalls on the hot path if the queue fills. Network errors in the background thread must not crash the build. |
| **Precedent** | Oracle Coherence write-behind, Redis AOF with `fsync=everysec` |

**Why it's good but not higher:** The near-real-time export is rarely valuable
— the central DB typically doesn't need to know about a hash until the build
is complete. The complexity of a thread-safe C queue with network I/O inside
the bomsh codebase is significant, and the failure modes are harder to reason
about than a simple post-build export step.

---

#### Architecture D: Shared Content-Addressable Store (CAS) — ★★ Specialized

A full [Bazel-style CAS](https://bazel.build/remote/caching) where the central
store holds both the gitoid and the file content. Any build host can download
the content and verify it matches the gitoid.

| Attribute | Detail |
|-----------|--------|
| **Build-time impact** | Could be **negative** (faster) — if a CAS hit avoids both hashing AND file read |
| **Complexity** | Very high — requires content storage, content-addressed deduplication, GC policy |
| **Dependency** | Heavy — S3 or GCS backend, CAS protocol implementation |
| **Precedent** | Bazel remote CAS, [BuildBarn](https://github.com/buildbarn), Pants remote cache |

**Why it's specialized:** A full CAS is overkill for OmniBOR's current needs.
OmniBOR doesn't need to store file content — it only needs the gitoid hash.
A CAS makes sense when you want to share **build outputs** across teams (e.g.,
"don't recompile curl on this CI runner, download the pre-built `.o` from CAS").
That's a different problem from sharing hash metadata.

---

### Hash Format Compatibility with Partner Applications

The partner application's MongoDB ComponentStore uses file hashes as keys
("here is a file hash, here's what we know about it"). For OmniBOR hashes
to be useful to this system, the hash formats must be compatible or mappable.

| Hash Format | Computation | Who Uses It |
|-------------|-------------|-------------|
| **OmniBOR gitoid** | `SHA256("blob " + decimal_size + "\0" + content)` | OmniBOR, Git (SHA-256 mode), SPDX `contentIdentifier` |
| **Raw SHA-256** | `SHA256(content)` | Most vulnerability databases, NIST NVD, common in SBOMs |
| **SHA-1** | `SHA1("blob " + size + "\0" + content)` | Git (legacy mode), many existing tools |

**If the partner app uses raw SHA-256:** The gitoid and raw SHA-256 of the same
file are **different hashes** (the "blob size\0" prefix changes the digest).
Two options:

1. **Store both.** During the export step, compute both
   `gitoid:sha256:<hash>` and `sha256:<raw_hash>` and write both to the
   central DB. The cost of a second SHA-256 pass is negligible in the
   post-build step.

2. **Standardize on gitoid.** The OmniBOR specification, SPDX 2.3+, and Git
   all use the gitoid format. If the partner app can adopt gitoid as its
   hash format, no translation is needed. This is the cleaner long-term
   approach.

**If the partner app uses SHA-1 (Git legacy):** The gitoid format supports
both SHA-1 and SHA-256 object types. OmniBOR currently uses SHA-256, but
`bomsh_hook.c` already has `calculate_sha1_omnibor()` for SHA-1 gitoids.
Both can be emitted during export.

---

### Central DB Schema Recommendation

Regardless of which architecture (A, B, C, or D) is chosen, the central DB
schema should support these queries:

| Query | Use Case |
|-------|----------|
| "What is the gitoid of `curl/src/main.c` at version 8.12.0?" | Pre-warm local cache (Architecture B) |
| "Which repositories contain a file with gitoid X?" | Vulnerability correlation across teams |
| "What metadata is known for gitoid X?" | Partner app ComponentStore integration |
| "What gitoids were produced by build run Y?" | Audit trail, SBOM provenance |

**Minimal schema:**

```json
{
  "gitoid": "gitoid:sha256:a1b2c3d4...",
  "raw_sha256": "e5f6a7b8...",
  "file_path": "src/main.c",
  "file_size": 4096,
  "repo": "curl",
  "repo_version": "8.12.0",
  "build_run_id": "2026-04-23T21:00:00Z",
  "language": "c-cpp",
  "team": "security-tools"
}
```

This schema works in MongoDB (as a document), PostgreSQL (as JSONB or
relational), or any document/relational store. The gitoid field should be
indexed for O(1) lookup.

---

### Recommendation

**Architecture A + B together** — they are complementary, not alternatives:

- **A (Post-Build Export)** pushes new gitoids **out** to the central DB after
  each build. This is the cross-team sharing mechanism. Implementation cost:
  ~10 lines of Python on top of the existing `bomsh_omnibor_treedb` output.

- **B (Out-of-Band Pre-Warm)** pulls known gitoids **in** from the central DB
  on each PR event, in the same daemon that already pre-hashes local files.
  This eliminates cold-cache penalties on new CI runners. Implementation cost:
  one bulk DB query added to the existing pre-hash daemon.

Together, the data flow forms a virtuous cycle:

```
Runner 1 builds curl → exports gitoids to Central DB
Runner 2 (new, cold cache) gets PR event →
    pre-hash daemon stat()s files + pulls known hashes from Central DB →
    cache is warm before build starts →
    build runs with zero cold-cache penalty →
    exports any new gitoids back to Central DB
```

**Key principle:** The central hash database is a **post-build knowledge store**
and an **out-of-band pre-warm source**, never a build-time dependency.
OmniBOR's local mmap'd cache handles the nanosecond-scale hot path. The central
DB handles the millisecond-scale cross-team queries and pre-warm bulk fetches.
These two layers must remain decoupled — the build must never block on the
central DB.

---

## References

1. **ccache manual — inode cache:** https://ccache.dev/manual/latest.html
2. **LMDB technical documentation:** http://www.lmdb.tech/doc/
3. **LMDB Wikipedia — benchmark comparisons:** https://en.wikipedia.org/wiki/Lightning_Memory-Mapped_Database
4. **SQLite WAL mode documentation:** https://sqlite.org/wal.html
5. **ShareHashFile — mmap'd shared hash table in C:** https://github.com/simonhf/sharedhashfile
6. **Robin Hood hashing benchmark:** https://www.sebastiansylvan.com/post/robin-hood-hashing-should-be-your-default-hash-table-implementation/
7. **ccache inode cache default discussion:** https://github.com/ccache/ccache/discussions/1086
8. **Cross-platform file identity APIs:** [cross-platform-applicability.md](cross-platform-applicability.md)
9. **MongoDB C Driver (libmongoc):** https://mongoc.org/
10. **MongoDB documentation:** https://www.mongodb.com/docs/
11. **Bazel remote caching architecture:** https://bazel.build/remote/caching
12. **ccache remote storage backends (local + remote two-tier):** https://ccache.dev/manual/4.9.html#_remote_storage_backends
13. **OmniBOR gitoid specification:** https://omnibor.io/docs/artifact-ids/
14. **Oracle Coherence write-behind caching pattern:** https://docs.oracle.com/cd/E16459_01/coh.350/e14510/readthrough.htm
15. **sccache — shared compilation cache with remote backends:** https://github.com/mozilla/sccache
16. **BuildBarn — Bazel remote execution and CAS:** https://github.com/buildbarn
