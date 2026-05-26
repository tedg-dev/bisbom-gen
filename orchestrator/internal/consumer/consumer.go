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

	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/config"
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

// handleMessage parses the S3 event from the SQS message and triggers Phase 2.
func (c *Consumer) handleMessage(ctx context.Context, msg types.Message) error {
	body := aws.ToString(msg.Body)
	log.Printf("[INFO] Received message: %s", aws.ToString(msg.MessageId))

	s3Key, err := parseS3EventKey(body)
	if err != nil {
		return fmt.Errorf("parse S3 event: %w", err)
	}

	log.Printf("[INFO] S3 key: %s", s3Key)

	// Extract path components:
	// java/omnibor-java-testapp/<sha>/<run_id>/phase1/.../<filename>
	// We need the prefix up to and including <run_id>
	jobPrefix, err := extractJobPrefix(s3Key)
	if err != nil {
		return fmt.Errorf("extract job prefix: %w", err)
	}

	log.Printf("[INFO] Job prefix: %s", jobPrefix)
	return c.runner.RunPhase2(ctx, jobPrefix)
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

// extractJobPrefix returns the S3 prefix up to <lang>/<repo>/<sha>/<run_id>
// from a key like java/omnibor-java-testapp/<sha>/<run_id>/phase1/.../file.json
func extractJobPrefix(key string) (string, error) {
	// Split: [lang, repo, sha, run_id, "phase1", ...]
	parts := strings.Split(key, "/")
	if len(parts) < 5 {
		return "", fmt.Errorf("key too short: %s", key)
	}
	// lang/repo/sha/run_id
	return strings.Join(parts[:4], "/"), nil
}
