---
description: Rust-specific best practices, tooling, and conventions
---

# Rust Best Practices

## Workspace & Manifest

- **Edition**: Always use the latest stable Rust edition (currently 2024)
- **rust-version**: Set `rust-version` in `[workspace.package]` to the MSRV
  that supports your edition
- **rust-toolchain.toml**: Always create one at the project root pinning
  `channel = "stable"` with `components = ["rustfmt", "clippy"]`
- **Virtual workspaces**: A virtual workspace (`[workspace]` without
  `[package]`) MUST NOT contain `[[bin]]`, `[dependencies]`, `[lib]`, or
  any package-level keys. Those belong in member crates only
- **CLI binary**: Put the CLI binary in a dedicated `crates/cli/` member,
  not the workspace root
- **Workspace lints**: Define `[workspace.lints]` and add
  `[lints] workspace = true` to every member crate
- **Workspace dependencies**: All shared dependencies go in
  `[workspace.dependencies]`. Members reference them with `{ workspace = true }`
- **Description**: Always set `description` in `[workspace.package]`

## Dependency Hygiene

- **No deprecated crates**: Before adding any dependency, verify it is
  actively maintained. Check crates.io and the repository
- **Feature flags**: Only enable features you actually use. Audit all
  feature flags before committing
- **All imports compile**: Every `use` statement MUST have a corresponding
  dependency in the crate's `Cargo.toml`. Verify by compiling
- **Pin major versions**: Use `"1"` not `"*"`. Use
  `{ version = "0.12", features = [...] }` for pre-1.0 crates

## Code Quality

- **Zero warnings**: Code must compile with zero warnings under
  `RUSTFLAGS="-Dwarnings"`
- **Clippy clean**: `cargo clippy --workspace --all-targets -- -D warnings`
  must pass
- **No unused code**: Remove unused imports, variables, functions, and dead
  code. Do not leave `#[allow(dead_code)]` without a comment explaining why
- **Default trait**: If `new()` takes no arguments, derive or implement `Default`
- **Error handling**: Use `thiserror` for library errors, `anyhow` for
  application/CLI errors. Never `unwrap()` in library code

## API Design

- **Single-callback APIs**: When an API accepts ONE callback/closure (like
  `WalkBuilder::filter_entry`), build a single closure — do NOT call it
  in a loop
- **Test what you ship**: Every `pub` function should have at least one test.
  Every struct with methods should be tested

## CI Configuration

- **Toolchain**: Use `rust-toolchain.toml` (preferred) or
  `dtolnay/rust-toolchain@stable`. Never rely on runner defaults
- **Cache**: Cache `~/.cargo/registry`, `~/.cargo/git`, and `target/`
  keyed on `Cargo.lock` hash
- **Job order**: check → (test, clippy, fmt) — `test` and `clippy` should
  `needs: check` to fail fast
- **Warnings as errors**: `RUSTFLAGS: "-Dwarnings"` in the workflow env

## Release Builds (Bisbom)

- Always `cargo build --release` (never plain `cargo build`)
- Output path must be `target/release/`, not `target/debug/`

## Dependency Audit

- `cargo audit` to scan for known advisories in `Cargo.lock`
- `cargo deny check` for license and duplicate dependency checks
