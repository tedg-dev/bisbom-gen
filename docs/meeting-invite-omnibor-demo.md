# OmniBOR Analysis Demo — Meeting Invite

## Outlook Title

`OmniBOR Demo: omnibor-analysis Framework + ADG SPDX vs. BDBA Side-by-Side`

---

## Meeting Description

Hey team — I've been using Windsurf AI to build a framework around bomsh and bomtrace that automates the full pipeline from git clone to validated SPDX 2.3 SBOMs for C/C++ projects. It's called **omnibor-analysis**, and I want to walk you through it and show you side-by-side comparisons of ADG SPDX SBOMs against BDBA binary scan SBOMs across several open-source repos (curl, redis, nmap, ffmpeg).

---

### What I'll Demo (~45 min)

**1. Infrastructure Overview** (5 min)

The entire pipeline runs inside a Docker container on an AWS EC2 instance:

| Component | Detail |
|-----------|--------|
| **Host** | AWS EC2 `c6i.xlarge` (4 vCPU, 8 GB RAM) |
| **OS** | Ubuntu 22.04 x86_64 |
| **Storage** | 50 GB EBS gp3 (3000 IOPS) |
| **Container** | Docker (Ubuntu 22.04 base) with gcc, bomtrace2/3, Syft |
| **Build Interception** | bomtrace3 (ptrace-based, from [omnibor/bomsh](https://github.com/omnibor/bomsh)) |
| **Region** | us-west-1 |
| **Cost** | ~$0.17/hr running, ~$4/mo stopped |

**2. C/C++ Workflow Walkthrough** (15 min)

High-level pipeline for each target repo (see attached draw.io diagram):

1. **Clone** target repo (e.g., curl, redis, nmap, ffmpeg)
2. **Syft baseline** — manifest-based SBOM for comparison
3. **Instrumented build** — `bomtrace3 make -j$(nproc)` intercepts every gcc/g++/ld invocation via ptrace
4. **ADG generation** — `bomsh_create_bom.py` ([omnibor/bomsh](https://github.com/omnibor/bomsh)) parses the raw trace log into an OmniBOR Artifact Dependency Graph with gitoid hashes
5. **OmniBOR SPDX** — `bomsh_sbom.py` ([omnibor/bomsh](https://github.com/omnibor/bomsh)) converts the ADG into SPDX 2.3 JSON
6. **Metadata enrichment** — `ldd`/`readelf` on each output binary to identify dynamically linked system libraries, `dpkg` resolution for package names/versions
7. **Per-binary ADG SPDX** — omnibor-analysis generates one SPDX per binary with vendored lib detection, dynamic lib dependencies, and D3.js interactive HTML visualization
8. **SPDX validation** — JSON Schema + semantic checks
9. **Comparison** — side-by-side ADG SPDX vs. BDBA binary scan

OmniBOR repos used in the pipeline:
- **[omnibor/bomsh](https://github.com/omnibor/bomsh)** — bomtrace2, bomtrace3, bomsh_create_bom.py, bomsh_sbom.py, bomsh_hook2.py

**3. Side-by-Side Comparisons** (15 min)

Live walkthrough of ADG SPDX vs. BDBA results for C/C++ repos:

| Repo | Binaries | Vendored Libs | Dynamic Libs | Build Time |
|------|----------|---------------|--------------|------------|
| **curl** | curl, libcurl.so | — | ~10 | ~5 min |
| **redis** | redis-server, redis-cli | 8 (jemalloc, lua, hiredis...) | ~5 | ~3 min |
| **nmap** | nmap, ncat, nping | 7 (liblua, libdnet, liblinear...) | 14 | ~3 min |
| **ffmpeg** | 6 bins/libs | — | 20+ | ~24 min |

Key finding: **ADG detects dynamically linked libraries and vendored code that BDBA completely misses.** BDBA only recognizes the top-level binary signature. Syft only finds CI/dev tooling from manifests.

**4. Developer Onboarding via Windsurf AI** (5 min)

omnibor-analysis includes Windsurf IDE rules and workflow files (`.windsurf/rules/` and `.windsurf/workflows/`) that enable any developer who clones the repo to:

- Run `/setup-environment` to auto-verify Python venv, tests, infrastructure, and Docker
- Run `/add-repo` to add a new target repository with auto-detected build steps
- Run `/run-analysis` to execute the full pipeline on any configured repo
- Run `/run-comparison` to compare ADG SPDX against a BDBA scan
- Follow enforced development rules: 97% test coverage gate, PR-first workflow, semantic versioning, pre-commit checks

27 rule files and 9 workflow files encode the project's conventions so that AI-assisted development stays consistent across contributors.

---

### Q&A (15 min)

---

### Reference Documents

These are in the [omnibor-analysis GitHub repo](https://github.com/tedg-dev/omnibor-analysis):

| Document | Description |
|----------|-------------|
| [SPDX Generation Deep Dive](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/summary/spdx-generation-deep-dive.md) | Full technical walkthrough of every pipeline stage, data flows, intermediate artifacts |
| [Three-Way SPDX Comparison (curl)](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/three-way-spdx-comparison.md) | ADG vs. Syft vs. GitHub vs. BDBA — what each tool finds and misses |
| [Enterprise Integration Guide](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/enterprise-integration-guide.md) | CI/CD integration patterns, distro compatibility, rollout plan |
| [Metadata Collection Pipeline](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/summary/metadata-collection-pipeline.md) | How ldd/readelf/dpkg enrich the SPDX with system library metadata |
| [Workflow Guide](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/summary/workflow-guide.md) | How to use the Windsurf workflows for analysis and comparison |
| [Upstream Changes to bomsh](https://github.com/tedg-dev/omnibor-analysis/blob/main/docs/upstream-changes.md) | Patches contributed back to omnibor/bomsh |

---

### Prerequisites for Attendees

None — this is a demo. Bring questions.
