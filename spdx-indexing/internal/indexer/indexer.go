// Package indexer writes DynamoDB records that map artifact SHA-256
// checksums to the S3 locations of their SPDX documents.
package indexer

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Indexer reads a Phase 1 manifest and writes SPDX location records
// to DynamoDB, keyed by artifact SHA-256.
type Indexer struct {
	s3Client     *s3.Client
	dynamoClient *dynamodb.Client
	bucket       string
	table        string
	graphTable   string // empty = skip dependency graph indexing
	DryRun       bool   // when true, log records but skip DynamoDB writes
}

// New creates an Indexer backed by the given AWS config.
// graphTable may be empty to disable dependency graph indexing.
func New(awsCfg aws.Config, bucket, table, graphTable string) *Indexer {
	return &Indexer{
		s3Client:     s3.NewFromConfig(awsCfg),
		dynamoClient: dynamodb.NewFromConfig(awsCfg),
		bucket:       bucket,
		table:        table,
		graphTable:   graphTable,
	}
}

// SpdxRecord is the DynamoDB item stored per artifact.
type SpdxRecord struct {
	// Partition key: SHA-256 hex digest of the artifact binary.
	ArtifactSHA256 string `dynamodbav:"ArtifactSHA256" json:"artifact_sha256"`

	// S3 URI to the analyzed SPDX document.
	AnalyzedSpdxS3 string `dynamodbav:"AnalyzedSpdxS3,omitempty" json:"analyzed_spdx_s3,omitempty"`

	// S3 URI to the build SPDX document.
	BuildSpdxS3 string `dynamodbav:"BuildSpdxS3,omitempty" json:"build_spdx_s3,omitempty"`

	// Original artifact path from the manifest.
	ArtifactPath string `dynamodbav:"ArtifactPath" json:"artifact_path"`

	// Repository name from the manifest.
	RepoName string `dynamodbav:"RepoName" json:"repo_name"`

	// Language from the manifest.
	Language string `dynamodbav:"Language" json:"language"`

	// Commit SHA from the manifest.
	CommitSHA string `dynamodbav:"CommitSHA,omitempty" json:"commit_sha,omitempty"`

	// VCS URI (e.g. https://github.com/kkaple/WebGoat).
	VcsURI string `dynamodbav:"VcsURI,omitempty" json:"vcs_uri,omitempty"`
}

// Manifest is the subset of phase1_manifest.json we need.
type Manifest struct {
	RepoName  string `json:"repo_name"`
	Language  string `json:"language"`
	CommitSHA string `json:"commit_sha"`
	VcsURI    string `json:"vcs_uri"`
	Artifacts struct {
		Binaries []BinaryEntry `json:"binaries"`
	} `json:"artifacts"`
}

// BinaryEntry represents an enriched binary from the manifest.
type BinaryEntry struct {
	Path   string `json:"path"`
	SHA1   string `json:"sha1"`
	SHA256 string `json:"sha256"`
}

