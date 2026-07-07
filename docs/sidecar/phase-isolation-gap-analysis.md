# Phase Isolation Gap Analysis: Phase 2 Dependencies on `repo_dir`

> **Partially consolidated (2026-06-24):** The Java build-speed and
> duplicate dependency-resolution material (the "Irony" in §2.1 and the
> related rows in §7) is consolidated into
> `java/phase1-build-speed-design.md`. This document is retained
> as the authoritative **multi-language** phase-isolation audit (C/C++,
> Rust, Go, Java) and is not fully superseded.

> **Date**: June 16, 2026
>
> **Status**: Architecture gap analysis — Phase 2 cannot run independently
>
> **Requirement**: Phase isolation is MANDATORY. Phase 2 must operate
> exclusively on Phase 1 artifacts (treedb, manifest, `bom_dir`). Phase 2
> must NEVER read from `repo_dir` (cloned source tree) because `repo_dir`
> does not exist when Phase 2 runs.

---

## 1. The Problem

Phase 2 (SPDX generation) currently reads directly from `repo_dir` in
multiple places across all languages. In an ephemeral CI/CD environment,
`repo_dir` is destroyed when the build stage (Phase 1) exits. Phase 2
runs in a different process, container, or host — the source tree, object
files, and build outputs are gone.

**Current state**: Phase 1 and Phase 2 run sequentially in the same
container via `run_*_pipeline()`. This masks the dependency on `repo_dir`
because the files happen to still exist. But phase isolation — a
mandatory requirement established before Java sidecar implementation —
requires Phase 2 to work without `repo_dir`.

---

## 2. Complete Audit: What Phase 2 Reads from `repo_dir`

### 2.1 Java (sidecar implemented, phase split NOT implemented)

| Phase 2 Operation | File | What it reads from `repo_dir` | How it reads |
|---|---|---|---|
| `get_maven_deps()` | `maven_parser.py:32` | Runs `mvn dependency:tree` subprocess | Needs Maven, `pom.xml`, resolved deps |
| `get_gradle_deps()` | `gradle_parser.py:43` | Runs `./gradlew dependencies` subprocess | Needs Gradle, `build.gradle`, wrapper |
| `get_version()` | `maven_parser.py:224` | Parses `pom.xml` for `<version>` tag | Reads XML from disk |
| `get_gradle_version()` | `gradle_parser.py:249` | Parses `build.gradle` for version | Reads file from disk |
| `get_project_group_id()` | `maven_parser.py:293` | Parses `pom.xml` for `<groupId>` | Reads XML from disk |
| `get_gradle_group()` | `gradle_parser.py:295` | Parses `build.gradle` for group | Reads file from disk |
| `_detect_gradle_version()` | `java_generator.py:234` | Reads `gradle-wrapper.properties` | Reads file from disk |
| `detect_repackaging_plugins()` | `maven_plugin_detector.py` | Reads `pom.xml` for shade/assembly plugins | Reads XML from disk |
| `is_gradle_project()` | `gradle_parser.py:337` | Checks if `gradlew` or `build.gradle` exists | `Path.exists()` |
| JAR globbing | `lang_runners.py:370` | Globs for output JAR files | `repo_dir.glob(pattern)` |
| JAR module detection | `lang_runners.py:452` | Walks up from JAR path to find `pom.xml`/`build.gradle` | `Path.exists()` |
| `BinaryCollector.collect()` | `binary_collector.py:90` | Copies JARs from `repo_dir` | `shutil.copy2()` |

**Irony**: Phase 1 sidecar already runs `mvn dependency:tree` and saves
`maven_deps.json` to `bom_dir`. Phase 2 ignores this and re-runs the
same command against the live source tree.

### 2.2 C/C++ (sidecar NOT implemented, standalone only)

