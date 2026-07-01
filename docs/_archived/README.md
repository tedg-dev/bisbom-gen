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
| **nonmaven-gradle-java/** | TABLED (deferred post-pilot) design + sub-issue for non-Maven/Gradle Java builds (Ant/Ivy, Bazel, `make`/`javac`); pilot is Maven/Gradle only |
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

## Convention: superseded docs move here

When a document is fully superseded by a consolidated reference (it carries
a **"Superseded"** banner pointing at the live doc), move it into the most
fitting subfolder here in the **same** change that consolidates it. These
archived copies are retained for traceability and detail — useful when
something appears missing from a live doc — but humans should read the live
docs, not these. A doc that is only **partially** consolidated and remains
authoritative for some scope stays in its live location.
