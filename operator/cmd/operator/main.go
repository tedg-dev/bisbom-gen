package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/api"
	operatorconfig "github.com/tedg-dev/omnibor-analysis/operator/internal/config"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/consumer"
)

func main() {
	cfg, err := operatorconfig.Load()
	if err != nil {
		log.Fatalf("[FATAL] Failed to load config: %v", err)
	}

	log.Printf("[INFO] Starting operator")
	log.Printf("[INFO] Launch Mode: %s", cfg.LaunchMode)
	log.Printf("[INFO] SQS Queue: %s", cfg.SQSQueueURL)
	log.Printf("[INFO] S3 Bucket: %s", cfg.S3Bucket)
	log.Printf("[INFO] Sidecar Image: %s", cfg.SidecarImage)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Graceful shutdown on SIGINT/SIGTERM
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		sig := <-sigCh
		log.Printf("[INFO] Received %s, shutting down...", sig)
		cancel()
	}()

	// Start HTTP API server in a goroutine if DynamoDB indexing is enabled
	if cfg.DynamoTable != "" {
		awsCfg, err := awsconfig.LoadDefaultConfig(ctx)
		if err != nil {
			log.Fatalf("[FATAL] Failed to load AWS config for API: %v", err)
		}
		apiServer := api.New(awsCfg, cfg.DynamoTable, cfg.APIAddr)
		go func() {
			if err := apiServer.Run(ctx); err != nil {
				log.Printf("[ERROR] API server exited: %v", err)
			}
		}()
	}

	c, err := consumer.New(cfg)
	if err != nil {
		log.Fatalf("[FATAL] Failed to create consumer: %v", err)
	}

	if err := c.Run(ctx); err != nil {
		log.Fatalf("[FATAL] Consumer exited with error: %v", err)
	}

	log.Printf("[INFO] Operator stopped")
}