| Phase 2 Operation | File | What it reads from `repo_dir` |
|---|---|---|
| `SpdxGenerator.generate()` | `spdx_generator.py:349` | Resolves binary paths via `repo_dir / rel_path` |
| `AdgSpdxStep.generate()` | `adg_spdx.py:67` | Globs for binaries via `repo_dir.glob(pattern)` |
| `AdgParser.parse()` | `parser.py:95` | Uses `repos_dir` prefix to classify project vs system files |
| `AdgSpdxGenerator.__init__()` | `generator.py:29` | Stores `repos_dir` for path classification |
| `SpdxEmitter.emit()` | `emitter.py:574` | Reads `Cargo.lock` from `repos_dir/repo_name/` |
| `MetadataCollector.collect()` | `metadata_collector.py:93` | Resolves binary paths via `repo_dir / rel_path` |
| `collect_metadata.main()` | `collect_metadata.py:64` | Scans `repo_dir` for version files, headers |
| `collect_dynamic_libs.main()` | `collect_dynamic_libs.py:30` | Runs `ldd` and `readelf` on binary at `repo_dir` path |

### 2.3 Rust (sidecar NOT implemented, standalone only)

Same as C/C++ above, plus:

| Phase 2 Operation | File | What it reads from `repo_dir` |
|---|---|---|
| `parse_cargo_lock()` | `lang_parsers.py:252` | Reads `Cargo.lock` from `repos_dir/repo_name/` |
| `parse_cargo_toml()` | `lang_parsers.py:281` | Reads `Cargo.toml` from `repos_dir/repo_name/` |

### 2.4 Go (sidecar NOT implemented, standalone only)

Same as C/C++ above, plus:

| Phase 2 Operation | File | What it reads from `repo_dir` |
|---|---|---|
| `parse_go_mod()` | `lang_parsers.py:136` | Reads `go.mod` from project files |
| `parse_go_modules_txt()` | `lang_parsers.py:167` | Reads `vendor/modules.txt` from project files |

### 2.5 Cross-cutting

| Phase 2 Operation | File | What it reads from `repo_dir` |
|---|---|---|
| `_detect_repo_version()` | `collect_metadata.py:64` | Iterates `repo_dir` files, scans `include/*.h`, `src/*.h` |

---

## 3. The Async SPDX Architecture Doc Also Has This Gap

`sidecar-async-spdx-architecture.md` line 533 explicitly states:

> "Phase 2 needs: Access to the source tree (for Go module parsing,
> Java dep:tree)"

And line 543:

> "Java: JDK + Gradle/Maven in container — Dep:tree resolution
> requires build toolchain"

This directly contradicts the ephemeral workspace constraint and
principle P5 (Fail-Safe for Ephemeral Build Environments). **The
architecture doc itself is internally inconsistent** — it says Phase 2
needs the source tree, while simultaneously saying the source tree is
destroyed when Phase 1 exits.

---

## 4. Foundational Constraint: Zero Modification to the Host Build

> **Scope**: This section describes the **enterprise K8s sidecar**
> deployment model (§4.2), where a platform team deploys the sidecar
> transparently via Kubernetes webhooks, eBPF DaemonSets, or
> pre-configured container images. The build team changes nothing.
>
> An alternative **CI/CD integration** model exists (see
> `java/enterprise-sbom.md`) in which Phase 1 metadata capture is
> explicitly added to the existing CI/CD build step. In that model,
> the CI/CD pipeline config **is** modified — but only to append a
> Phase 1 `docker run` after the build command. Build scripts
> (`pom.xml`, `build.gradle`, `Makefile`) and build invocations
> (`mvn`, `gradle`, `make`) remain unchanged in both models.

The enterprise K8s sidecar requires **ZERO modifications** to the
customer's:

- **Build system** — no `pom.xml` changes, no `build.gradle` changes,
  no Makefile changes
- **Build commands** — no wrapping `make` with `omnibor-build -- make`,
  no adding flags
- **CI/CD pipeline config** — no changing the pipeline YAML, Jenkinsfile,
  or `.gitlab-ci.yml` (K8s sidecar model only — see note above)

The sidecar is purely **additive infrastructure** — a container,
DaemonSet, or system-level service added by the DevOps/platform team.
The build team changes nothing. The build does not know the sidecar
exists.

### 4.1 What This Rules Out

Several approaches that work for non-sidecar tools are **invalid**
under this constraint:

