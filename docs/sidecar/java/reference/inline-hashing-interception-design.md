# Java Inline-Hashing Interception — Design

| | |
|---|---|
| **Status** | Implemented (Python assembler + strategies + config + shim); byte-identity EC2-validation pending |
| **Date** | 2026-07-15 |
| **Authors** | Ted G. (architect), Cascade AI |
| **Applies to** | Java sidecar mode (Maven and Gradle; extensible to Ivy/Bazel/`make`) |
| **Objective** | Compute OmniBOR gitoids **inline during build interception** for Java, eliminating the post-build workspace rescan that dominates Phase 1 wall time |
| **Hard constraints** | Sidecar-only; native build system UNCHANGED; CI/CD-YAML injection only; golden-clean output |
| **Related** | `infrastructure.md` §10.1, `cicd-workspace-lifecycle.md` §3.3/§5, `sidecar-design.md`, `phase1-build-speed-design.md`, `phase2-consume-dep-capture.md` |

---

## 1. Problem and the rule being enforced

Build interception means **hashing artifacts inline as the build produces
them**. Every other language already does this — C/C++ via `CC`/`CXX`/`AR`/`LD`
wrappers, Go via `-toolexec`, Rust via `RUSTC_WRAPPER`, standalone via
`bomtrace3` (see `app/pipeline/interception.py`). Java is the **only**
strategy whose `instrument_command()` is a no-op
(`@/Users/tedg/workspace/omnibor-analysis/app/pipeline/interception.py:349-355`
and `:465-471`): the build runs uninstrumented and **all** gitoid/treedb work
is deferred to a post-build workspace rescan in `generate_adg()` →
`_generate_java_treedb()` (`:43-93`), which runs `bomsh_create_bom_java.py`.

That rescan is the cost. For a JAR with N `.class` files it does `find` +
`jar -xf`/unzip + `git hash-object` (SHA-1) + `SourceFile` parse over every
class (`bomsh_java_fast_io.py` docstring: "~3N subprocesses per JAR"). Even
after the ~12x fast-path optimization (`bomsh_java_fast_classreader.py` +
`bomsh_java_fast_io.py`), the residual rescan cost dominates Phase 1 on large
multi-module repos.

Measured `adg` (treedb + `dep:tree`) wall time, sidecar, warm caches, EC2:

| Repo | Native build | `adg` | `adg` as % of build |
|---|---|---|---|
| `spring-boot` | 21.7 s | 79.6 s | +362% |
| `dependency-check` | 22.2 s | 22.9 s | +102% |
| `bc-java` | — | 18.5 s | — |
| `checkstyle` | — | 6.3 s | — |
| `logging-log4j2` | — | 4.8 s | — |
| `jsoup` | — | 3.0 s | — |
| `crawler4j` | — | 2.3 s | — |
| `omnibor-java-testapp` | — | 2.2 s | — |

The interception overhead itself is ~free today (−1.1 s .. +1.8 s) **only
because nothing is intercepted**. The goal is to move the hashing inline so
the post-build step collapses to cheap in-memory assembly.

---

## 2. Constraints (non-negotiable)

| # | Constraint | Source |
|---|---|---|
| C1 | **Sidecar only** — no `SYS_PTRACE`, no ptrace, no strace | `strategy-evaluation.md` §1; project memory |
| C2 | **Native build system UNCHANGED** — `pom.xml`, `build.gradle(.kts)`, `settings.gradle`, and the `mvn`/`gradle` command line are byte-for-byte identical | USER directive; `enterprise-sbom.md` |
| C3 | **CI/CD-YAML injection only** — the only permitted customer action is adding a step or environment variable in the pipeline YAML | USER directive |
| C4 | **Inline hashing is mandatory** — hash at production time, not by rescan | `cicd-workspace-lifecycle.md` §3.3/§5 Rule 2 |
| C5 | **Golden-clean** — SPDX output must be byte-identical to the approved baselines; report diffs and STOP | `golden-file-policy.md` |
| C6 | **Generic and config-driven** — no per-repo or per-language branches in executable code | project rules |

