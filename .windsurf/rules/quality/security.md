---
description: Security practices for secrets, inputs, dependencies, and outputs
trigger: always_on
priority: critical
---

# Security Standards

These rules apply to all code, CI pipelines, and Cascade interactions.

## Secrets and Credentials

- **NEVER** hardcode secrets, tokens, API keys, or passwords in source code
- **NEVER** commit credential files (`.env` with secrets, `keys.json`,
  `service-account.json`, SSH private keys)
- **NEVER** display, echo, or log secret values in Cascade chat, terminal
  output, or CI logs
- Store secrets in environment variables, secret managers (AWS SSM, GitHub
  Secrets), or encrypted config files excluded by `.gitignore`
- Reference credential files by path and key name only — never by value
- Prefer fine-grained PATs and short-lived tokens over long-lived credentials

## Input Validation

- Validate ALL external input before use (CLI arguments, API payloads,
  config file values, environment variables)
- Use allowlists over denylists when possible
- Sanitize file paths — never pass user-provided strings directly to
  `open()`, `exec()`, or shell commands
- Validate JSON against schemas before processing

## Dependency Security

- Before adding any dependency, verify it is actively maintained and
  not deprecated. Check for known CVEs
- Pin dependency versions in applications. Use compatible ranges only
  in libraries
- Audit dependencies periodically:
  - Python: `pip audit` or `safety check`
  - Rust: `cargo audit`
  - Go: `govulncheck`
  - Java: `mvn dependency-check:check` (OWASP)
  - C/C++: manual review of vendored sources
- Never install packages from untrusted registries or personal forks
  without review

## Output Safety

- Sanitize all output written to files, reports, or HTML — prevent
  injection (XSS in HTML reports, path traversal in file writes)
- Log warnings and errors without including sensitive data (no tokens,
  no passwords, no PII)
- SPDX documents must not contain file system paths from the build host
  that reveal internal infrastructure

## CI/CD Security

- Scope GitHub Actions permissions to minimum required (`contents: read`)
- Never expose secrets in workflow logs — use `::add-mask::` if needed
- Pin action versions to full SHA, not mutable tags
- Use `concurrency` groups to prevent parallel runs that might race on
  shared resources

## OWASP / CWE References

These rules address the following common weaknesses:

| CWE | Description | Addressed by |
|-----|-------------|-------------|
| CWE-798 | Hard-coded credentials | Secrets rules above |
| CWE-20 | Improper input validation | Input validation rules |
| CWE-502 | Deserialization of untrusted data | JSON schema validation |
| CWE-78 | OS command injection | Path sanitization, no shell=True with user input |
| CWE-200 | Exposure of sensitive information | Output safety, logging rules |
| CWE-1104 | Use of unmaintained third-party components | Dependency audit rules |
