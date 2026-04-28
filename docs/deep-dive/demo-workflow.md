<style>
body { font-size: 18px; line-height: 1.6; }
h1 { font-size: 36px; }
h2 { font-size: 30px; }
h3 { font-size: 26px; }
h4 { font-size: 22px; }
table { font-size: 18px; }
code { font-size: 16px; }
pre code { font-size: 15px; }
blockquote { font-size: 18px; }
</style>

# OmniBOR Tech Deep Dive — Demo Cheat Sheet

> **Last modified:** 2026-04-17 11:41 HST

| | |
|---|---|
| **Target Repo** | OpenOSC (Cisco Open Object Size Checking library) |
| **Build Time** | ~6 seconds instrumented build, ~15 seconds total |
| **Why This Repo** | Fast build, Cisco project, full C/C++ pipeline |

---

## How This Runs Inside Windsurf

### What the architects see on your screen share

| Panel | Shows |
|-------|-------|
| **Windsurf Editor** (left) | Source code, config files, diagrams, SPDX JSON |
| **Cascade Chat** (right) | Cascade explaining output + suggesting next steps |
| **Windsurf Terminal** (bottom) | Live terminal output from each command |

### The demo flow

1. **Tell Cascade** to start the demo — Cascade drives every step
2. For each step, Cascade **explains** what's about to happen in chat
3. Cascade **prompts you** with a Continue button before running any command
4. You **click Continue** — Cascade submits the command
5. After the command completes, Cascade **reads the output** and provides
   expert commentary
6. **Repeat** — Cascade explains, you approve, Cascade runs and comments

### Why this works

- **Zero copy-paste** — Cascade runs every command, you just click Continue
- **Natural conversation** — architects see you talking to an AI assistant
- **Cascade sees everything** — it reads terminal output and explains live
- **Persistent container** — `/tmp` state survives between commands
  (bomtrace3 writes to `/tmp/`), volume mounts keep `repos/` and `output/`

---

## Pre-Meeting Prep (run the day before)

### 1. Start EC2 and verify readiness

```bash
# Check instance status
aws ec2 describe-instances --profile ted-admin \
  --filters "Name=tag:Name,Values=*omnibor*" \
  --query "Reservations[].Instances[].{ID:InstanceId,State:State.Name,IP:PublicIpAddress}" \
  --output table --no-cli-pager

# Start if needed (use Instance ID from above)
aws ec2 start-instances --profile ted-admin --instance-ids <ID> --no-cli-pager
aws ec2 wait instance-running --profile ted-admin --instance-ids <ID> --no-cli-pager

# Verify SSH
ssh omnibor-build "echo SSH OK"
```

### 2. Sync code + rebuild Docker

```bash
# Sync all project code
rsync -avz --exclude='__pycache__' app/ omnibor-build:/home/ubuntu/omnibor-analysis/app/
rsync -avz --exclude='__pycache__' docker/ omnibor-build:/home/ubuntu/omnibor-analysis/docker/
rsync -avz requirements.txt omnibor-build:/home/ubuntu/omnibor-analysis/

# Rebuild Docker image (if needed)
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && \
  docker compose -f docker/docker-compose.yml build 2>&1 | tail -5"
```

### 3. Sync results to local Mac

```bash
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/ output/
```

### 4. Reset EC2 to greenfield for OpenOSC

The live demo clones OpenOSC from scratch. Ensure no previous clone exists:

```bash
ssh omnibor-build "sudo rm -rf /home/ubuntu/omnibor-analysis/repos/openosc"
ssh omnibor-build "docker rm -f demo 2>/dev/null; true"
```

### 5. Verify local artifacts for Part 3

Check for latest timestamped directories under:

- `output/omnibor/c-cpp/openosc/<ts>/metadata/bomsh/`
- `output/spdx/c-cpp/openosc/<ts>/`

---

## During the Meeting — Demo Script

<br><br><hr>

### Part 1: Architecture Overview (presenter-driven, ~8 min)

<hr>

Walk through three diagrams, then show the code. Open each PNG so architects
can see it on the screen share.

**1a. Development environment**

Open `docs/architecture/development-environment-overview.png`.

**Say:** "This is the full development environment. At the top is Windsurf IDE
running on my Mac — it has Cascade AI for pair programming, a .windsurf/
directory with 30+ rules and 9 slash commands that encode all our project
conventions, and local dev tools. In the middle is the Docker container on
EC2 — that's where the actual builds and interception happen. At the bottom
are the external services: GitHub for source repos, the OmniBOR/bomsh tools
we pull from upstream, and the analysis outputs we generate. Everything is
connected over SSH — Windsurf drives the container remotely."

