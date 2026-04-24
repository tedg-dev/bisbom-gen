# GitHub Issue: bomtrace3 fails under QEMU x86_64 emulation (Apple Silicon)

**Repository:** omnibor/bomsh
**Title:** bomtrace3 produces empty raw logfile under QEMU x86_64 emulation on Apple Silicon

---

## Description

bomtrace3 produces a **0-byte raw logfile** (`/tmp/bomsh_hook_raw_logfile.sha1`) when running inside a Docker container on Apple Silicon (M1/M2/M3/M4) via QEMU x86_64 emulation. No compiler calls are intercepted, making build interception non-functional on this increasingly common development platform.

## Environment

- **Host:** macOS on Apple Silicon (M-series)
- **Docker:** Docker Desktop with QEMU x86_64 emulation (Rosetta enabled)
- **Container:** Ubuntu 22.04 (`linux/amd64`)
- **CPU reported inside container:** `VirtualApple @ 2.50GHz`
- **strace system:** v5.16 (with mpers, also fails)
- **bomtrace3:** built from strace v6.11 with bomtrace3.patch

## Root Cause Analysis

We traced the failure through three compounding issues:

### Issue 1: mpers/syscall decoding failure

strace cannot decode syscall registers under QEMU's x86_64 emulation. The `VirtualApple` CPU causes strace to misidentify the process personality, constantly flipping between `x32 mode` and `64 bit mode`.

**Impact:** `decode_execve()` is never called → `bomsh_record_command()` never fires → no `cmd_data` is created → `bomsh_hook_program()` finds nothing at process exit.

**Evidence:**

```
bomtrace3: WARNING: Proper structure decoding for this personality is not supported,
please consider building strace with mpers support enabled.
```

- Building with `--enable-mpers=check` results in `no-m32-mpers no-mx32-mpers` because the QEMU build environment lacks i686 cross-compilation libs
- Even system strace v5.16 (with mpers) shows constant personality flipping

### Issue 2: /proc fallback partially works but hits Rosetta wrapper

We implemented a `/proc` fallback that hooks at `TE_STOP_BEFORE_EXECVE` (process still alive) to read from `/proc/<pid>/exe`, `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, and `/proc/<pid>/root`.

**Result:** The fallback successfully reads argv and creates `cmd_data`. However, `/proc/<pid>/exe` resolves to `/usr/bin/rosetta-wrapper` — a virtual binary injected by Apple's Rosetta translation layer — instead of the actual program (e.g., `/usr/bin/gcc`).

### Issue 3: Rosetta wrapper masks real binary path

Under Docker Desktop with Rosetta on Apple Silicon, every executed binary is wrapped:

```
/proc/<pid>/cmdline contents:
/usr/bin/rosetta-wrapper\0/usr/bin/gcc\0gcc\0-o\0/tmp/test\0/tmp/test.c\0
```

- `argv[0]` = `/usr/bin/rosetta-wrapper` (wrapper binary)
- `argv[1]` = `/usr/bin/gcc` (real binary path)
- `argv[2]` = `gcc` (program name as invoked)
- `argv[3..]` = actual arguments

Because `cmd->path` is set to `/usr/bin/rosetta-wrapper`, `bomsh_process_shell_command()` uses `bomsh_basename(cmd->path)` → `"rosetta-wrapper"` matches no handler → falls through to "Not-supported shell command" → raw logfile stays empty.

## What Works

- `PTRACE_EVENT_EXEC` still fires correctly under QEMU
- `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, `/proc/<pid>/root` all return correct data
- `bomsh_hook_program()` correctly retrieves `cmd_data` from the hash table at process exit
- The overall bomtrace3 tracing infrastructure (process tracking, hash table, hook dispatch) works fine

## Suggested Fix

A `/proc`-based fallback mechanism could make bomtrace3 work under QEMU/Rosetta:

1. **New function `bomsh_record_command_proc(pid_t pid)`** in `bomsh_hook.c`:

   - Called at `TE_STOP_BEFORE_EXECVE` when `decode_execve()` did not record a command
   - Reads `/proc/<pid>/exe` for program path
   - Reads `/proc/<pid>/cmdline` for argv (split on NUL bytes)
   - Reads `/proc/<pid>/cwd` and `/proc/<pid>/root` for working directory
   - Detects Rosetta wrapper: if exe path contains "rosetta", uses `argv[1]` as real path
   - Creates `cmd_data` and inserts into `bomsh_cmds` hash table

2. **Call site in `strace.c`** at `TE_STOP_BEFORE_EXECVE` case, after `TCB_CHECK_EXEC_SYSCALL` flag clear

3. **Declaration in `bomsh_hook.h`**: `extern int bomsh_record_command_proc(pid_t pid);`

We have a working patch script at `docker/patches/apply_qemu_fallback.py` that implements this approach. The `/proc` reading and `cmd_data` creation work correctly. The remaining issue is that `bomsh_is_watched_program()` does not match `argv[1]` paths (e.g., `/usr/bin/gcc`) for reasons we haven't fully diagnosed — possibly related to symlink resolution (`/usr/bin/gcc` → `gcc-11`) or watched programs list initialization timing.

## Workaround

Run bomtrace3 on **native x86_64 Linux** (bare metal or cloud VM). All issues are specific to QEMU/Rosetta emulation and do not occur on native hardware.

## Additional Issues Found During Investigation

1. **`bomtrace.conf` raw_logfile is commented out** — the default config has `#raw_logfile=/tmp/bomsh_hook_raw_logfile`. bomtrace3 defaults to `/tmp/bomsh_hook_raw_logfile.sha1` internally, but this should be documented.

2. **`bomsh_create_bom.py` crashes on empty logfile** — when the raw logfile is 0 bytes, the script reads it successfully but crashes with `FileNotFoundError` at line 775 trying to copy `/tmp/bomsh_createbom_jsonfile` which was never created. Should handle the empty-logfile case gracefully.

3. **mpers silently disabled** — `--enable-mpers=check` silently disables mpers when the build environment lacks i686 cross-compilation toolchain. This is expected but undocumented.

## Labels

`bug`, `platform:apple-silicon`, `component:bomtrace3`
