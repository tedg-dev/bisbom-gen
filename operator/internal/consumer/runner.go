package consumer

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/sqs"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/config"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/indexer"
)

// Runner downloads Phase 1 artifacts from S3 and launches the Phase 2 container.
type Runner struct {
	cfg              *config.Config
	s3Client         *s3.Client
	sqsClient        *sqs.Client // for sbom-tree queue
	launcher         Launcher
	indexer          *indexer.Indexer // nil when DYNAMO_TABLE is not set
	sbomTreeQueueURL string           // empty = skip sbom-tree publishing
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

	r := &Runner{
		cfg:              cfg,
		s3Client:         s3.NewFromConfig(awsCfg),
		launcher:         launcher,
		sbomTreeQueueURL: cfg.SbomTreeQueueURL,
	}

	if cfg.SbomTreeQueueURL != "" {
		r.sqsClient = sqs.NewFromConfig(awsCfg)
		log.Printf("[INFO] sbom-tree publishing enabled (queue: %s)", cfg.SbomTreeQueueURL)
	}

	if cfg.DynamoTable != "" {
		r.indexer = indexer.New(awsCfg, cfg.S3Bucket, cfg.DynamoTable, cfg.GraphTable)
		log.Printf("[INFO] SPDX indexing enabled (table: %s)", cfg.DynamoTable)
		if cfg.GraphTable != "" {
			log.Printf("[INFO] Dependency graph indexing enabled (table: %s)", cfg.GraphTable)
		}
	}

	return r
}

// RunPhase2 downloads artifacts from S3 and launches the sidecar container.
// jobPrefix is the S3 path: <owner>/<repo>/<job_id>
// archiveFile is the tar.gz filename (e.g., "phase1.tar.gz") or empty for legacy multi-file mode.
func (r *Runner) RunPhase2(ctx context.Context, jobPrefix string, archiveFile string) error {
	parts := strings.Split(jobPrefix, "/")
	if len(parts) < 3 {
		return fmt.Errorf("invalid job prefix: %s", jobPrefix)
	}
	repoName := parts[1]
	jobID := parts[2]

	job := &Phase2Job{
		RepoName:  repoName,
		S3Bucket:  r.cfg.S3Bucket,
		JobPrefix: jobPrefix,
	}

	// In ECS mode, the Phase 2 task handles its own S3 I/O.
	// We just launch the task and wait for it to finish.
	if r.cfg.LaunchMode == config.LaunchModeECS {
		log.Printf("[INFO] Launching Phase 2 via ECS for %s (job: %s)", repoName, jobID)
		if err := r.launcher.Launch(ctx, job); err != nil {
			return fmt.Errorf("launch phase2: %w", err)
		}
		return r.indexSpdx(ctx, jobPrefix)
	}

	// Docker mode: download artifacts locally, run container, upload results.
	workDir := filepath.Join(r.cfg.WorkDir, jobID)
	phase1Dir := filepath.Join(workDir, "phase1")
	spdxDir := filepath.Join(workDir, "spdx")

	for _, dir := range []string{phase1Dir, spdxDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("mkdir %s: %w", dir, err)
		}
	}

	// Download Phase 1 artifacts (treedb, dep:tree, manifest)
	if archiveFile != "" {
		// tar.gz mode: download single archive and extract
		log.Printf("[INFO] Downloading Phase 1 archive: s3://%s/%s/%s",
			r.cfg.S3Bucket, jobPrefix, archiveFile)
		archivePath := filepath.Join(workDir, archiveFile)
		s3Key := jobPrefix + "/" + archiveFile
		if err := r.downloadFile(ctx, s3Key, archivePath); err != nil {
			return fmt.Errorf("download archive: %w", err)
		}
		if err := extractTarGz(archivePath, phase1Dir); err != nil {
			return fmt.Errorf("extract archive: %w", err)
		}
		os.Remove(archivePath)
	} else {
		// Legacy mode: download individual files by prefix
		log.Printf("[INFO] Downloading Phase 1 artifacts: s3://%s/%s/phase1/",
			r.cfg.S3Bucket, jobPrefix)
		if err := r.downloadPrefix(ctx, jobPrefix+"/phase1/", phase1Dir); err != nil {
			return fmt.Errorf("download phase1: %w", err)
		}
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
	job.ContainerManifest = containerManifest

	// Launch Phase 2 container
	log.Printf("[INFO] Launching Phase 2 via Docker for %s (job: %s)", repoName, jobID)
	if err := r.launcher.Launch(ctx, job); err != nil {
		return fmt.Errorf("launch phase2: %w", err)
	}

	// Upload SPDX output back to S3
	spdxPrefix := jobPrefix + "/spdx/"
	log.Printf("[INFO] Uploading SPDX to s3://%s/%s", r.cfg.S3Bucket, spdxPrefix)
	if err := r.uploadDir(ctx, phase1Dir, spdxPrefix); err != nil {
		return fmt.Errorf("upload spdx: %w", err)
	}

	// Index SPDX documents in DynamoDB
	if err := r.indexSpdx(ctx, jobPrefix); err != nil {
		return fmt.Errorf("index spdx: %w", err)
	}

	log.Printf("[INFO] Phase 2 complete for %s/%s", repoName, jobID)
	return nil
}

