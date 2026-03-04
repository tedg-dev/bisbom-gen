# =============================================================================
# Outputs — Displayed after terraform apply
# =============================================================================

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.omnibor_build.id
}

output "elastic_ip" {
  description = "Elastic IP address (stable across stop/start)"
  value       = aws_eip.omnibor.public_ip
}

output "ami_id" {
  description = "AMI used for the instance"
  value       = data.aws_ami.ubuntu.id
}

output "ami_name" {
  description = "AMI name (includes date)"
  value       = data.aws_ami.ubuntu.name
}

output "instance_type" {
  description = "EC2 instance type"
  value       = aws_instance.omnibor_build.instance_type
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.omnibor.id
}

output "ssh_command" {
  description = "SSH command to connect"
  value       = "ssh -i ${var.ssh_public_key_path} ubuntu@${aws_eip.omnibor.public_ip}"
}

output "ssh_config_entry" {
  description = "Add this to ~/.ssh/config"
  value       = <<-EOT

    Host omnibor-build
        HostName ${aws_eip.omnibor.public_ip}
        User ubuntu
        IdentityFile ~/.ssh/id_ed25519

  EOT
}

output "power_commands" {
  description = "AWS CLI commands for power management"
  value       = <<-EOT

    # Check status
    aws ec2 describe-instances --profile ${var.aws_profile} --instance-ids ${aws_instance.omnibor_build.id} --query 'Reservations[].Instances[].{State:State.Name,IP:PublicIpAddress}' --output table --no-cli-pager

    # Stop (saves money, keeps EBS)
    aws ec2 stop-instances --profile ${var.aws_profile} --instance-ids ${aws_instance.omnibor_build.id} --no-cli-pager

    # Start
    aws ec2 start-instances --profile ${var.aws_profile} --instance-ids ${aws_instance.omnibor_build.id} --no-cli-pager

  EOT
}
