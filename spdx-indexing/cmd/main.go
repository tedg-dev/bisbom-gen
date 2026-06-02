// spdx-indexing is a debug CLI for indexing SPDX documents into DynamoDB.
//
// It reads a Phase 1 manifest (local file or S3 URI), lists SPDX files
// under the job's S3 prefix, and writes a DynamoDB record per artifact
// keyed by SHA-256. This is the same logic the orchestrator runs inline
// after Phase 2 completes — this CLI exists for manual re-indexing and
// debugging.
//
// Usage:
//
//	spdx-indexing -manifest <path-or-s3-uri> -bucket <bucket> -table <table> -prefix <job-prefix>
//
// Examples:
//
//	# Index from a local manifest file
//	spdx-indexing \
//	  -manifest /tmp/orchestrator/abc123/42/phase1/omnibor/java/WebGoat/20250601/phase1_manifest.json \
//	  -bucket omnibor-spdx-artifacts \
//	  -table SpdxIndexTable \
//	  -prefix java/WebGoat/abc123/42
//
//	# Index from an S3 manifest
//	spdx-indexing \
//	  -manifest s3://omnibor-spdx-artifacts/java/WebGoat/abc123/42/phase1/omnibor/java/WebGoat/20250601/phase1_manifest.json \
//	  -bucket omnibor-spdx-artifacts \
//	  -table SpdxIndexTable \
//	  -prefix java/WebGoat/abc123/42
//
//	# Dry run — show what would be indexed without writing to DynamoDB
//	spdx-indexing \
//	  -manifest /tmp/phase1_manifest.json \
//	  -bucket omnibor-spdx-artifacts \
//	  -table SpdxIndexTable \
//	  -prefix java/WebGoat/abc123/42 \
//	  -dry-run
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/aws/aws-sdk-go-v2/config"

	"github.com/tedg-dev/omnibor-analysis/spdx-indexing/internal/indexer"
)

func main() {
	manifestPath := flag.String("manifest", "", "Path to phase1_manifest.json (local file or s3:// URI)")
	bucket := flag.String("bucket", envOrDefault("S3_BUCKET", ""), "S3 bucket containing SPDX output")
	table := flag.String("table", envOrDefault("DYNAMO_TABLE", ""), "DynamoDB table name for SPDX index records")
	jobPrefix := flag.String("prefix", envOrDefault("JOB_PREFIX", ""), "S3 job prefix (e.g. java/WebGoat/abc123/42)")
	graphTable := flag.String("graph-table", envOrDefault("DYNAMO_GRAPH_TABLE", ""), "DynamoDB table for dependency graph (optional)")
	region := flag.String("region", envOrDefault("AWS_REGION", "us-east-1"), "AWS region")
	dryRun := flag.Bool("dry-run", false, "Show what would be indexed without writing to DynamoDB")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "spdx-indexing — Index SPDX document locations in DynamoDB by artifact SHA-256\n\n")
		fmt.Fprintf(os.Stderr, "This tool reads a Phase 1 manifest, lists SPDX files under the job's\n")
		fmt.Fprintf(os.Stderr, "S3 prefix, and writes a DynamoDB record per artifact so downstream\n")
		fmt.Fprintf(os.Stderr, "consumers can look up SPDX availability by binary hash.\n\n")
		fmt.Fprintf(os.Stderr, "Flags:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nEnvironment variables:\n")
		fmt.Fprintf(os.Stderr, "  S3_BUCKET      Default for -bucket\n")
		fmt.Fprintf(os.Stderr, "  DYNAMO_TABLE   Default for -table\n")
		fmt.Fprintf(os.Stderr, "  DYNAMO_GRAPH_TABLE  Default for -graph-table\n")
		fmt.Fprintf(os.Stderr, "  JOB_PREFIX     Default for -prefix\n")
		fmt.Fprintf(os.Stderr, "  AWS_REGION     Default for -region (fallback: us-east-1)\n\n")
		fmt.Fprintf(os.Stderr, "Examples:\n")
		fmt.Fprintf(os.Stderr, "  # Index from a local manifest\n")
		fmt.Fprintf(os.Stderr, "  spdx-indexing -manifest /tmp/phase1_manifest.json -bucket my-bucket -table SpdxIndexTable -prefix java/WebGoat/abc123/42\n\n")
		fmt.Fprintf(os.Stderr, "  # Dry run from S3\n")
		fmt.Fprintf(os.Stderr, "  spdx-indexing -manifest s3://my-bucket/java/WebGoat/.../phase1_manifest.json -bucket my-bucket -table SpdxIndexTable -prefix java/WebGoat/abc123/42 -dry-run\n")
	}

	flag.Parse()

	if *manifestPath == "" || *bucket == "" || *table == "" || *jobPrefix == "" {
		flag.Usage()
		fmt.Fprintf(os.Stderr, "\nError: -manifest, -bucket, -table, and -prefix are all required\n")
		os.Exit(1)
	}

	ctx := context.Background()
	awsCfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(*region))
	if err != nil {
		log.Fatalf("[FATAL] Load AWS config: %v", err)
	}

	idx := indexer.New(awsCfg, *bucket, *table, *graphTable)
	idx.DryRun = *dryRun

	if *dryRun {
		log.Println("[INFO] Dry run mode — no DynamoDB writes")
	}

	if err := idx.Index(ctx, *manifestPath, *jobPrefix); err != nil {
		log.Fatalf("[FATAL] Indexing failed: %v", err)
	}

	log.Println("[INFO] Indexing complete")
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
