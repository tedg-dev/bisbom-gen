# =============================================================================
# OmniBOR Analysis — AWS EC2 Build Host
# =============================================================================
# Provisions an EC2 instance for running OmniBOR build interception analysis.
# See docs/aws-ec2-migration-recommendation.md for sizing rationale.
#
# Authentication: Uses duo-sso STS credentials via AWS profile.
# Sessions expire every 1 hour — re-authenticate before running terraform.
#
# Usage:
#   terraform init                          # one-time
#   terraform plan  -out=tfplan             # review changes
#   terraform apply tfplan                  # apply changes
#   terraform destroy                       # tear down everything
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

# ---------------------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------------------

# Latest Ubuntu 22.04 LTS x86_64 AMI from Canonical
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# Current public IP for SSH security group rule
data "http" "my_ip" {
  url = "https://checkip.amazonaws.com"
}

# ---------------------------------------------------------------------------
# SSH Key Pair
# ---------------------------------------------------------------------------

resource "aws_key_pair" "omnibor" {
  key_name   = "${var.project_name}-key"
  public_key = file(var.ssh_public_key_path)

  tags = {
    Name    = "${var.project_name}-key"
    Project = var.project_name
  }
}

# ---------------------------------------------------------------------------
# Security Group
# ---------------------------------------------------------------------------

resource "aws_security_group" "omnibor" {
  name        = "${var.project_name}-sg"
  description = "SSH access for OmniBOR build host"

  # SSH on port 22 (standard — works off-VPN)
  ingress {
    description = "SSH-22"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
  }

  # SSH on port 443 (Cisco VPN blocks port 22 to AWS IPs)
  ingress {
    description = "SSH-443"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
  }

  # All outbound (apt, git, Docker Hub, etc.)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-sg"
    Project = var.project_name
  }
}

# ---------------------------------------------------------------------------
# EC2 Instance
# ---------------------------------------------------------------------------

resource "aws_instance" "omnibor_build" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.omnibor.key_name
  vpc_security_group_ids = [aws_security_group.omnibor.id]

  root_block_device {
    volume_size           = var.ebs_volume_size_gb
    volume_type           = "gp3"
    iops                  = 3000
    throughput            = 125
    delete_on_termination = true
  }

  user_data = file("${path.module}/user-data.sh")

  tags = {
    Name    = "${var.project_name}-build"
    Project = var.project_name
  }
}

# ---------------------------------------------------------------------------
# Elastic IP (persists across stop/start)
# ---------------------------------------------------------------------------

resource "aws_eip" "omnibor" {
  instance = aws_instance.omnibor_build.id
  domain   = "vpc"

  tags = {
    Name    = "${var.project_name}-eip"
    Project = var.project_name
  }
}
