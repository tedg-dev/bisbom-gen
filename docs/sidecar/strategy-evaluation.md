# Sidecar Interception Strategies — Comprehensive Evaluation

> **Date**: June 15, 2026
>
> **Status**: Active evaluation — corrections applied from prior analysis
>
> **Prerequisite docs**: `c-cpp/sidecar-interception-strategies.md`,
> `ebpf-investigation-report.md`, `sidecar-async-spdx-architecture.md`,
> `infrastructure.md`

---

## 1. Strategic Context

**Sidecar is the ONLY actual strategy.** It is the authoritative and
sole target mode for enterprise build-interception SBOM generation.
The entire `bisbom-gen` project exists to serve enterprise C/C++
(and other language) build environments.

**Standalone mode is being phased out.** It exists only as:

- A deprecated fallback for a rare (~1%) embedded-systems corner case
  where sidecar interception is genuinely unavailable (e.g. a team that
  forks and embeds their own OS, tools, and build orchestration — a fork
  they own)

- A transitional baseline — golden files are being **migrated from
  standalone to sidecar** as each language gets sidecar support (Java
  complete; C/C++ is next)

Development should always use sidecar when the sidecar approach is
available for a given language. Standalone is not a strategy — it is
a stepping stone being phased out.

---

## 2. Per-Language Sidecar Strategy Status

| Language | Sidecar Strategy | Status | Phase Split | Priority |
|----------|-----------------|--------|-------------|----------|
| **Java** | `MavenDepTreeStrategy` / `GradleDepTreeStrategy` | ✅ Fully wired, tested, golden files migrated | ✅ Complete | Done |
| **C/C++** | **TBD — active investigation** (see §4) | ❌ Not implemented | ❌ Not started | **NEXT — #1** |
| **Go** | `GoToolexecStrategy` (`-toolexec=`) | ⚠️ Skeleton only — not wired | ❌ Not started | #2 |
| **Rust** | `RustcWrapperStrategy` (`RUSTC_WRAPPER=`) | ⚠️ Skeleton only — not wired | ❌ Not started | #3 |
| **Python** | Metadata-only pipeline (future) | ❌ Not designed | ❌ N/A | #4 (may move up) |

---

## 3. Go and Rust — Low Risk, Clear Path

Both have well-defined, language-native wrapper mechanisms that are
first-class features of their respective build tools:

- **Go `-toolexec`**: Every Go project uses `go build`. `-toolexec`
  is a Go-native flag — no build system compatibility concerns.
  `bomsh_hook2.py` already has Go command parsers. Same raw logfile
  format as ptrace.

- **Rust `RUSTC_WRAPPER`**: Every Rust project uses
  `cargo build --release`. `RUSTC_WRAPPER` is a Cargo-native env var.
  `bomsh_hook2.py` has the `rustc` parser. Only risk: conflict with
  existing wrappers like `sccache`.

Implementation for each follows the Java pattern (~3 days each): add
`_select_{lang}_strategy()`, accept `mode=`, wire to CLI.

**Blocker**: Verifying `bomsh_hook.sh` with `-toolexec` and
`RUSTC_WRAPPER` calling conventions.

---

## 4. C/C++ — The Critical Enterprise Problem

This is the hardest and most important language to solve. C/C++ is the
primary enterprise target.

### 4.1 Viable Enterprise C/C++ Sidecar Strategies

The strategies that can intercept compiler invocations **without
requiring build system cooperation** — sorted by enterprise coverage
(highest to lowest):

<table>
<tr>
  <th style="width:14%">Strategy</th>
  <th style="width:8%">Overhead</th>
  <th style="width:20%">Enterprise Coverage</th>
  <th style="width:20%">Capabilities Needed</th>
  <th style="width:18%">Maturity</th>
  <th style="width:20%">Key Limitation</th>
</tr>
<tr>
  <td><strong>eBPF tracepoints</strong></td>
  <td>1–3%</td>
  <td><strong>High</strong> — kernel-level, works regardless of build system</td>
  <td><code>CAP_BPF</code>+<code>CAP_PERFMON</code> (kernel 5.8+) or <code>CAP_SYS_ADMIN</code> (older)</td>
  <td><code>build-observer</code> shipped (Apache 2.0, open-source). <code>ebomf</code> private.</td>
  <td>Kernel 5.8+ for <code>CAP_BPF</code>; older kernels need <code>CAP_SYS_ADMIN</code>; SELinux may block</td>
</tr>
<tr>
  <td><strong>Linux audit (<code>auditd</code>)</strong></td>
  <td>5–15%</td>
  <td><strong>High</strong> — kernel-level <code>execve</code> tracing</td>
  <td>Root or <code>CAP_AUDIT_CONTROL</code></td>
  <td>Proven for security monitoring; not proven for SBOM</td>
  <td>Higher overhead; verbose logging; may conflict with existing audit policies</td>
</tr>
<tr>
  <td><strong><code>LD_PRELOAD</code></strong></td>
  <td>1–3%</td>
  <td><strong>Medium</strong> — works on any dynamically-linked build tool regardless of <code>CC=</code> compliance</td>
  <td>None</td>
  <td>Proven (Bear uses this for 10+ years)</td>
  <td>Fails on statically-linked build tools. Fails on musl/Alpine. Fails if build sanitizes env.</td>
