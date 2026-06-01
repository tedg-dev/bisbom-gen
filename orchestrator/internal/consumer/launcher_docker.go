package consumer

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"

	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/config"
)

// DockerLauncher runs Phase 2 via `docker run` on the local Docker daemon.
//
// How it works:
//  1. The orchestrator has already downloaded Phase 1 artifacts from S3
//     to a local directory (Phase1Dir).
//  2. Phase1Dir is bind-mounted into the sidecar container at
//     /workspace/output (treedb, dep:tree, manifest).
//  3. The sidecar runs Phase 2 (SPDX generation) using the manifest's
//     binary metadata — actual JAR files are not needed on disk.
//  4. After the container exits, the orchestrator uploads SPDX files from
//     Phase1Dir back to S3.
//
// Requirements:
//   - Docker daemon running on the host
//   - Docker socket accessible (default: /var/run/docker.sock)
//   - Sidecar image pulled or pullable
//
// Best for: local development, testing, EC2 hosts with Docker installed.
type DockerLauncher struct {
	cfg *config.Config
}

// NewDockerLauncher creates a DockerLauncher.
func NewDockerLauncher(cfg *config.Config) *DockerLauncher {
	return &DockerLauncher{cfg: cfg}
}

// Launch starts the sidecar container via `docker run`.
func (d *DockerLauncher) Launch(ctx context.Context, job *Phase2Job) error {
	args := []string{
		"run", "--rm",
		"-v", job.Phase1Dir + ":/workspace/output",
		"-e", "OMNIBOR_MODE=sidecar",
		d.cfg.SidecarImage,
		"python3", "/workspace/app/analyze.py",
		"--repo", job.RepoName,
		"--mode", "sidecar",
		"--phase", "spdx",
		"--manifest", job.ContainerManifest,
		"--skip-clone",
	}

	log.Printf("[INFO] docker %s", strings.Join(args, " "))

	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("docker run: %w", err)
	}
	return nil
}
