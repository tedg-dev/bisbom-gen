---
description: Go-specific best practices, tooling, and conventions
---

# Go Best Practices

## Project Structure

- **Go version**: Pin in `go.mod` (e.g., `go 1.22`). Use the latest stable
  release unless backward compatibility is required
- **Module path**: Use the canonical import path
  (e.g., `github.com/org/repo`)
- **Layout**: Follow the standard Go project layout — `cmd/` for binaries,
  `internal/` for private packages, `pkg/` for public libraries
- **go.sum**: Always commit `go.sum`. Never `.gitignore` it

## Formatting & Linting

- **Formatter**: `gofmt` (or `goimports`) — non-negotiable, no configuration
- **Linter**: `golangci-lint` with `.golangci.yml` config. Enable at minimum:
  `govet`, `errcheck`, `staticcheck`, `gosimple`, `unused`
- **Vet**: `go vet ./...` catches subtle bugs (shadow variables, printf args)

## Idioms

- **Error handling**: Return `error` as the last return value. Check every
  error — never ignore with `_`. Use `fmt.Errorf("context: %w", err)` for
  wrapping
- **Naming**: Short, lowercase package names. Exported names are PascalCase.
  Unexported are camelCase. No underscores in Go names
- **Interfaces**: Define interfaces at the consumer, not the producer.
  Keep interfaces small (1–3 methods)
- **Goroutines**: Always ensure goroutines can be cancelled (via `context`)
  and that they terminate cleanly. Use `errgroup` for fan-out
- **Struct initialization**: Use named fields in composite literals
  (`Foo{Name: "bar"}` not `Foo{"bar"}`)
- **Avoid init()**: Use explicit initialization in `main()` or constructors.
  `init()` is invisible and hard to test

## Error Handling

- ALWAYS check returned errors — `errcheck` linter enforces this
- Wrap errors with context: `fmt.Errorf("loading config: %w", err)`
- Use sentinel errors (`var ErrNotFound = errors.New(...)`) for expected
  error conditions the caller should match with `errors.Is()`
- Use custom error types only when the caller needs structured error data

## Testing

- **Framework**: stdlib `testing` package. Use `testify` only if already
  in the project
- **Table-driven tests**: Preferred pattern for testing multiple inputs
- **Test helpers**: Use `t.Helper()` in helper functions so failures report
  the correct line
- **Temp dirs**: `t.TempDir()` (auto-cleaned) for file I/O tests
- **Parallel**: Use `t.Parallel()` for independent tests to speed up suite
- **Mocking**: Use interfaces + test doubles. `gomock` or hand-written fakes

## CI Configuration

- **Setup**: `actions/setup-go` with pinned version (e.g., `1.22`)
- **Cache**: `~/go/pkg/mod` and `~/.cache/go-build` keyed on `go.sum` hash
- **Lint job**: `golangci-lint run ./...`
- **Test job**: `go test -race -coverprofile=coverage.out ./...`
- **Race detector**: Always run tests with `-race` in CI

## Release Builds (OmniBOR)

- Always include `-trimpath -ldflags="-s -w"` in `go build`
- `-trimpath` strips local filesystem paths from the binary
- `-ldflags="-s -w"` strips symbol table and DWARF debug info
- `-a` required for bomtrace2 cache bypass

## Dependency Audit

- `govulncheck ./...` to scan for known vulnerabilities
- `go mod tidy` to remove unused dependencies
- `go mod verify` to check integrity of downloaded modules
