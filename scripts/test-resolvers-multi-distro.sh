#!/usr/bin/env bash
# Multi-distro resolver integration tests.
#
# Runs the resolver integration test suite inside Ubuntu, Fedora, and
# Alpine containers to verify DpkgResolver, RpmResolver, and ApkResolver
# against real package manager binaries.
#
# Usage:
#   scripts/test-resolvers-multi-distro.sh          # all distros
#   scripts/test-resolvers-multi-distro.sh ubuntu    # single distro
#   scripts/test-resolvers-multi-distro.sh fedora
#   scripts/test-resolvers-multi-distro.sh alpine
#
# Requirements:
#   - Docker installed and running
#   - Run from the project root directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
SKIPPED=0

run_distro() {
    local distro="$1"
    local image="$2"
    local marker="$3"
    local setup_cmd="$4"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${YELLOW}Testing ${distro}${NC} (${image})"
    echo "  Marker: ${marker}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if ! docker image inspect "$image" > /dev/null 2>&1; then
        echo "  Pulling ${image}..."
        docker pull --platform linux/amd64 "$image" || {
            echo -e "  ${RED}SKIP${NC}: Failed to pull ${image}"
            SKIPPED=$((SKIPPED + 1))
            return 0
        }
    fi

    # Run tests inside the container
    if docker run --rm \
        --platform linux/amd64 \
        -v "${PROJECT_ROOT}":/workspace:ro \
        -w /workspace \
        "$image" \
        bash -c "
            ${setup_cmd} && \
            pip3 install --quiet --break-system-packages \
                -r requirements.txt 2>/dev/null || \
            pip3 install --quiet -r requirements.txt && \
            python3 -m pytest tests/test_resolver_integration.py \
                -m ${marker} -v --tb=short 2>&1
        "; then
        echo -e "  ${GREEN}PASS${NC}: ${distro}"
        PASSED=$((PASSED + 1))
    else
        echo -e "  ${RED}FAIL${NC}: ${distro}"
        FAILED=$((FAILED + 1))
    fi
}

# Distro definitions
run_ubuntu() {
    run_distro "Ubuntu 22.04" "ubuntu:22.04" "requires_dpkg" \
        "apt-get update -qq && apt-get install -y -qq python3 python3-pip > /dev/null 2>&1"
}

run_fedora() {
    run_distro "Fedora 39" "fedora:39" "requires_rpm" \
        "dnf install -y -q python3 python3-pip > /dev/null 2>&1"
}

run_alpine() {
    run_distro "Alpine 3.18" "alpine:3.18" "requires_apk" \
        "apk add --quiet python3 py3-pip > /dev/null 2>&1"
}

# Main
echo "╔══════════════════════════════════════════════════╗"
echo "║  Multi-Distro Resolver Integration Tests        ║"
echo "╚══════════════════════════════════════════════════╝"

# Check Docker is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}ERROR${NC}: Docker not found. Install Docker first."
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}ERROR${NC}: Docker daemon not running."
    exit 1
fi

# Run specified distro or all
TARGET="${1:-all}"

case "$TARGET" in
    ubuntu)  run_ubuntu ;;
    fedora)  run_fedora ;;
    alpine)  run_alpine ;;
    all)
        run_ubuntu
        run_fedora
        run_alpine
        ;;
    *)
        echo "Unknown distro: ${TARGET}"
        echo "Usage: $0 [ubuntu|fedora|alpine|all]"
        exit 1
        ;;
esac

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  RESULTS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  ${GREEN}Passed${NC}: ${PASSED}"
echo -e "  ${RED}Failed${NC}: ${FAILED}"
if [ "$SKIPPED" -gt 0 ]; then
    echo -e "  ${YELLOW}Skipped${NC}: ${SKIPPED}"
fi
echo ""

if [ "$FAILED" -gt 0 ]; then
    echo -e "${RED}OVERALL: FAIL${NC}"
    exit 1
else
    echo -e "${GREEN}OVERALL: PASS${NC}"
    exit 0
fi