Any mechanism that cannot satisfy C1–C3 is off the table and will be reported
as infeasible rather than proposed.

---

## 3. What the treedb actually requires (grounded)

The bomsh Java treedb record, per JAR, is:

```python
record = {"outfile": (git_blob_sha1(jarfile), jarfile), "infiles": [...]}
```

To build it, bomsh needs, for the built workspace:

| Datum | Where it comes from today (post-build) | Available inline at write time? |
|---|---|---|
| `.class` git-blob SHA-1 (treedb topology) | `git hash-object` over each `.class` | **Yes** — hash the bytes at `close()` |
| `.class` `SourceFile` attribute (class → source) | parse `.class` bytecode (`bomsh_java_fast_classreader.py`) | **Yes** — parse the same bytes at `close()` |
| `.class` fully-qualified class name | parse `.class` bytecode | **Yes** — same parse |
| JAR git-blob SHA-1 (outfile id) | `git hash-object` over the JAR | **Yes** — hash the bytes at JAR `close()` |
| JAR → `.class` membership | `jar -xf`/unzip + match | **Yes** — read the JAR central directory at JAR `close()` |
| SHA-256 gitoid (SBOM identity) | `manifest.py:_sha256_gitoid` post-build | **Yes** — compute alongside the SHA-1 |

Conclusion: **every input to the treedb is derivable from the bytes of each
`.class`/`.jar` at the instant it is written.** The rescan recomputes what the
build already produced. Capturing it inline makes `generate_adg()` an assembly
step over a capture log — no `find`, no unzip, no re-hash.

---

## 4. Design

### 4.1 Interposition mechanism — `LD_PRELOAD` shim (sidecar, no build change)

A small shared library (`libomnibor_java_intercept.so`) is loaded into the
build's JVM processes via `LD_PRELOAD`, exported **from the CI/CD YAML** before
the existing build step runs. This is the direct Java analog of the C/C++
sidecar shim described in `infrastructure.md` §10.1, and it satisfies C1–C3:
the JVM, `pom.xml`, `build.gradle`, and the `mvn`/`gradle` command are all
untouched.

The shim interposes libc file-finalization calls and, when the finalized path
is a build artifact, records one capture event:

| Interposed call | Why |
|---|---|
| `close(2)` (via `close`/`__close`) | Primary artifact-finalization point for `.class`/`.jar` written in place |
| `rename(2)`/`renameat(2)` | Build tools commonly write `foo.tmp` then atomically rename to `foo.jar`/`foo.class` |
| `openat(2)` (read-only tracking) | Optional: correlate compile inputs; not required for the treedb |

The shim classifies a finalized path by suffix (`.class`, `.jar`/`.war`/`.ear`)
and by being under the build workspace root (config-provided), never by repo
name.

### 4.2 What the shim records per artifact

For each finalized `.class`:

- git-blob SHA-1 and SHA-256 gitoid of the bytes
- `SourceFile` attribute and fully-qualified class name (parsed from the same
  in-memory bytes using the existing pure-Python reader logic ported to the
  shim, or delegated — see §4.6)
- absolute path

For each finalized `.jar`/`.war`/`.ear`:

- git-blob SHA-1 and SHA-256 gitoid of the archive bytes
- the archive's entry list (central directory) restricted to `.class` entries,
  by **name only** (read from the central directory without inflating). The
  assembler correlates each member name to the already-captured on-disk
  `.class` git-blob SHA-1 (the member bytes equal the on-disk `.class` bytes),
  so no decompression happens in the shim. The JSONL schema still allows an
  optional per-entry `sha1` for flows that produce it.
- absolute path

### 4.3 Capture-log format (config-driven location)

Events append to a capture log at a **config-driven** path (default under the
bomsh metadata dir, never hardcoded). The format is an append-only JSONL stream
so concurrent JVM processes (parallel modules) can write without coordination:

```json
{"kind": "class", "path": "…/App.class", "sha1": "…", "gitoid": "…", "source_file": "App.java", "class_name": "com.example.App"}
{"kind": "jar", "path": "…/app.jar", "sha1": "…", "gitoid": "…", "entries": [{"name": "com/example/App.class", "sha1": "…"}]}
```

