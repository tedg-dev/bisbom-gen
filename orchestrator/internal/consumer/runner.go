package consumer

import (
	"context"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/config"
)

// Runner downloads Phase 1 artifacts from S3 and launches the Phase 2 container.
type Runner struct {
	cfg      *config.Config
	s3Client *s3.Client
	launcher Launcher
}

// NewRunner creates a Runner with an S3 client and the appropriate launcher
// based on the configured LaunchMode.
//
// Docker mode (default / testing):
//   - Downloads artifacts to local disk, mounts into container via docker run
//   - Uploads SPDX results back to S3 after container exits
//   - Requires Docker daemon on the host
//
// ECS mode (production):
//   - Skips local download — passes S3 paths to the ECS task as env overrides
//   - The Phase 2 task handles its own S3 I/O
//   - Skips local SPDX upload — the task writes directly to S3
func NewRunner(cfg *config.Config, awsCfg aws.Config) *Runner {
	var launcher Launcher
	switch cfg.LaunchMode {
	case config.LaunchModeECS:
		launcher = NewECSLauncher(cfg, awsCfg)
	default:
		launcher = NewDockerLauncher(cfg)
	}

	return &Runner{
		cfg:      cfg,
		s3Client: s3.NewFromConfig(awsCfg),
		launcher: launcher,
	}
}

// RunPhase2 downloads artifacts from S3 and launches the sidecar container.
// jobPrefix is the S3 path: <lang>/<repo>/<sha>/<run_id>
func (r *Runner) RunPhase2(ctx context.Context, jobPrefix string) error {
	parts := strings.Split(jobPrefix, "/")
	if len(parts) < 4 {
		return fmt.Errorf("invalid job prefix: %s", jobPrefix)
	}
	repoName := parts[1]
	sha := parts[2]
	runID := parts[3]

	job := &Phase2Job{
		RepoName:  repoName,
		S3Bucket:  r.cfg.S3Bucket,
		JobPrefix: jobPrefix,
	}

	// In ECS mode, the Phase 2 task handles its own S3 I/O.
	// We just launch the task and wait for it to finish.
	if r.cfg.LaunchMode == config.LaunchModeECS {
		log.Printf("[INFO] Launching Phase 2 via ECS for %s (sha: %s)", repoName, sha)
		return r.launcher.Launch(ctx, job)
	}

	// Docker mode: download artifacts locally, run container, upload results.
	workDir := filepath.Join(r.cfg.WorkDir, sha, runID)
	phase1Dir := filepath.Join(workDir, "phase1")
	buildDir := filepath.Join(workDir, "build")
	spdxDir := filepath.Join(workDir, "spdx")

	for _, dir := range []string{phase1Dir, buildDir, spdxDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("mkdir %s: %w", dir, err)
		}
	}

	// Download Phase 1 artifacts
	log.Printf("[INFO] Downloading Phase 1 artifacts: s3://%s/%s/phase1/",
		r.cfg.S3Bucket, jobPrefix)
	if err := r.downloadPrefix(ctx, jobPrefix+"/phase1/", phase1Dir); err != nil {
		return fmt.Errorf("download phase1: %w", err)
	}

	// Download build output (optional — may not exist)
	log.Printf("[INFO] Downloading build output: s3://%s/%s/build/",
		r.cfg.S3Bucket, jobPrefix)
	if err := r.downloadPrefix(ctx, jobPrefix+"/build/", buildDir); err != nil {
		log.Printf("[WARN] No build output found (non-fatal): %v", err)
	}

	// Find the manifest file
	manifestPath, err := findFile(phase1Dir, "phase1_manifest.json")
	if err != nil {
		return fmt.Errorf("find manifest: %w", err)
	}
	log.Printf("[INFO] Manifest: %s", manifestPath)

	// Compute container-relative manifest path
	// Host: <workDir>/phase1/omnibor/java/<repo>/<ts>/phase1_manifest.json
	// Container: /workspace/output/omnibor/java/<repo>/<ts>/phase1_manifest.json
	relManifest, err := filepath.Rel(phase1Dir, manifestPath)
	if err != nil {
		return fmt.Errorf("relative manifest path: %w", err)
	}
	containerManifest := filepath.Join("/workspace/output", relManifest)

	job.Phase1Dir = phase1Dir
	job.BuildDir = buildDir
	job.ContainerManifest = containerManifest

	// Launch Phase 2 container
	log.Printf("[INFO] Launching Phase 2 via Docker for %s (sha: %s)", repoName, sha)
	if err := r.launcher.Launch(ctx, job); err != nil {
		return fmt.Errorf("launch phase2: %w", err)
	}

	// Upload SPDX output back to S3
	spdxPrefix := jobPrefix + "/spdx/"
	log.Printf("[INFO] Uploading SPDX to s3://%s/%s", r.cfg.S3Bucket, spdxPrefix)
	if err := r.uploadDir(ctx, phase1Dir, spdxPrefix); err != nil {
		return fmt.Errorf("upload spdx: %w", err)
	}

	log.Printf("[INFO] Phase 2 complete for %s/%s", sha, runID)
	return nil
}