**1b. OmniBOR Analysis - Portable container**

Open `docs/architecture/omnibor-container-portable.png`.

**Say:** "This is the container architecture. The container provides
everything — interception tools on the left, default build toolchains on the
right, the analysis pipeline, and SBOM generation. 
This is a self-contained reproducible environment for analyzing GitHub projects.

Notice the subtitle — Standalone mode is what we're running today:  
Sidecar mode is the deployment mode that is under development.

For production CI/CD, sidecar mode — where the container provides only 
the interception tools and analysis pipeline, and your native build 
toolchains do the actual compilation. The CC= compiler wrapper approach 
lets our tools observe your build without changing it. The SBOM then 
reflects exactly what your pipeline produces, not what our container would 
produce. Look at the deployment targets at the bottom — Your Build Machine 
and Your CI/CD Pipeline both show the planned sidecar flow."

**1c. C/C++ build interception detail**

Open `docs/architecture/c-cpp-build-interception.png`.

**Say:** "This diagram shows the three stages of our pipeline in detail.

**Section 1** is a standard C/C++ build — make spawns gcc, which compiles .c
files into .o objects, ar bundles them into .a archives, and ld links
everything into the final binary. 


**Section 2** shows where bomtrace3 inserts
itself — it wraps the make process using ptrace and intercepts every execve()
syscall, capturing the exact inputs and outputs of each tool invocation.

**Section 3** is our analysis pipeline that takes the raw build trace and
generates an SPDX 2.3 SBOM with full provenance."

**1d. Repository configuration**

Open `app/config.yaml` lines 2-17.

**Say:** "Each target repo is defined in YAML — a GitHub URL, a pinned
release tag for reproducibility, and the build steps. The pipeline runs
all steps except the last one normally, then wraps the final `make` with
bomtrace3 for interception."

**1e. Pipeline orchestration**

Open `app/pipeline/runners.py`.

**Say:** "`main()` clones the repo, generates a Syft manifest SBOM, then
dispatches to the language-specific pipeline. For C/C++ that's
`_run_c_cpp_pipeline()` — instrumented build, SPDX generation, validation,
and documentation. Add a repo to the YAML and the pipeline handles the
rest."

**1f. Builder — where interception happens**

Open `app/pipeline/builder.py`.

**Say:** "The builder runs pre-build steps normally, then prepends
bomtrace3 to the final `make` command. After the build, it calls
`bomsh_create_bom.py` to generate the Artifact Dependency Graph from the
raw logfile."

<br><br><hr>

### Starting the Live Demo

Tell Cascade:

> **Start the demo**

Cascade will automatically:

1. Verify EC2 is in greenfield state (remove any existing `demo` container
   and `repos/openosc`)
2. Clear the terminal
3. Prompt: **"Ready to start the demo container on EC2?"**

Click **Continue** to begin. Cascade then drives every remaining step.

<br><br><hr>

### Part 2: Live Build Interception (~10 min)

<hr>

Cascade drives every step. For each step below, Cascade will:

1. Explain what's about to happen (the **Say** text)
2. Prompt you with a **Continue** button
3. Run the command after you click Continue
4. Read the output and provide the **Commentary**

---

#### Step 1: Start the demo container

**Say:** "Starting a persistent Docker container on EC2. This gives us a
long-running environment where `/tmp` state persists between commands."

**Command:**

```bash
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && docker compose -f docker/docker-compose.yml run -d --name demo omnibor-env sleep infinity"
```

**After:** A Windsurf terminal opens. Click the terminal icon in the
bottom panel to make it visible to the architects.

---

#### Step 2: Clone the target repo

**Say:** "Cloning Cisco's OpenOSC library — a buffer overflow detection
library for C/C++. Small, focused project — perfect for a quick demo. The
pipeline works identically for larger projects like curl or Node.js."

**Command:**

```bash
ssh omnibor-build "docker exec demo git clone --branch v1.0.7 --depth 1 https://github.com/cisco/OpenOSC.git /workspace/repos/openosc"
```

**Commentary:** Read the terminal output and confirm the shallow clone at
the pinned tag.

---

#### Step 3: Show the source files

**Say:** "Let's see the source files we're about to build."

**Command:**

```bash
ssh omnibor-build "docker exec demo bash -c 'ls /workspace/repos/openosc/src/*.c'"
```

