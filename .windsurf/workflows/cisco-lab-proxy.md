---
description: Configure proxy for Docker builds and runs on Cisco lab hosts behind WSA proxy
---

# Cisco Lab Proxy Configuration

Use this workflow when setting up or troubleshooting Docker-based workflows
on any Cisco lab or datacenter host behind `proxy-wsa.esl.cisco.com`. This
applies to any on-prem host routing external traffic through the Cisco WSA
proxy (e.g., `coronaXXX.cisco.com` hosts). The full reference guide is at
`docs/guides/cisco-lab-proxy.md`.

## When to use

- First-time Docker setup on a Cisco lab or datacenter host
- Docker build fails with "TLS handshake" or "Service Unavailable" errors
- Maven fails with "Connect timed out" to `repo.maven.apache.org`
- `apt-get update` inside a container returns empty package lists
- Docker fills the root partition during builds

## 1. Verify shell proxy (critical first check)

```bash
ssh <HOST> "echo https_proxy=\$https_proxy"
```

If it shows `https://proxy-wsa...` (note `https://`), it is **wrong**.
The proxy speaks HTTP on port 80. Fix by overriding in commands or
updating the host's `~/.bashrc`:

```bash
# Correct values
export http_proxy=http://proxy-wsa.esl.cisco.com:80
export https_proxy=http://proxy-wsa.esl.cisco.com:80
export no_proxy=localhost,.cisco.com,127.0.0.1
```

## 2. Docker image builds

Always pass proxy build args AND override `HTTPS_PROXY` in the shell:

```bash
HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  docker compose -f docker/docker-compose.yml build \
  --build-arg HTTP_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  --build-arg HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  --build-arg NO_PROXY=localhost,.cisco.com,127.0.0.1
```

## 3. Docker container runs (git, curl, Go, Rust)

Create `docker/docker-compose.override.yml` on the host:

```yaml
services:
  omnibor-env:
    environment:
      - HTTP_PROXY=http://proxy-wsa.esl.cisco.com:80
      - HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80
      - http_proxy=http://proxy-wsa.esl.cisco.com:80
      - https_proxy=http://proxy-wsa.esl.cisco.com:80
      - NO_PROXY=localhost,.cisco.com,127.0.0.1
    volumes:
      - ../docker/maven-proxy-settings.xml:/root/.m2/settings.xml:ro
```

Then always include both compose files:

```bash
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.override.yml \
  run --rm omnibor-env <COMMAND>
```

## 4. Maven / Java (special handling required)

Java does NOT read `http_proxy` env vars. Proxy must be configured
in Maven's `settings.xml`. The project includes
`docker/maven-proxy-settings.xml` — mount it as shown in step 3.

## 5. Docker storage (CentOS 7 VFS workaround)

If Docker fills the root partition, move data to `/home`:

```bash
sudo systemctl stop docker
echo '{"data-root": "/home/docker"}' | sudo tee /etc/docker/daemon.json
sudo rm -rf /var/lib/docker
sudo systemctl start docker
```

## 6. Verify everything works

```bash
# Container can reach the internet
docker compose -f docker/docker-compose.yml \
  -f docker/docker-compose.override.yml \
  run --rm omnibor-env bash -c \
  'curl -sI https://github.com | head -1'

# Maven Central reachable
docker compose -f docker/docker-compose.yml \
  -f docker/docker-compose.override.yml \
  run --rm omnibor-env bash -c \
  'mvn --version 2>&1 | head -1'
```

## Proxy values

| Key | Value |
|-----|-------|
| **Host** | `proxy-wsa.esl.cisco.com` |
| **Port** | `80` |
| **Scheme** | `http://` (NOT `https://`) |
| **No-proxy** | `localhost,.cisco.com,127.0.0.1` |
