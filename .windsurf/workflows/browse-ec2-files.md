---
description: Browse and manage files on EC2 via web-based file browser
---

# Browse EC2 Files

Launch a web-based file browser (filebrowser) on the EC2 build host,
tunneled securely via SSH. Allows browsing, downloading, and deleting
files in the `output/` directory.

## Prerequisites

- EC2 instance must be running
- SSH access to `ubuntu@<EC2_IP>` must work
- `filebrowser` must be installed on EC2 (installed once, persists)

## Steps

1. **Get EC2 IP** from AWS:
   ```bash
   aws ec2 describe-instances \
     --instance-ids <INSTANCE_ID> \
     --region us-west-1 --profile ted-admin \
     --query 'Reservations[0].Instances[0].PublicIpAddress' \
     --output text
   ```

2. **Fix file ownership** (Docker creates files as root):
   ```bash
   ssh ubuntu@<EC2_IP> "sudo chown -R ubuntu:ubuntu ~/bisbom-gen/output/"
   ```

3. **Start filebrowser** on EC2 (port 8080, no auth, serving output/):
   ```bash
   ssh ubuntu@<EC2_IP> "pkill filebrowser 2>/dev/null; rm -f /tmp/filebrowser.db"
   ssh ubuntu@<EC2_IP> "filebrowser config init -d /tmp/filebrowser.db -r /home/ubuntu/bisbom-gen/output"
   ssh ubuntu@<EC2_IP> "filebrowser users add admin adminadmin12 --perm.admin -d /tmp/filebrowser.db"
   ssh ubuntu@<EC2_IP> "nohup filebrowser -d /tmp/filebrowser.db -p 8080 -a 0.0.0.0 > /tmp/filebrowser.log 2>&1 &"
   ```

4. **Open SSH tunnel** (port 8080 is not exposed in the security group):
   ```bash
   ssh -f -N -L 8090:localhost:8080 ubuntu@<EC2_IP>
   ```

5. **Open browser** at `http://localhost:8090`
   - Login: `admin` / `adminadmin12`
   - Browse, download, or delete files/folders

6. **When done**, shut everything down:
   ```bash
   ssh ubuntu@<EC2_IP> "pkill filebrowser; rm -f /tmp/filebrowser.db"
   pkill -f "ssh -f -N -L 8090:localhost:8080"
   ```

## Notes

- filebrowser is installed at `/usr/local/bin/filebrowser` on EC2
  (installed via `curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | sudo bash`)
- The SSH tunnel avoids opening port 8080 in the security group
- The database is ephemeral (`/tmp/filebrowser.db`) — no persistent state
- Always fix ownership before starting if Docker has created new files
