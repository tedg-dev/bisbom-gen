// sbom-tree generates a nested JSON dependency tree from the
// SpdxDependencyGraph DynamoDB table and uploads it to S3.
//
// It runs as an SQS consumer: the orchestrator publishes a message
// after dependency graph indexing, and this worker picks it up,
// queries DynamoDB, builds the tree, and uploads the result.
//
// Usage:
//
//	sbom-tree                          # SQS consumer mode (default)
//	sbom-tree -once -sha <sha> ...     # One-shot mode for debugging
//
// Environment variables (SQS consumer mode):
//
//	SQS_SBOM_TREE_URL  — SQS queue URL (required)
//	AWS_REGION         — AWS region (default: us-east-1)
//
// Flags (one-shot mode):
//
//	-once         Run once and exit (no SQS polling)
//	-sha          Artifact SHA to query (SHA-256 or SHA-1)
//	-name         Artifact name (used in output filename)
//	-prefix       S3 job prefix
//	-bucket       S3 bucket
//	-graph-table  DynamoDB graph table name
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/aws/aws-sdk-go-v2/config"

	"github.com/tedg-dev/omnibor-analysis/sbom-tree/internal/consumer"
	"github.com/tedg-dev/omnibor-analysis/sbom-tree/internal/treegen"
)

func main() {
	once := flag.Bool("once", false, "Run once (one-shot mode) instead of polling SQS")
	sha := flag.String("sha", "", "Artifact SHA (one-shot mode)")
	name := flag.String("name", "", "Artifact name (one-shot mode)")
	prefix := flag.String("prefix", "", "S3 job prefix (one-shot mode)")
	bucket := flag.String("bucket", envOrDefault("S3_BUCKET", ""), "S3 bucket")
	graphTable := flag.String("graph-table", envOrDefault("DYNAMO_GRAPH_TABLE", "SpdxDependencyGraph"), "DynamoDB graph table")
	region := flag.String("region", envOrDefault("AWS_REGION", "us-east-1"), "AWS region")
	scanOutputBucket := envOrDefault("SCAN_OUTPUT_BUCKET", "")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "sbom-tree — Generate nested dependency tree JSON from DynamoDB graph\n\n")
		fmt.Fprintf(os.Stderr, "Modes:\n")
		fmt.Fprintf(os.Stderr, "  SQS consumer (default): polls SQS for generation requests\n")
		fmt.Fprintf(os.Stderr, "  One-shot (-once):       generates a single tree and exits\n\n")
		fmt.Fprintf(os.Stderr, "Flags:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nEnvironment variables:\n")
		fmt.Fprintf(os.Stderr, "  SQS_SBOM_TREE_URL   SQS queue URL (consumer mode)\n")
		fmt.Fprintf(os.Stderr, "  S3_BUCKET           Default for -bucket\n")
		fmt.Fprintf(os.Stderr, "  DYNAMO_GRAPH_TABLE  Default for -graph-table\n")
		fmt.Fprintf(os.Stderr, "  AWS_REGION          Default for -region\n")
		fmt.Fprintf(os.Stderr, "  SCAN_OUTPUT_BUCKET  Override bucket for tree JSON output\n")
	}

	flag.Parse()

	ctx, cancel := signal.NotifyContext(
		context.Background(), syscall.SIGINT, syscall.SIGTERM,
	)
	defer cancel()

	awsCfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(*region))
	if err != nil {
		log.Fatalf("[FATAL] Load AWS config: %v", err)
	}

	gen := treegen.New(awsCfg)

	if *once {
		if *sha == "" || *name == "" || *prefix == "" || *bucket == "" {
			flag.Usage()
			fmt.Fprintf(os.Stderr, "\nError: -sha, -name, -prefix, and -bucket are required in one-shot mode\n")
			os.Exit(1)
		}

		req := treegen.Request{
			ArtifactSHA:      *sha,
			ArtifactName:     *name,
			JobPrefix:        *prefix,
			Bucket:           *bucket,
			GraphTable:       *graphTable,
			ScanOutputBucket: scanOutputBucket,
		}

		if err := gen.Generate(ctx, req); err != nil {
			log.Fatalf("[FATAL] Generation failed: %v", err)
		}
		log.Println("[INFO] Done")
		return
	}

	// SQS consumer mode
	queueURL := os.Getenv("SQS_SBOM_TREE_URL")
	if queueURL == "" {
		flag.Usage()
		fmt.Fprintf(os.Stderr, "\nError: SQS_SBOM_TREE_URL is required in consumer mode\n")
		os.Exit(1)
	}

	c := consumer.New(awsCfg, queueURL, gen, scanOutputBucket)
	if err := c.Run(ctx); err != nil && ctx.Err() == nil {
		log.Fatalf("[FATAL] Consumer error: %v", err)
	}
}

func envOrDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