| Approach | Why it's invalid |
|---|---|
| Wrapper script (`cov-build make`, `bear -- make`) | Changes the build command |
| Maven lifecycle hook (`<phase>verify</phase>` in `pom.xml`) | Modifies the project's `pom.xml` |
| Gradle `finalizedBy` task / init script | Modifies build config or requires `-I` flag |
| `RUSTC_WRAPPER=wrapper cargo build` | Requires setting env var in build command |
| `go build -toolexec=wrapper` | Requires adding flag to build command |
| CI/CD platform hooks (`post:`, `after_script`) | Modifies pipeline config |

Note: Coverity (`cov-build`), SonarQube (`build-wrapper`), and Bear
all use the wrapper pattern. These tools require build command changes.
The OmniBOR sidecar cannot use this pattern.

### 4.2 Valid Sidecar Integration Patterns

The sidecar must intercept at the **kernel/system level** — transparent
to the build system. The valid patterns are:

#### Pattern 1: K8s Mutating Webhook + `LD_PRELOAD` Injection

A Kubernetes `MutatingAdmissionWebhook` automatically injects the
OmniBOR sidecar into build pods. An init container copies the
interception shared library into a shared `emptyDir` volume and sets
`LD_PRELOAD` in the build container's environment. The build command
is unmodified — the dynamic linker loads the interception library
before any other libraries.

```yaml
# Injected automatically by the webhook — customer never sees this
spec:
  initContainers:
    - name: omnibor-init
      image: omnibor-env:init
      command: ["cp", "/opt/omnibor/libintercept.so", "/omnibor/"]
      volumeMounts:
        - name: omnibor-lib
          mountPath: /omnibor
    - name: omnibor-sidecar
      image: omnibor-env:sidecar
      restartPolicy: Always    # K8s 1.28+ native sidecar
      volumeMounts:
        - name: workspace
          mountPath: /workspace
        - name: omnibor-artifacts
          mountPath: /artifacts
  containers:
    - name: build
      # Customer's original build container — UNCHANGED
      image: customer-build:latest
      command: ["make", "-j16"]  # UNCHANGED
      env:
        - name: LD_PRELOAD        # Injected by webhook
          value: /omnibor/libintercept.so
      volumeMounts:
        - name: workspace
          mountPath: /workspace
        - name: omnibor-lib
          mountPath: /omnibor
```

Industry precedent: This is exactly how `EnvProxy` (Vault secret
injection), Istio service mesh, and Dynatrace APM work — mutating
webhooks inject sidecars and `LD_PRELOAD` libraries transparently.

**Applicability**: C/C++ (all build systems), Rust, Go, Java
(for compiler interception). Works with any dynamically-linked binary.

#### Pattern 2: K8s Native Sidecar with eBPF (K8s 1.28+)

The OmniBOR container runs as a native sidecar container (KEP-753).
It loads eBPF programs that attach to kernel tracepoints
(`sched_process_exec`, `sched_process_exit`, `sys_enter_openat`) to
intercept compiler invocations inline. No `LD_PRELOAD` needed — works
even with statically-linked binaries.

K8s sidecar termination guarantee (kubernetes.io): "Upon Pod
termination, the kubelet postpones terminating sidecar containers
until the main application container has fully stopped."

**Applicability**: All languages. Requires `CAP_BPF` / `CAP_SYS_ADMIN`
in the sidecar container.

#### Pattern 3: Node-Level eBPF DaemonSet

A DaemonSet runs on every build node, loading eBPF programs that
monitor all compiler invocations system-wide. Build pods do not need
any modification — the eBPF programs observe from the kernel.

**Applicability**: All languages, all build systems. Requires
privileged DaemonSet on the node.

#### Pattern 4: Container Image with Pre-Configured Interception

The customer uses an OmniBOR-enabled base image for their build
containers. The image has `LD_PRELOAD` and the interception library
pre-installed. The build command is unchanged.

**Applicability**: Requires the customer to change their base image.
This is an infrastructure change (platform team), not a build system
change (dev team). Common pattern for enterprise build environments
that standardize on approved base images.

### 4.3 Build Completion Detection

The sidecar does NOT control the build process. It must detect when
the build finishes so it can run post-build capture before the
workspace is destroyed.