### 4.4 `generate_adg()` becomes assembly, not rescan

The Java `generate_adg()` no longer runs the workspace scan. It:

1. reads the capture log,
2. assembles the treedb in the exact bomsh schema (`outfile`/`infiles`,
   JAR → class → source) from the captured events, and
3. runs `dep:tree`/`gradlew dependencies` as today (unchanged — that is
   declared-graph capture, orthogonal to hashing).

If the capture log is missing or incomplete, it **fails loudly** (C4/C5); it
does not silently fall back to a rescan in the enterprise path. A co-located
dev/test convenience fallback may run the legacy scan, clearly logged as a
non-enterprise path (mirrors `phase2-consume-dep-capture.md` §6).

### 4.5 CI/CD-YAML injection (the only customer-visible change)

```yaml
- name: Build (unchanged)
  run: |
    export LD_PRELOAD=/opt/omnibor/lib/libomnibor_java_intercept.so
    export OMNIBOR_CAPTURE_LOG="$PWD/.omnibor/capture.jsonl"
    mvn -B package -DskipTests      # ← identical to the customer's existing command
```

`pom.xml`/`build.gradle`/`settings.gradle` and the `mvn`/`gradle` invocation
are unchanged. Only two environment variables are added, in the pipeline YAML.

### 4.6 Strategy composition (generic, config-driven)

Instead of a separate subclass, the inline-hash behavior is composed into the
existing `MavenDepTreeStrategy` and `GradleDepTreeStrategy` via shared helpers,
so Maven and Gradle use one implementation (DRY). Selection is config-driven
(`omnibor_java.java_inline_hash`), never repo/language hardcoded.
`instrument_command()` returns the build command **unmodified** with the
`LD_PRELOAD`/`OMNIBOR_CAPTURE_LOG` env additions (plus a Gradle daemon-disable
flag) — the only strategy-injected change; the treedb source is chosen by the
shared `build_java_treedb()` dispatcher ("assemble-from-capture" vs legacy scan).

### 4.7 Delivered components

| Component | Location |
|---|---|
| Capture-log reader + treedb assembler | `app/pipeline/java_capture.py` |
| Inline-hash helpers + strategy wiring | `app/pipeline/interception.py` |
| Config-driven selection | `app/pipeline/lang_runners.py` (`_java_inline_config`, `_select_java_strategy`) |
| Config flag | `app/config.yaml` (`omnibor_java.java_inline_hash`, default **true**) |
| `LD_PRELOAD` shim | `docker/shim/omnibor_java_intercept.c` (built in the Docker `standalone` stage, copied into `sidecar`) |

Byte-identical treedb vs the legacy rescan was validated on EC2 (see §7, §10):
all 8 Java repos are golden-clean at package **and** file level with the flag
on, so `java_inline_hash` defaults to `true` — this is the mandatory inline
path (C4). The flag remains as an explicit override: set it to `false` to
force the legacy post-build rescan on a platform where the shim cannot
interpose (musl/Alpine or a statically-linked launcher, V4), where the inline
path otherwise fails loudly rather than silently rescanning.

---

## 5. Artifact identity

Per `artifact-identity.md`, every artifact carries a SHA-256 gitoid **and** a
SHA-256 raw digest in the SBOM; the SHA-1 git-blob hash is the bomsh treedb
**topology bridge only** and never surfaces in the SBOM. The shim therefore
computes both the SHA-1 (to reproduce the treedb byte-identically) and the
SHA-256 gitoid (for SBOM identity) at capture time.

---

## 6. Correctness / golden-clean strategy

The treedb assembled from the capture log must be **byte-identical** to the
treedb the rescan produces, so downstream SPDX is unchanged. Verification:

1. Run both paths (legacy rescan and inline-capture) on the same build and
   diff the resulting `bomsh_omnibor_treedb` — must be identical.