// Index reads the manifest, discovers SPDX files in S3, and writes
// a DynamoDB record per artifact.
func (ix *Indexer) Index(ctx context.Context, manifestPath, jobPrefix string) error {
	manifest, err := ix.loadManifest(ctx, manifestPath)
	if err != nil {
		return fmt.Errorf("load manifest: %w", err)
	}

	if len(manifest.Artifacts.Binaries) == 0 {
		log.Println("[WARN] No binaries in manifest — nothing to index")
		return nil
	}

	// List SPDX files under the job's spdx/ prefix in S3
	spdxPrefix := jobPrefix + "/spdx/"
	spdxKeys, err := ix.listSpdxKeys(ctx, spdxPrefix)
	if err != nil {
		return fmt.Errorf("list spdx keys: %w", err)
	}
	log.Printf("[INFO] Found %d SPDX files under s3://%s/%s", len(spdxKeys), ix.bucket, spdxPrefix)

	// Index: map each binary's jar stem to its SPDX S3 paths
	indexed := 0
	for _, bin := range manifest.Artifacts.Binaries {
		if bin.SHA256 == "" {
			log.Printf("[WARN] Skipping binary with no SHA-256: %s", bin.Path)
			continue
		}

		stem := jarStem(bin.Path)
		record := SpdxRecord{
			ArtifactSHA256: bin.SHA256,
			ArtifactPath:   bin.Path,
			RepoName:       manifest.RepoName,
			Language:       manifest.Language,
			CommitSHA:      manifest.CommitSHA,
			VcsURI:         manifest.VcsURI,
		}

		// Match SPDX keys by jar stem
		for _, key := range spdxKeys {
			base := filepath.Base(key)
			if strings.HasPrefix(base, stem+"_analyzed") {
				record.AnalyzedSpdxS3 = fmt.Sprintf("s3://%s/%s", ix.bucket, key)
			}
			if strings.HasPrefix(base, stem+"_build") {
				record.BuildSpdxS3 = fmt.Sprintf("s3://%s/%s", ix.bucket, key)
			}
		}

		if record.AnalyzedSpdxS3 == "" && record.BuildSpdxS3 == "" {
			log.Printf("[WARN] No SPDX files found for %s (stem: %s)", bin.Path, stem)
			continue
		}

		if ix.DryRun {
			log.Printf("[DRY-RUN] Would index %s → analyzed=%s build=%s",
				bin.SHA256[:12], record.AnalyzedSpdxS3, record.BuildSpdxS3)
		} else {
			if err := ix.putRecord(ctx, record); err != nil {
				return fmt.Errorf("put record for %s: %w", bin.SHA256, err)
			}
		}
		indexed++
		log.Printf("[OK] Indexed %s → %s", bin.SHA256[:12], stem)

		// Write dependency graph if a graph table is configured
		// and a build SPDX exists (it contains DEPENDS_ON edges).
		if ix.graphTable != "" && record.BuildSpdxS3 != "" {
			buildKey := buildSpdxKeyFromURI(record.BuildSpdxS3, ix.bucket)
			if err := ix.IndexGraph(ctx, bin.SHA256, buildKey, ix.graphTable); err != nil {
				log.Printf("[GRAPH] Error indexing graph for %s: %v", bin.SHA256[:12], err)
			}
		}
	}

	log.Printf("[INFO] Indexed %d/%d artifacts", indexed, len(manifest.Artifacts.Binaries))
	return nil
}

// loadManifest reads the manifest from a local path or S3 URI.
func (ix *Indexer) loadManifest(ctx context.Context, path string) (*Manifest, error) {
	var data []byte
	var err error

	if strings.HasPrefix(path, "s3://") {
		data, err = ix.readS3Object(ctx, path)
	} else {
		data, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, err
	}

	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("parse manifest: %w", err)
	}
	return &m, nil
}

// readS3Object fetches an object by s3:// URI.
func (ix *Indexer) readS3Object(ctx context.Context, uri string) ([]byte, error) {
	// s3://bucket/key
	trimmed := strings.TrimPrefix(uri, "s3://")
	slash := strings.IndexByte(trimmed, '/')
	if slash < 0 {
		return nil, fmt.Errorf("invalid S3 URI: %s", uri)
	}
	bucket := trimmed[:slash]
	key := trimmed[slash+1:]

	out, err := ix.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &bucket,
		Key:    &key,
	})
	if err != nil {
		return nil, err
	}
	defer out.Body.Close()

	return io.ReadAll(out.Body)
}

// listSpdxKeys returns all S3 keys matching *.spdx.json under the prefix.
func (ix *Indexer) listSpdxKeys(ctx context.Context, prefix string) ([]string, error) {
	var keys []string
	paginator := s3.NewListObjectsV2Paginator(ix.s3Client, &s3.ListObjectsV2Input{
		Bucket: &ix.bucket,
		Prefix: &prefix,
	})

	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, err
		}
		for _, obj := range page.Contents {
			key := aws.ToString(obj.Key)
			if strings.HasSuffix(key, ".spdx.json") {
				keys = append(keys, key)
			}
		}
	}
	return keys, nil
}

// putRecord writes a single SpdxRecord to DynamoDB.
func (ix *Indexer) putRecord(ctx context.Context, record SpdxRecord) error {
	item, err := attributevalue.MarshalMap(record)
	if err != nil {
		return fmt.Errorf("marshal record: %w", err)
	}

	_, err = ix.dynamoClient.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: &ix.table,
		Item:      item,
	})
	return err
}

// buildSpdxKeyFromURI strips the s3://bucket/ prefix to get the S3 key.
func buildSpdxKeyFromURI(s3URI, bucket string) string {
	prefix := fmt.Sprintf("s3://%s/", bucket)
	return strings.TrimPrefix(s3URI, prefix)
}

// jarStem extracts the filename stem from a path (no extension).
// e.g. "/workspace/target/webgoat-2025.4-SNAPSHOT.jar" → "webgoat-2025.4-SNAPSHOT"
func jarStem(path string) string {
	base := filepath.Base(path)
	ext := filepath.Ext(base)
	return strings.TrimSuffix(base, ext)
}