| Detection Mechanism | How it works | Reliability |
|---|---|---|
| **eBPF `sched_process_exit`** | Kernel tracepoint fires when the build process exits. Sidecar receives ring buffer event with PID + exit code. | ✅ Kernel-level, no race conditions |
| **Process monitoring** | Sidecar watches the build PID (via `/proc` or `waitpid` on shared PID namespace). | ✅ Reliable with shared PID namespace |
| **`inotify`/`fanotify`** | Watch for creation of known build output files (JARs, ELF binaries). | ⚠️ May trigger before build fully completes |
| **Shared volume signal** | `LD_PRELOAD` library writes a completion marker file when the build process exits. | ✅ If using `LD_PRELOAD` pattern |

The eBPF `sched_process_exit` tracepoint is the most reliable: it
fires exactly when the build process terminates and includes the PID,
exit code, and parent PID. Tools like `exitsnoop` (bcc/libbpf)
demonstrate this pattern. The sidecar can register a callback for the
build process PID and immediately begin post-build capture when it
fires.

### 4.4 Post-Build Capture Window

Once the sidecar detects build completion, it has a limited window to
capture metadata before workspace destruction. The window depends on
the deployment model:

| Deployment | Window guarantee |
|---|---|
| **K8s native sidecar** | Sidecar runs until SIGTERM after main container exits. `terminationGracePeriodSeconds` (default 30s) provides the window. |
| **K8s non-native sidecar** | No guarantee — sidecar may be terminated simultaneously with build container. |
| **Same-container** | Sidecar process runs inside the build container. Window lasts until the container's entrypoint exits. |
| **DaemonSet** | Runs on the node — survives pod termination. Can access pod volumes until garbage-collected. |

**Critical constraint**: For K8s native sidecars, the default 30-second
`terminationGracePeriodSeconds` may not be enough for Java dep:tree
(5-15 minutes). The pod spec must set a longer grace period — but this
is an infrastructure config change (platform team), not a build change.

---

## 5. Build-Time Impact Reassessment (All Languages)

Everything that must access `repo_dir` runs inside the build stage.
The workspace is destroyed after the stage exits. The sidecar cannot
modify the build command, so all metadata capture happens either:

- **Inline** — via `LD_PRELOAD` or eBPF during the build
- **Post-build** — by the sidecar after detecting build completion,
  within the capture window (section 4.4)

### 5.1 C/C++

| Operation | Time | When it runs | Mechanism |
|---|---|---|---|
| `make -j16` (native build) | ~30 min | Customer's build — unchanged | N/A |
| Inline interception + hashing | +1-3% | During build | `LD_PRELOAD` or eBPF |
| `ldd` + `readelf` per binary | 5-30 sec | Post-build (sidecar) | Sidecar runs on shared volume |
| Version detection from source files | <5 sec | Post-build (sidecar) | Sidecar reads shared volume |
| Copy binaries to `bom_dir` | <10 sec | Post-build (sidecar) | File copy from shared volume |

**Total overhead**: ~1-3% in-band + <1 min post-build = **~3-4%**.

**C/C++ is the cleanest case**: inline interception adds minimal
overhead, and post-build capture is seconds. The 30-second default
K8s `terminationGracePeriodSeconds` is more than enough.

### 5.2 Rust

| Operation | Time | When it runs | Mechanism |
|---|---|---|---|
| `cargo build --release` (native) | varies | Customer's build — unchanged | N/A |
| Inline interception + hashing | +1-3% | During build | `LD_PRELOAD` or eBPF |
| Copy `Cargo.lock`, `Cargo.toml` | <1 sec | Post-build (sidecar) | File copy |
| Copy binaries | <5 sec | Post-build (sidecar) | File copy |

**Total overhead**: ~1-3% in-band + ~5 sec post-build = **~3-4%**.

No live commands needed post-build. `Cargo.lock` and `Cargo.toml` are
small static files that the sidecar copies from the shared volume.

### 5.3 Go

