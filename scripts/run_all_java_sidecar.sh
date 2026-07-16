#!/usr/bin/env bash
# Run Java repos in sidecar mode (inline hashing per config.yaml flag),
# logging each to /tmp/jval/<repo>.log. Each repo runs in its own
# ephemeral --rm container, so /tmp treedb cannot cross-contaminate.
set -uo pipefail
cd /home/ubuntu/omnibor-analysis

REPOS="${*:-bc-java checkstyle crawler4j dependency-check jsoup logging-log4j2 spring-boot}"
mkdir -p /tmp/jval
DC="docker compose -f docker/docker-compose.yml run --rm --remove-orphans omnibor-sidecar"

for r in $REPOS; do
    echo "=== $r START $(date -u +%H:%M:%S) ==="
    $DC python3 /workspace/app/analyze.py --repo "$r" --skip-clone --mode sidecar \
        > "/tmp/jval/$r.log" 2>&1
    ec=$?
    echo "=== $r EXIT=$ec $(date -u +%H:%M:%S) ==="
    grep -E "Analysis COMPLETE|CI/CD build|Build overhead|\[ERROR\]|Traceback" \
        "/tmp/jval/$r.log" | tail -n 6
done
echo "=== ALL DONE $(date -u +%H:%M:%S) ==="
