package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/api"
	operatorconfig "github.com/tedg-dev/omnibor-analysis/operator/internal/config"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/consumer"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/oidc"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/whitelist"
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

	awsCfg, err := awsconfig.LoadDefaultConfig(ctx)
	if err != nil {
		log.Fatalf("[FATAL] Failed to load AWS config: %v", err)
	}

	// Build API server options
	var apiOpts []api.Option

	// Set up presigned URL broker if DATABASE_URL is configured
	var validator *oidc.Validator
	if cfg.DatabaseURL != "" {
		pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
		if err != nil {
			log.Fatalf("[FATAL] Failed to connect to database: %v", err)
		}
		defer pool.Close()

		store := whitelist.NewStore(pool)
		if err := store.Migrate(ctx); err != nil {
			log.Fatalf("[FATAL] Failed to migrate whitelist table: %v", err)
		}
		log.Printf("[INFO] Repo whitelist table ready")

		validator = oidc.NewValidator(cfg.OIDC)
		defer validator.Close()

		s3Client := s3.NewFromConfig(awsCfg)

		uploadHandler := api.NewUploadHandler(validator, store, s3Client, cfg.S3Bucket)
		whitelistHandler := api.NewWhitelistHandler(store)

		apiOpts = append(apiOpts,
			api.WithUploadHandler(uploadHandler),
			api.WithWhitelistHandler(whitelistHandler),
		)

		log.Printf("[INFO] Presigned URL broker enabled")
		log.Printf("[INFO] OIDC issuers: %v", cfg.OIDC.IssuerURLs())
	}

	// Start HTTP API server
	if cfg.DynamoTable != "" || len(apiOpts) > 0 {
		apiServer := api.New(awsCfg, cfg.DynamoTable, cfg.APIAddr, apiOpts...)
		go func() {
			if err := apiServer.Run(ctx); err != nil {
				log.Printf("[ERROR] API server exited: %v", err)
			}
		}()
	}

	// Start SQS consumer only if queue URL is configured
	if cfg.SQSQueueURL != "" {
		c, err := consumer.New(cfg)
		if err != nil {
			log.Fatalf("[FATAL] Failed to create consumer: %v", err)
		}

		if err := c.Run(ctx); err != nil {
			log.Fatalf("[FATAL] Consumer exited with error: %v", err)
		}
	} else {
		log.Printf("[INFO] SQS consumer disabled (no SQS_QUEUE_URL)")
		// Block until shutdown signal
		<-ctx.Done()
	}

	log.Printf("[INFO] Operator stopped")
}
