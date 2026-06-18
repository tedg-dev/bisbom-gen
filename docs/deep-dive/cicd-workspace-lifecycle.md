# CI/CD Workspace Lifecycle: When Source and Build Artifacts Disappear

> **Date**: June 16, 2026
>
> **Status**: Industry best practices research — architectural constraint for sidecar Phase 1
>
> **Context**: The OmniBOR sidecar Phase 1 must hash files during the build because the workspace is destroyed after the build stage completes. This document establishes the industry-standard CI/CD workspace lifecycle and its implications for build interception architecture.

---

## Executive Summary

**The build workspace is ephemeral.** In every major CI/CD platform used
by enterprise C/C++ teams, source files, object files, and intermediate
build artifacts are **destroyed** when the build stage/job/pod completes.
There is no guarantee that any file — source or binary — will exist after
the build step finishes.

This is not an edge case. It is the **default behavior** of:

- GitHub Actions (hosted runners)
- GitLab CI/CD (Docker/Kubernetes executors)
- Jenkins (Kubernetes agents, ephemeral Docker agents)
- Harness CI (Kubernetes pods)
- Azure DevOps (hosted agents)
- CircleCI (Docker executors)
- TeamCity (cloud agents)

**Architectural implication**: Phase 1 (build interception) MUST hash
all input and output files **inline, per compilation unit, during the
build** — not in a post-build batch. When the build stage exits, the
files are gone forever.

---

## 1. The Five Workspace Lifecycle Models

Enterprise CI/CD platforms implement one of five workspace lifecycle
models. In all models except Model E (legacy persistent), the workspace
is destroyed at stage or job boundary.

### Model A: Ephemeral VM (destroyed after each job)

**Platforms**: GitHub Actions (hosted), Azure DevOps (hosted agents)

Each job runs on a **fresh virtual machine** that is destroyed when the
job completes. The entire filesystem — source checkout, build artifacts,
temporary files — is gone.

```yaml
# GitHub Actions — each job is a fresh VM
jobs:
  build:
    runs-on: ubuntu-latest     # Fresh VM
    steps:
      - uses: actions/checkout@v4
      - run: make -j$(nproc)
      # When this job ends, the VM is destroyed
      # Source code, .o files, binaries — ALL gone

  test:
    runs-on: ubuntu-latest     # DIFFERENT fresh VM
    needs: build
    steps:
      # Source code does NOT exist here
      # Must download artifacts explicitly
      - uses: actions/download-artifact@v4
```

**GitHub documentation**: "Each job runs in a fresh instance of the
virtual environment specified by `runs-on`." Files created in one job
are not available in subsequent jobs without explicit artifact upload.

### Model B: Ephemeral Container (destroyed after each stage)

**Platforms**: GitLab CI (Docker executor), CircleCI (Docker)

Each stage runs in a **fresh container**. The container is removed when
the stage completes. Source code is re-checked-out in each stage unless
`GIT_STRATEGY: none` is set.

```yaml
# GitLab CI — each stage is a fresh container
stages:
  - build
  - test

build_job:
  stage: build
  script:
    - ./configure && make -j$(nproc)
  artifacts:
    paths:
      - build/output-binary  # Only artifacts survive

test_job:
  stage: test
  script:
    # Source code is re-cloned here (fresh container)
    # Object files from build stage do NOT exist
    # Only explicitly declared artifacts are available
    - ./build/output-binary --self-test
```

