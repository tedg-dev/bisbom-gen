# GitHub Issue: bomsh_sbom.py fails to inject OmniBOR ExternalRefs for libtool-built binaries

**Repository:** omnibor/bomsh
**Title:** bomsh_sbom.py silently skips ExternalRef injection when libtool relinks binary after bomtrace3 records hash

---

## Description

`bomsh_sbom.py` fails to inject OmniBOR `externalRefs` into SPDX packages for binaries built with **libtool** (autotools). The `--force_insert` flag does not help. The root cause is a hash mismatch between the binary hash recorded by `bomtrace3` during the `gcc` link step and the final binary hash on disk after libtool performs a post-link relink.

This affects a large class of open-source projects that use autotools/libtool, including **curl**, **FFmpeg**, and many others.

## Environment

- **OS:** Ubuntu 22.04 (x86_64, native)
- **bomtrace3:** built from strace v6.11 with bomtrace3.patch
- **bomsh:** latest from omnibor/bomsh main branch
- **Target project:** curl (built with autotools/libtool)

## Steps to Reproduce

1. Build curl with bomtrace3 instrumentation:

   ```bash
   bomtrace3 make -j$(nproc)
   ```

2. Generate OmniBOR ADG documents:

   ```bash
   bomsh_create_bom.py -r /tmp/bomsh_hook_raw_logfile.sha1 \
       -b /output/omnibor/curl
   ```

3. Generate SPDX SBOM with ExternalRefs:

   ```bash
   bomsh_sbom.py -b /output/omnibor/curl \
       -F /repos/curl/src/.libs/curl \
       -O /output/spdx/curl \
       -s spdx-json --force_insert
   ```

4. Inspect the generated SPDX JSON — no OmniBOR `externalRefs` are present on any package.

## Root Cause

The issue is a three-step hash mismatch:

### Step 1: bomtrace3 records hash at gcc link time

bomtrace3 intercepts the `gcc` link command and computes the SHA1 hash of the output binary immediately after `gcc` returns. This hash is recorded in the raw logfile:

```
outfile: a89518afb48da8755a473773f0f570b56ef45976 path: /workspace/repos/curl/src/.libs/curl
```

### Step 2: libtool modifies the binary after gcc

For libtool-managed projects, `gcc` is invoked by libtool, which may perform post-link operations (RPATH adjustment, relinking, symbol stripping) that **modify the binary on disk** after `gcc` returns. The final binary has a different hash:

```bash
$ sha1sum /workspace/repos/curl/src/.libs/curl
ad6da2839626a2ec545376855722d8acc39ebb22  /workspace/repos/curl/src/.libs/curl
```

### Step 3: bomsh_sbom.py can't find the binary in doc_mapping

`bomsh_sbom.py` hashes the binary on disk (`ad6da283...`), looks it up in `bomsh_omnibor_doc_mapping`, finds no match, and silently skips ExternalRef injection:

```python
# bomsh_omnibor_doc_mapping contains:
{
    "a89518afb48da8755a473773f0f570b56ef45976": "562f8602821be5d3a6ba00bef8ecc01460ad2d9b"
}
# But the on-disk binary hash is ad6da2839626a2ec545376855722d8acc39ebb22
# → no match → no ExternalRef
```

### Evidence

```
Build-time hash (raw logfile):  a89518afb48da8755a473773f0f570b56ef45976
On-disk hash (after libtool):   ad6da2839626a2ec545376855722d8acc39ebb22
OmniBOR doc (keyed by build):   562f8602821be5d3a6ba00bef8ecc01460ad2d9b

a89518af in doc_mapping: True
ad6da283 in doc_mapping: False
```

Both the raw logfile and the binary were produced in the same build run (timestamps within seconds of each other). The binary was not rebuilt — libtool modified it in place.

## Expected Behavior

`bomsh_sbom.py` should inject OmniBOR `externalRefs` into the SPDX package for `curl`, referencing the OmniBOR document `562f8602...`.

## Actual Behavior

No `externalRefs` are injected. The SPDX output contains no OmniBOR references. No warning or error is printed.

## Suggested Fixes

### Option A: Re-hash after parent process completes (bomtrace3)

Instead of hashing the output file immediately after `gcc` returns, bomtrace3 could defer hashing until the parent process (libtool) completes or until the file is no longer being modified. This would capture the final on-disk hash.

### Option B: Path-based fallback matching (bomsh_sbom.py)

When hash-based lookup fails, `bomsh_sbom.py` could fall back to matching by **filename/path**. The raw logfile contains both the hash and the path. If the binary path matches but the hash doesn't, the script could use the build-time hash to look up the OmniBOR document.

### Option C: Detect libtool and track final hash (bomsh_create_bom.py)

`bomsh_create_bom.py` could detect libtool wrapper scripts and re-hash the final binary after the build completes, adding the new hash as an alias in the doc_mapping.

### Option D: Warning when --force_insert finds no matches

At minimum, `bomsh_sbom.py --force_insert` should print a warning when it cannot inject any ExternalRefs, rather than silently succeeding. This would help users diagnose the issue.

## Workaround

We implemented a post-processing step in our pipeline that:

1. Parses the raw logfile to build a `binary_path → build-time SHA1` map
2. Looks up the build-time SHA1 in `bomsh_omnibor_doc_mapping` to get the OmniBOR document ID
3. Matches SPDX package names to binary basenames
4. Injects `PERSISTENT-ID` ExternalRefs with `gitoid:blob:sha1:<omnibor_id>` locators

This workaround is available at: https://github.com/tedg-dev/omnibor-analysis

## Impact

This bug affects **any project built with libtool/autotools**, which includes a significant portion of the open-source C/C++ ecosystem. Without the workaround, bomsh-generated SPDX SBOMs for these projects will be missing OmniBOR provenance data, undermining the core value proposition of the toolchain.

## Labels

`bug`, `component:bomsh_sbom.py`, `component:bomtrace3`