</tr>
<tr>
  <td><strong>CC= wrappers</strong></td>
  <td>3–5%</td>
  <td><strong>Low</strong> — only compliant builds that respect <code>$(CC)</code></td>
  <td>None</td>
  <td>Pattern proven (ccache/distcc/sccache) but wrappers not written</td>
  <td>Majority of enterprise builds do NOT respect <code>CC=</code></td>
</tr>
</table>

See `c-cpp/sidecar-interception-strategies.md` for exhaustive analysis
of each strategy, including devil's advocate challenges, data capture
capabilities, compatibility matrices, and enterprise adoption data.

### 4.2 eBPF — Kernel Version Reality Check

Linux 5.8 was released **August 2, 2020** — less than 6 years ago.
For enterprise environments running 10+ year old build infrastructure:

| Enterprise OS | Kernel | eBPF Tracepoints | `CAP_BPF` (needs 5.8+) | Still in Use? |
|--------------|--------|-----------------|----------------------|---------------|
| **RHEL 7** | 3.10 (2014) | ❌ No eBPF | ❌ No | Yes — EOL but extended support until 2028 |
| **RHEL 8** | 4.18 (2019) | ✅ Backported | ❌ Needs `CAP_SYS_ADMIN` | **Very common** |
| **Ubuntu 18.04** | 4.15 (2018) | ⚠️ Limited | ❌ Needs `CAP_SYS_ADMIN` | Still exists in legacy |
| **Ubuntu 20.04** | 5.4 (2020) | ✅ Available | ❌ Needs `CAP_SYS_ADMIN` | Common |
| **RHEL 9** | 5.14 (2022) | ✅ Available | ✅ Available | Growing |
| **Ubuntu 22.04+** | 5.15+ | ✅ Available | ✅ Available | Current |

**Problem**: On RHEL 7 (kernel 3.10), eBPF is simply unavailable. On
RHEL 8 and Ubuntu 20.04 (the most common enterprise platforms today),
eBPF works but requires `CAP_SYS_ADMIN` — a significantly harder ask
than `CAP_BPF` in locked-down enterprise environments. SELinux (RHEL
default) may also block BPF program loading.

**Implication**: eBPF is not a universal enterprise solution *today*,
though it will become one as older kernels age out. For legacy
environments, `LD_PRELOAD` or Linux audit may be the only sidecar
options that work without kernel capabilities.

### 4.3 `build-observer` (sbom-observer) — Key External Validation

`build-observer` from the sbom-observer project is an **open-source,
government-funded, Apache 2.0** tool that uses eBPF for build
interception to generate SBOMs. It validates the eBPF approach as
production-viable.

**Repository**: https://github.com/sbom-observer/build-observer

**Important distinction**: `build-observer` produces **CycloneDX**
SBOMs, not SPDX. This project supports **SPDX 2.3 only** (with 3.x
coming). The observation log format from `build-observer` could
potentially be adapted to feed our SPDX generators, but the SBOM
output itself is not directly compatible.

Key facts:

- Requires root for eBPF load, then drops privileges
- Linux 5.8+ kernel
- Claims "minimal performance impact — only added a few percent"
- JSON observation log of all files read, written, or executed
- Uses eBPF perf ring buffer for event delivery
- Language-agnostic — tested with C, Rust, Java, Python, Node.js
- Would need an adapter layer to produce our treedb/raw-logfile
  format for `bomsh_create_bom.py`, or a new pipeline path

### 4.4 Why CC= Wrappers Are NOT Viable for Enterprise

`CcWrapperStrategy` (setting `CC=`, `CXX=`, `AR=`, `LD=` env vars)
**has been evaluated and dismissed as inadequate for enterprise C/C++
builds** across multiple evaluations. It is the **last resort**,
applicable only to a very small subset of well-structured open-source
projects that happen to use `$(CC)` variable expansion.

**Enterprise C/C++ reality** (the sole target of this program):

- **Hardcoded compiler paths** in Makefiles and scripts (10+ years
  old) — literal `/usr/bin/gcc` or `/opt/vendor/bin/cc` instead of
  `$(CC)`

- **Proprietary or custom build systems** that ignore `CC=` env vars
  entirely

- **Multi-layer build orchestrations** — wrapper around wrapper around
  compiler; env vars don't propagate

- **Generated Makefiles** — `gyp`, legacy autoconf caches, code
  generators that embed absolute paths

- **Configure-time compiler caching** — autoconf captures the compiler
  path at `./configure` time and bakes it in

The 6 open-source C/C++ test repos (curl, ffmpeg, openosc, nmap,
openssl, redis) are **not enterprise repos** and are **not
representative** of enterprise build environments. They work with
`CC=` because they are well-structured open-source projects.

CC= wrappers also carry an **implementation cost**: the wrapper scripts
(`bomsh_cc_wrapper.sh` etc.) are not yet built — they would be thin wrappers
around upstream `bomsh`'s `bomsh_hook2.py`, developed in this repo.

