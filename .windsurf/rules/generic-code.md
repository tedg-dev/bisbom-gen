# Generic Code — No Hardcoded Repo Names

## Rule

All application code MUST be generic and repo-agnostic. This is a universal analysis
tool that works on ANY repository defined in config.yaml.

## Prohibited Patterns

1. **No hardcoded repository names** — Never reference `curl`, `nmap`, `redis`, `ffmpeg`,
   or any specific repo name in executable code (imports, conditionals, paths, field names).
   - Comments/docstrings may use repo names as illustrative examples (e.g. `"e.g. curl"`)
   - Test fixtures may reference repo names when testing specific scenarios
   - config.yaml entries are expected to have repo names as keys

2. **No repo-specific logic** — Never write `if repo_name == "curl"` or similar
   conditional branches for specific repositories. All behavior must be driven by
   config.yaml fields (language, build_steps, output_binaries, vendored_dirs, etc.)

3. **No hardcoded paths to repo files** — Never construct paths like
   `repos/curl/include/curl/curlver.h`. Use generic version detection strategies
   that work across all repos.

4. **No legacy field names tied to specific repos** — Field names like `curl_version`
   that embed a repo name must be renamed to generic equivalents (e.g. `repo_version`).

5. **No hardcoded defaults in `__main__` blocks** — If a script has a standalone
   `__main__`, use argparse with required arguments or sensible generic defaults,
   never repo-specific paths.

## Required Patterns

- **Config-driven behavior** — Language-specific logic branches on `lang_subdir()`
  values (`c-cpp`, `go`, `rust`, `java`), never on repo names.
- **Strategy/detector patterns** — Use generic detection strategies (e.g.,
  VendoredVersionDetector's 10 ordered strategies) that work across all repos.
- **DRY pipeline steps** — Common logic shared across language pipelines must be
  extracted into reusable methods, not copy-pasted with minor variations.
