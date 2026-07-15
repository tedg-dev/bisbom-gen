package config

import (
	"fmt"
	"os"
	"strings"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/oidc"
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

	// Presigned URL broker (optional — skipped if DatabaseURL is empty)
	DatabaseURL      string       // Postgres connection string for repo_whitelist
	OIDC             *oidc.Config // OIDC validation settings
	WhitelistEnabled bool         // When false, skip repo whitelist check (OIDC only)

	// ECS-specific (required when LAUNCH_MODE=ecs)
	ECSCluster        string // ECS cluster ARN or name
	ECSTaskDefinition string // Task definition family or ARN (e.g., "omnibor-phase2")
	ECSSubnets        string // Comma-separated subnet IDs for awsvpc networking
	ECSSecurityGroup  string // Security group ID for the Phase 2 task
}

// Load reads configuration from environment variables.
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
	bucket := os.Getenv("S3_BUCKET")

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

	cfg.DatabaseURL = os.Getenv("DATABASE_URL")

	// Whitelist mode: default true for backward compatibility
	wlEnv := os.Getenv("WHITELIST_ENABLED")
	cfg.WhitelistEnabled = wlEnv == "" || wlEnv == "true" || wlEnv == "1"

	// Parse OIDC config from environment
	cfg.OIDC = parseOIDCConfig()

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

// parseOIDCConfig reads OIDC settings from environment variables.
//
// Environment variables:
//   - OIDC_AUDIENCE: expected audience claim (optional)
//   - OIDC_ISSUERS: comma-separated "url|type" pairs, e.g.
//     "https://token.actions.githubusercontent.com|github.com,https://ghe.example.com/_services/token|ghe"
//   - OIDC_ENTERPRISE_ALLOWLIST: comma-separated enterprise slugs
//   - OIDC_ORG_ALLOWLIST: comma-separated GitHub org names
func parseOIDCConfig() *oidc.Config {
	cfg := &oidc.Config{
		Audience: os.Getenv("OIDC_AUDIENCE"),
	}

	if issuers := os.Getenv("OIDC_ISSUERS"); issuers != "" {
		for _, pair := range strings.Split(issuers, ",") {
			parts := strings.SplitN(strings.TrimSpace(pair), "|", 2)
			if len(parts) == 2 {
				cfg.Issuers = append(cfg.Issuers, oidc.IssuerConfig{
					URL:  strings.TrimSpace(parts[0]),
					Type: strings.TrimSpace(parts[1]),
				})
			}
		}
	}

	if ents := os.Getenv("OIDC_ENTERPRISE_ALLOWLIST"); ents != "" {
		for _, e := range strings.Split(ents, ",") {
			if t := strings.TrimSpace(e); t != "" {
				cfg.EnterpriseAllowlist = append(cfg.EnterpriseAllowlist, t)
			}
		}
	}

	if orgs := os.Getenv("OIDC_ORG_ALLOWLIST"); orgs != "" {
		for _, o := range strings.Split(orgs, ",") {
			if t := strings.TrimSpace(o); t != "" {
				cfg.OrgAllowlist = append(cfg.OrgAllowlist, t)
			}
		}
	}

	return cfg
}
