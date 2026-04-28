# OmniBOR Build Interception: Source Code Reference

> **Purpose:** Map every concept from the [architecture diagrams](../architecture/README.md)
> to the exact source files and functions that implement it, in both the upstream
> [omnibor/bomsh](https://github.com/omnibor/bomsh) repository and the local
> [omnibor-analysis](https://github.com/tedg-cisco/omnibor-analysis) project.
>
> All file paths for bomsh use the repository-relative format `bomsh/path/to/file`.
> All file paths for omnibor-analysis use the repository-relative format `omnibor-analysis/path/to/file`.

---

## Table of Contents

1. [bomtrace3: The Modified strace](#1-bomtrace3-the-modified-strace)
2. [bomsh_hook.c: The Interception Engine](#2-bomsh_hookc-the-interception-engine)
3. [bomsh_config.c: Initialization and Logging](#3-bomsh_configc-initialization-and-logging)
4. [SHA-256 / gitoid Hash Computation](#4-sha-256--gitoid-hash-computation)
5. [Raw Logfile Format](#5-raw-logfile-format)
6. [bomsh_create_bom.py: Logfile → ADG + Treedb](#6-bomsh_create_bompy-logfile--adg--treedb)
7. [bomtrace2 and bomsh_hook2.py: Go/Rust Support](#7-bomtrace2-and-bomsh_hook2py-gorust-support)
8. [omnibor-analysis: ADG → SPDX Pipeline](#8-omnibor-analysis-adg--spdx-pipeline)
9. [Docker and Build Infrastructure](#9-docker-and-build-infrastructure)
10. [Patches Applied by omnibor-analysis](#10-patches-applied-by-omnibor-analysis)

---

## 1. bomtrace3: The Modified strace

bomtrace3 is built by applying `bomtrace3.patch` to strace v6.11. The patch modifies
**two existing strace files** and adds **four new source files**.

### Modified strace Files

| File | Change | Purpose |
|------|--------|---------|
| `strace/src/execve.c` | Added `#include "bomsh_hook.h"` and call to `bomsh_record_command(tcp, index)` inside `decode_execve()` | **Pre-exec hook point.** Every time strace intercepts an `execve()` syscall, it now also calls bomsh to record the command. |
| `strace/src/strace.c` | Added `#include "bomsh_hook.h"` and call to `bomsh_hook_program(pid, status)` in `dispatch_event()` at the `TE_EXITED` case. Also replaced `init(argc, argv)` with `bomsh_init(argc, argv)` in `main()`. | **Post-exec hook point and initialization.** When a traced process exits, bomsh records its results. At startup, bomsh parses its own CLI args before handing control to strace. |

### Added Source Files

| File | Location in bomsh repo | Purpose |
|------|----------------------|---------|
| `bomsh_hook.c` | `bomsh/.devcontainer/src/bomsh_hook.c` | Core interception logic: command recording, argv parsing, file hashing, raw logfile writing. ~4,000 lines. |
| `bomsh_hook.h` | `bomsh/.devcontainer/src/bomsh_hook.h` | Header declaring `bomsh_record_command()`, `bomsh_hook_program()`, `bomsh_hook_init()`, and the `bomsh_cmd_data_t` struct. |
| `bomsh_config.c` | `bomsh/.devcontainer/src/bomsh_config.c` | CLI argument parsing (`bomsh_init()`), logfile initialization, watched-program list management, logging functions. |
| `bomsh_config.h` | `bomsh/.devcontainer/src/bomsh_config.h` | Header declaring `g_bomsh_config`, `g_bomsh_global`, config structs, and `bomsh_init()`. |
| `sha1.c` / `sha256.c` | GNU coreutils SHA implementations | Provides `sha256_init_ctx()`, `sha256_process_bytes()`, `sha256_finish_ctx()` used by gitoid hashing. |

### Patch File

| File | Location |
|------|----------|
| `bomtrace3.patch` | `bomsh/.devcontainer/patches/bomtrace3.patch` |

**Key patch details:**

```c
// In execve.c — decode_execve():
+   (void)bomsh_record_command(tcp, index);  // PRE-EXEC HOOK

// In strace.c — dispatch_event(), case TE_EXITED:
+   bomsh_hook_program(current_tcp->pid, status);  // POST-EXEC HOOK

// In strace.c — main():
-   init(argc, argv);
+   bomsh_init(argc, argv);  // bomsh parses its args, then calls strace_init()
```

---

## 2. bomsh_hook.c: The Interception Engine

This is the heart of bomtrace3. Located at `bomsh/.devcontainer/src/bomsh_hook.c`.

### Entry Points (called from patched strace)

| Function | Called From | When | What It Does |
|----------|-----------|------|-------------|
| `bomsh_record_command(tcp, index)` | `execve.c:decode_execve()` | When kernel delivers `PTRACE_EVENT_EXEC` | Copies program path and argv from tracee memory, identifies the tool, calls the pre-exec handler, stores `cmd_data` in hash table. |
| `bomsh_hook_program(pid, status)` | `strace.c:dispatch_event()` | When traced process exits (`TE_EXITED`) | Retrieves stored `cmd_data`, calls the post-exec handler (which hashes files and writes to raw logfile), frees memory. |
| `bomsh_hook_init()` | `bomsh_config.c:bomsh_init()` | At startup | Allocates the 1024-bucket hash table for `cmd_data` storage. |

### Command Data Structure

```c
// The central data structure — one instance per traced process
typedef struct bomsh_cmd_data {
    struct tcb *tcp;         // strace's per-process control block
    pid_t pid;               // Process ID of the tracee
    char *pwd;               // Working directory (from /proc/PID/cwd)
    char *root;              // Root directory (from /proc/PID/root, for chroot)
    char *path;              // Program path (from execve arg 0)
    char **argv;             // Full argument vector (copied from tracee memory)
    int num_argv;            // Argument count
    char *output_file;       // Parsed -o output file
    char **input_files;      // Parsed input files (.c, .o, .a, etc.)
    int num_inputs;          // Input file count
    char **dynlib_files;     // Resolved dynamic library paths (-lssl → /usr/lib/.../libssl.so)
    char **input_sha1;       // SHA-1 hashes of input files (if configured)
    char **input_sha256;     // SHA-256 hashes of input files
    char *depend_file;       // Path to gcc-generated .d dependency file
    char **depends_array;    // Parsed dependency list from .d file
    int depends_num;         // Dependency count
    struct bomsh_cmd_data *ld_cmd;  // Associated linker cmd (for gcc linking mode)
    int skip_record_raw_info;       // Flag to skip recording (e.g., /dev/null output)
    int flags;               // Bit flags (1=output_file allocated, 2=instrumented for deps)
    int refcount;            // Reference count for memory management
    struct bomsh_cmd_data *next;    // Linked list for hash collision chaining
} bomsh_cmd_data_t;
```

### Command Dispatch: bomsh_process_shell_command()

This function routes each intercepted tool to its specific handler:

| Tool Detected By | Handler Function | Handles |
|-----------------|-----------------|---------|
| `is_cc_compiler(name)` — matches gcc, g++, cc, clang, clang++ | `bomsh_process_gcc_command()` | Compilation (-c), linking, preprocessing |
| `is_cc_linker(name)` — matches ld, ld.bfd, ld.gold, ld.lld, gold | `bomsh_process_ld_command()` | Linking .o + .a + -l → binary |
| `is_ar_command(name)` — matches ar, *-ar | `bomsh_process_ar_command()` | Archiving .o → .a |
| `name == "as"` | `bomsh_process_as_command()` | Assembly .s → .o |
| `name == "rustc"` | `bomsh_process_rustc_command()` | Rust compilation |
| `bomsh_endswith(name, "objcopy")` | `bomsh_process_objcopy_command()` | Binary transformation |
| `is_strip_command(name)` | `bomsh_process_strip_like_command()` | Debug symbol stripping |
| `name == "cat"` | `bomsh_process_cat_command()` | File concatenation (used in some builds) |
| `name == "patch"` | `bomsh_process_patch_command()` | Source patching |

### Tracee Memory Access Functions

| Function | Purpose | ptrace Operation |
|----------|---------|-----------------|
| `copy_path(tcp, addr)` | Copy program path string from tracee | `umovestr()` (strace wrapper around `PTRACE_PEEKDATA`) |
| `copy_argv_array(tcp, addr)` | Copy entire argv array from tracee | `umoven()` for pointers + `umovestr()` for each string |
| `copy_single_str(tcp, addr)` | Copy one string from tracee | `umovestr()` |
| `get_argc(tcp, addr)` | Count argv entries in tracee | `umoven()` scanning for NULL |
| `bomsh_get_pwd(tcp)` | Read tracee's working directory | `readlink("/proc/PID/cwd")` |
| `bomsh_get_rootdir(tcp)` | Read tracee's root directory | `readlink("/proc/PID/root")` |
| `bomsh_get_stdin_file(tcp)` | Read tracee's stdin file | `readlink("/proc/PID/fd/0")` |

### Dependency File Instrumentation (gcc-specific)

When gcc is invoked without `-MD` flags, bomtrace3 **modifies the tracee's argv
in memory** to inject dependency tracking:

| Function | Purpose |
|----------|---------|
| `bomsh_execve_instrument_for_dependency(cmd)` | Uses `PTRACE_POKEDATA` (via strace's `upoken()`) to write new argv entries into the tracee's stack, adding `-MD -MF /tmp/bomsh_hook_target_dependency_pidNNNN` to gcc's command line. |
| `bomsh_invoke_subprocess_for_dependency(cmd)` | Alternative: forks a child process to run gcc with -MD separately, without modifying the tracee. |
| `bomsh_cmd_read_depend_file(cmd)` | After gcc exits, reads the generated `.d` file to extract the complete list of transitively included headers. |

### Raw Logfile Writing

| Function | Purpose |
|----------|---------|
| `bomsh_record_raw_info(cmd)` | Writes one record to the raw logfile. Format: `outfile:` line followed by `infile:` lines for static inputs and `dynlib:` lines for dynamic libraries. Each line includes the gitoid hash and file path. |
| `bomsh_record_raw_info2(cmd)` | Variant for "same-file" operations (e.g., strip modifies a file in-place). Records both the pre-modification hash and the post-modification hash. |
| `bomsh_record_afile(cmd, afile, lead, hash_alg, ahash)` | Writes a single file entry: computes hash, writes `{lead}{hash} path: {noroot_path}`. |

---

## 3. bomsh_config.c: Initialization and Logging

Located at `bomsh/.devcontainer/src/bomsh_config.c`.

### Key Functions

| Function | Purpose |
|----------|---------|
| `bomsh_init(argc, argv)` | Parses bomsh-specific CLI arguments (`-r` raw_logfile, `-l` logfile, `-w` watched-programs, `-v` verbose level, etc.), then constructs a new argv array and calls `strace_init()` to initialize strace proper. |
| `bomsh_init_logfiles()` | Opens the raw_logfile and debug logfile for writing. These are file handles used throughout the bomtrace3 lifetime. |
| `bomsh_log_printf(level, fmt, ...)` | Logging function. `level == -1` writes to raw_logfile (the critical output). `level >= 0` writes to the debug logfile if `bomsh_verbose >= level`. |
| `bomsh_log_string(level, str)` | String-only logging variant. Uses `fputs_unlocked()` for performance. |

### Global Configuration

```c
struct bomsh_configs g_bomsh_config;   // Parsed config options
struct bomsh_globals g_bomsh_global;   // Runtime state (logfile handles, etc.)
int bomsh_verbose;                      // Debug level (0 = quiet, 50+ = dump everything)
```

### Watched Programs

bomtrace3 maintains a sorted list of program basenames to intercept. By default,
this includes gcc, g++, clang, ld, ar, as, strip, objcopy, rustc, and others.
Programs not in this list are traced but ignored (their execve is not recorded).

---

## 4. SHA-256 / gitoid Hash Computation

Located in `bomsh/.devcontainer/src/bomsh_hook.c` (hashing functions) and
`sha256.c` (GNU coreutils implementation).

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `calculate_sha256_omnibor(afile, resblock)` | `bomsh_hook.c` | Computes the gitoid-format SHA-256 of a file: `SHA256("blob {decimal_size}\0" + file_contents)`. Returns 32 raw bytes. |
| `bomsh_get_omnibor_sha256_hash(afile, str_hash)` | `bomsh_hook.c` | Wrapper that converts 32 bytes → 64 hex chars. |
| `bomsh_convert_omnibor_hash(str_hash, resblock, length)` | `bomsh_hook.c` | Binary-to-hex conversion. |
| `bomsh_get_hash(afile, hash_alg, ahash)` | `bomsh_hook.c` | Dispatches to SHA-1 or SHA-256 based on `g_bomsh_config.hash_alg`. |
| `get_hash_of_infiles(cmd)` | `bomsh_hook.c` | Batch-hashes all input files. Allocates arrays of hash strings for later logfile writing. |

### gitoid Format

The hash is computed identically to `git hash-object`:

```
SHA-256( "blob " + decimal_file_size_string + "\0" + raw_file_bytes )
```

Example for a 1,234-byte file:
```
SHA-256("blob 1234\0" + <1234 bytes of file content>)
→ "a1b2c3d4e5f67890..."  (64 hex characters)
```

This ensures that `bomtrace3`'s hashes match `git hash-object --algorithm=sha256 <file>`.

---

## 5. Raw Logfile Format

The raw logfile (`/tmp/bomsh_hook_raw_logfile.sha1` by default) is a plain-text
file with one multi-line record per intercepted tool invocation.

### Record Format

```
outfile: <sha256_hex_64chars> path: <absolute_path_without_chroot>
infile: <sha256_hex_64chars> path: <absolute_path>
infile: <sha256_hex_64chars> path: <absolute_path>
...
dynlib: <sha256_hex_64chars> path: <absolute_path>
...
```

### Concrete Example (gcc compilation)

```
outfile: 7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b path: /workspace/repos/curl/src/.libs/main.o
infile: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef path: /workspace/repos/curl/src/main.c
infile: abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab path: /workspace/repos/curl/include/curl/curl.h
infile: fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321 path: /usr/include/stdio.h
```

### Concrete Example (ar archiving)

```
outfile: 2222333344445555666677778888999900001111222233334444555566667777 path: /workspace/repos/curl/lib/.libs/libcurl.a
infile: aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666aaaa7777bbbb8888 path: /workspace/repos/curl/lib/.libs/x509.o
infile: 9999aaaa8888bbbb7777cccc6666dddd5555eeee4444ffff3333aaaa2222bbbb path: /workspace/repos/curl/lib/.libs/ssl.o
```

### Concrete Example (ld linking)

```
outfile: ffff0000eeee1111dddd2222cccc3333bbbb4444aaaa5555999966668888777 path: /workspace/repos/curl/src/.libs/curl
infile: 7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b path: /workspace/repos/curl/src/.libs/main.o
infile: 2222333344445555666677778888999900001111222233334444555566667777 path: /workspace/repos/curl/lib/.libs/libcurl.a
dynlib: 1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff path: /usr/lib/x86_64-linux-gnu/libssl.so.3
dynlib: aaaa0000bbbb1111cccc2222dddd3333eeee4444ffff5555aaaa6666bbbb7777 path: /usr/lib/x86_64-linux-gnu/libcrypto.so.3
```

**Key distinctions:**

- `infile:` = statically linked input (embedded in the output at build time)
- `dynlib:` = dynamically linked library (loaded at runtime, not embedded)
- `outfile:` = the output artifact produced by this tool invocation

---

## 6. bomsh_create_bom.py: Logfile → ADG + Treedb

Located at `bomsh/scripts/bomsh_create_bom.py` (~2,500 lines).

### Invocation

```bash
bomsh_create_bom.py -r /tmp/bomsh_hook_raw_logfile.sha1 -b /output/omnibor/c-cpp/curl/2026-04-02/
```

### What It Does

1. **Parses raw_logfile:** Reads the text file, splits into records, builds an
   in-memory graph where each record becomes a node with edges from inputs to output.

2. **Generates ADG directory:** Creates `.omnibor/` with one file per output artifact:

   ```
   output/omnibor/c-cpp/curl/2026-04-02/metadata/bomsh/.omnibor/
   ├── objects/
   │   └── sha256/
   │       ├── gitoid_sha256_ffff0000...  (for curl binary)
   │       └── gitoid_sha256_2222333...   (for libcurl.a)
   ```

   Each file's content lists the gitoid of every input:
   ```
   blob gitoid:sha256:7a8b9c0d...
   blob gitoid:sha256:2222333...
   ```

3. **Generates treedb:** Creates `bomsh_omnibor_treedb` JSON mapping gitoid → path:

   ```json
   {
     "gitoid:sha256:1234567890abcdef...": {
       "file_path": "/workspace/repos/curl/src/main.c"
     },
     "gitoid:sha256:7a8b9c0d1e2f...": {
       "file_path": "/workspace/repos/curl/src/.libs/main.o",
       "build_cmd": "gcc -c main.c -o main.o"
     }
   }
   ```

### Key Functions in bomsh_create_bom.py

| Function | Purpose |
|----------|---------|
| `read_raw_logfile()` | Parses the text logfile into structured records |
| `process_raw_logfile()` | Builds the dependency graph from records |
| `create_omnibor_doc()` | Writes ADG files (one per output artifact) |
| `create_treedb()` | Writes the JSON gitoid→path mapping |
| `get_git_file_hash()` | Computes gitoid hash in Python (must match bomsh_hook.c's C implementation) |

---

## 7. bomtrace2 and bomsh_hook2.py: Go/Rust Support

bomtrace2 is a lighter variant of bomtrace3 that delegates complex logic to a
Python hook script (`bomsh_hook2.py`) instead of implementing it in C.

### Architecture Difference

| Aspect | bomtrace3 | bomtrace2 |
|--------|----------|----------|
| **Tool detection** | C code in `bomsh_hook.c` | Python code in `bomsh_hook2.py` |
| **Argv parsing** | C code, in-process | Python script, forked per event |
| **Hashing** | C code, in-process SHA-256 | Python `hashlib.sha256` |
| **Overhead** | Lower (no Python startup) | Higher (~50ms Python startup per event) |
| **Flexibility** | Hard-coded tool handlers | Configurable via bomtrace.conf |

### bomtrace2 Configuration (Go-specific)

Located at `omnibor-analysis/docker/bomtrace_go.conf`:

```ini
hook_script_file=/tmp/bomsh_hook2.py
hook_script_cmdopt=-vv -n -w /usr/local/go/pkg/tool/linux_amd64/compile,/usr/local/go/pkg/tool/linux_amd64/link > /dev/null 2>&1 < /dev/null
shell_cmd_file=/tmp/bomsh_cmd
logfile=/tmp/bomsh_hook_bomtrace_logfile
raw_logfile=/tmp/bomsh_hook_raw_logfile.sha1
syscalls=openat
```

**Key setting:** `syscalls=openat` — tells bomtrace2 to also trace the `openat` syscall
(in addition to the default `execve`). Go tools use `openat` for all file I/O.

### bomsh_hook2.py Key Functions

Located at `bomsh/scripts/bomsh_hook2.py` (~2,000 lines).

| Function | Purpose |
|----------|---------|
| `is_cc_compiler(prog)` | Detects gcc/clang by program name |
| `is_golang_prog(prog)` | Detects Go compile/link tools by path pattern |
| `get_all_subfiles_in_rustc_cmdline(argv)` | Parses rustc command line to extract `.rs` input files and output `.rlib`/binary |
| `get_all_subfiles_in_golang_compile_cmdline(argv)` | Parses Go compile command to extract `.go` input files |
| `get_all_subfiles_in_golang_link_cmdline(argv)` | Parses Go link command to extract `.a` package archives |
| `process_gcc_command(prog, argv, ...)` | Full gcc argv parser (Python equivalent of `bomsh_process_gcc_command` in C) |
| `get_git_file_hash(afile)` | gitoid hash computation in Python |

### omnibor-analysis Patch to bomsh_hook2.py

`omnibor-analysis/docker/patches/bomsh_hook2_golang_path.patch` patches the
`is_golang_prog()` function to recognize Go installed at `/usr/local/go/`
(the standard tarball location) in addition to the default `/usr/lib/go-*/`
(the apt package location):

```python
# Before patch:
if "lib/go" not in prog or "pkg/tool" not in prog:
    return False

# After patch:
if ("lib/go" not in prog and "local/go" not in prog) or "pkg/tool" not in prog:
    return False
```

---

## 8. omnibor-analysis: ADG → SPDX Pipeline

### Pipeline Orchestration

| File | Class/Function | Role |
|------|---------------|------|
| `omnibor-analysis/app/pipeline/runners.py` | `_run_c_cpp_pipeline()` | Orchestrates the full C/C++ pipeline: apt validation → bomtrace3 build → SPDX generation → metadata → validation → binary collection |
| `omnibor-analysis/app/pipeline/builder.py` | `BomtraceBuilder.build()` | Runs pre-build steps, then `bomtrace3 make -j$(nproc)`, then `bomsh_create_bom.py` |
| `omnibor-analysis/app/pipeline/facade.py` | `AnalysisPipeline` | Facade class that assembles all pipeline components |

### SPDX Generation Chain

| Step | File | Class | Input | Output |
|------|------|-------|-------|--------|
| 1. Parse ADG | `app/spdx/parser.py` | `AdgParser` | treedb JSON + ADG files | Classified artifacts dict (system_lib, project_source, build_intermediate, etc.) |
| 2. Detect versions | `app/version_detection.py` | `VendoredVersionDetector` | Source directories from treedb | Package name → version map |
| 3. Collect dynamic libs | `app/collect_dynamic_libs.py` | `DynamicLibCollector` | Output binaries | List of dicts: {pkg_name, version, so_path} |
| 4. Emit SPDX | `app/spdx/emitter.py` | `SpdxEmitter` | All of the above | SPDX 2.3 JSON file |
| 5. Visualize | `app/spdx_visualize.py` | (module-level) | SPDX JSON | Interactive D3.js HTML |

### AdgParser: Artifact Classification Logic

`omnibor-analysis/app/spdx/parser.py`, `AdgParser.parse()`:

```python
# Classification rules (simplified):
for sha1, entry in treedb.items():
    fp = entry["file_path"]
    if fp.startswith("/usr/local/go/src/"):  → go_stdlib
    elif fp.startswith("/usr/lib"):
        if basename.startswith("crt") and basename.endswith(".o"):  → crt_object
        elif ".so" in basename:  → system_lib
        else:  → system_header  (or build_intermediate)
    elif fp.startswith("/usr/include"):  → system_header
    elif fp.startswith(repos_dir):  → project_source or build_intermediate
```

### SpdxEmitter: Relationship Generation

`omnibor-analysis/app/spdx/emitter.py`:

| Input Data | SPDX Relationship Type | SPDX Term |
|-----------|----------------------|-----------|
| `.a` archive from AdgParser `static_inputs` | `STATIC_LINK` | Static archive code is embedded in the binary |
| `.so` library from `collect_dynamic_libs` | `DYNAMIC_LINK` | Shared library loaded at runtime |
| gcc, ld from AdgParser `build_tools` | `BUILD_TOOL_OF` | Tool used during compilation |
| `.c`/`.h` files from AdgParser `project_source` | `CONTAINS` | Source files compiled into the binary |

### VendoredVersionDetector: 12 Detection Strategies

`omnibor-analysis/app/version_detection.py`:

| Strategy | Pattern | Example |
|----------|---------|---------|
| 1. `configure.ac` | `AC_INIT([name], [version])` | curl's `AC_INIT([curl], [8.12.0])` |
| 2. `CMakeLists.txt` | `project(name VERSION x.y.z)` | |
| 3. `#define VERSION` | `#define CURL_VERSION "8.12.0"` | Header files |
| 4. `Makefile` | `VERSION = x.y.z` | |
| 5. `Cargo.toml` | `version = "x.y.z"` | Rust crates |
| 6. `go.mod` | Module path + tag | Go modules |
| 7. `pom.xml` | `<version>x.y.z</version>` | Java/Maven |
| 8. `package.json` | `"version": "x.y.z"` | Node.js |
| 9. `CHANGES` / `NEWS` | First version pattern in changelog | |
| 10. `.pc` files | `Version:` field in pkg-config | |
| 11. Git tags | `git describe --tags` | |
| 12. Directory name | `libfoo-1.2.3/` | Vendored source dirs |

---

## 9. Docker and Build Infrastructure

### Dockerfile

`omnibor-analysis/docker/Dockerfile` — builds the container image with all toolchains
and bomtrace2/bomtrace3.

| Dockerfile Section | Purpose |
|-------------------|---------|
| Lines 14–68 | Install C/C++ build tools (gcc, clang, make, cmake, autotools) and project-specific apt deps |
| Lines 78–80 | Install Python deps from `requirements.txt` |
| Lines 85 | Install Syft (manifest-based SBOM scanner) |
| Lines 96–101 | Install Go SDK (1.26.0) |
| Lines 113–138 | Install Java JDK 17/21 + Maven 3.6/3.9 |
| Lines 152–157 | Install Rust toolchain via rustup |
| Lines 197–221 | Build bomtrace2 and bomtrace3 from source |
| Lines 231–234 | Apply Go path patch to `bomsh_hook2.py` |
| Lines 241–243 | Apply Java SourceFile patch to `bomsh_create_bom_java.py` |
| Lines 246 | Copy Go-specific `bomtrace_go.conf` |

### Build Process for bomtrace3

```dockerfile
# Clone strace v6.11, apply bomtrace3 patch, copy bomsh_hook.c + friends, build
RUN git clone --branch v6.11 --depth 1 https://github.com/strace/strace.git strace3 && \
    cd strace3 && \
    patch -p1 < /opt/bomsh/.devcontainer/patches/bomtrace3.patch && \
    cp /opt/bomsh/.devcontainer/src/*.[hc] src/ && \
    ./bootstrap && \
    ./configure --enable-mpers=check && \
    make -j1 CFLAGS="... -Wno-error=stringop-overflow" && \
    cp src/strace /opt/bomsh/bin/bomtrace3
```

**CRITICAL:** bomtrace3 MUST be built with `make -j1` (serial) because the patch
adds `bomsh_hook.c` which `#include`s `printers.h` — a generated file that may not
exist yet during parallel builds (Makefile.am dependency bug in the patch).

---

## 10. Patches Applied by omnibor-analysis

| Patch File | Target | Purpose |
|-----------|--------|---------|
| `docker/patches/bomsh_hook2_golang_path.patch` | `bomsh/scripts/bomsh_hook2.py` | Add `/usr/local/go/` path recognition to `is_golang_prog()`. Without this, bomtrace2 cannot detect Go compile/link tools installed from the official tarball. |
| `docker/patches/bomsh_java_sourcefile.patch` | `bomsh/scripts/bomsh_create_bom_java.py` | Initialize `source_file = ''` before the class-processing loop. Fixes `UnboundLocalError` crash when a JAR contains `.class` files without `SourceFile` attributes. |
| `docker/patches/bomsh_hook_qemu_fallback.patch` | `bomsh/.devcontainer/src/bomsh_hook.c` | (Optional) QEMU compatibility fallback for ARM64 development on Apple Silicon. |

---

## Quick Reference: "Where Is This Implemented?"

| Concept | Source File |
|---------|------------|
| ptrace attach to child process | strace `strace.c` → `startup_attach()` |
| Intercept execve syscall | strace `execve.c` → `decode_execve()` + **bomsh patch** |
| Intercept process exit | strace `strace.c` → `dispatch_event(TE_EXITED)` + **bomsh patch** |
| Copy argv from tracee memory | `bomsh_hook.c` → `copy_argv_array()` |
| Detect gcc/clang | `bomsh_hook.c` → `is_cc_compiler()`, `is_special_cc_compiler()` |
| Detect ld/gold/lld | `bomsh_hook.c` → `is_cc_linker()` |
| Detect ar | `bomsh_hook.c` → `is_ar_command()` |
| Parse gcc argv | `bomsh_hook.c` → `bomsh_process_gcc_command()` |
| Parse ld argv | `bomsh_hook.c` → `bomsh_process_ld_command()`, `get_all_subfiles_in_ld_cmdline()` |
| Parse ar argv | `bomsh_hook.c` → `bomsh_process_ar_command()` |
| Inject -MD dep flag | `bomsh_hook.c` → `bomsh_execve_instrument_for_dependency()` |
| Read gcc .d dep file | `bomsh_hook.c` → `bomsh_cmd_read_depend_file()` |
| Compute gitoid SHA-256 | `bomsh_hook.c` → `calculate_sha256_omnibor()` |
| Write to raw logfile | `bomsh_hook.c` → `bomsh_record_raw_info()` |
| Parse raw logfile → ADG | `bomsh/scripts/bomsh_create_bom.py` |
| Parse treedb → SPDX | `omnibor-analysis/app/spdx/parser.py` → `AdgParser` |
| Detect component versions | `omnibor-analysis/app/version_detection.py` → `VendoredVersionDetector` |
| Resolve dynamic libraries | `omnibor-analysis/app/collect_dynamic_libs.py` → `DynamicLibCollector` |
| Generate SPDX 2.3 JSON | `omnibor-analysis/app/spdx/emitter.py` → `SpdxEmitter` |
| Generate HTML visualization | `omnibor-analysis/app/spdx_visualize.py` |
| Pipeline orchestration | `omnibor-analysis/app/pipeline/runners.py` → `_run_c_cpp_pipeline()` |
| Build invocation | `omnibor-analysis/app/pipeline/builder.py` → `BomtraceBuilder.build()` |

---

*This document references bomsh commit [main branch](https://github.com/omnibor/bomsh)
as of April 2026. Function names and line numbers may shift with upstream updates.*