| Operation | Time | When it runs | Mechanism |
|---|---|---|---|
| `go build` (native) | varies | Customer's build — unchanged | N/A |
| Inline interception + hashing | +1-3% | During build | `LD_PRELOAD` or eBPF |
| Copy `go.mod`, `vendor/modules.txt` | <1 sec | Post-build (sidecar) | File copy |
| Copy binaries | <5 sec | Post-build (sidecar) | File copy |

**Total overhead**: ~1-3% in-band + ~5 sec post-build = **~3-4%**.

Same as Rust — trivial post-build capture.

### 5.4 Java — The Hard Problem

Java is fundamentally different from the other languages because the
sidecar needs **dependency graph information** that is not available
from inline interception alone. The treedb (JAR → class → source)
captures what went INTO the JAR, but the full dependency graph
(transitive Maven/Gradle dependencies) requires running the build
tool's dependency resolver.

| Operation | Time | When it runs | Mechanism |
|---|---|---|---|
| `mvn package` or `./gradlew build` (native) | 3-10 min | Customer's build — unchanged | N/A |
| `bomsh_create_bom_java.py` (treedb) | ~2 min | Post-build (sidecar) | Sidecar runs on shared volume |
| `mvn dependency:tree` | 5-15 min | Post-build (sidecar) | **Problem** — see below |
| Parse `pom.xml` for version/groupId | <1 sec | Post-build (sidecar) | Read from shared volume |
| Copy JARs | <5 sec | Post-build (sidecar) | File copy |

**Total overhead**: ~2 min treedb + **5-15 min dep:tree** + seconds
= **7-17 min post-build**.

**The dep:tree problem**: The sidecar cannot modify the build command
to include `dependency:tree` as a lifecycle phase. It must run
`mvn dependency:tree` (or `./gradlew dependencies`) as a **separate
subprocess** after the build completes. This requires:

1. Maven or Gradle installed in the sidecar container
2. The `pom.xml` / `build.gradle` still on the shared volume
3. The local dependency cache (`~/.m2/repository` or `~/.gradle/caches`)
   still accessible — populated during the build
4. A long enough capture window (5-15 minutes)

**This is the single biggest phase isolation challenge.** The K8s
`terminationGracePeriodSeconds` must be set high enough (e.g., 900s)
to allow the sidecar to complete dep:tree before the pod is killed.
This is an infrastructure config change (platform team).

### 5.5 Java: Alternative Approaches to dep:tree

Given that running `mvn dependency:tree` post-build takes 5-15 minutes
and requires a long capture window, are there faster alternatives?

#### Option A: Parse `pom.xml` Offline (No Maven Required)

Parse `pom.xml` and its parent POMs directly to extract `<dependencies>`
declarations. Read the local Maven cache (`~/.m2/repository`) to
resolve transitive dependencies by walking each dependency's POM.

- **Pro**: No Maven subprocess. Runs in seconds. Python-only.
- **Con**: Must reimplement Maven's dependency resolution algorithm
  (version ranges, exclusions, BOM imports, profiles, property
  interpolation). Complex and fragile.

#### Option B: Extract from JAR `META-INF/maven/`

Every JAR built by Maven contains `META-INF/maven/<groupId>/<artifactId>/pom.xml`
and `pom.properties`. The embedded `pom.xml` includes `<dependencies>`.

- **Pro**: No Maven subprocess. Data is in the build output.
- **Con**: Only contains the dependencies declared in THAT module's
  POM, not the fully resolved transitive graph. Dependency versions
  may use property references (`${project.version}`) that are resolved
  at build time but not in the embedded POM.

#### Option C: Read Maven's Resolved Dependency Files

After `mvn package`, Maven writes resolved dependency information to:

- `target/maven-status/maven-compiler-plugin/compile/default-compile/`
  — input file lists
- `~/.m2/repository/` — the full resolved dependency tree is cached here

The sidecar could walk the local repo cache, cross-referencing with
the POM's declared dependencies, to reconstruct the dependency graph.

- **Pro**: No Maven subprocess. Data already exists.
- **Con**: Requires understanding Maven's cache layout. More complex
  than running `mvn dependency:tree`.

#### Option D: eBPF Interception of Maven's Dependency Resolution

During `mvn package`, Maven resolves all dependencies and downloads
them. The sidecar could use eBPF to intercept Maven's JVM file system
calls (reading `pom.xml` files, writing to `~/.m2/repository/`) and
build the dependency graph from those observations.

