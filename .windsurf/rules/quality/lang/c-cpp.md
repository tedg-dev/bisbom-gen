---
description: C/C++-specific best practices, tooling, and conventions
---

# C/C++ Best Practices

## Project Structure

- **Standard**: Target C11 (C) or C++17/C++20 (C++) unless the project
  requires older standards
- **Build systems**: autoconf/make, CMake (preferred for new projects), or
  Meson. Always provide a clean `make clean` / `cmake --build build --target clean`
- **Layout**: Separate `src/` (implementation), `include/` (public headers),
  `tests/` (test sources), `third_party/` or `vendor/` (vendored deps)
- **Header guards**: Use `#pragma once` (modern compilers) or traditional
  `#ifndef PROJECT_MODULE_H_` / `#define` / `#endif`

## Formatting & Linting

- **Formatter**: `clang-format` with a `.clang-format` config at the
  project root (Google, LLVM, or project-specific style)
- **Linter**: `clang-tidy` with checks enabled:
  `modernize-*`, `bugprone-*`, `performance-*`, `readability-*`
- **Static analysis**: `cppcheck`, Coverity, or compiler warnings
  (`-Wall -Wextra -Werror`)
- **Compiler warnings**: Always build with `-Wall -Wextra`. Treat warnings
  as errors (`-Werror`) in CI

## Idioms

### C

- **Memory management**: Always pair `malloc`/`free`. Use `calloc` for
  zero-initialized allocations. Check return values
- **String handling**: Prefer `snprintf` over `sprintf`. Always specify
  buffer sizes
- **Error codes**: Return `int` error codes (0 = success). Define error
  constants as `enum` or `#define`
- **Const correctness**: Use `const` for read-only pointers and parameters

### C++

- **RAII**: Use constructors/destructors for resource management. No raw
  `new`/`delete` — use `std::unique_ptr` and `std::shared_ptr`
- **Move semantics**: Accept large objects by value and `std::move` for
  ownership transfer
- **std::string_view**: Use for non-owning string references (C++17)
- **std::optional**: For values that may or may not be present (C++17)
- **Range-based for loops**: Prefer `for (const auto& item : container)`
- **auto**: Use for complex iterator types and template deduction. Avoid
  for primitive types where the type isn't obvious

## Error Handling

- C: Return error codes, set `errno` for POSIX-compatible errors. Document
  all error conditions
- C++: Use exceptions for truly exceptional conditions. Use `std::expected`
  (C++23) or `std::optional` for expected failure paths
- Never ignore return values of functions that can fail (use
  `[[nodiscard]]` in C++)
- Log errors with file/line context for debugging

## Testing

- **Framework**: Google Test (gtest) + Google Mock (gmock) for C++.
  `check` or custom test harness for C
- **Build**: Tests should compile and run via `ctest` (CMake) or
  `make check` (autotools)
- **Sanitizers**: Run tests under AddressSanitizer (`-fsanitize=address`)
  and UndefinedBehaviorSanitizer (`-fsanitize=undefined`) in CI
- **Valgrind**: Run `valgrind --leak-check=full` on test binaries to detect
  memory leaks (if sanitizers are not available)

## CI Configuration

- **Compiler matrix**: Test with both GCC and Clang when possible
- **Cache**: Cache build directories, `ccache` for compilation caching
- **Build job**: `cmake --build build -j$(nproc)` or `make -j$(nproc)`
- **Test job**: `ctest --test-dir build --output-on-failure`
- **Static analysis job**: `clang-tidy` on changed files

## Release Builds (Bisbom)

- `./configure` without `--enable-debug` or `CFLAGS="-g -O0"`
- `make` with default optimization (typically `-O2`)
- Never pass `DEBUG=1`, `ASAN=1`, or sanitizer flags in release builds
- Verify output binaries are NOT in a `debug/` directory

## Dependency Management

- **Vendored sources**: Commit vendored dependencies under `vendor/` or
  `third_party/`. Document versions and upstream URLs
- **System libraries**: Declare required system packages in build docs.
  Use `pkg-config` for discovery
- **Package managers**: Conan or vcpkg for C++ dependency management in
  new projects

## Dependency Audit

- Manual review of vendored source versions against upstream CVE databases
- `cppcheck` for code-level issues
- Compiler warning count should never increase between commits
