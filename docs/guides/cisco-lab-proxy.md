# Cisco Lab / Datacenter Host Proxy Configuration Guide

This guide documents the proxy configuration required to run Docker-based
build workflows on Cisco lab or datacenter hosts behind the WSA corporate
proxy. It applies to **any on-prem host** that routes external traffic
through `proxy-wsa.esl.cisco.com` — not just a specific machine.

Originally developed and verified on `corona210.cisco.com` (CentOS 7,
x86_64) as a representative example.

## Quick Reference

| Service | Proxy mechanism | Config location |
|---------|----------------|-----------------|
| Shell (git, curl, wget) | `http_proxy` / `https_proxy` env vars | `~/.bashrc` or `/etc/profile.d/` |
| Docker daemon (image pulls) | systemd env + `daemon.json` | `/etc/systemd/system/docker.service.d/` |
| Docker build (apt, wget inside) | `--build-arg HTTP_PROXY=...` | CLI or `docker-compose.override.yml` |
| Docker run (git, curl inside) | `-e http_proxy=...` | CLI or `docker-compose.override.yml` |
| Maven / Java (JVM) | `settings.xml` `<proxies>` block | `~/.m2/settings.xml` or volume mount |
| Go modules | `http_proxy` / `https_proxy` env vars | Inherited from container env |
| Rust / Cargo | `http_proxy` / `https_proxy` env vars | Inherited from container env |

## Known Pitfalls

### 1. Shell `https_proxy` uses wrong protocol scheme

The default CentOS profile on some lab hosts sets:

```bash
# WRONG — causes "first record does not look like a TLS handshake"
https_proxy=https://proxy-wsa.esl.cisco.com:80
```

The proxy at port 80 speaks **HTTP**, not HTTPS. Fix:

```bash
# CORRECT
https_proxy=http://proxy-wsa.esl.cisco.com:80
```

This affects Docker image pulls and any tool that reads `https_proxy`.

### 2. Docker daemon proxy vs shell proxy

The Docker daemon has its own proxy config at
`/etc/systemd/system/docker.service.d/http-proxy.conf`, which is correct
(`http://`). However, Docker BuildKit inherits **shell** env vars and
they override the daemon config when the shell has the wrong `https://`
scheme.

**Always override** `HTTPS_PROXY` on the command line when running
`docker compose build`:

```bash
HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  docker compose build \
  --build-arg HTTP_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  --build-arg HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80 \
  --build-arg NO_PROXY=localhost,.cisco.com,127.0.0.1
```

### 3. Maven / JVM ignores shell proxy env vars

Java does **not** read `http_proxy` or `https_proxy` environment
variables. Maven requires proxy configuration via one of:

- **`~/.m2/settings.xml`** (recommended — works for all Maven commands)
- **`JAVA_TOOL_OPTIONS`** env var with `-D` flags (less reliable)
- **`MAVEN_OPTS`** env var (Maven-specific)

Recommended `~/.m2/settings.xml`:

```xml
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
```

For Docker containers, mount this file as a volume:

```yaml
# docker-compose.override.yml
services:
  my-service:
    volumes:
      - ./maven-proxy-settings.xml:/root/.m2/settings.xml:ro
```

### 4. Docker VFS storage driver fills root partition

CentOS 7 uses the VFS storage driver by default, which copies the
entire filesystem for each Docker layer. A multi-stage Dockerfile can
easily fill a 50 GB root partition.

**Solution:** Move Docker data to a larger partition:

```bash
sudo systemctl stop docker
echo '{"data-root": "/home/docker"}' | sudo tee /etc/docker/daemon.json
sudo rm -rf /var/lib/docker
sudo systemctl start docker
docker info 2>/dev/null | grep "Docker Root Dir"
```

### 5. Container-created files are owned by root

Docker containers run as root by default. Files created in mounted
volumes (e.g., cloned repos, build artifacts) are owned by `root:root`
and cannot be deleted by the host user without `sudo` or using the
container:

```bash
# Delete via container (no sudo needed)
docker compose run --rm my-service rm -rf /workspace/repos/my-repo

# Or use sudo on the host
sudo rm -rf repos/my-repo
```

## Complete `docker-compose.override.yml` Template

Create this file alongside your `docker-compose.yml` for any project
that needs outbound network access from containers on Cisco lab hosts:

```yaml
services:
  omnibor-env:  # change to match your service name
    environment:
      - HTTP_PROXY=http://proxy-wsa.esl.cisco.com:80
      - HTTPS_PROXY=http://proxy-wsa.esl.cisco.com:80
      - http_proxy=http://proxy-wsa.esl.cisco.com:80
      - https_proxy=http://proxy-wsa.esl.cisco.com:80
      - NO_PROXY=localhost,.cisco.com,127.0.0.1
    volumes:
      - ./maven-proxy-settings.xml:/root/.m2/settings.xml:ro
```

## Proxy Details

| Field | Value |
|-------|-------|
| **Proxy host** | `proxy-wsa.esl.cisco.com` |
| **Proxy port** | `80` |
| **Protocol** | HTTP (not HTTPS) |
| **No-proxy** | `localhost,.cisco.com,127.0.0.1` |
| **Example host** | `corona210.cisco.com` (CentOS 7 x86_64) |
| **Date verified** | 2026-04-30 |

## Verification Commands

```bash
# 1. Verify shell proxy is correct
echo $https_proxy  # should show http:// not https://

# 2. Verify Docker daemon proxy
cat /etc/systemd/system/docker.service.d/http-proxy.conf

# 3. Verify Docker data location
docker info 2>/dev/null | grep "Docker Root Dir"

# 4. Verify outbound from container
docker run --rm -e https_proxy=http://proxy-wsa.esl.cisco.com:80 \
  ubuntu:22.04 bash -c 'apt-get update 2>&1 | head -5'

# 5. Verify Maven Central reachable from container
docker run --rm -e https_proxy=http://proxy-wsa.esl.cisco.com:80 \
  ubuntu:22.04 bash -c \
  'apt-get update -qq && apt-get install -qq -y curl && \
   curl -x http://proxy-wsa.esl.cisco.com:80 -sI \
   https://repo.maven.apache.org/maven2/ | head -3'
```
