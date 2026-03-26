# Output Binaries Completeness

## Rule
When adding or modifying a repository in `app/config.yaml`, the `output_binaries` list **must include ALL binaries and shared libraries produced by the build**.

## Why
Each entry in `output_binaries` gets its own SPDX SBOM generated. Missing entries mean incomplete analysis — project-built libraries will appear as dependencies in other binaries' SBOMs but won't have their own SBOM.

## How to verify
1. After a successful build on EC2, list all produced binaries and `.so` files:
   - **C/C++**: `find repos/<name> -name '*.so' -o -type f -executable | grep -v '.o$'`
   - **Rust**: Check `target/release/` for executables
   - **Go**: Check the build output directory
   - **Java**: Check `target/` for `.jar` files
2. Compare against `output_binaries` in config.yaml.
3. Any project-built binary or `.so` that is dynamically linked by another output binary **must** be listed.

## Red flags
- A dependency in an SPDX visualization has the same version as the root package — it's likely a project-built library that should have its own SBOM.
- `ldd` shows a `.so` resolving to the repo's build tree rather than a system path.
