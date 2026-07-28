---
description: Regenerate PNG when draw.io diagrams are modified
---

# Draw.io PNG Export Rule

Whenever a `.drawio` file is modified in the repository, Cascade MUST regenerate the corresponding PNG file.

## Command

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --output <output.png> <input.drawio>
```

## Example

If `docs/architecture/omnibor-analysis-workflow.drawio` is modified:

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --output docs/architecture/omnibor-analysis-workflow.png docs/architecture/omnibor-analysis-workflow.drawio
```

## Workflow

1. After modifying any `.drawio` file, run the export command
2. Commit both the `.drawio` and `.png` files together
3. The PNG should have the same base name as the drawio file

## Known Locations

- `docs/architecture/omnibor-analysis-workflow.drawio` → `docs/architecture/omnibor-analysis-workflow.png`
- `docs/architecture/ci-cd-integration.drawio` → `docs/architecture/ci-cd-integration.png`

## Regenerating HTML Visualizations from SPDX JSON

When regenerating HTML visualizations, **only regenerate the most recent
timestamp folder per language per repo**. Do not regenerate older folders.

Each repo's output is at `output/spdx/<language>/<repo>/<timestamp>/`.
The most recent folder sorts last alphabetically (`YYYY-MM-DD_HHMM`).

```bash
for lang_dir in output/spdx/*/; do
  for repo_dir in "${lang_dir}"*/; do
    latest=$(ls -1d "${repo_dir}"*/ 2>/dev/null | sort | tail -1)
    [ -z "$latest" ] && continue
    for json_file in "${latest}"*.spdx.json; do
      [ -f "$json_file" ] || continue
      case "$json_file" in *syft*) continue;; esac
      html_file="${json_file%.spdx.json}.spdx.html"
      .venv/bin/python3 -m app.spdx_visualize "$json_file" -o "$html_file"
    done
  done
done
```

- Exclude `*syft*` SPDX files (they have their own visualization)
- Run from the project root
