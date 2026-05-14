# bomtrace3 Fails Under QEMU x86_64 Emulation (Apple Silicon)

**Upstream repo:** omnibor/bomsh
**Status:** Known limitation — workaround available

---

## Problem

bomtrace3 produces a **0-byte raw logfile**
(`/tmp/bomsh_hook_raw_logfile.sha1`) when running inside a Docker
container on Apple Silicon (M1/M2/M3/M4) via QEMU x86_64 emulation.
No compiler calls are intercepted, making build interception
non-functional.

## Environment

- **Host:** macOS on Apple Silicon (M-series)
- **Docker:** Docker Desktop with QEMU x86_64 emulation (Rosetta
  enabled)
- **Container:** Ubuntu 22.04 (`linux/amd64`)
- **CPU reported:** `VirtualApple @ 2.50GHz`
- **bomtrace3:** built from strace v6.11 with bomtrace3.patch

## Root Cause: Three Compounding Issues

### Issue 1: mpers / syscall register decoding failure

strace cannot decode syscall registers under QEMU's x86_64 emulation.
The `VirtualApple` CPU causes constant personality flipping between
`x32 mode` and `64 bit mode`.

**Impact:** `decode_execve()` never fires →
`bomsh_record_command()` never creates `cmd_data` →
`bomsh_hook_program()` finds nothing at exit → logfile stays empty.

**Evidence:**

```text
bomtrace3: WARNING: Proper structure decoding for this personality
is not supported, please consider building strace with mpers
support enabled.
```

Building with `--enable-mpers=check` results in
`no-m32-mpers no-mx32-mpers` because the QEMU build environment
lacks i686 cross-compilation libs. Even system strace v5.16 (with
mpers) shows constant personality flipping.

### Issue 2: `/proc` fallback partially works

A `/proc` fallback was implemented that hooks at
`TE_STOP_BEFORE_EXECVE` (process still alive) to read from
`/proc/<pid>/exe`, `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, and
`/proc/<pid>/root`.

The fallback successfully reads argv and creates `cmd_data`. However,
`/proc/<pid>/exe` resolves to `/usr/bin/rosetta-wrapper` instead of
the actual program.

### Issue 3: Rosetta wrapper masks real binary path

Under Docker Desktop with Rosetta on Apple Silicon, every executed
binary is wrapped:

```text
/proc/<pid>/cmdline contents:
/usr/bin/rosetta-wrapper\0/usr/bin/gcc\0gcc\0-o\0test\0test.c\0
```

- `argv[0]` = `/usr/bin/rosetta-wrapper` (wrapper binary)
- `argv[1]` = `/usr/bin/gcc` (real binary path)
- `argv[2..N]` = actual arguments

Because `cmd->path` is `/usr/bin/rosetta-wrapper`,
`bomsh_process_shell_command()` matches no handler → falls through
→ logfile stays empty.

## What Works Under QEMU

- `PTRACE_EVENT_EXEC` fires correctly
- `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, `/proc/<pid>/root`
  return correct data
- `bomsh_hook_program()` correctly retrieves `cmd_data` at exit
- All bomtrace3 infrastructure (process tracking, hash table, hook
  dispatch) works

## Patch Location

- **Function:** `bomsh_record_command_proc(pid_t pid)` in
  `bomsh_hook.c`
- **Call site:** `strace.c` at `TE_STOP_BEFORE_EXECVE`
- **Patch script:** `docker/patches/apply_qemu_fallback.py`

The patch implements Rosetta detection (checking if exe path contains
`"rosetta"` and using `argv[1]`), but `bomsh_is_watched_program()`
does not match the `argv[1]` path for undiagnosed reasons (possibly
symlink resolution or watched programs list timing).

## Workaround

**Run bomtrace3 on native x86_64 Linux** (bare metal or cloud VM).
All issues are specific to QEMU/Rosetta emulation and do not occur
on native hardware.

## Additional Issues Found

1. **`bomtrace.conf` raw_logfile commented out** — default config has
   `#raw_logfile=/tmp/bomsh_hook_raw_logfile`. bomtrace3 defaults to
   `/tmp/bomsh_hook_raw_logfile.sha1` internally.
2. **`bomsh_create_bom.py` crashes on empty logfile** — reads 0-byte
   logfile successfully, then crashes at line 775 trying to copy
   `/tmp/bomsh_createbom_jsonfile` (never created). Should handle
   gracefully.
3. **mpers silently disabled** — `--enable-mpers=check` silently
   disables mpers when build env lacks i686 cross-compilation
   toolchain.

---

**Labels:** `bug`, `platform:apple-silicon`, `component:bomtrace3`