**Commentary:** "These are the 5 source files. Each implements a different
aspect of OpenOSC's buffer overflow checking. When we run bomtrace3, it
will intercept every gcc compilation of these files and record exactly
which inputs produced which outputs."

---

#### Step 4: Run pre-build steps (configure)

**Say:** "Running autoreconf and configure — standard autotools preparation.
These generate Makefiles and detect the build environment. We run these
*without* bomtrace3 because they aren't the actual compilation. Only the
make step gets instrumented."

**Command 1:**

```bash
ssh omnibor-build "docker exec demo bash -c 'cd /workspace/repos/openosc && autoreconf -vfi 2>&1 | tail -3'"
```

**Command 2:**

```bash
ssh omnibor-build "docker exec demo bash -c 'cd /workspace/repos/openosc && ./configure --disable-safec 2>&1 | tail -5'"
```

**Commentary:** Confirm configure completed successfully.

---

#### Step 5: THE MONEY SHOT — Instrumented build

**Say:** "Now the key step — wrapping the make command with bomtrace3.
bomtrace3 attaches via ptrace as the parent process and intercepts every
execve() syscall. Every time make spawns gcc, ar, or the linker, bomtrace3
captures the full command line and computes SHA-256 gitoid hashes for every
input and output file."

**Command:**

```bash
ssh omnibor-build "docker exec demo bash -c 'cd /workspace/repos/openosc && bomtrace3 make -j\$(nproc) 2>&1'"
```

**Commentary:** "The instrumented build completed in about 6 seconds. The
build ran normally — bomtrace3 is transparent to the compiler. The result
is a raw logfile at `/tmp/bomsh_hook_raw_logfile.sha1` containing the
ground truth of exactly what happened during this build."

---

#### Step 6: Inspect the raw logfile

**Say:** "Let's look at what bomtrace3 actually captured — the raw build
trace."

**Command:**

```bash
ssh omnibor-build "docker exec demo head -7 /tmp/bomsh_hook_raw_logfile.sha1"
```

**Commentary:** "This is the ground truth:

- `outfile` — the .o object file gcc produced, with its SHA-256 gitoid hash
- `infile` lines — every source file and header that gcc read as input
- `build_cmd` — the exact gcc command line intercepted via ptrace
- `End of raw info` — boundary between intercepted processes

This is not guessing from package manifests. This is what actually happened
at build time."

---

#### Step 7: Count intercepted compilations

**Say:** "Let's count how many process invocations bomtrace3 intercepted."

**Command:**

```bash
ssh omnibor-build "docker exec demo grep -c 'End of raw info' /tmp/bomsh_hook_raw_logfile.sha1"
```

**Commentary:** "10 intercepted invocations — 5 gcc compilations (each
compiled twice by libtool for PIC and non-PIC), plus ar and ld producing
`libopenosc.so`. Every tool invocation that make spawned was captured."

---

#### Step 8: Generate the ADG

**Say:** "Now we parse the raw logfile into an Artifact Dependency Graph —
a per-binary tree showing exactly which source files contributed to each
output."

**Command:**

```bash
ssh omnibor-build "docker exec demo bash -c 'cd /workspace/repos/openosc && bomsh_create_bom.py -r /tmp/bomsh_hook_raw_logfile.sha1 -b /tmp/demo_adg'"
```

**Commentary:** "bomsh_create_bom.py produced two key artifacts: the treedb
(gitoid-to-filepath mapping) and the ADG documents (OmniBOR standard
dependency graph)."

---

#### Step 9: Inspect the treedb

**Say:** "Let's look at the treedb — the hash-tree database that maps
every gitoid to a filepath."

**Command:**

```bash
ssh omnibor-build "docker exec demo head -30 /tmp/bomsh_createbom_jsonfile"
```

**Commentary:** "For simple source files, it's a hash-to-path entry. For
output files like .o objects, there's a `hash_tree` array — the complete
list of every input gitoid that went into building that object. This is
how we answer: given this binary, what exact source files built it?"

---

#### Step 10: Run full pipeline + sync to local Mac

**Say:** "That completes the live build. Now let me run the full analysis
pipeline — it takes the raw build trace, generates SPDX SBOMs, collects
binaries, and produces HTML visualizations. Then I'll pull everything down."

**Command 1** (run full pipeline on EC2):

```bash
ssh omnibor-build "cd /home/ubuntu/omnibor-analysis && docker compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo openosc 2>&1 | tail -20"
```

