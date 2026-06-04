// Package indexer writes DynamoDB records that map artifact SHA
// checksums to the S3 locations of their SPDX documents.
package indexer

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"path/filepath"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Indexer reads a Phase 1 manifest from S3 and writes SPDX location
// records to DynamoDB, keyed by artifact SHA (SHA-256 and SHA-1).
type Indexer struct {
	s3Client     *s3.Client
	dynamoClient *dynamodb.Client
	bucket       string
	table        string
	graphTable   string // empty = skip dependency graph indexing
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
// Two items are written per binary — one keyed by SHA-256, one by SHA-1.
type SpdxRecord struct {
	// Partition key: SHA hex digest (SHA-256 64 chars, or SHA-1 40 chars).
	ArtifactSHA string `dynamodbav:"ArtifactSHA" json:"artifact_sha"`

	// S3 URI to the analyzed SPDX document.
	AnalyzedSpdxS3 string `dynamodbav:"AnalyzedSpdxS3,omitempty" json:"analyzed_spdx_s3,omitempty"`

	// S3 URI to the build SPDX document.
	BuildSpdxS3 string `dynamodbav:"BuildSpdxS3,omitempty" json:"build_spdx_s3,omitempty"`

	// S3 URI to the sbom-tree JSON document.
	SbomTreeS3 string `dynamodbav:"SbomTreeS3,omitempty" json:"sbom_tree_s3,omitempty"`

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

// IndexedArtifact is returned by Index for each successfully indexed artifact.
type IndexedArtifact struct {
	SHA256       string // artifact SHA-256
	Name         string // jar stem (e.g. "webgoat-2025.4-SNAPSHOT")
	GraphIndexed bool   // true if dependency graph was written
}

// Index reads the manifest from S3, discovers SPDX files under the
// job's spdx/ prefix, and writes a DynamoDB record per artifact.
// Returns the list of successfully indexed artifacts.
func (ix *Indexer) Index(ctx context.Context, jobPrefix string) ([]IndexedArtifact, error) {
	manifest, err := ix.loadManifestFromS3(ctx, jobPrefix)
	if err != nil {
		return nil, fmt.Errorf("load manifest: %w", err)
	}

	if len(manifest.Artifacts.Binaries) == 0 {
		log.Println("[INDEX] No binaries in manifest — nothing to index")
		return nil, nil
	}

	// List SPDX files under the job's spdx/ prefix in S3
	spdxPrefix := jobPrefix + "/spdx/"
	spdxKeys, err := ix.listSpdxKeys(ctx, spdxPrefix)
	if err != nil {
		return nil, fmt.Errorf("list spdx keys: %w", err)
	}
	log.Printf("[INDEX] Found %d SPDX files under s3://%s/%s", len(spdxKeys), ix.bucket, spdxPrefix)

	if len(spdxKeys) == 0 {
		log.Println("[INDEX] No SPDX files found — nothing to index")
		return nil, nil
	}

	// Write a DynamoDB record for each binary
	var results []IndexedArtifact
	for _, bin := range manifest.Artifacts.Binaries {
		if bin.SHA256 == "" {
			log.Printf("[INDEX] Skipping binary with no SHA-256: %s", bin.Path)
			continue
		}

		stem := jarStem(bin.Path)
		record := SpdxRecord{
			ArtifactSHA:  bin.SHA256,
			ArtifactPath: bin.Path,
			RepoName:     manifest.RepoName,
			Language:     manifest.Language,
			CommitSHA:    manifest.CommitSHA,
			VcsURI:       manifest.VcsURI,
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
			if base == stem+"-sbom-tree.json" {
				record.SbomTreeS3 = fmt.Sprintf("s3://%s/%s", ix.bucket, key)
			}
		}

		if record.AnalyzedSpdxS3 == "" && record.BuildSpdxS3 == "" {
			log.Printf("[INDEX] No SPDX files matched for %s (stem: %s)", bin.Path, stem)
			continue
		}

		// Write SHA-256 keyed record
		if err := ix.putRecord(ctx, record); err != nil {
			return nil, fmt.Errorf("put record for %s: %w", bin.SHA256[:12], err)
		}
		log.Printf("[INDEX] Indexed SHA-256 %s → %s", bin.SHA256[:12], stem)

		// Write SHA-1 keyed record (same S3 URIs, enables lookup by either hash)
		if bin.SHA1 != "" {
			record.ArtifactSHA = bin.SHA1
			if err := ix.putRecord(ctx, record); err != nil {
				return nil, fmt.Errorf("put sha1 record for %s: %w", bin.SHA1[:12], err)
			}
			log.Printf("[INDEX] Indexed SHA-1   %s → %s", bin.SHA1[:12], stem)
		}

		result := IndexedArtifact{SHA256: bin.SHA256, Name: stem}

		// Write dependency graph if a graph table is configured
		// and a build SPDX exists (it contains DEPENDS_ON edges).
		if ix.graphTable != "" && record.BuildSpdxS3 != "" {
			buildKey := buildSpdxKeyFromURI(record.BuildSpdxS3, ix.bucket)
			if err := ix.IndexGraph(ctx, bin.SHA256, buildKey, ix.graphTable); err != nil {
				log.Printf("[GRAPH] Error indexing graph for %s: %v", bin.SHA256[:12], err)
			} else {
				result.GraphIndexed = true
			}
		}

		results = append(results, result)
	}

	log.Printf("[INDEX] Indexed %d/%d artifacts", len(results), len(manifest.Artifacts.Binaries))
	return results, nil
}

// buildSpdxKeyFromURI strips the s3://bucket/ prefix to get the S3 key.
func buildSpdxKeyFromURI(s3URI, bucket string) string {
	prefix := fmt.Sprintf("s3://%s/", bucket)
	return strings.TrimPrefix(s3URI, prefix)
}

// loadManifestFromS3 finds and reads the phase1_manifest.json under
// the job's phase1/ prefix in S3.
func (ix *Indexer) loadManifestFromS3(ctx context.Context, jobPrefix string) (*Manifest, error) {
	// The manifest is at <jobPrefix>/phase1/.../phase1_manifest.json
	// List objects to find it since the path varies by language/repo structure
	prefix := jobPrefix + "/phase1/"
	paginator := s3.NewListObjectsV2Paginator(ix.s3Client, &s3.ListObjectsV2Input{
		Bucket: &ix.bucket,
		Prefix: &prefix,
	})

	var manifestKey string
	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("list phase1 objects: %w", err)
		}
		for _, obj := range page.Contents {
			key := aws.ToString(obj.Key)
			if strings.HasSuffix(key, "phase1_manifest.json") {
				manifestKey = key
				break
			}
		}
		if manifestKey != "" {
			break
		}
	}

	if manifestKey == "" {
		return nil, fmt.Errorf("phase1_manifest.json not found under s3://%s/%s", ix.bucket, prefix)
	}

	out, err := ix.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &ix.bucket,
		Key:    &manifestKey,
	})
	if err != nil {
		return nil, fmt.Errorf("get manifest: %w", err)
	}
	defer out.Body.Close()

	data, err := io.ReadAll(out.Body)
	if err != nil {
		return nil, fmt.Errorf("read manifest: %w", err)
	}

	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("parse manifest: %w", err)
	}
	return &m, nil
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

// jarStem extracts the filename stem from a path (no extension).
// e.g. "/workspace/target/webgoat-2025.4-SNAPSHOT.jar" → "webgoat-2025.4-SNAPSHOT"
func jarStem(path string) string {
	base := filepath.Base(path)
	ext := filepath.Ext(base)
	return strings.TrimSuffix(base, ext)
}
