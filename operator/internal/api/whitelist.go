package api

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"

	"github.com/tedg-dev/omnibor-analysis/operator/internal/whitelist"
)

// WhitelistHandler provides tenant-scoped CRUD for the
// repo_whitelist table. All operations use X-SSVS-TENANT-ID
// and X-SSVS-USERNAME from the nginx gateway.
type WhitelistHandler struct {
	store *whitelist.Store
}

// NewWhitelistHandler creates a WhitelistHandler.
func NewWhitelistHandler(store *whitelist.Store) *WhitelistHandler {
	return &WhitelistHandler{store: store}
}

// ServeHTTP routes to list, add, or remove based on method and path.
//
//	GET  /v1/whitelist          → list repos for this tenant
//	POST /v1/whitelist          → add a repo for this tenant
//	DELETE /v1/whitelist/{id}   → remove a repo (only if this tenant owns it)
func (h *WhitelistHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	tenantID := r.Header.Get("X-SSVS-TENANT-ID")
	if tenantID == "" {
		http.Error(w, `{"error":"missing tenant context"}`, http.StatusForbidden)
		return
	}

	username := r.Header.Get("X-SSVS-USERNAME")

	switch r.Method {
	case http.MethodGet:
		h.handleList(w, r, tenantID)
	case http.MethodPost:
		h.handleAdd(w, r, tenantID, username)
	case http.MethodDelete:
		h.handleRemove(w, r, tenantID)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (h *WhitelistHandler) handleList(w http.ResponseWriter, r *http.Request, tenantID string) {
	entries, err := h.store.List(r.Context(), tenantID)
	if err != nil {
		log.Printf("[ERROR] whitelist list: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	if entries == nil {
		entries = []whitelist.Entry{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(entries)
}

type addRequest struct {
	Repository string `json:"repository"`
}

func (h *WhitelistHandler) handleAdd(w http.ResponseWriter, r *http.Request, tenantID, username string) {
	var req addRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Repository == "" {
		http.Error(w, `{"error":"repository is required"}`, http.StatusBadRequest)
		return
	}

	// Validate format: must be "owner/repo"
	parts := strings.Split(req.Repository, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		http.Error(w, `{"error":"repository must be in owner/repo format"}`, http.StatusBadRequest)
		return
	}

	entry, err := h.store.Add(r.Context(), tenantID, req.Repository, username)
	if err != nil {
		if strings.Contains(err.Error(), "duplicate key") ||
			strings.Contains(err.Error(), "unique constraint") {
			http.Error(w, `{"error":"repository already whitelisted for this tenant"}`, http.StatusConflict)
			return
		}
		log.Printf("[ERROR] whitelist add: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	log.Printf("[WHITELIST] tenant=%s user=%s added repo=%s", tenantID, username, req.Repository)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(entry)
}

func (h *WhitelistHandler) handleRemove(w http.ResponseWriter, r *http.Request, tenantID string) {
	// Extract entry ID from path: /v1/whitelist/{id}
	entryID := strings.TrimPrefix(r.URL.Path, "/v1/whitelist/")
	if entryID == "" || entryID == r.URL.Path {
		http.Error(w, `{"error":"entry ID required in path"}`, http.StatusBadRequest)
		return
	}

	deleted, err := h.store.Remove(r.Context(), entryID, tenantID)
	if err != nil {
		log.Printf("[ERROR] whitelist remove: %v", err)
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}

	if !deleted {
		http.Error(w, `{"error":"not found or not owned by this tenant"}`, http.StatusNotFound)
		return
	}

	username := r.Header.Get("X-SSVS-USERNAME")
	log.Printf("[WHITELIST] tenant=%s user=%s removed entry=%s", tenantID, username, entryID)

	w.WriteHeader(http.StatusNoContent)
}