- **Pro**: Captured inline during the build — no post-build cost.
  Zero modification to the build.
- **Con**: Extremely complex. Must understand Maven's internal file
  access patterns. High engineering effort.

#### Option E: Keep the Current Subprocess Approach

Run `mvn dependency:tree` or `./gradlew dependencies` in the sidecar
post-build, with a sufficiently long `terminationGracePeriodSeconds`.

- **Pro**: Simple. Already implemented. Correct results.
- **Con**: 5-15 minute post-build cost. Requires Maven/Gradle in the
  sidecar container. Requires long capture window.

#### Option F: `mvn dependency:tree -o` (Offline Mode)

After `mvn package` populates the local cache, run
`mvn dependency:tree -o` (offline mode). This skips all network
access (no checking Maven Central for updates) and resolves only from
the local cache. Significantly faster than a full dep:tree.

- **Pro**: Much faster (seconds to 1-2 minutes vs 5-15 minutes).
  Still uses Maven's own resolver — correct results.
- **Con**: Still requires Maven in the sidecar container. Still a
  subprocess call. Fails if the local cache is incomplete (rare after
  a successful build).

**Recommended for Java**: Option F (`-o` offline mode) as the primary
approach, with Option A (offline POM parsing) as a longer-term
replacement that eliminates the Maven dependency entirely.

### 5.6 Summary: Build Stage Overhead by Language

| Language | Native Build | In-Band Overhead | Post-Build Capture | Capture Window Needed | Total Overhead |
|---|---|---|---|---|---|
| **C/C++** | 30 min | 1-3% (~30 sec) | <1 min | 30 sec (default) | **~3%** |
| **Rust** | varies | 1-3% | ~5 sec | 30 sec (default) | **~3%** |
| **Go** | varies | 1-3% | ~5 sec | 30 sec (default) | **~3%** |
| **Java** | 3-10 min | 0% (no inline interception) | 2-17 min | **15+ min** | **~70-500%** |
| **Java (with `-o`)** | 3-10 min | 0% | 2-4 min | **5 min** | **~40-130%** |

**Java remains the outlier** but the offline mode approach (`-o`)
significantly reduces the post-build window requirement from 15+
minutes to ~5 minutes

---

## 6. Phase Isolation Architecture Under Sidecar Constraint

Given that the sidecar cannot modify the build, the phase isolation
architecture must work as follows:

### 6.1 What the Sidecar Captures During the Build (Inline)

| What | How | All languages? |
|---|---|---|
| Compiler/tool invocations | `LD_PRELOAD` or eBPF tracepoint interception | ✅ |
| Input/output file hashes | Inline hashing in interception library | ✅ |
| File open/read/write events | eBPF `sys_enter_openat` or `LD_PRELOAD` `open()` | ✅ |
| Process tree (parent → child) | eBPF `sched_process_fork`/`sched_process_exec` | ✅ |

### 6.2 What the Sidecar Captures Post-Build (Capture Window)

| What | How | Language |
|---|---|---|
| `ldd` + `readelf` on binaries | Sidecar subprocess on shared volume | C/C++ |
| Treedb generation | `bomsh_create_bom_java.py` on shared volume | Java |
| Dependency graph | `mvn dependency:tree -o` on shared volume | Java (Maven) |
| Dependency graph | `./gradlew dependencies --offline` on shared volume | Java (Gradle) |
| Static file copies | `cp` from shared volume to `bom_dir` | All |
| Output binary copies | `cp` from shared volume to `bom_dir/binaries/` | All |
| Version detection | Parse files on shared volume | All |
| `project_metadata.json` | Extract from files on shared volume | All |
| `phase1_manifest.json` | Write to `bom_dir` | All |
| Push to durable storage | `rsync` / S3 upload / artifact store | All |

### 6.3 What Phase 2 Reads (Exclusively from `bom_dir`)

Phase 2 runs on a different host/container/time. It has NO access to
`repo_dir`. It reads only from `bom_dir`:

