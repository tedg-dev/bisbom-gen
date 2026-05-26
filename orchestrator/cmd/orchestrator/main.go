package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/config"
	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/consumer"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("[FATAL] Failed to load config: %v", err)
	}

	log.Printf("[INFO] Starting orchestrator")
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

	c, err := consumer.New(cfg)
	if err != nil {
		log.Fatalf("[FATAL] Failed to create consumer: %v", err)
	}

	if err := c.Run(ctx); err != nil {
		log.Fatalf("[FATAL] Consumer exited with error: %v", err)
	}

	log.Printf("[INFO] Orchestrator stopped")
}