**Command 2** (rsync all output — use timestamp from pipeline output):

```bash
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/spdx/c-cpp/openosc/<TS>/ output/spdx/c-cpp/openosc/<TS>/
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/binaries/c-cpp/openosc/<TS>/ output/binaries/c-cpp/openosc/<TS>/
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/omnibor/c-cpp/openosc/<TS>/ output/omnibor/c-cpp/openosc/<TS>/
rsync -avz omnibor-build:/home/ubuntu/omnibor-analysis/output/build-logs/c-cpp/openosc/<TS>/ output/build-logs/c-cpp/openosc/<TS>/
```

**Command 3** (VALIDATE — always confirm files exist locally):

Cascade must use `find_by_name` to list each local directory and confirm
non-zero files exist. Do NOT proceed until validation passes.

**Local artifact paths (timestamped):**

| Artifact | Path |
|----------|------|
| SPDX JSON + HTML | `output/spdx/c-cpp/openosc/<TS>/` |
| Binary | `output/binaries/c-cpp/openosc/<TS>/libopenosc.so` |
| OmniBOR metadata | `output/omnibor/c-cpp/openosc/<TS>/metadata/` |
| Build doc | `output/build-logs/c-cpp/openosc/<TS>/build.md` |

<br><br><hr>

### Part 3: Pre-Run Artifact Deep Dive (local Mac, ~10 min)

<hr>

All steps use the pipeline output from the timestamped directory synced
in Step 10. Cascade reads the timestamp from the pipeline run output.

**Display rule:** For each file, Cascade uses BOTH methods:

1. `read_file` — content appears in the Cascade chat panel (right side)
2. `cat` or `head -N` — content appears in the terminal panel (bottom)

Both panels are visible to architects on screen share. Using both ensures
maximum visibility regardless of which panel they're focused on.

---

#### 3a. Raw logfile (the build trace)

**Say:** "Let me open the raw logfile that bomtrace3 just captured during
our live build."

**Action:** Cascade reads `output/omnibor/c-cpp/openosc/<TS>/metadata/bomsh/bomsh_hook_raw_logfile`.

**Commentary:** "Each PID block is one intercepted process — a single gcc,
ar, or ld invocation. The `outfile` is the compiled object with its gitoid,
and every `infile` is a source or header that gcc read. Notice it captured
dozens of system headers too — bomtrace3 discovers these via gcc's `-MD`
dependency output."

---

#### 3b. Treedb JSON (gitoid → path mapping)

**Say:** "Now the treedb — the hash-tree database generated from that raw
logfile."

**Action:** Cascade reads `output/omnibor/c-cpp/openosc/<TS>/metadata/bomsh/bomsh_omnibor_treedb`.

**Commentary:** "The `hash_tree` array inside an output file entry lists
every input gitoid. You look up the binary's gitoid, follow the hash_tree,
and resolve each entry back to a filepath."

---

#### 3c. SPDX JSON (the final SBOM)

**Say:** "And the final output — the SPDX 2.3 SBOM for libopenosc.so."

**Action:** Cascade finds the latest `libopenosc.so_analyzed.spdx.json`
under `output/spdx/c-cpp/openosc/` and reads it.

**Commentary:** Highlights packages, files, and relationships:

- `packages` — root package (`libopenosc.so`) with version, build date, compiler info
- `files` — every source file compiled into the binary, each with its gitoid checksum
- `relationships` — `DESCRIBES`, `CONTAINS` linking the document to sources

"OpenOSC is simple — one library, no vendored deps, and every source file
traced with its gitoid checksum."

---

#### 3d. Show Visualizations of SPDX files

**Say:** "Each SPDX JSON also gets an interactive D3.js visualization.
Let me show you what these look like."

**Action:** The user opens HTML files from Finder. Cascade prompts with
a Continue button, then provides commentary after the user clicks.

**Visualization files (local paths — build SBOMs only):**

| Visualization | Path |
|---------------|------|
| OpenOSC build | `output/spdx/c-cpp/openosc/<TS>/libopenosc.so_build.spdx.html` |

**Commentary (after user opens OpenOSC build):** "The purple root node is
`libopenosc.so` — gcc as the build tool in yellow, dynamic system libraries
in red (libc6 with full PURL and CPE), and every source file traced with its
gitoid. You can hover for tooltips, drag nodes, search, and zoom.

This is what binary scanners miss: the exact source files compiled into the
binary, traced at build time with ground-truth evidence."

