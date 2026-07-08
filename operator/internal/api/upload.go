package api

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/oidc"
	"github.com/tedg-dev/omnibor-analysis/operator/internal/whitelist"
)

// UploadURLRequest is the JSON body for POST /v1/upload-url.
type UploadURLRequest struct {
	Repository string   `json:"repository"`
	JobID      string   `json:"job_id"`
	Files      []string `json:"files"`
}

// UploadURLResponse contains presigned URLs keyed by filename.
type UploadURLResponse struct {
	URLs map[string]string `json:"urls"`
}

// UploadHandler handles POST /v1/upload-url requests.
// It validates the OIDC token, checks ownership and whitelist,
// then returns presigned S3 PUT URLs.
type UploadHandler struct {
	validator      *oidc.Validator
	whitelistStore *whitelist.Store
	s3Presigner    *s3.PresignClient
	bucket         string
}

// NewUploadHandler creates an UploadHandler.
func NewUploadHandler(
	validator *oidc.Validator,
	store *whitelist.Store,
	s3Client *s3.Client,
	bucket string,
) *UploadHandler {
	return &UploadHandler{
		validator:      validator,
		whitelistStore: store,
		s3Presigner:    s3.NewPresignClient(s3Client),
		bucket:         bucket,
	}
}

// ServeHTTP handles the upload-url endpoint.
func (h *UploadHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Extract Bearer token
	authHeader := r.Header.Get("Authorization")
	if !strings.HasPrefix(authHeader, "Bearer ") {
		http.Error(w, `{"error":"missing Authorization header"}`, http.StatusUnauthorized)
		return
	}
	tokenStr := strings.TrimPrefix(authHeader, "Bearer ")

	// Parse request body
	var req UploadURLRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}
	if req.Repository == "" || req.JobID == "" || len(req.Files) == 0 {
		http.Error(w, `{"error":"repository, job_id, and files are required"}`, http.StatusBadRequest)
		return
	}

	// Step 1: Validate token signature + standard claims
	claims, err := h.validator.ValidateToken(r.Context(), tokenStr)
	if err != nil {
		h.rejectWithLog(w, http.StatusUnauthorized, err, claims)
		return
	}

	// Step 2: Validate Cisco ownership (3-tier)
	if err := h.validator.ValidateOwnership(claims); err != nil {
		h.rejectWithLog(w, http.StatusForbidden, err, claims)
		return
	}

	// Step 3: Check repo whitelist
	whitelisted, err := h.whitelistStore.IsRepoWhitelisted(r.Context(), req.Repository)
	if err != nil {
		log.Printf("[ERROR] whitelist check failed: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	if !whitelisted {
		verr := &oidc.ValidationError{
			Reason: oidc.ReasonRepoNotWhitelisted,
			Err:    fmt.Errorf("repository %q not whitelisted", req.Repository),
		}
		h.rejectWithLog(w, http.StatusForbidden, verr, claims)
		return
	}

	// Step 4: Validate sub claim matches requested repo
	if err := h.validator.ValidateSub(claims, req.Repository); err != nil {
		h.rejectWithLog(w, http.StatusForbidden, err, claims)
		return
	}

	// All checks passed — generate presigned URLs
	urls, err := h.generatePresignedURLs(r.Context(), req)
	if err != nil {
		log.Printf("[ERROR] presign failed: %v", err)
		http.Error(w, `{"error":"failed to generate presigned URLs"}`, http.StatusInternalServerError)
		return
	}

	log.Printf("[OIDC OK] repo=%s actor=%s job=%s files=%d",
		req.Repository, claims.Actor, req.JobID, len(req.Files))

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(UploadURLResponse{URLs: urls})
}

// rejectWithLog logs the rejection and sends an HTTP error.
func (h *UploadHandler) rejectWithLog(w http.ResponseWriter, status int, err error, claims *oidc.Claims) {
	reason := "unknown"
	if ve, ok := err.(*oidc.ValidationError); ok {
		reason = ve.Reason
	}
	oidc.LogRejection(reason, claims)

	resp := map[string]string{"error": reason}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(resp)
}

// generatePresignedURLs creates scoped S3 PUT URLs for each file.
func (h *UploadHandler) generatePresignedURLs(ctx context.Context, req UploadURLRequest) (map[string]string, error) {
	urls := make(map[string]string, len(req.Files))

	for _, file := range req.Files {
		key := fmt.Sprintf("%s/%s/%s", req.Repository, req.JobID, file)
		presigned, err := h.s3Presigner.PresignPutObject(ctx,
			&s3.PutObjectInput{
				Bucket: aws.String(h.bucket),
				Key:    aws.String(key),
			},
			func(opts *s3.PresignOptions) {
				opts.Expires = 15 * time.Minute
			},
		)
		if err != nil {
			return nil, fmt.Errorf("presign %s: %w", key, err)
		}
		urls[file] = presigned.URL
	}

	return urls, nil
}
