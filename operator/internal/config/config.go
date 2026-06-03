package config

import (
	"fmt"
	"os"
)

// LaunchMode determines how Phase 2 containers are launched.
//
//   - "docker" (default): Uses local Docker daemon via `docker run`.
//     Best for local development, testing, and EC2 hosts with Docker installed.
//     Requires Docker socket access.
//
//   - "ecs": Uses AWS ECS RunTask API to launch a Fargate (or EC2) task.
//     Best for production deployments where the operator itself runs in
//     ECS/Fargate and cannot access a Docker daemon. Each Phase 2 job runs
//     as an independent ECS task with its own compute allocation.
type LaunchMode string

const (
	LaunchModeDocker LaunchMode = "docker"
	LaunchModeECS    LaunchMode = "ecs"
)

// Config holds all operator configuration, loaded from environment variables.
type Config struct {
	// Common
	SQSQueueURL  string
	S3Bucket     string
	SidecarImage string
	WorkDir      string
	LaunchMode   LaunchMode

	// SPDX indexing (optional — skipped if empty)
	DynamoTable      string // DynamoDB table name for SPDX index records
	GraphTable       string // DynamoDB table for dependency graph (adjacency list)
	SbomTreeQueueURL string // SQS queue URL for sbom-tree generation requests

	// HTTP API (optional — skipped if DynamoTable is empty)
	APIAddr string // Listen address for REST API (default: ":8080")

	// ECS-specific (required when LAUNCH_MODE=ecs)
	ECSCluster        string // ECS cluster ARN or name
	ECSTaskDefinition string // Task definition family or ARN (e.g., "omnibor-phase2")
	ECSSubnets        string // Comma-separated subnet IDs for awsvpc networking
	ECSSecurityGroup  string // Security group ID for the Phase 2 task
}

// Load reads configuration from environment variables.
//
// Required (all modes):
//   - SQS_QUEUE_URL, S3_BUCKET
//
// Optional (all modes):
//   - SIDECAR_IMAGE (default: ghcr.io/tedg-dev/omnibor-sidecar:latest)
//   - WORK_DIR (default: /tmp/operator)
//   - LAUNCH_MODE (default: "docker", or "ecs" for production)
//   - DYNAMO_TABLE (optional: DynamoDB table for SPDX indexing; skipped if empty)
//   - DYNAMO_GRAPH_TABLE (optional: DynamoDB table for dependency graph)
//   - SQS_SBOM_TREE_URL (optional: SQS queue for sbom-tree generation)
//   - API_ADDR (optional: HTTP API listen address; default ":8080")
//
// Required when LAUNCH_MODE=ecs:
//   - ECS_CLUSTER, ECS_TASK_DEFINITION, ECS_SUBNETS, ECS_SECURITY_GROUP
func Load() (*Config, error) {
	queueURL := os.Getenv("SQS_QUEUE_URL")
	if queueURL == "" {
		return nil, fmt.Errorf("SQS_QUEUE_URL is required")
	}

	bucket := os.Getenv("S3_BUCKET")
	if bucket == "" {
		return nil, fmt.Errorf("S3_BUCKET is required")
	}

	image := os.Getenv("SIDECAR_IMAGE")
	if image == "" {
		image = "ghcr.io/tedg-dev/omnibor-sidecar:latest"
	}

	workDir := os.Getenv("WORK_DIR")
	if workDir == "" {
		workDir = "/tmp/operator"
	}

	mode := LaunchMode(os.Getenv("LAUNCH_MODE"))
	if mode == "" {
		mode = LaunchModeDocker
	}
	if mode != LaunchModeDocker && mode != LaunchModeECS {
		return nil, fmt.Errorf("LAUNCH_MODE must be 'docker' or 'ecs', got %q", mode)
	}

	cfg := &Config{
		SQSQueueURL:      queueURL,
		S3Bucket:         bucket,
		SidecarImage:     image,
		WorkDir:          workDir,
		LaunchMode:       mode,
		DynamoTable:      os.Getenv("DYNAMO_TABLE"),
		GraphTable:       os.Getenv("DYNAMO_GRAPH_TABLE"),
		SbomTreeQueueURL: os.Getenv("SQS_SBOM_TREE_URL"),
		APIAddr:          os.Getenv("API_ADDR"),
	}

	if cfg.APIAddr == "" {
		cfg.APIAddr = ":8080"
	}

	// Validate ECS-specific config
	if mode == LaunchModeECS {
		cfg.ECSCluster = os.Getenv("ECS_CLUSTER")
		cfg.ECSTaskDefinition = os.Getenv("ECS_TASK_DEFINITION")
		cfg.ECSSubnets = os.Getenv("ECS_SUBNETS")
		cfg.ECSSecurityGroup = os.Getenv("ECS_SECURITY_GROUP")

		if cfg.ECSCluster == "" {
			return nil, fmt.Errorf("ECS_CLUSTER is required when LAUNCH_MODE=ecs")
		}
		if cfg.ECSTaskDefinition == "" {
			return nil, fmt.Errorf("ECS_TASK_DEFINITION is required when LAUNCH_MODE=ecs")
		}
		if cfg.ECSSubnets == "" {
			return nil, fmt.Errorf("ECS_SUBNETS is required when LAUNCH_MODE=ecs")
		}
		if cfg.ECSSecurityGroup == "" {
			return nil, fmt.Errorf("ECS_SECURITY_GROUP is required when LAUNCH_MODE=ecs")
		}
	}

	return cfg, nil
}
