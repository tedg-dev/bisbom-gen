# Strategy 1: Out-of-Band Pre-Hash Cache

**Impact:** 11 percentage points reduction (40% → 29%)

**Complexity:** Low

**Target budget category:** SHA-256 file hashing (10pp → ~0.5pp)

## The Idea

Before the build starts, pre-compute SHA256 gitoid hashes for all files in the
repository and system headers. Store them in a shared, mmap'd hash table. During
the build, `bomsh_hook_program()` performs O(1) cache lookups instead of O(filesize)
hash computations for input files.

## Addressing the "Lookup vs Compute" Concern

> *"Creating gitoids versus doing a lookup in a giant database — is that really a
> big performance improvement?"*

**Yes — but not for the reason you might think.** The win is not "lookup is faster
than hashing" (though it is). The win is **deduplication** — eliminating tens of
thousands of redundant hash computations that the current code performs.

**The real cost model — what happens without a cache:**

A single gcc compilation of `main.c` typically includes 30–50 header files (source
headers + transitive system headers like `stdio.h`, `stdlib.h`, `string.h`, etc.).
Each of those files is read from disk and SHA256-hashed by `calculate_sha256_omnibor()`.

In a 1,000-file project, the popular headers are included by *most* compilation
units. Without caching:

| Header File | Size | Included By | Times Hashed | Total I/O |
|-------------|------|-------------|-------------|-----------|
| `stdio.h` + transitive | ~28 KB | 800 of 1,000 TUs | **800** | 22 MB |
| `stdlib.h` + transitive | ~24 KB | 750 TUs | **750** | 18 MB |
| `string.h` + transitive | ~18 KB | 600 TUs | **600** | 11 MB |
| `unistd.h` + transitive | ~20 KB | 500 TUs | **500** | 10 MB |
| Project `config.h` | ~2 KB | 900 TUs | **900** | 1.8 MB |

That's **3,550 redundant hash operations** for just 5 commonly-included files.
Across all headers, the total is typically **30,000–35,000 hash operations** for
a 1,000-file build — even though only ~2,000–3,000 unique files exist.

**This is the same problem ccache solved.** ccache 4.0+ introduced an "inode cache"
specifically to avoid re-hashing the same header files during a single build.
Their documentation notes that popular headers like `<vector>` in C++ projects
can be hashed thousands of times without caching. Bazel and Buck2 use the same
content-addressable approach — hash once, lookup thereafter.

## Per-Operation Cost Breakdown

| Operation | Time | What Happens | Source |
|-----------|------|--------------|--------|
| `stat()` syscall | ~1–2 μs | Kernel reads inode metadata from VFS cache | Linux kernel VFS |
| In-memory hash table lookup | ~50–100 ns | Compare (dev, ino, mtime, size) tuple | Standard hash table |
| **Cache hit total** | **~2 μs** | stat + lookup + return cached hash | — |
| `open()` + `read()` (8 KB header) | ~10–15 μs | Kernel reads file from page cache | Linux kernel VFS |
| `open()` + `read()` (28 KB header) | ~25–40 μs | Larger read, possibly multiple pages | Linux kernel VFS |
| `malloc()` + `read()` (full file) | ~30–50 μs | bomsh's current approach: alloc + read entire file | bomsh_hook.c |
| SHA256 compute (8 KB, software) | ~15–20 μs | Hand-rolled sha256.c, no HW accel | bomsh sha256.c |
| SHA256 compute (28 KB, software) | ~50–60 μs | Hand-rolled sha256.c, no HW accel | bomsh sha256.c |
| `free()` | ~0.1 μs | Return buffer | libc |
| **Full hash (no cache), 8 KB file** | **~60–90 μs** | malloc + read + SHA256 + free | — |
| **Full hash (no cache), 28 KB file** | **~100–170 μs** | malloc + read + SHA256 + free | — |

**A cache hit is 30–85x faster than a full hash** — not because the "lookup is fast"
but because you skip the file I/O and SHA256 computation entirely.

## Why It Works

For a typical gcc compilation of `main.c`:

- **Input files (existed before build):** `main.c`, `curl.h`, `stdio.h`, `stdlib.h`,
  ... ~30–50 header files → all **cache hits** (~2 μs each)
- **Output files (created by gcc):** `main.o` → **cache miss**, must hash (~100 μs)

For 1,000 gcc invocations with an average of 35 input files each:

| Metric | Current (no cache) | With Pre-Hash Cache |
|--------|-------------------|---------------------|
| Hash operations during build | ~35,000 | ~1,000 (outputs only) |
| Cache lookups during build | 0 | ~34,000 |
| Time per hash operation | ~100–170 μs (read + SHA256) | ~100–170 μs (unchanged) |
| Time per cache lookup | N/A | ~2 μs (stat + table lookup) |
| **Total hash time during build** | **~4.5–6.0 seconds** | **~0.17 seconds** |
| **Reduction** | — | **96–97%** |

## Industry Precedent

This is not a novel optimization. It is the standard approach in every major build
tool that deals with content hashing:

| Tool | Cache Mechanism | What It Avoids |
|------|----------------|---------------|
| **ccache 4.0+** | Inode cache (dev/ino/mtime/size → hash) | Re-hashing headers across TUs |
| **Bazel** | Content-addressable store (CAS) | Re-hashing unchanged inputs |
| **Buck2** | BLAKE3 content hash with CAS | Redundant I/O on unchanged files |
| **Git** | Object store (blob hash → content) | Re-reading unchanged tracked files |
| **Docker BuildKit** | Layer content hash cache | Re-computing layer digests |

All of these tools faced the same problem: hashing is cheap for one file, but
multiplied across thousands of redundant operations it becomes a measurable bottleneck.
The solution is always the same — hash once, cache by identity, invalidate on change.

## Cascading Cache

The cache becomes even more effective with intermediate build artifacts:

| Build Step | File | Cache Result | Why |
|-----------|------|-------------|-----|
| `gcc -c main.c -o main.o` | main.c | **HIT** | Pre-hashed before build |
| | curl.h | **HIT** | Pre-hashed before build |
| | stdio.h | **HIT** | Pre-hashed before build |
| | main.o | **MISS → INSERT** | Just created by gcc |
| `ar rcs libcurl.a main.o ssl.o http.o` | main.o | **HIT** | Cached from gcc step above |
| | ssl.o | **HIT** | Cached from its gcc step |
| | http.o | **HIT** | Cached from its gcc step |
| | libcurl.a | **MISS → INSERT** | Just created by ar |
| `ld -o curl main.o libcurl.a -lssl` | main.o | **HIT** | Cached from gcc step |
| | libcurl.a | **HIT** | Cached from ar step above |
| | curl | **MISS → hash** | Final output binary |

Every intermediate artifact is hashed exactly once. `ar` and `ld` have **zero** hashing
overhead for their input files.
