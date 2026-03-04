# Three-Way SPDX Comparison: curl Binary

**Date:** February 13, 2026
**Target:** curl 8.19.0-DEV (built from source on Ubuntu 22.04 with gcc 11.4.0)
**Binary:** dynamically linked ELF 64-bit x86-64

## Summary

Four tools were used to generate or analyze SBOMs for the same curl build. Each tool examines a fundamentally different data source, resulting in **completely disjoint findings** with zero package overlap between categories.

| Category | ADG (OmniBOR) | Syft | GitHub | BDBA |
|---|:---:|:---:|:---:|:---:|
| **Dynamically linked libraries (.so)** | **23** | 0 | 0 | 0 |
| Project binary / build compiler | 2 | 2 | 1 | 1 |
| Python CI/dev tools (pip) | 0 | 13 | 14 | 0 |
| GitHub Actions (CI workflows) | 0 | 11 | 11 | 0 |
| **Total (unique)** | **25** | **26** | **26** | **1** |

## What Each Tool Scans

| Tool | Method | Data Source | Finds |
|---|---|---|---|
| **ADG (OmniBOR)** | `ldd`/`readelf` on compiled binary + `dpkg` metadata | ELF headers of the built binary | Shared libraries (`.so`) loaded at runtime by the dynamic linker |
| **Syft** | Source tree manifest scan | `.github/workflows/*.yml`, `requirements.txt` | CI/dev tooling references checked into the repo |
| **GitHub** | Dependency graph API | Same manifest files as Syft | CI/dev tooling — pip packages + GitHub Actions |
| **BDBA** | Binary signature fingerprinting | The curl binary file itself | Only recognizes curl's own binary signature |

## Dynamically Linked Libraries

These are `.so` (shared object) files — Linux's equivalent of Windows DLLs — that the dynamic linker (`ld-linux`) loads into memory when curl runs. They are **not compiled into** the curl binary; they are separate files on disk that curl depends on at runtime.

**Only ADG detects these. Neither Syft, GitHub, nor BDBA find any of them.**

### Direct Dependencies (3)

Listed in the curl binary's ELF `NEEDED` entries (discovered via `readelf -d`). The binary explicitly requests these at load time.

| Component | Version | Sonames |
|---|---|---|
| **curl** (libcurl) | 7.81.0-1ubuntu1.21 | `libcurl.so.4` |
| **glibc** | 2.35-0ubuntu3.13 | `libc.so.6`, `libresolv.so.2` |
| **zlib** | 1:1.2.11.dfsg-2ubuntu9.2 | `libz.so.1` |

### Transitive Dependencies (20)

Pulled in by `libcurl.so` and its own dependencies. Discovered via `ldd`, which recursively resolves the full shared library dependency chain.

| Component | Version | Sonames |
|---|---|---|
| **brotli** | 1.0.9-2build6 | `libbrotlidec.so.1`, `libbrotlicommon.so.1` |
| **cyrus-sasl2** | 2.1.27+dfsg2-3ubuntu1.2 | `libsasl2.so.2` |
| **e2fsprogs** | 1.46.5-2ubuntu1.2 | `libcom_err.so.2` |
| **gmp** | 2:6.2.1+dfsg-3ubuntu1 | `libgmp.so.10` |
| **gnutls28** | 3.7.3-4ubuntu1.7 | `libgnutls.so.30` |
| **keyutils** | 1.6.1-2ubuntu3 | `libkeyutils.so.1` |
| **krb5** | 1.19.2-2ubuntu0.7 | `libgssapi_krb5.so.2`, `libkrb5.so.3`, `libk5crypto.so.3`, `libkrb5support.so.0` |
| **libffi** | 3.4.2-4 | `libffi.so.8` |
| **libidn2** | 2.3.2-2build1 | `libidn2.so.0` |
| **libpsl** | 0.21.0-1.2build2 | `libpsl.so.5` |
| **libssh** | 0.9.6-2ubuntu0.22.04.5 | `libssh.so.4` |
| **libtasn1-6** | 4.18.0-4ubuntu0.1 | `libtasn1.so.6` |
| **libunistring** | 1.0-1 | `libunistring.so.2` |
| **libzstd** | 1.4.8+dfsg-3build1 | `libzstd.so.1` |
| **nettle** | 3.7.3-1build2 | `libnettle.so.8`, `libhogweed.so.6` |
| **nghttp2** | 1.43.0-1ubuntu0.2 | `libnghttp2.so.14` |
| **openldap** | 2.5.20+dfsg-0ubuntu0.22.04.1 | `libldap-2.5.so.0`, `liblber-2.5.so.0` |
| **openssl** | 3.0.2-0ubuntu1.21 | `libssl.so.3`, `libcrypto.so.3` |
| **p11-kit** | 0.24.0-6build1 | `libp11-kit.so.0` |
| **rtmpdump** | 2.4+20151223.gitfa8646d.1-2build4 | `librtmp.so.1` |

