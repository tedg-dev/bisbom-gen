#!/usr/bin/env bash
# cisco-lab-proxy-setup.sh — One-time proxy setup for Docker on Cisco lab/datacenter hosts
#
# Applies to any on-prem Cisco host behind proxy-wsa.esl.cisco.com
# (e.g., coronaXXX.cisco.com or similar lab/datacenter machines).
#
# Usage:
#   bash cisco-lab-proxy-setup.sh           # interactive, prompts before changes
#   bash cisco-lab-proxy-setup.sh --check   # verify-only, no changes
#
# What it does:
#   1. Checks shell proxy env vars for the common https:// vs http:// mistake
#   2. Verifies Docker daemon proxy config
#   3. Checks Docker storage location (warns if on small root partition)
#   4. Creates docker-compose.override.yml with proxy env vars
#   5. Creates Maven proxy settings.xml for Java builds
#
# Proxy: proxy-wsa.esl.cisco.com:80 (HTTP, not HTTPS)
# Example host: corona210.cisco.com (CentOS 7 x86_64)

set -euo pipefail

PROXY_HOST="proxy-wsa.esl.cisco.com"
PROXY_PORT="80"
PROXY_URL="http://${PROXY_HOST}:${PROXY_PORT}"
NO_PROXY="localhost,.cisco.com,127.0.0.1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CHECK_ONLY=false
if [[ "${1:-}" == "--check" ]]; then
    CHECK_ONLY=true
fi

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "       $1"; }

echo "============================================"
echo "  Cisco Lab/Datacenter Proxy Config Check"
echo "  Host: $(hostname)"
echo "  Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================"
echo

# --- Check 1: Shell proxy env vars ---
echo "--- 1. Shell proxy environment variables ---"
if [[ "${https_proxy:-}" == https://* ]]; then
    fail "https_proxy uses https:// scheme (should be http://)"
    info "Current:  https_proxy=${https_proxy}"
    info "Correct:  https_proxy=${PROXY_URL}"
    info "Fix: Add to ~/.bashrc:"
    info "  export https_proxy=${PROXY_URL}"
else
    if [[ -n "${https_proxy:-}" ]]; then
        pass "https_proxy=${https_proxy}"
    else
        warn "https_proxy is not set"
        info "Set in ~/.bashrc: export https_proxy=${PROXY_URL}"
    fi
fi

if [[ -n "${http_proxy:-}" ]]; then
    pass "http_proxy=${http_proxy}"
else
    warn "http_proxy is not set"
fi
echo

# --- Check 2: Docker daemon proxy ---
echo "--- 2. Docker daemon proxy ---"
DOCKER_PROXY_CONF="/etc/systemd/system/docker.service.d/http-proxy.conf"
if [[ -f "$DOCKER_PROXY_CONF" ]]; then
    if grep -q "http://${PROXY_HOST}" "$DOCKER_PROXY_CONF"; then
        pass "Docker daemon proxy configured correctly"
    else
        warn "Docker daemon proxy exists but may have wrong values"
        info "Check: cat $DOCKER_PROXY_CONF"
    fi
else
    fail "No Docker daemon proxy config found"
    info "Create $DOCKER_PROXY_CONF with:"
    info '  [Service]'
    info "  Environment=\"HTTPS_PROXY=${PROXY_URL}/\""
    info "  Environment=\"HTTP_PROXY=${PROXY_URL}/\""
    info "  Environment=\"NO_PROXY=${NO_PROXY}\""
fi
echo

# --- Check 3: Docker storage ---
echo "--- 3. Docker storage location ---"
if command -v docker &>/dev/null; then
    DOCKER_ROOT=$(docker info 2>/dev/null | grep "Docker Root Dir" | awk '{print $NF}')
    if [[ -n "$DOCKER_ROOT" ]]; then
        ROOT_AVAIL=$(df -BG "$DOCKER_ROOT" 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G')
        if [[ "$ROOT_AVAIL" -lt 50 ]]; then
            warn "Docker Root Dir: $DOCKER_ROOT (${ROOT_AVAIL}G free — may be too small)"
            info "Consider moving to /home: see docs/guides/cisco-lab-proxy.md section 4"
        else
            pass "Docker Root Dir: $DOCKER_ROOT (${ROOT_AVAIL}G free)"
        fi
    else
        warn "Could not determine Docker Root Dir (is Docker running?)"
    fi
else
    fail "Docker is not installed"
fi
echo

# --- Check 4: docker-compose.override.yml ---
echo "--- 4. docker-compose.override.yml ---"
if [[ "$CHECK_ONLY" == true ]]; then
    info "Skipping file creation (--check mode)"
else
    OVERRIDE_DIR="${2:-.}"
    OVERRIDE_FILE="${OVERRIDE_DIR}/docker/docker-compose.override.yml"
    if [[ -f "$OVERRIDE_FILE" ]]; then
        pass "Override file exists: $OVERRIDE_FILE"
    else
        echo -n "Create $OVERRIDE_FILE? [y/N] "
        read -r REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            mkdir -p "$(dirname "$OVERRIDE_FILE")"
            cat > "$OVERRIDE_FILE" << YAML
services:
  bisbom-env:
    environment:
      - HTTP_PROXY=${PROXY_URL}
      - HTTPS_PROXY=${PROXY_URL}
      - http_proxy=${PROXY_URL}
      - https_proxy=${PROXY_URL}
      - NO_PROXY=${NO_PROXY}
    volumes:
      - ../docker/maven-proxy-settings.xml:/root/.m2/settings.xml:ro
YAML
            pass "Created $OVERRIDE_FILE"
        else
            info "Skipped"
        fi
    fi
fi
echo

# --- Check 5: Maven proxy settings ---
echo "--- 5. Maven proxy settings.xml ---"
if [[ "$CHECK_ONLY" == true ]]; then
    info "Skipping file creation (--check mode)"
else
    MAVEN_SETTINGS="${2:-.}/docker/maven-proxy-settings.xml"
    if [[ -f "$MAVEN_SETTINGS" ]]; then
        pass "Maven proxy settings exists: $MAVEN_SETTINGS"
    else
        echo -n "Create $MAVEN_SETTINGS? [y/N] "
        read -r REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            mkdir -p "$(dirname "$MAVEN_SETTINGS")"
            cat > "$MAVEN_SETTINGS" << 'XML'
<settings>
  <proxies>
    <proxy>
      <id>cisco-proxy-https</id>
      <active>true</active>
      <protocol>https</protocol>
      <host>proxy-wsa.esl.cisco.com</host>
      <port>80</port>
      <nonProxyHosts>localhost|*.cisco.com</nonProxyHosts>
    </proxy>
    <proxy>
      <id>cisco-proxy-http</id>
      <active>true</active>
      <protocol>http</protocol>
      <host>proxy-wsa.esl.cisco.com</host>
      <port>80</port>
      <nonProxyHosts>localhost|*.cisco.com</nonProxyHosts>
    </proxy>
  </proxies>
</settings>
XML
            pass "Created $MAVEN_SETTINGS"
        else
            info "Skipped"
        fi
    fi
fi
echo

echo "============================================"
echo "  Check complete. See docs/guides/cisco-lab-proxy.md"
echo "  for the full reference guide."
echo "============================================"