// downloadPrefix downloads all objects under a given S3 prefix to a local directory.
func (r *Runner) downloadPrefix(ctx context.Context, prefix, destDir string) error {
	paginator := s3.NewListObjectsV2Paginator(r.s3Client, &s3.ListObjectsV2Input{
		Bucket: &r.cfg.S3Bucket,
		Prefix: &prefix,
	})

	count := 0
	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return fmt.Errorf("list objects: %w", err)
		}

		for _, obj := range page.Contents {
			key := aws.ToString(obj.Key)
			relPath := strings.TrimPrefix(key, prefix)
			if relPath == "" {
				continue
			}

			localPath := filepath.Join(destDir, relPath)
			if err := r.downloadFile(ctx, key, localPath); err != nil {
				return fmt.Errorf("download %s: %w", key, err)
			}
			count++
		}
	}

	if count == 0 {
		return fmt.Errorf("no objects found under s3://%s/%s", r.cfg.S3Bucket, prefix)
	}
	log.Printf("[INFO] Downloaded %d files from s3://%s/%s", count, r.cfg.S3Bucket, prefix)
	return nil
}

// downloadFile downloads a single S3 object to a local file path.
func (r *Runner) downloadFile(ctx context.Context, key, localPath string) error {
	if err := os.MkdirAll(filepath.Dir(localPath), 0o755); err != nil {
		return err
	}

	out, err := r.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &r.cfg.S3Bucket,
		Key:    &key,
	})
	if err != nil {
		return err
	}
	defer out.Body.Close()

	f, err := os.Create(localPath)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = io.Copy(f, out.Body)
	return err
}

// uploadDir uploads all files in a local directory to an S3 prefix.
func (r *Runner) uploadDir(ctx context.Context, localDir, s3Prefix string) error {
	count := 0
	err := filepath.Walk(localDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}

		// Only upload SPDX files
		if !strings.HasSuffix(path, ".spdx.json") && !strings.HasSuffix(path, ".spdx.html") {
			return nil
		}

		relPath, err := filepath.Rel(localDir, path)
		if err != nil {
			return err
		}

		key := s3Prefix + relPath
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()

		_, putErr := r.s3Client.PutObject(ctx, &s3.PutObjectInput{
			Bucket: &r.cfg.S3Bucket,
			Key:    &key,
			Body:   f,
		})
		if putErr != nil {
			return fmt.Errorf("put %s: %w", key, putErr)
		}
		count++
		return nil
	})

	if err != nil {
		return err
	}
	log.Printf("[INFO] Uploaded %d SPDX files to s3://%s/%s", count, r.cfg.S3Bucket, s3Prefix)
	return nil
}

// findFile recursively searches for a file by name under root.
func findFile(root, name string) (string, error) {
	var found string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && info.Name() == name {
			found = path
			return filepath.SkipAll
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	if found == "" {
		return "", fmt.Errorf("%s not found under %s", name, root)
	}
	return found, nil
}