### Build Tool (1)

| Component | Version | SPDX Relationship |
|---|---|---|
| **gcc** | 11.4.0 | `BUILD_TOOL_OF` |

## Python CI/Dev Tools (pip)

These are development and CI dependencies declared in `requirements.txt` files within the curl source repository. **None of these are compiled into or loaded by the curl binary.**

| Package | Version | In Syft | In GitHub |
|---|:---:|:---:|:---:|
| cmakelang | 0.6.13 | ✓ | ✓ |
| codespell | 2.4.1 | ✓ | ✓ |
| cryptography | 46.0.5 | ✓ | ✓ |
| filelock | 3.20.3 | ✓ | ✓ |
| impacket | >= 0.11.0 | ✗ | ✓ |
| proselint | 0.16.0 | ✓ | ✓ |
| psutil | 7.2.2 | ✓ | ✓ |
| pyspelling | 2.12.1 | ✓ | ✓ |
| pytest | 9.0.2 | ✓ | ✓ |
| pytest-xdist | 3.8.0 | ✓ | ✓ |
| pytype | 2024.10.11 | ✓ | ✓ |
| reuse | 6.2.0 | ✓ | ✓ |
| ruff | 0.14.14 | ✓ | ✓ |
| websockets | 16.0 | ✓ | ✓ |

## GitHub Actions (CI Workflows)

These are GitHub Actions referenced in `.github/workflows/*.yml` files. They run in CI pipelines and have **no presence in the compiled binary**.

| Action | In Syft | In GitHub |
|---|:---:|:---:|
| actions/cache | ✓ | ✓ |
| actions/checkout | ✓ | ✓ |
| actions/download-artifact | ✓ | ✓ |
| actions/labeler | ✓ | ✓ |
| actions/upload-artifact | ✓ | ✓ |
| cross-platform-actions/action | ✓ | ✓ |
| curl/curl-fuzzer/.github/workflows/ci.yml | ✓ | ✓ |
| cygwin/cygwin-install-action | ✓ | ✓ |
| github/codeql-action/analyze | ✓ | ✓ |
| github/codeql-action/init | ✓ | ✓ |
| msys2/setup-msys2 | ✓ | ✓ |

## SPDX Document Details

| Property | ADG (OmniBOR) | Syft | GitHub |
|---|---|---|---|
| **SPDX version** | 2.3 | 2.3 | 2.3 |
| **Packages** | 25 | 43 (with duplicates) | 26 |
| **Files** | 441 | 23 | 0 |
| **Relationships** | 466 | 85 | 26 |
| **Relationship types** | `DYNAMIC_LINK` (23), `BUILD_TOOL_OF` (1), `CONTAINS` (441), `DESCRIBES` (1) | `CONTAINS` (42), `OTHER` (42), `DESCRIBES` (1) | `DEPENDS_ON` (25), `DESCRIBES` (1) |
| **Package purpose** | `APPLICATION` (curl, gcc), `LIBRARY` (23 libs) | `FILE` (1), unset (42) | unset (26) |
| **PURLs** | `pkg:deb/ubuntu/...` | mixed | `pkg:pypi/...`, `pkg:githubactions/...` |
| **CPEs** | ✓ (all 23 libs) | ✗ | ✗ |
| **OmniBOR ExternalRef** | ✓ (gitoid on root package) | ✗ | ✗ |
| **Source files** | 441 (.c, .h, .S, .inc) | 0 | 0 |

## Conclusions

1. **ADG (OmniBOR) is the only tool that identifies the 23 shared libraries actually loaded at runtime.** These represent the real attack surface and vulnerability exposure of the curl binary.

2. **Syft and GitHub find the same CI/dev tooling** (pip packages and GitHub Actions) from manifest files. These are useful for supply chain auditing of the build pipeline but are not present in the compiled binary.

3. **BDBA binary scanning detected only curl itself** — it cannot identify the dynamically linked third-party libraries.

4. **The three approaches are complementary, not competing.** A complete supply chain SBOM would combine:
   - ADG for runtime dependencies (what's in the binary)
   - Syft/GitHub for build pipeline dependencies (what built the binary)
   - OmniBOR for cryptographic build provenance (how the binary was built)

---

*Generated by omnibor-analysis ([github.com/tedg-dev/omnibor-analysis](https://github.com/tedg-dev/omnibor-analysis))*
