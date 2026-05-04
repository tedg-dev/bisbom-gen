#!/usr/bin/env bash
# ============================================================
# End-to-end standalone regression gate (C8 / #120)
#
# Runs all repos in standalone mode, compares against golden
# files, verifies unit tests + coverage.
#
# Must run INSIDE the Docker container on EC2.
#
# Usage:
#   bash scripts/regression_gate.sh [--repo REPO]
#
# Exit codes:
#   0 — all checks pass
#   1 — regression detected or test failure
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default: all repos. Override with --repo.
REPOS=(redis curl ffmpeg nmap fzf lazygit oxipng dura jsoup checkstyle)
SINGLE_REPO=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) SINGLE_REPO="$2"; shift 2 ;;
        *) echo "[ERROR] Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -n "$SINGLE_REPO" ]]; then
    REPOS=("$SINGLE_REPO")
fi

FAIL=0

echo "============================================"
echo "  OmniBOR Regression Gate"
echo "  Repos: ${REPOS[*]}"
echo "============================================"

# -----------------------------------------------
# Step 1: Unit tests
# -----------------------------------------------
echo ""
echo "[STEP 1] Running unit tests..."
cd "$PROJECT_DIR"
if python3 -m pytest tests/ -x -q --tb=short; then
    echo "[PASS] Unit tests"
else
    echo "[FAIL] Unit tests"
    FAIL=1
fi

# -----------------------------------------------
# Step 2: Coverage check
# -----------------------------------------------
echo ""
echo "[STEP 2] Checking coverage..."
if python3 -m pytest tests/ -q --cov=app --cov-report=term-missing --cov-fail-under=95 2>&1 | tail -n 20; then
    echo "[PASS] Coverage >= 95%"
else
    echo "[FAIL] Coverage below threshold"
    FAIL=1
fi

# -----------------------------------------------
# Step 3: Run each repo in standalone mode
# -----------------------------------------------
echo ""
echo "[STEP 3] Running pipelines..."
for repo in "${REPOS[@]}"; do
    echo ""
    echo "--- Running: $repo ---"
    if python3 -m app.pipeline.runners --repo "$repo" --skip-clone --mode standalone; then
        echo "[PASS] Pipeline: $repo"
    else
        echo "[FAIL] Pipeline: $repo"
        FAIL=1
    fi
done

# -----------------------------------------------
# Step 4: Golden file comparison
# -----------------------------------------------
echo ""
echo "[STEP 4] Comparing against golden files..."
GOLDEN_DIR="$PROJECT_DIR/tests/golden/spdx"
OUTPUT_DIR="/workspace/output/spdx"

DIFFS=0
for lang_dir in "$GOLDEN_DIR"/*/; do
    lang=$(basename "$lang_dir")
    for repo_dir in "$lang_dir"*/; do
        repo=$(basename "$repo_dir")
        # Skip if not in our repo list
        if [[ " ${REPOS[*]} " != *" $repo "* ]]; then
            continue
        fi
        for golden_file in "$repo_dir"*.spdx.json; do
            fname=$(basename "$golden_file")
            # Find latest actual output
            actual_dir=$(ls -td "$OUTPUT_DIR/$lang/$repo"/*/ 2>/dev/null | head -1)
            if [[ -z "$actual_dir" ]]; then
                echo "[DIFF] No output for $lang/$repo"
                DIFFS=$((DIFFS + 1))
                continue
            fi
            actual="$actual_dir/$fname"
            if [[ ! -f "$actual" ]]; then
                echo "[DIFF] Missing: $lang/$repo/$fname"
                DIFFS=$((DIFFS + 1))
                continue
            fi
            # Use Python comparison
            python3 -c "
from tests.test_spdx_regression import compare_against_golden
from pathlib import Path
diffs = compare_against_golden(
    Path('$actual'),
    '$lang', '$repo',
    '${fname%%_*}',
)
if diffs:
    for d in diffs:
        print(f'[DIFF] {d}')
    exit(1)
else:
    print('[MATCH] $lang/$repo/$fname')
" || DIFFS=$((DIFFS + 1))
        done
    done
done

if [[ $DIFFS -gt 0 ]]; then
    echo ""
    echo "[FAIL] $DIFFS golden file differences found"
    FAIL=1
else
    echo "[PASS] All golden files match"
fi

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "============================================"
if [[ $FAIL -eq 0 ]]; then
    echo "  REGRESSION GATE: PASSED"
else
    echo "  REGRESSION GATE: FAILED"
fi
echo "============================================"

exit $FAIL
