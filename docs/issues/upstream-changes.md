# Upstream Changes Needed in omnibor/bomsh

Tracked here so we can open GitHub Issues and propose fixes
against https://github.com/omnibor/bomsh.

---

## 1. Bug fix: `is_golang_prog()` missing `/usr/local/go/` path

**This is the only upstream code change.** Everything else below
is a new-file contribution suggestion.

**Upstream file**: `scripts/bomsh_hook2.py`, function
`is_golang_prog()` (line ~388)

**Our local patch**:
`docker/patches/bomsh_hook2_golang_path.patch`

**Problem**: The function only matches Go compiler/linker paths
under `/usr/lib/go-*` and `/usr/lib/golang/`, but the official
Go installer (from https://go.dev/dl/) installs to
`/usr/local/go/`. This means bomtrace2 silently ignores Go
compile/link commands on systems with the standard Go
installation.

**Fix** (one-line change):

```python
# Before (upstream)
if "lib/go" not in prog or "pkg/tool" not in prog:

# After (fixed)
if ("lib/go" not in prog and "local/go" not in prog) or "pkg/tool" not in prog:
```

**Affects**: Any Go project built with `/usr/local/go/` (the
default install path from go.dev).

**GitHub Issue**: "is_golang_prog() does not match
/usr/local/go/ install path"

---

## 2. New file suggestion: Go-specific bomtrace2 config

**This is NOT an upstream code change.** It is a new file we
could propose contributing to the bomsh repo as an example.

**Our local file**: `docker/bomtrace_go.conf`

**Problem**: bomtrace2's default configuration does not watch
Go compiler/linker tools or the `openat` syscall (which Go
tools use instead of plain `open`). Users need a separate
config for Go builds.

**Key settings**:
- `-n` flag: prevent BOM embedding (Go compiler rejects
  modified `.go` files with checksum mismatches)
- `-w` flag: explicitly watch
  `/usr/local/go/pkg/tool/linux_amd64/compile` and `link`
- `syscalls=openat`: capture Go file I/O

**Suggested upstream path**: `examples/bomtrace_go.conf` or
referenced in the Go analysis documentation.

**GitHub Issue**: "Add Go-specific bomtrace2 configuration
example"