<br><br><hr>

### Part 4: Performance Discussion (~5 min)

<hr>

The user drives this section — they open the performance proposal doc
themselves. Cascade only prompts with a Continue button and provides
commentary after the user clicks.

**File:** `docs/deep-dive/omnibor-performance-optimization-proposal.md`

**Action:** Cascade prompts "Ready for Part 4?". After the user clicks
Continue, Cascade provides commentary in the chat panel.

**Commentary:** "bomtrace3 currently adds 20–60% overhead to build times.
The bottleneck is a single-threaded tracer performing synchronous SHA-256
hashing with no deduplication — the same `stdio.h` gets hashed hundreds of
times across compilation units.

We have a 5-strategy optimization roadmap that reduces overhead from 40%
to 7% through incremental improvements, or to 3–5% with compiler wrappers
replacing ptrace entirely. Phase 1 (cache + OpenSSL) is 3–4 days of work
for the biggest single improvement."

**Sections to highlight in the document:**

- **Section 1** — the overhead table (measured data across 6 projects)
- **Section 4** — the overhead budget breakdown (where the 40% goes)
- **Section 9** — cumulative reduction table (40% → 7%, verified math)
- **Section 10** — implementation roadmap (3 phases, effort estimates)

<br><br><hr>

### Part 5: Anticipated Question — "What about our native toolchains?" (~3 min)

<hr>

This question will come up when architects see the container has its own
gcc/go/rustc. Be ready for it.

**Say:** "That's an important question. What you're seeing today is what we
call **standalone mode** — the container provides a complete, self-contained
build environment with known toolchains. This is ideal for analyzing
open-source projects where there's no canonical native build environment.
The SBOM we generate is reproducible and auditable against a known state.

But you're right that for production CI/CD integration, the SBOM must
reflect **your actual build** — your compiler versions, your linked
libraries, your binary. That's **sidecar mode**, which is our next
architectural milestone.

The key insight is in our performance optimization proposal: **Strategy 6 —
compiler wrappers**. Instead of bomtrace3 wrapping the entire build via
ptrace, we provide thin wrapper scripts:

```text
CC=/opt/bomsh/gcc-wrapper make -j$(nproc)
```

The wrapper calls through to YOUR gcc — whatever version is on your PATH —
records the command, then hashes the output after your compiler finishes.
For Rust, `RUSTC_WRAPPER` is a native cargo mechanism (it's how sccache
works). For Java, our strace approach already observes your native Maven
and JDK without substituting anything.

So the container becomes a lightweight interception toolkit — you install
our wrappers into your existing CI pipeline, set `CC=` and `RUSTC_WRAPPER`,
and we observe your production build without changing it. The SBOM matches
exactly what ships to customers.

We're building toward this now. The performance proposal documents the
full roadmap — compiler wrappers reduce overhead from 40% to 3-5% while
also enabling true sidecar deployment."

If they ask about Go specifically:

**Say:** "Go is the one language where sidecar is harder — Go's internal
compiler has no `CC=` equivalent, so we currently need ptrace to intercept
it. Our long-term path for Go is eBPF-based tracing, which observes all
process spawns from kernel space without modifying the build at all. That's
Strategy 7 in the proposal."

Reference: `docs/deep-dive/sidecar-vs-cleanroom-analysis.md`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| AWS session expired | Re-auth: `duo-sso --profile ted-admin`, then `sed -i '' 's/^\[default\]/[ted-admin]/' ~/.aws/credentials` |
| SSH timeout | Check your public IP: `curl -s ifconfig.me` — update security group if IP changed |
| SSH connection refused | Wait 30s for sshd after EC2 start; disable VPN if on Cisco VPN |
| Docker image missing | `docker compose -f docker/docker-compose.yml build` |
| bomtrace3 not found | Verify: `docker exec demo which bomtrace3` |
| Repo already cloned | Run greenfield reset (see below) |

## Emergency Fallback

If EC2/SSH/Docker fails during the live demo, switch entirely to
pre-run artifacts on your local Mac (Part 3). All the data is there —
you just won't have the live build animation.

---

## Greenfield Reset

Run this after the demo to reset EC2 back to a clean state for the next run.
Do not mention this to meeting attendees.

```bash
ssh omnibor-build "docker rm -f demo 2>/dev/null; true"
ssh omnibor-build "sudo rm -rf /home/ubuntu/omnibor-analysis/repos/openosc"
```

---

*Last updated: 2026-04-17 11:41 HST*