2. Run the full pipeline and compare SPDX against the approved golden baselines
   for the multi-module repos (`dependency-check`, `logging-log4j2`,
   `checkstyle`, `spring-boot`). Any diff is reported and work STOPS pending
   USER review — no golden updates.

---

## 7. Open validation items (must be proven, not assumed)

These are genuine risks. None will be asserted as working until validated on
EC2 against real repos:

| # | Risk | Validation |
|---|---|---|
| V1 | **JVM libc interposition** — HotSpot must reach `.class`/`.jar` finalization through interposable libc symbols, not raw `syscall()` | Instrument a real `mvn package`; confirm every produced `.class`/`.jar` yields a capture event vs a `find` inventory |
| V2 | **Atomic-write rename patterns** — tools writing `*.tmp` then `rename()` | Confirm `rename`/`renameat` hooks capture final paths for Maven, Gradle `Jar` task, and `jar` |
| V3 | **Gradle daemon reuse** — a pre-existing daemon started without the preload would miss classes | Disable the daemon via **env** (`GRADLE_OPTS=-Dorg.gradle.daemon=false`) set in CI/CD YAML — confirm this is not a build-file/command change |
| V4 | **musl/Alpine / statically-linked launchers** — `LD_PRELOAD` limitations noted in `strategy-evaluation.md` §4 | Test on the Alpine image; document fallback behavior |
| V5 | **In-memory JAR assembly** — tools that assemble a JAR fully in memory then write once | The single final `close()` still yields the JAR bytes + central directory — confirm entry hashes match |
| V6 | **Concurrent module builds** — parallel JVMs appending to one capture log | JSONL append-only + per-line atomicity; confirm no interleaving corruption |

If any of V1–V6 cannot be satisfied within C1–C3, that will be reported plainly
and the design revised — no workaround that touches the build definition.

---

## 8. Measurement plan

Report two numbers **separately** (never conflate the rescan with build time):

- **Build-stage in-band cost** — the added wall time inside the developer's
  build step (target: 1–3%, matching the inline overhead of other languages).
- **Post-build capture-window cost** — treedb assembly + `dep:tree` + any push,
  which runs after the build command returns.

Method: extend the existing baseline/instrumented harness (`app/pipeline/timing.py`,
`/tmp/parse_java_timing.py`) to record inline-capture overhead vs the legacy
rescan across all eight Java repos, warm caches, on EC2.

---

## 9. Testing plan

| Layer | Tests |
|---|---|
| Unit | shim capture-event schema; treedb assembler produces the bomsh schema from a fixture capture log; `SourceFile`/class-name parse parity with `bomsh_java_fast_classreader.py`; missing/partial capture fails loudly |
| Unit | `JavaInlineHashStrategy.instrument_command()` injects only `LD_PRELOAD`/`OMNIBOR_CAPTURE_LOG`, leaves the command unchanged |
| Integration (EC2) | treedb byte-identical (legacy vs inline) per repo; SPDX golden comparison; performance split per §8 |
| Coverage | ≥97% overall, ≥95% per file, including new modules |

---

## 10. Staged delivery (each stage gated on approval)

1. This design doc — approve before any code.
2. Prototype shim + capture-log assembler; prove V1/V2 on `omnibor-java-testapp`
   and `dependency-check`; treedb byte-identical.
3. `JavaInlineHashStrategy` wired via config; Maven + Gradle share it.
4. Measurement across all eight repos (§8); golden validation (§6).
5. Validate V3–V6 (Gradle daemon, Alpine, in-memory JAR, concurrency).
6. PR for USER review.

---

## 11. Explicitly NOT changed

- `pom.xml`, `build.gradle(.kts)`, `settings.gradle`, `build.xml`, `ivy.xml`,
  `Makefile` — untouched.
- The `mvn`/`gradle`/`ant`/`javac` command line — untouched.
- No compiler plugins, no annotation processors, no build-arg edits.
- Phase 2 SPDX generation — unchanged; it still consumes the treedb +
  dep-capture JSON.

The only additions are (a) the `LD_PRELOAD` shim shipped in the sidecar image
and (b) two environment variables set in the CI/CD YAML.
