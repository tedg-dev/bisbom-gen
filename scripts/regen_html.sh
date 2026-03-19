#!/usr/bin/env bash
# Regenerate HTML visualizations for all SPDX JSON files
# in output/spdx/ using the updated spdx_visualize.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

COUNT=0
ERRORS=0

# Find all *_analyzed.spdx.json and *_adg.spdx.json files
find output/spdx -name '*_analyzed.spdx.json' -o -name '*_adg.spdx.json' | sort | while read -r json_file; do
    html_file="${json_file%.spdx.json}.spdx.html"
    echo "  $json_file -> $(basename "$html_file")"
    if .venv/bin/python3 -m app.spdx_visualize "$json_file" -o "$html_file" 2>&1; then
        COUNT=$((COUNT + 1))
    else
        echo "  ERROR: $json_file"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "Done. Processed files. Check output above for errors."
