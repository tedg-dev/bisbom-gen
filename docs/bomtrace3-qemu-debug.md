# bomtrace3 QEMU/Apple Silicon Debug Notes

## Problem

bomtrace3 produces a **0-byte raw logfile** when running inside a Docker
container on Apple Silicon (M1/M2/M3) via QEMU x86_64 emulation.

## Root Cause

strace (and by extension bomtrace3) cannot decode syscall registers under
QEMU's x86_64 emulation on Apple Silicon. The `VirtualApple` CPU causes
strace to misidentify the process personality, constantly flipping between
`x32 mode` and `64 bit mode`.

### Detailed Trace

1. **bomtrace3** is a patched strace v6.11 with `bomsh_hook.c` compiled in.
2. The patch hooks `decode_execve()` to call `bomsh_record_command()` on
   execve **enter**, and `TE_EXITED` to call `bomsh_hook_program()` on
   process **exit**.
3. `bomsh_record_command()` (bomsh_hook.c:976) calls:
   - `copy_path(tcp, tcp->u_arg[index + 0])` to read the program path
   - `copy_argv_array(tcp, tcp->u_arg[index + 1], ...)` to read argv
4. Both use `umovestr()` which reads from the tracee's memory at the
   address stored in `tcp->u_arg[]`.
5. **Under QEMU**, `tcp->u_arg[]` contains garbage because strace cannot
   decode the syscall registers without mpers (multiple personalities)
   support.
6. `copy_path()` returns NULL → `bomsh_record_command()` returns 0 early →
   no `cmd_data` is created.
7. Later, `bomsh_hook_program()` (bomsh_hook.c:4036) calls
   `bomsh_remove_cmd(pid)` which returns NULL → logs
   `"No pid X cmd_data found"` → raw logfile stays empty.

### Evidence

- bomtrace3 built with `--enable-mpers=check` but binary shows
  `no-m32-mpers no-mx32-mpers` (mpers not compiled because QEMU build
  env lacks i686 cross-compilation libs)
- System strace v5.16 (with mpers) also fails — shows constant
  `Process PID runs in x32 mode / 64 bit mode` flipping
- `bomsh_get_pwd()` and `bomsh_get_rootdir()` work fine because they
  use `/proc/<pid>/cwd` and `/proc/<pid>/root` (procfs, not ptrace)
- `/proc/<pid>/exe` and `/proc/<pid>/cmdline` also work correctly

## Attempted Fix: `/proc` Fallback Patch

We implemented a `/proc` fallback in `bomsh_hook.c` that hooks at
`TE_STOP_BEFORE_EXECVE` (process still alive) to read program info from
`/proc/<pid>/exe`, `/proc/<pid>/cmdline`, `/proc/<pid>/cwd`, and
`/proc/<pid>/root`.

### Patch Location

- New function: `bomsh_record_command_proc(pid_t pid)` in `bomsh_hook.c`
- Declaration: `extern int bomsh_record_command_proc(pid_t pid)` in `bomsh_hook.h`
- Call site: `strace.c` at `TE_STOP_BEFORE_EXECVE` case, after
  `TCB_CHECK_EXEC_SYSCALL` flag clear
- Patch script: `docker/patches/apply_qemu_fallback.py`

### Results

The `/proc` fallback **partially works**:

- `bomsh_record_command_proc()` fires correctly at `TE_STOP_BEFORE_EXECVE`
- `/proc/<pid>/cmdline` is read successfully, argv is parsed
- `cmd_data` is stored in the hash table
- `bomsh_hook_program()` finds the `cmd_data` at process exit

**However**, a second issue was discovered:

### Issue 2: Rosetta Wrapper Masking

Under Docker Desktop on Apple Silicon, `/proc/<pid>/exe` resolves to
`/usr/bin/rosetta-wrapper` — a virtual binary injected by Apple's Rosetta
translation layer. The real program path (e.g., `/usr/bin/gcc`) appears as
`argv[1]` in `/proc/<pid>/cmdline`.

**cmdline format under Rosetta:**

```
/usr/bin/rosetta-wrapper\0/usr/bin/gcc\0gcc\0-o\0/tmp/test\0/tmp/test.c\0
```

- `argv[0]` = `/usr/bin/rosetta-wrapper` (wrapper)
- `argv[1]` = `/usr/bin/gcc` (real binary path)
- `argv[2]` = `gcc` (program name as invoked)
- `argv[3..]` = actual arguments

This means:

1. `cmd->path` is set to `/usr/bin/rosetta-wrapper`
2. `bomsh_process_shell_command()` uses `bomsh_basename(cmd->path)` to
   dispatch → `"rosetta-wrapper"` matches no handler
3. Falls through to `"Not-supported shell command"` → raw logfile stays empty

We attempted to detect rosetta by checking if exe_path contains `"rosetta"`
and falling back to `argv[1]`, but `bomsh_is_watched_program(argv[1])` also
returned false for unknown reasons (possibly a timing issue with the watched
programs list initialization, or a symlink resolution mismatch since
`/usr/bin/gcc` → `gcc-11`).

### Conclusion

Fixing bomtrace3 for QEMU/Rosetta emulation requires patching at least
three layers (mpers, /proc fallback, rosetta-wrapper detection). This is
not practical for local development. **The recommended approach is to run
bomtrace3 on native x86_64 Linux** where none of these issues exist.

## Additional Issues Found

1. **bomtrace.conf `raw_logfile` is commented out** — the default config
   has `#raw_logfile=/tmp/bomsh_hook_raw_logfile`. bomtrace3 appears to
   default to `/tmp/bomsh_hook_raw_logfile.sha1` internally, but this
   should be documented.

2. **`bomsh_create_bom.py` FileNotFoundError** — when the raw logfile is
   empty (0 bytes), `bomsh_create_bom.py` reads it successfully but then
   crashes at line 775 trying to copy `/tmp/bomsh_createbom_jsonfile`
   which was never created. The script should handle the empty-logfile
   case gracefully instead of crashing.

3. **mpers not built under QEMU** — `--enable-mpers=check` silently
   disables mpers when the build environment (itself running under QEMU)
   lacks the i686 cross-compilation toolchain. This is expected but
   undocumented.

## Environment

- Host: macOS on Apple Silicon (M1/M2/M3)
- Docker: Docker Desktop with QEMU x86_64 emulation
- Container: Ubuntu 22.04 (linux/amd64)
- CPU reported: `VirtualApple @ 2.50GHz`
- strace system: v5.16 (with mpers, still fails)
- bomtrace3: built from strace v6.11 (without mpers)
