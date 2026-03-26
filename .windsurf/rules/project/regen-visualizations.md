# Regenerating HTML Visualizations

## Rule
When regenerating HTML visualization files from SPDX JSON, **only regenerate the most recent timestamp folder per language per repo**. Do not regenerate older folders.

## How to find the most recent folder
Each repo's output is at `output/spdx/<language>/<repo>/<timestamp>/`. The most recent folder is the one that sorts last alphabetically (timestamps are `YYYY-MM-DD_HHMM` format).

## Command
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

## Notes
- Exclude `*syft*` SPDX files (they have their own visualization pipeline).
- This command should be run from the project root (`/Users/tedg/workspace/omnibor-analysis`).
