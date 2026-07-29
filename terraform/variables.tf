# =============================================================================
# Variables — Override via terraform.tfvars (gitignored)
# =============================================================================

variable "aws_profile" {
  description = "AWS CLI profile name (from ~/.aws/credentials, populated by duo-sso)"
  type        = string
  # No default — each developer must set this in terraform.tfvars
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-west-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "bisbom"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type. Must be x86_64 (NOT Graviton/ARM).
    Recommended options (see docs/aws-ec2-migration-recommendation.md):
      t3.medium   — 2 vCPU, 4 GB RAM, ~$0.042/hr (budget)
      t3.large    — 2 vCPU, 8 GB RAM, ~$0.083/hr (comfortable)
      c6i.xlarge  — 4 vCPU, 8 GB RAM, ~$0.170/hr (performance, recommended)
  EOT
  type        = string
  default     = "c6i.xlarge"
}

variable "ebs_volume_size_gb" {
  description = "Root EBS volume size in GB (gp3)"
  type        = number
  default     = 50
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for EC2 access"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "repo_url" {
  description = "Git URL for bisbom-gen repository (HTTPS or SSH)"
  type        = string
  default     = "https://github.com/tedg-dev/bisbom-gen.git"
}