// indexSpdx writes SPDX location records to DynamoDB if indexing is enabled.
// After successful graph indexing, publishes sbom-tree requests to SQS.
func (r *Runner) indexSpdx(ctx context.Context, jobPrefix string) error {
	if r.indexer == nil {
		return nil
	}
	log.Printf("[INFO] Indexing SPDX documents for %s", jobPrefix)
	results, err := r.indexer.Index(ctx, jobPrefix)
	if err != nil {
		return err
	}

	// Publish sbom-tree generation requests for each graph-indexed artifact
	for _, art := range results {
		if art.GraphIndexed && r.sbomTreeQueueURL != "" {
			if err := r.publishSbomTreeRequest(ctx, art, jobPrefix); err != nil {
				log.Printf("[WARN] Failed to publish sbom-tree request for %s: %v",
					art.SHA256[:12], err)
			}
		}
	}

	return nil
}

// sbomTreeMessage is the SQS message body for sbom-tree generation.
type sbomTreeMessage struct {
	ArtifactSHA  string `json:"artifactSHA"`
	ArtifactSHA1 string `json:"artifactSHA1,omitempty"`
	ArtifactName string `json:"artifactName"`
	JobPrefix    string `json:"jobPrefix"`
	Bucket       string `json:"bucket"`
	GraphTable   string `json:"graphTable"`
	IndexTable   string `json:"indexTable"`
}

// publishSbomTreeRequest sends an SQS message to trigger tree generation.
func (r *Runner) publishSbomTreeRequest(
	ctx context.Context,
	art indexer.IndexedArtifact,
	jobPrefix string,
) error {
	msg := sbomTreeMessage{
		ArtifactSHA:  art.SHA256,
		ArtifactSHA1: art.SHA1,
		ArtifactName: art.Name,
		JobPrefix:    jobPrefix,
		Bucket:       r.cfg.S3Bucket,
		GraphTable:   r.cfg.GraphTable,
		IndexTable:   r.cfg.DynamoTable,
	}

	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal message: %w", err)
	}

	bodyStr := string(body)
	_, err = r.sqsClient.SendMessage(ctx, &sqs.SendMessageInput{
		QueueUrl:    &r.sbomTreeQueueURL,
		MessageBody: &bodyStr,
	})
	if err != nil {
		return fmt.Errorf("send message: %w", err)
	}

	log.Printf("[INFO] Published sbom-tree request for %s (%s)",
		art.Name, art.SHA256[:12])
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

		// Upload flat — use only the filename, not the nested subdirectory
		// structure that the sidecar creates (e.g., spdx/java/WebGoat/<ts>/).
		key := s3Prefix + filepath.Base(path)
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

// extractTarGz extracts a .tar.gz archive into destDir,
// preserving the directory structure from the archive.
func extractTarGz(archivePath, destDir string) error {
	f, err := os.Open(archivePath)
	if err != nil {
		return fmt.Errorf("open archive: %w", err)
	}
	defer f.Close()

	gz, err := gzip.NewReader(f)
	if err != nil {
		return fmt.Errorf("gzip reader: %w", err)
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	count := 0
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}

		// Sanitize path to prevent directory traversal
		target := filepath.Join(destDir, filepath.Clean(hdr.Name))
		if !strings.HasPrefix(target, filepath.Clean(destDir)+string(os.PathSeparator)) {
			return fmt.Errorf("tar entry escapes destination: %s", hdr.Name)
		}

		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o755); err != nil {
				return fmt.Errorf("mkdir %s: %w", target, err)
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return fmt.Errorf("mkdir parent %s: %w", target, err)
			}
			out, err := os.Create(target)
			if err != nil {
				return fmt.Errorf("create %s: %w", target, err)
			}
			if _, err := io.Copy(out, tr); err != nil {
				out.Close()
				return fmt.Errorf("write %s: %w", target, err)
			}
			out.Close()
			count++
		}
	}

	log.Printf("[INFO] Extracted %d files from %s", count, filepath.Base(archivePath))
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
