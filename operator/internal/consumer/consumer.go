package consumer

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/config"
)

const maxWaitTimeSeconds = 20

// Consumer polls SQS for S3 event notifications and triggers Phase 2.
type Consumer struct {
	cfg       *config.Config
	sqsClient *sqs.Client
	runner    *Runner
}

// New creates a Consumer with AWS clients configured from the environment.
func New(cfg *config.Config) (*Consumer, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(context.Background())
	if err != nil {
		return nil, fmt.Errorf("load AWS config: %w", err)
	}

	return &Consumer{
		cfg:       cfg,
		sqsClient: sqs.NewFromConfig(awsCfg),
		runner:    NewRunner(cfg, awsCfg),
	}, nil
}

// Run polls the SQS queue until the context is cancelled.
func (c *Consumer) Run(ctx context.Context) error {
	log.Printf("[INFO] Polling SQS queue (wait time: %ds)", maxWaitTimeSeconds)

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}

		out, err := c.sqsClient.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
			QueueUrl:              &c.cfg.SQSQueueURL,
			MaxNumberOfMessages:   1,
			WaitTimeSeconds:       maxWaitTimeSeconds,
			MessageAttributeNames: []string{"All"},
		})
		if err != nil {
			if ctx.Err() != nil {
				return nil // context cancelled during long poll
			}
			log.Printf("[ERROR] ReceiveMessage: %v", err)
			continue
		}

		for _, msg := range out.Messages {
			if err := c.handleMessage(ctx, msg); err != nil {
				// Test events and skippable messages should be deleted, not retried
				if errors.Is(err, errTestEvent) {
					log.Printf("[INFO] Skipping test event: %s", aws.ToString(msg.MessageId))
				} else if errors.Is(err, errFilesNotReady) {
					// Files not yet uploaded — let SQS retry after visibility timeout
					log.Printf("[WAIT] Files not ready for %s, will retry: %v",
						aws.ToString(msg.MessageId), err)
					continue
				} else {
					log.Printf("[ERROR] Failed to process message %s: %v",
						aws.ToString(msg.MessageId), err)
					continue
				}
			}

			// Delete message on success (or when skipping test events)
			_, delErr := c.sqsClient.DeleteMessage(ctx, &sqs.DeleteMessageInput{
				QueueUrl:      &c.cfg.SQSQueueURL,
				ReceiptHandle: msg.ReceiptHandle,
			})
			if delErr != nil {
				log.Printf("[ERROR] DeleteMessage %s: %v",
					aws.ToString(msg.MessageId), delErr)
			}
		}
	}
}

// handleMessage parses the S3 event from the SQS message, reads
// ssvs_meta.json, validates expected files are present, and routes
// the job based on what was uploaded.
func (c *Consumer) handleMessage(ctx context.Context, msg types.Message) error {
	body := aws.ToString(msg.Body)
	log.Printf("[INFO] Received message: %s", aws.ToString(msg.MessageId))

	s3Key, err := parseS3EventKey(body)
	if err != nil {
		return fmt.Errorf("parse S3 event: %w", err)
	}

	log.Printf("[INFO] S3 key: %s", s3Key)

	// Extract job prefix: <owner>/<repo>/<job_id>
	// S3 key: <owner>/<repo>/<job_id>/ssvs_meta.json
	jobPrefix, err := extractJobPrefix(s3Key)
	if err != nil {
		return fmt.Errorf("extract job prefix: %w", err)
	}

	// Read ssvs_meta.json — the file that triggered this notification
	meta, err := c.runner.ReadSsvsMeta(ctx, jobPrefix)
	if err != nil {
		return fmt.Errorf("read ssvs_meta.json: %w", err)
	}

	log.Printf("[INFO] Job prefix: %s repo: %s files: %v", jobPrefix, meta.Repository, meta.Files)

	// Validate that all declared files are present in S3
	if len(meta.Files) > 0 {
		if err := c.runner.ValidateFilesReady(ctx, jobPrefix, meta.Files); err != nil {
			return err // errFilesNotReady triggers SQS retry
		}
	}

	// Route based on what files were uploaded
	return c.routeJob(ctx, jobPrefix, meta)
}

// routeJob decides how to process the upload based on the declared files.
func (c *Consumer) routeJob(ctx context.Context, jobPrefix string, meta *SsvsMeta) error {
	hasPhase1 := false
	for _, f := range meta.Files {
		if f == "phase1.tar.gz" {
			hasPhase1 = true
			break
		}
	}

	if hasPhase1 {
		// Phase 1 artifacts present — launch sidecar for SPDX generation
		log.Printf("[INFO] Routing to Phase 2 sidecar (phase1.tar.gz present)")
		return c.runner.RunPhase2(ctx, jobPrefix, "phase1.tar.gz")
	}

	// No phase1.tar.gz — assume pre-built SPDX, route to indexing
	log.Printf("[INFO] No phase1.tar.gz — routing to index-only")
	return c.runner.IndexOnly(ctx, jobPrefix, meta)
}

// errTestEvent is returned when an S3 test event is received.
// S3 sends this once when bucket notifications are first configured.
var errTestEvent = errors.New("S3 test event (no records)")

// s3Event matches the structure of S3 event notifications sent via SQS.
type s3Event struct {
	Event   string `json:"Event"`
	Records []struct {
		S3 struct {
			Bucket struct {
				Name string `json:"name"`
			} `json:"bucket"`
			Object struct {
				Key string `json:"key"`
			} `json:"object"`
		} `json:"s3"`
	} `json:"Records"`
}

// parseS3EventKey extracts the S3 object key from an SQS message body.
func parseS3EventKey(body string) (string, error) {
	var event s3Event
	if err := json.Unmarshal([]byte(body), &event); err != nil {
		return "", fmt.Errorf("unmarshal S3 event: %w", err)
	}
	// S3 sends a test event when notifications are first configured:
	// {"Service":"Amazon S3","Event":"s3:TestEvent",...}
	if event.Event == "s3:TestEvent" || len(event.Records) == 0 {
		return "", errTestEvent
	}
	key := event.Records[0].S3.Object.Key
	if key == "" {
		return "", fmt.Errorf("empty S3 object key")
	}
	return key, nil
}

// extractJobPrefix returns the S3 prefix up to <owner>/<repo>/<job_id>
// from a key like kkaple/WebGoat/<job_id>/phase1/.../file.json
func extractJobPrefix(key string) (string, error) {
	// Split: [owner, repo, job_id, "phase1", ...]
	parts := strings.Split(key, "/")
	if len(parts) < 4 {
		return "", fmt.Errorf("key too short: %s", key)
	}
	// owner/repo/job_id
	return strings.Join(parts[:3], "/"), nil
}
