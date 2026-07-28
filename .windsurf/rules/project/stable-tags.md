# Stable Release Tags

## Rule
When adding or modifying a repository in `app/config.yaml`, the `branch` field **must point to a stable release tag** (e.g., `v8.0.6`, `7.2.13`), never to a development branch like `unstable`, `master`, `main`, or `dev`.

## Why
Development branches often use placeholder versions (e.g., Redis `unstable` uses `255.255.255`), produce unreproducible builds, and make SBOM version fields meaningless.

## When adding a new repo
1. Check the repo's releases/tags page for the latest stable version.
2. Use that tag as the `branch` value (git clone --branch accepts tags).
3. Document the chosen version in the `description` field.

## Audit checklist
When reviewing config.yaml, flag any `branch` value that matches:
- `master`, `main`, `develop`, `dev`, `unstable`, `nightly`
- Any branch name without a version number
