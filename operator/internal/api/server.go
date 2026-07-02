// Package api provides a lightweight HTTP server for querying
// artifact S3 locations from the SpdxIndexTable.
package api

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	dbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

// ArtifactResponse is the JSON payload returned by GET /artifact-s3/<sha>.
type ArtifactResponse struct {
	ArtifactSHA    string `json:"artifactSHA"`
	AnalyzedSpdxS3 string `json:"analyzedSpdxS3,omitempty"`
	BuildSpdxS3    string `json:"buildSpdxS3,omitempty"`
	SbomTreeS3     string `json:"sbomTreeS3,omitempty"`
	ArtifactPath   string `json:"artifactPath,omitempty"`
	RepoName       string `json:"repoName,omitempty"`
	Language       string `json:"language,omitempty"`
	CommitSHA      string `json:"commitSHA,omitempty"`
	VcsURI         string `json:"vcsURI,omitempty"`
}

// Server is the HTTP API server.
type Server struct {
	dynamoClient *dynamodb.Client
	table        string
	httpServer   *http.Server
}

// New creates an API server that reads from the given DynamoDB table.
func New(awsCfg aws.Config, table, addr string) *Server {
	s := &Server{
		dynamoClient: dynamodb.NewFromConfig(awsCfg),
		table:        table,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/artifact-s3/", s.handleArtifactS3)
	mux.HandleFunc("/healthz", s.handleHealthz)

	s.httpServer = &http.Server{
		Addr:    addr,
		Handler: mux,
	}
	return s
}

// Run starts the HTTP server. It blocks until the context is cancelled,
// then performs a graceful shutdown.
func (s *Server) Run(ctx context.Context) error {
	log.Printf("[API] Listening on %s", s.httpServer.Addr)

	errCh := make(chan error, 1)
	go func() {
		if err := s.httpServer.ListenAndServe(); err != http.ErrServerClosed {
			errCh <- err
		}
		close(errCh)
	}()

	select {
	case <-ctx.Done():
		log.Println("[API] Shutting down HTTP server")
		return s.httpServer.Shutdown(context.Background())
	case err := <-errCh:
		return fmt.Errorf("http server: %w", err)
	}
}

// handleHealthz returns 200 OK for load balancer health checks.
func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	fmt.Fprintln(w, "ok")
}

// handleArtifactS3 looks up an artifact SHA in DynamoDB and returns
// the S3 locations as JSON.
func (s *Server) handleArtifactS3(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	sha := strings.TrimPrefix(r.URL.Path, "/artifact-s3/")
	if sha == "" {
		http.Error(w, "missing artifact SHA", http.StatusBadRequest)
		return
	}

	out, err := s.dynamoClient.GetItem(r.Context(), &dynamodb.GetItemInput{
		TableName: &s.table,
		Key: map[string]dbtypes.AttributeValue{
			"ArtifactSHA": &dbtypes.AttributeValueMemberS{Value: sha},
		},
	})
	if err != nil {
		log.Printf("[API] DynamoDB error for %s: %v", sha[:min(12, len(sha))], err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	if out.Item == nil {
		http.Error(w, "artifact not found", http.StatusNotFound)
		return
	}

	resp := ArtifactResponse{
		ArtifactSHA:    strVal(out.Item, "ArtifactSHA"),
		AnalyzedSpdxS3: strVal(out.Item, "AnalyzedSpdxS3"),
		BuildSpdxS3:    strVal(out.Item, "BuildSpdxS3"),
		SbomTreeS3:     strVal(out.Item, "SbomTreeS3"),
		ArtifactPath:   strVal(out.Item, "ArtifactPath"),
		RepoName:       strVal(out.Item, "RepoName"),
		Language:       strVal(out.Item, "Language"),
		CommitSHA:      strVal(out.Item, "CommitSHA"),
		VcsURI:         strVal(out.Item, "VcsURI"),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// strVal extracts a string attribute from a DynamoDB item.
func strVal(item map[string]dbtypes.AttributeValue, key string) string {
	if v, ok := item[key].(*dbtypes.AttributeValueMemberS); ok {
		return v.Value
	}
	return ""
}