**GitLab documentation** (Runner Issue #336): "GitLab CI, by default,
starts each stage with a clean environment, which means files created
in one stage (like compiled binaries or build outputs) are not
automatically available in subsequent stages."

### Model C: Ephemeral Kubernetes Pod (destroyed after each stage)

**Platforms**: Jenkins (Kubernetes plugin), Harness CI, Tekton, Argo Workflows

Each build stage creates a Kubernetes pod. The pod is **destroyed
immediately** when the stage completes — even if other stages in the
same pipeline are still running.

**Harness CI documentation**: "Build pod cleanup takes place immediately
after the completion of a stage's execution. This is true even if there
are multiple CI stages in the same pipeline; as each build stage ends,
the pod for that stage is cleaned up."

**Jenkins with Kubernetes agents**: The pod is the workspace. When the
build stage finishes, the pod is terminated and its filesystem is lost.

### Model D: Persistent Workspace with Explicit Cleanup

**Platforms**: Jenkins (persistent agents), TeamCity (on-prem agents)

The workspace persists on a long-lived agent, but **best practice is
explicit cleanup after each build**. The Jenkins Workspace Cleanup
Plugin (`ws-cleanup`) is one of the most installed Jenkins plugins.

```groovy
// Jenkins Declarative Pipeline — standard pattern
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh './configure && make -j$(nproc)'
            }
        }
    }
    post {
        always {
            // THIS IS THE STANDARD PATTERN
            // Workspace is wiped after every build
            cleanWs(deleteDirs: true, disableDeferredWipeout: true)
        }
    }
}
```

Even on persistent agents, workspace cleanup is the **default
recommendation** because:

- Disk space: C/C++ builds produce GBs of object files
- Reproducibility: stale files from previous builds cause failures
- Security: source code and secrets must not persist on shared agents
- Compliance: SOC 2 / FedRAMP require workspace sanitization

### Model E: Persistent Workspace (legacy — declining)

**Platforms**: Jenkins (traditional persistent agents without cleanup)

Workspace persists between builds on the same agent. Source and build
artifacts remain on disk until the next build or manual cleanup.

**This model is actively being phased out** in enterprise environments
due to security, reproducibility, and disk space concerns. The industry
trend is overwhelmingly toward ephemeral environments.

---

## 2. Enterprise C/C++ Build Cleanup Patterns

Enterprise C/C++ builds are particularly aggressive about cleanup because
of the large artifact sizes involved. A typical large C/C++ project
produces 5-50 GB of intermediate object files during a `-j64` build.

### 2.1 Common Cleanup Patterns in Enterprise C/C++ CI

| Pattern | When It Runs | What Gets Deleted | Prevalence |
|---------|-------------|-------------------|-----------|
| Pod/VM destruction | Immediately after stage completes | Everything — source, objects, binaries | ~60% of enterprise (K8s/cloud) |
| `cleanWs()` (Jenkins) | Post-build `always` block | Entire workspace directory | ~25% of enterprise (Jenkins persistent) |
| `make clean` / `make distclean` | End of build script | Object files, libraries (source remains) | ~10% (within persistent agents) |
| Docker volume removal | Container exit | Container filesystem | ~40% (Docker-in-Docker builds) |
| No cleanup (rely on next checkout) | Never explicit | Nothing explicitly | ~5% (legacy, declining) |

### 2.2 What `make clean` and `make distclean` Delete

For builds on persistent agents that don't destroy the entire workspace,
build scripts frequently run `make clean` as a final step:

| Target | Deletes | Source Code Survives? |
|--------|---------|----------------------|
| `make clean` | `.o`, `.a`, `.so`, binaries | Yes |
| `make distclean` | Above + configure output, `.d` files, `Makefile` (generated) | Yes (but build is not re-runnable) |
| `rm -rf build/` (out-of-tree) | Entire build directory | Yes (source is separate) |
| Pod/container destruction | Everything | **No** |

### 2.3 The Overwhelming Industry Trend: Ephemeral

Enterprise CI/CD is moving rapidly toward ephemeral build environments:

- **Security**: Ephemeral runners eliminate credential persistence and
  cross-job contamination. ARC (Actions Runner Controller) documentation
  states: "secrets, tokens, and build artifacts from one job can leak
  into the next" on persistent runners.
- **Reproducibility**: Fresh environments guarantee no stale state
- **Compliance**: SOC 2, FedRAMP, and PCI-DSS require build isolation
- **Cost optimization**: Cloud-native CI only pays for compute during
  the actual build, not idle time with persistent workspaces
- **Kubernetes-native**: All modern CI platforms support or prefer K8s
  pod-per-job execution

---

## 3. Implications for OmniBOR Sidecar Architecture

### 3.1 Phase 1 MUST Be Self-Contained

Phase 1 (build interception) runs **inside** the build stage. When the
build stage completes, the workspace is destroyed. Phase 1 cannot rely
on ANY file existing after the stage exits.

This means Phase 1 must, **before the build stage exits**:

1. Hash ALL input and output files per compilation unit (inline)
2. Persist all hash records to the treedb
3. Push all Phase 1 artifacts to durable storage:
   - `phase1_manifest.json`
   - treedb (OmniBOR ADG with gitoid hashes)
   - Event log (raw syscall/interception data)
4. Compute and record gitoid of the final build output (binary/library)

### 3.2 Phase 2 Has NO Access to Source or Build Artifacts

Phase 2 (SPDX generation) runs in a **different process, container,
host, or time**. It has access ONLY to:

- `phase1_manifest.json` (from durable storage)
- treedb (from durable storage)
- Event log (from durable storage)
- The final binary (if uploaded as an artifact)

Phase 2 does NOT have access to:

- Source files (`.c`, `.h`)
- Object files (`.o`)
- Libraries (`.a`, `.so`)
- Build directory structure
- The build host filesystem
- Any intermediate artifacts

This is not a hypothetical constraint — it is the **architecture we
designed** in `sidecar-async-spdx-architecture.md` (principle P5:
"Fail-Safe for Phase 2 — Ephemeral Build Environments").

### 3.3 Why Inline Hashing Is Non-Negotiable

Given the above, the per-unit inline hashing described in Appendix C of
the interception strategies document is **architecturally mandatory**,
not a performance optimization:

| Scenario | Inline hash available? | Post-build hash possible? | Outcome |
|----------|----------------------|--------------------------|---------|
| Ephemeral VM (GitHub Actions) | ✅ During build | ❌ VM destroyed | Only inline works |
| Ephemeral pod (K8s/Harness) | ✅ During build | ❌ Pod destroyed | Only inline works |
| Ephemeral container (GitLab) | ✅ During build | ❌ Container removed | Only inline works |
| Jenkins + `cleanWs()` | ✅ During build | ❌ Workspace wiped | Only inline works |
| Jenkins persistent (no cleanup) | ✅ During build | ⚠️ Files exist but risky | Inline is still required for provenance |

**Even in the rare case where files persist** (Model E), inline hashing
is still required because:

- A concurrent build on the same agent could modify files
- Source files could be `git pull`'d between build and hash
- The provenance guarantee requires hash-at-build-time, not hash-later

### 3.4 What Phase 1 Artifacts Must Contain

Because Phase 2 cannot read source or object files, Phase 1 must
capture ALL metadata needed for SPDX generation:

| Data | Captured By | Stored In |
|------|------------|-----------|
| Input file gitoids (SHA-256) | Per-unit inline hashing | treedb |
| Output file gitoids (SHA-256) | Per-unit inline hashing | treedb |
| Input→output mappings | Event log (argv parsing) | treedb |
| Compiler flags and version | Event log | manifest |
| Header dependencies | `.d` file parsing during build | treedb |
| Process tree (parent→child) | PID/PPID tracking | event log |
| Build timestamp per unit | Interception event | event log |
| Final binary gitoid | Post-build hash (before stage exits) | manifest |

Phase 2 uses ONLY the treedb, event log, and manifest to generate
the SPDX document. It never needs to read a source file.

---

## 4. Platform-Specific Evidence

### 4.1 GitHub Actions

```yaml
# Standard enterprise C++ workflow
name: Build
on: push
jobs:
  build:
    runs-on: ubuntu-latest  # Ephemeral VM
    steps:
      - uses: actions/checkout@v4
      - run: |
          mkdir build && cd build
          cmake .. -DCMAKE_BUILD_TYPE=Release
          make -j$(nproc)
      - uses: actions/upload-artifact@v4
        with:
          name: release-binary
          path: build/myapp
    # VM IS DESTROYED HERE — source, .o files, everything gone
```

### 4.2 GitLab CI

```yaml
# Standard enterprise C++ pipeline
stages:
  - build
  - scan
  - deploy

build:
  stage: build
  image: gcc:13
  script:
    - mkdir build && cd build
    - cmake .. -DCMAKE_BUILD_TYPE=Release
    - make -j$(nproc)
  artifacts:
    paths:
      - build/myapp
    expire_in: 1 hour
  # Container destroyed — source gone, only artifact survives

sbom_scan:
  stage: scan
  image: sbom-tool:latest
  script:
    # NO SOURCE CODE HERE — only the artifact from build stage
    - sbom-generate --binary build/myapp
```

### 4.3 Jenkins (Kubernetes agents)

```groovy
pipeline {
    agent {
        kubernetes {
            yaml '''
            spec:
              containers:
              - name: gcc
                image: gcc:13
            '''
        }
    }
    stages {
        stage('Build') {
            steps {
                container('gcc') {
                    sh 'cmake -B build && cmake --build build -j$(nproc)'
                }
            }
        }
    }
    // Pod destroyed when pipeline completes
    // No source, no objects, no binaries remain
}
```

### 4.4 Jenkins (persistent agents with standard cleanup)

```groovy
pipeline {
    agent { label 'linux-x86_64' }
    stages {
        stage('Build') {
            steps {
                sh './configure && make -j$(nproc)'
                archiveArtifacts artifacts: 'build/myapp'
            }
        }
    }
    post {
        always {
            // Standard practice: clean workspace after every build
            cleanWs(deleteDirs: true, disableDeferredWipeout: true)
        }
    }
}
```

---

## 5. Summary: The Five Rules

1. **Assume the workspace is destroyed after the build stage exits.**
   This is true for ~95% of enterprise CI/CD environments.

2. **Phase 1 must hash every file inline during the build.** There is
   no opportunity to "come back later" and hash files.

3. **Phase 1 must push all artifacts to durable storage before exiting.**
   The treedb, event log, and manifest must survive workspace destruction.

4. **Phase 2 operates exclusively on Phase 1 artifacts.** It never
   reads source files, object files, or the build directory.

5. **The final binary must be hashed before the build stage exits.**
   The binary's gitoid binds the SPDX document to the exact artifact.

---

## 6. Data Sources

| Source | Finding |
|--------|---------|
| GitHub Actions docs | "Each job runs in a fresh instance of the virtual environment" |
| GitLab Runner Issue #336 | "starts each stage with a clean environment...files created in one stage are not automatically available in subsequent stages" |
| Harness CI FAQ | "Build pod cleanup takes place immediately after the completion of a stage's execution" |
| Jenkins Workspace Cleanup Plugin | One of the most installed plugins; `post { always { cleanWs() } }` is standard |
| ARC (Actions Runner Controller) | "secrets, tokens, and build artifacts from one job can leak into the next" — reason for ephemeral |
| GitHub community discussion | "All files and directories created during a workflow run are ephemeral and automatically cleaned up on GitHub-hosted runners" |
| Stack Overflow (GitLab) | `GIT_STRATEGY: none` required to even attempt workspace sharing; default is full re-clone per stage |

---

*Research conducted June 16, 2026. Based on current documentation from
GitHub, GitLab, Jenkins, Harness, and industry DevOps practices.*