**Bottom line**: `CcWrapperStrategy` may have a niche role for the
small subset of compliant builds, but it is **not the enterprise C/C++
sidecar solution**.

### 4.5 Recommended C/C++ Strategy — Multi-Tier with Graceful Fallback

Since no single strategy covers all enterprise environments, a
**tiered fallback** is needed:

<table>
<tr>
  <th style="width:12%">Tier</th>
  <th style="width:18%">Strategy</th>
  <th style="width:35%">Target Environment</th>
  <th style="width:35%">When to Use</th>
</tr>
<tr>
  <td><strong>1 (primary)</strong></td>
  <td><strong><code>LD_PRELOAD</code></strong></td>
  <td>Enterprise builds with dynamically-linked toolchains (majority)</td>
  <td>Default sidecar strategy — no capabilities needed, high coverage</td>
</tr>
<tr>
  <td><strong>2 (advanced)</strong></td>
  <td><strong>eBPF</strong></td>
  <td>Environments with 5.8+ kernels AND <code>CAP_BPF</code> granted AND <code>LD_PRELOAD</code> fails (static tools, env sanitization)</td>
  <td>Config-selectable; evaluate <code>build-observer</code> as reference</td>
</tr>
<tr>
  <td><strong>3 (fallback)</strong></td>
  <td><strong>CC= wrappers</strong></td>
  <td>Well-structured builds that respect <code>$(CC)</code> where <code>LD_PRELOAD</code> is unavailable</td>
  <td>Last resort for niche cases</td>
</tr>
<tr>
  <td><strong>4 (legacy)</strong></td>
  <td><strong>ptrace (standalone fork)</strong></td>
  <td>Extreme corner cases — team forks standalone with custom OS/tools</td>
  <td>Not a sidecar strategy; team-owned fork</td>
</tr>
</table>

**`LD_PRELOAD` should be the primary enterprise strategy** because:

- Zero special capabilities needed
- Works regardless of whether the build system respects `CC=`
- Covers any dynamically-linked build tool (gcc, g++, clang, make,
  cmake, etc.)
- 10+ years of production use in Bear
- Available on every kernel version (no 5.8+ requirement)
- Only fails on statically-linked tools (uncommon for compilers) or
  env-sanitizing builds

eBPF is the **future primary strategy** as older kernels age out and
`CAP_BPF` becomes standard in enterprise container policies.

See `c-cpp/sidecar-interception-strategies.md` §8 for the full
auto-detection decision tree and recommended strategy combinations
with coverage estimates.

---

## 5. Phase Isolation — Solid Foundation

The manifest-based phase split is well-designed and validated for Java:

- `phase1_manifest.json` is the sole contract between phases
- Gitoid integrity verification
- Proven in CI/CD across 3 Azure runners
- 35 unit tests (22 manifest + 13 phase isolation)

Scaling to C/C++ (and then Go/Rust) requires:

- Splitting monolithic runners into `phase1()`/`phase2()`
- Pre-computing version metadata in Phase 1 for cross-host Phase 2
- Handling binary transfer for `bomsh_sbom.py` and `BinaryCollector`

See `infrastructure.md`
for full manifest schema, execution patterns, and implementation plan.

---

## 6. Prioritized Action Plan

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **1** | Design and implement `LdPreloadStrategy` for C/C++ sidecar | ~5–7d | Primary enterprise C/C++ solution |
| **2** | Evaluate `build-observer` (sbom-observer) for eBPF reference | ~2d | Validates eBPF path; informs Tier 2 strategy |
| **3** | Split C/C++ runner into `phase1()`/`phase2()` | ~2d | Enables phase isolation for C/C++ |
| **4** | Wire Go sidecar (`GoToolexecStrategy`) | ~3d | Covers 6 Go repos |
| **5** | Wire Rust sidecar (`RustcWrapperStrategy`) | ~3d | Covers 2 Rust repos |
| **6** | Full eBPF strategy (using `build-observer` or in-house) | ~6d | Future primary for 5.8+ environments |
| **7** | Python sidecar design (metadata-only) | TBD | May move up based on side project |

---

## 7. Key Corrections Documented

This evaluation corrects errors from prior analysis:

1. **Sidecar is the ONLY strategy** — standalone is a legacy niche
   being phased out, not a co-equal mode

2. **CC= wrappers are NOT the enterprise C/C++ proposal** — they are
   the last resort for a small subset of compliant builds, not the
   current strategy

3. **eBPF requires kernel 5.8+** (released August 2, 2020) — not
   available on RHEL 7; requires `CAP_SYS_ADMIN` on RHEL 8 and
   Ubuntu 20.04

4. **SPDX only** — `build-observer` produces CycloneDX, not SPDX;
   adapter needed for our pipeline

5. **Enterprise coverage assessment corrected** — ptrace standalone is
   not a sidecar strategy and must not appear in sidecar coverage
   comparisons

6. **Language priority**: C/C++ is NEXT, then Go, then Rust, then
   Python (may move up)

---

*Evaluation conducted June 15, 2026. Corrections applied from prior
sessions where CC= wrappers were incorrectly presented as the current
enterprise C/C++ proposal.*
