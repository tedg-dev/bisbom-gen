#!/bin/bash
# =============================================================================
# EC2 User Data — Bootstrap script for OmniBOR build host
# =============================================================================
# Runs once on first boot. Installs Docker, clones repo, builds container.
# Cloud-init logs: /var/log/cloud-init-output.log
#
# NOTE: Cisco VPN blocks port 22 to AWS IPs. SSH is configured on port 443.
# =============================================================================

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== OmniBOR build host bootstrap starting ==="

# --- Configure SSH to also listen on port 443 ---
# Cisco VPN blocks port 22 to AWS IPs. Use a drop-in config file
# to avoid conflicting with the default sshd_config.
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/omnibor-ports.conf <<'EOF'
# Listen on both 22 (off-VPN) and 443 (on Cisco VPN)
Port 22
Port 443
EOF
# Comment out any Port directive in the main config to avoid conflicts
sed -i 's/^Port /#Port /' /etc/ssh/sshd_config
systemctl restart sshd
echo "=== SSH configured on ports 22 and 443 ==="

# --- System updates ---
apt-get update -y
apt-get upgrade -y

# --- Install Docker ---
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu

# --- Install docker-compose (standalone v2) ---
DOCKER_COMPOSE_VERSION="v2.29.2"
curl -fsSL "https://github.com/docker/compose/releases/download/$${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# --- Install git and build essentials ---
apt-get install -y git rsync

# --- Clone omnibor-analysis repo ---
# If the repo is private, clone will fail here. User can clone manually via SSH.
if sudo -u ubuntu git clone ${repo_url} /home/ubuntu/omnibor-analysis 2>/dev/null; then
  echo "=== Repo cloned, building Docker image ==="
  cd /home/ubuntu/omnibor-analysis
  sudo -u ubuntu docker-compose -f docker/docker-compose.yml build
else
  echo "=== Repo clone failed (private repo?) — user must clone manually ==="
  echo "=== SSH in and run: git clone <repo_url> ~/omnibor-analysis ==="
fi

echo "=== OmniBOR build host bootstrap complete ==="
echo "=== Check cloud-init-output.log for details ==="
