package consumer

import "context"

// Phase2Job holds the parameters needed to launch a Phase 2 container.
type Phase2Job struct {
	RepoName          string // e.g., "omnibor-java-testapp"
	S3Bucket          string // e.g., "omnibor-spdx-artifacts"
	JobPrefix         string // e.g., "java/omnibor-java-testapp/<sha>/<run_id>"
	Phase1Dir         string // Local path to downloaded Phase 1 artifacts (docker mode)
	BuildDir          string // Local path to downloaded build output (docker mode)
	ContainerManifest string // Container-relative path to phase1_manifest.json
}

// Launcher abstracts how Phase 2 containers are started.
//
// Two implementations:
//
//   - DockerLauncher: Runs `docker run` on the local Docker daemon.
//     Use for local testing, development, and EC2 hosts with Docker.
//     The orchestrator downloads S3 artifacts to local disk and mounts
//     them into the sidecar container as volumes.
//
//   - ECSLauncher: Calls the ECS RunTask API to start a Fargate task.
//     Use for production ECS/Fargate deployments. The Phase 2 task
//     downloads artifacts from S3 itself (no local disk needed).
//     The orchestrator passes S3 paths as environment variable overrides.
type Launcher interface {
	Launch(ctx context.Context, job *Phase2Job) error
}
