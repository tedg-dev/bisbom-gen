# Archived Documentation

These documents are preserved for historical reference. They are **not
current** and may contain outdated information about standalone mode,
early design iterations, or point-in-time snapshots.

## Subfolders

| Folder | Contents |
|--------|----------|
| **standalone/** | Pre-sidecar standalone mode docs, CI/CD integration (ptrace-era), demo workflows |
| **performance/** | Build-time overhead analysis, optimization proposals (pre-hash cache, seccomp-BPF, eBPF) |
| **design-evolution/** | Sidecar design iterations, cleanroom analysis, refactoring plans, Python/polyglot proposals |
| **snapshots/** | Point-in-time build results, coverage milestones, meeting agendas, per-feature changelogs |
| **features/** | Superseded feature docs (Go support, three-way SPDX comparison) |

## Why These Were Archived

- **Standalone-focused docs** — the project baseline moved to sidecar
  mode with phase isolation. Standalone is documented in
  `architecture/standalone-mode.md`.
- **Design evolution docs** — superseded by implemented code and
  current architecture docs.
- **Performance proposals** — research completed; findings are
  summarized in current docs where applicable.
- **Snapshots** — point-in-time data that is no longer actionable.
