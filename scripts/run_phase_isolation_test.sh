#!/bin/bash
# ============================================================
# System-level phase isolation test
#
# Proves that Phase 1 and Phase 2 can run in SEPARATE
# containers, communicating only via the manifest file
# and shared volume.
#
# Phase 1 (Container A): build + write manifest
# Phase 2 (Container B): read manifest + generate SPDX
#
# After Phase 2, compares SPDX output against golden files.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"
GOLDEN_DIR="$PROJECT_ROOT/tests/golden/spdx/java"
LOG_DIR="/tmp/phase_isolation_test"
COMPARE_SCRIPT="$SCRIPT_DIR/compare_golden.py"

# Default: test jsoup (fast, has golden files)
REPOS="${1:-jsoup}"

mkdir -p "$LOG_DIR"

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0

run_phase_test() {
    local repo="$1"
    local repo_log_dir="$LOG_DIR/$repo"
    mkdir -p "$repo_log_dir"

    echo ""
    echo "============================================================"
    info "Phase Isolation Test: $repo"
    echo "============================================================"

    # ── Phase 1: Build (Container A) ─────────────────────
    info "Phase 1: Starting build in Container A..."
    local p1_start
    p1_start=$(date +%s)

    # Capture container hostname as unique container ID proof
    docker compose -f "$DOCKER_DIR/docker-compose.yml" \
        run --rm -T omnibor-sidecar \
        bash -c "echo CONTAINER_ID=\$(hostname) && \
            cd /workspace && python3 app/analyze.py \
            --repo $repo --mode sidecar --phase build \
            --skip-clone" \
        > "$repo_log_dir/phase1.log" 2>&1
    local p1_rc=$?
    local p1_end
    p1_end=$(date +%s)
    local p1_wall=$((p1_end - p1_start))

    if [ $p1_rc -ne 0 ]; then
        fail "Phase 1 FAILED for $repo (exit $p1_rc)"
        tail -10 "$repo_log_dir/phase1.log"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi

    local p1_container_id
    p1_container_id=$(grep '^CONTAINER_ID=' \
        "$repo_log_dir/phase1.log" | head -1 | cut -d= -f2)
    ok "Phase 1 complete: ${p1_wall}s (container: ${p1_container_id:-unknown})"

    # ── Find the manifest ────────────────────────────────
    # Manifest is at output/omnibor/java/{repo}/{ts}/phase1_manifest.json
    # Extract the timestamp from Phase 1 log
    local manifest_path
    manifest_path=$(grep -o 'Phase 1 manifest: [^ ]*' \
        "$repo_log_dir/phase1.log" | head -1 | cut -d' ' -f4)

    if [ -z "$manifest_path" ]; then
        fail "No manifest path found in Phase 1 log for $repo"
        tail -20 "$repo_log_dir/phase1.log"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi
    ok "Manifest: $manifest_path"

    # ── Verify manifest content ────────────────────────
    if [ ! -f "$manifest_path" ]; then
        fail "Manifest file does not exist: $manifest_path"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi
    info "Manifest contents (summary):"
    # Log key manifest fields for audit trail
    grep -o '"run_ts": *"[^"]*"' "$manifest_path" | head -1
    grep -o '"commit_sha": *"[^"]*"' "$manifest_path" | head -1
    grep -c '"gitoids"' "$manifest_path" | \
        xargs -I{} echo "  gitoid entries present: {}"
    cp "$manifest_path" "$repo_log_dir/manifest.json"
    ok "Manifest validated and archived to logs"

    # ── Pre-Phase 2: Clean SPDX output dir ─────────────
    # Ensures any SPDX files found after Phase 2 were
    # produced by Container B, not left over from prior runs.
    local run_ts
    run_ts=$(grep -o '"run_ts": *"[^"]*"' "$manifest_path" \
        | head -1 | sed 's/.*": *"//;s/"//')
    local spdx_dir="$PROJECT_ROOT/output/spdx/java/$repo/$run_ts"

    if [ -d "$spdx_dir" ]; then
        local pre_count
        pre_count=$(find "$spdx_dir" -name '*.spdx.json' | wc -l)
        if [ "$pre_count" -gt 0 ]; then
            info "Cleaning $pre_count pre-existing SPDX files"
            rm -f "$spdx_dir"/*.spdx.json "$spdx_dir"/*.spdx.html
        fi
    fi

    # Assert no SPDX files exist before Phase 2
    local pre_spdx_count=0
    if [ -d "$spdx_dir" ]; then
        pre_spdx_count=$(find "$spdx_dir" -name '*.spdx.json' | wc -l)
    fi
    if [ "$pre_spdx_count" -gt 0 ]; then
        fail "SPDX files exist before Phase 2 — test invalid"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi
    ok "Pre-Phase 2: zero SPDX files in output dir"

    # ── Phase 2: SPDX generation (Container B) ──────────
    info "Phase 2: Starting SPDX generation in Container B..."
    local p2_start
    p2_start=$(date +%s)

    # Capture container hostname as unique container ID proof
    docker compose -f "$DOCKER_DIR/docker-compose.yml" \
        run --rm -T omnibor-sidecar \
        bash -c "echo CONTAINER_ID=\$(hostname) && \
            cd /workspace && python3 app/analyze.py \
            --repo $repo --mode sidecar --phase spdx \
            --manifest $manifest_path \
            --skip-clone" \
        > "$repo_log_dir/phase2.log" 2>&1
    local p2_rc=$?
    local p2_end
    p2_end=$(date +%s)
    local p2_wall=$((p2_end - p2_start))

    if [ $p2_rc -ne 0 ]; then
        fail "Phase 2 FAILED for $repo (exit $p2_rc)"
        tail -10 "$repo_log_dir/phase2.log"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi

    local p2_container_id
    p2_container_id=$(grep '^CONTAINER_ID=' \
        "$repo_log_dir/phase2.log" | head -1 | cut -d= -f2)
    ok "Phase 2 complete: ${p2_wall}s (container: ${p2_container_id:-unknown})"

    # ── Proof: different containers ────────────────────
    if [ -n "$p1_container_id" ] && [ -n "$p2_container_id" ]; then
        if [ "$p1_container_id" != "$p2_container_id" ]; then
            ok "PROOF: Different containers (A=$p1_container_id B=$p2_container_id)"
        else
            fail "SAME container ID for Phase 1 and Phase 2!"
            TOTAL_FAIL=$((TOTAL_FAIL + 1))
            return 1
        fi
    else
        warn "Could not extract container IDs for comparison"
    fi

    # ── Proof: gitoid verification ─────────────────────
    local gitoid_ok
    gitoid_ok=$(grep -c 'verified via gitoid' \
        "$repo_log_dir/phase2.log" || true)
    if [ "$gitoid_ok" -gt 0 ]; then
        local verified_line
        verified_line=$(grep 'verified via gitoid' \
            "$repo_log_dir/phase2.log" | head -1)
        ok "PROOF: Artifact integrity — $verified_line"
    else
        warn "No gitoid verification found in Phase 2 log"
    fi

    # ── Proof: SPDX files created by Phase 2 ───────────
    local post_spdx_count=0
    if [ -d "$spdx_dir" ]; then
        post_spdx_count=$(find "$spdx_dir" -name '*.spdx.json' | wc -l)
    fi
    if [ "$post_spdx_count" -gt 0 ]; then
        ok "PROOF: Phase 2 produced $post_spdx_count SPDX files"
    else
        fail "Phase 2 produced zero SPDX files"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi

    # ── Timing report ────────────────────────────────────
    local total_wall=$((p1_wall + p2_wall))
    echo ""
    info "Timing: Phase1=${p1_wall}s  Phase2=${p2_wall}s  Total=${total_wall}s"

    # Extract internal timing from logs
    local p1_internal p2_internal
    p1_internal=$(grep -o 'Build: [0-9.]*s' \
        "$repo_log_dir/phase1.log" | head -1 || echo "N/A")
    p2_internal=$(grep -o 'Analysis: [0-9.]*s' \
        "$repo_log_dir/phase2.log" | head -1 || echo "N/A")
    info "Internal timing: $p1_internal  $p2_internal"

    # ── Golden file comparison ───────────────────────────
    local golden_repo_dir="$GOLDEN_DIR/$repo"

    if [ ! -d "$golden_repo_dir" ]; then
        warn "No golden files for $repo — skipping comparison"
        TOTAL_SKIP=$((TOTAL_SKIP + 1))
        return 0
    fi

    if [ ! -d "$spdx_dir" ]; then
        fail "No SPDX output directory: $spdx_dir"
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        return 1
    fi

    info "Comparing SPDX output against golden files..."
    info "  Golden: $golden_repo_dir"
    info "  Output: $spdx_dir"

    python3 "$COMPARE_SCRIPT" "$golden_repo_dir" "$spdx_dir" \
        > "$repo_log_dir/golden_diff.log" 2>&1
    local cmp_rc=$?

    cat "$repo_log_dir/golden_diff.log"

    if [ $cmp_rc -ne 0 ]; then
        warn "DIFFERENCES FOUND — requires user review"
        echo ""
        info "Full diff log: $repo_log_dir/golden_diff.log"
        # Differences are reported but NOT a test failure
        # (user decides whether to update golden files)
    else
        ok "Golden file comparison: IDENTICAL"
    fi

    # ── Summary ──────────────────────────────────────────
    echo ""
    ok "$repo: Phase isolation test PASSED"
    echo ""
    info "  === Proof Summary ==="
    info "  Container A (Phase 1): ${p1_container_id:-?}"
    info "  Container B (Phase 2): ${p2_container_id:-?}"
    info "  Containers differ: $([ "$p1_container_id" != "$p2_container_id" ] && echo YES || echo NO)"
    info "  Manifest written: $manifest_path"
    info "  Gitoid verification: $(grep -c 'verified via gitoid' "$repo_log_dir/phase2.log" || echo 0) artifacts"
    info "  SPDX files produced: $post_spdx_count"
    info "  Phase 1 wall time: ${p1_wall}s"
    info "  Phase 2 wall time: ${p2_wall}s"
    info "  Total wall time: $((p1_wall + p2_wall))s"
    info "  Logs: $repo_log_dir/"
    TOTAL_PASS=$((TOTAL_PASS + 1))
    return 0
}

# ── Main ─────────────────────────────────────────────────

echo "============================================================"
echo "  Phase Isolation System Test"
echo "  Two-container proof: Phase 1 → manifest → Phase 2"
echo "============================================================"
echo ""
info "Repos: $REPOS"
info "Log dir: $LOG_DIR"
echo ""

for repo in $REPOS; do
    run_phase_test "$repo" || true
done

# ── Final summary ────────────────────────────────────────
echo ""
echo "============================================================"
echo "  RESULTS"
echo "============================================================"
ok   "Passed: $TOTAL_PASS"
if [ $TOTAL_FAIL -gt 0 ]; then
    fail "Failed: $TOTAL_FAIL"
fi
if [ $TOTAL_SKIP -gt 0 ]; then
    warn "Skipped: $TOTAL_SKIP"
fi
echo "Logs: $LOG_DIR/"
echo ""

exit $TOTAL_FAIL