| Phase 2 Input | Source | Currently exists? |
|---|---|---|
| Treedb | `bom_dir/metadata/bomsh/bomsh_omnibor_treedb` | ✅ |
| Dependency graph | `bom_dir/maven_deps.json` or `gradle_deps.json` | ✅ (but Phase 2 ignores it) |
| Project metadata | `bom_dir/project_metadata.json` | ❌ Must create |
| Binary copies | `bom_dir/binaries/` | ❌ Must create |
| Static files | `bom_dir/source_snapshot/` | ❌ Must create |
| Dynamic lib info | `bom_dir/metadata/<binary>/dynamic_libs.json` | ⚠️ Currently in Phase 2 |
| Phase 1 manifest | `bom_dir/phase1_manifest.json` | ⚠️ Partially exists |

---

## 7. What Currently Exists vs What Must Be Built

| Item | Status | Action needed |
|---|---|---|
| `maven_deps.json` capture | ✅ Phase 1 sidecar already does this | Wire Phase 2 to read it instead of re-running `mvn dep:tree` |
| `gradle_deps.json` capture | ✅ Phase 1 sidecar already does this | Wire Phase 2 to read it instead of re-running `./gradlew dependencies` |
| `project_metadata.json` | ❌ Does not exist | Create writer (version, groupId, build system, plugins) |
| `resolved_binaries.json` | ❌ Does not exist | Create writer (resolved globs → actual paths) |
| Static file copies to `bom_dir` | ❌ Not done | Copy `pom.xml`, `Cargo.lock`, `go.mod`, etc. |
| Binary copies to `bom_dir` | ❌ Not done | Copy JARs/ELF binaries to `bom_dir/binaries/` |
| `ldd`/`readelf` capture | ⚠️ Runs in Phase 2 | Move to sidecar post-build capture |
| Phase 2 reads from `bom_dir` only | ❌ Reads from `repo_dir` | Refactor all parsers and generators |
| Phase 2 re-runs dep:tree | ❌ Ignores captured JSON | Wire to read `maven_deps.json`/`gradle_deps.json` |
| Build completion detection | ❌ Not implemented | eBPF `sched_process_exit` or PID monitoring |
| `mvn dep:tree -o` (offline) | ❌ Not implemented | Add offline flag to sidecar dep:tree call |

---

## 8. Data Sources

- `app/pipeline/lang_runners.py` — Phase 1/2 orchestration
- `app/pipeline/builder.py` — `strategy.generate_adg()` invocation
- `app/pipeline/interception.py` — `MavenDepTreeStrategy`, `GradleDepTreeStrategy`
- `app/spdx/java_generator.py` — `repo_dir` dependencies in Phase 2
- `app/spdx/maven_parser.py` — live `mvn dependency:tree` execution in Phase 2
- `app/spdx/gradle_parser.py` — live `./gradlew dependencies` execution in Phase 2
- `app/spdx/lang_parsers.py` — `Cargo.lock`, `Cargo.toml`, `go.mod` parsing from `repo_dir`
- `app/pipeline/binary_collector.py` — binary copying from `repo_dir`
- `app/pipeline/metadata_collector.py` — `ldd`/`readelf` on binaries in `repo_dir`
- `app/collect_metadata.py` — version detection from source files in `repo_dir`
- `app/spdx/parser.py` — `repos_dir` prefix for file classification
- `async-spdx-architecture.md` — architecture doc
  (internally inconsistent: says Phase 2 needs source tree access)
- `infrastructure.md`
  — phase isolation design
- Kubernetes KEP-753 (kubernetes.io) — native sidecar container lifecycle
- eBPF `sched_process_exit` tracepoint (iovisor/bcc `exitsnoop`)
- `EnvProxy` (github.com/minivolk/EnvProxy) — `LD_PRELOAD` + K8s webhook precedent
- Maven Dependency Plugin `-o` offline mode (maven.apache.org)

---

*Analysis conducted June 16, 2026. Corrected to enforce the sidecar
constraint: zero modifications to customer build system, commands, or
CI/CD pipeline config. Wrapper patterns and lifecycle hooks are invalid
under this constraint. Phase isolation is a mandatory architectural
requirement established before Java sidecar implementation.*
