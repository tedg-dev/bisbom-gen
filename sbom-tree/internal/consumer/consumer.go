// Package consumer polls an SQS queue for sbom-tree generation
// requests and dispatches them to the tree generator.
package consumer

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"

	"github.com/tedg-dev/omnibor-analysis/sbom-tree/internal/treegen"
)

// Consumer polls SQS for tree generation requests.
type Consumer struct {
	sqsClient        *sqs.Client
	queueURL         string
	generator        *treegen.Generator
	scanOutputBucket string // override upload bucket (from SCAN_OUTPUT_BUCKET)
}

// New creates a Consumer that polls the given SQS queue.
// scanOutputBucket may be empty; when set, tree JSON is uploaded there
// instead of the bucket specified in the SQS message.
func New(awsCfg aws.Config, queueURL string, gen *treegen.Generator, scanOutputBucket string) *Consumer {
	return &Consumer{
		sqsClient:        sqs.NewFromConfig(awsCfg),
		queueURL:         queueURL,
		generator:        gen,
		scanOutputBucket: scanOutputBucket,
	}
}

// Run polls for messages until the context is cancelled.
func (c *Consumer) Run(ctx context.Context) error {
	log.Printf("[INFO] Polling SQS: %s", c.queueURL)

	for {
		select {
		case <-ctx.Done():
			log.Println("[INFO] Shutting down consumer")
			return ctx.Err()
		default:
		}

		out, err := c.sqsClient.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
			QueueUrl:            &c.queueURL,
			MaxNumberOfMessages: 1,
			WaitTimeSeconds:     20,
		})
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			log.Printf("[WARN] ReceiveMessage error: %v", err)
			time.Sleep(5 * time.Second)
			continue
		}

		for _, msg := range out.Messages {
			c.handleMessage(ctx, msg)
		}
	}
}

// handleMessage processes a single SQS message.
func (c *Consumer) handleMessage(ctx context.Context, msg sqstypes.Message) {
	body := aws.ToString(msg.Body)
	log.Printf("[INFO] Received message: %s", body)

	var req treegen.Request
	if err := json.Unmarshal([]byte(body), &req); err != nil {
		log.Printf("[ERROR] Invalid message body: %v", err)
		c.deleteMessage(ctx, msg)
		return
	}

	if c.scanOutputBucket != "" {
		req.ScanOutputBucket = c.scanOutputBucket
	}

	if err := c.generator.Generate(ctx, req); err != nil {
		log.Printf("[ERROR] Tree generation failed for %s: %v",
			req.ArtifactSHA[:12], err)
		// Do NOT delete — SQS will retry after visibility timeout
		return
	}

	c.deleteMessage(ctx, msg)
}

// deleteMessage removes a processed message from the queue.
func (c *Consumer) deleteMessage(ctx context.Context, msg sqstypes.Message) {
	_, err := c.sqsClient.DeleteMessage(ctx, &sqs.DeleteMessageInput{
		QueueUrl:      &c.queueURL,
		ReceiptHandle: msg.ReceiptHandle,
	})
	if err != nil {
		log.Printf("[WARN] Delete message failed: %v", err)
	}
}
