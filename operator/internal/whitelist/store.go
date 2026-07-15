// Package whitelist provides tenant-scoped CRUD and upload
// validation queries for the repo_whitelist table.
package whitelist

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Entry represents a single repo_whitelist row.
type Entry struct {
	ID         string    `json:"id"`
	TenantID   string    `json:"tenant_id"`
	Repository string    `json:"repository"`
	AddedBy    string    `json:"added_by"`
	Enabled    bool      `json:"enabled"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

// Store provides database operations for the repo_whitelist table.
type Store struct {
	pool *pgxpool.Pool
}

// NewStore creates a Store backed by the given connection pool.
func NewStore(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// Migrate creates the repo_whitelist table if it does not exist.
func (s *Store) Migrate(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS repo_whitelist (
			id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
			tenant_id       UUID NOT NULL,
			repository      TEXT NOT NULL,
			added_by        TEXT NOT NULL,
			enabled         BOOLEAN NOT NULL DEFAULT TRUE,
			created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			UNIQUE(tenant_id, repository)
		)
	`)
	if err != nil {
		return fmt.Errorf("create repo_whitelist table: %w", err)
	}

	_, err = s.pool.Exec(ctx, `
		CREATE INDEX IF NOT EXISTS idx_repo_whitelist_repo
		ON repo_whitelist(repository)
	`)
	if err != nil {
		return fmt.Errorf("create repo index: %w", err)
	}

	_, err = s.pool.Exec(ctx, `
		CREATE INDEX IF NOT EXISTS idx_repo_whitelist_tenant
		ON repo_whitelist(tenant_id)
	`)
	if err != nil {
		return fmt.Errorf("create tenant index: %w", err)
	}

	return nil
}

// IsRepoWhitelisted checks whether the given tenant has
// whitelisted the given repository. Used during upload-url
// validation — scoped to the requesting tenant's entries.
func (s *Store) IsRepoWhitelisted(ctx context.Context, tenantID, repository string) (bool, error) {
	var exists bool
	err := s.pool.QueryRow(ctx, `
		SELECT EXISTS(
			SELECT 1 FROM repo_whitelist
			WHERE tenant_id = $1 AND repository = $2 AND enabled = TRUE
		)
	`, tenantID, repository).Scan(&exists)
	if err != nil {
		return false, fmt.Errorf("check whitelist: %w", err)
	}
	return exists, nil
}

// List returns all whitelist entries for the given tenant.
// Tenant-scoped: only returns entries owned by this tenant.
func (s *Store) List(ctx context.Context, tenantID string) ([]Entry, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, tenant_id, repository, added_by, enabled, created_at, updated_at
		FROM repo_whitelist
		WHERE tenant_id = $1
		ORDER BY created_at DESC
	`, tenantID)
	if err != nil {
		return nil, fmt.Errorf("list whitelist: %w", err)
	}
	defer rows.Close()

	var entries []Entry
	for rows.Next() {
		var e Entry
		if err := rows.Scan(&e.ID, &e.TenantID, &e.Repository, &e.AddedBy,
			&e.Enabled, &e.CreatedAt, &e.UpdatedAt); err != nil {
			return nil, fmt.Errorf("scan whitelist row: %w", err)
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// Add inserts a new whitelist entry for the given tenant.
// Returns the created entry.
func (s *Store) Add(ctx context.Context, tenantID, repository, addedBy string) (*Entry, error) {
	var e Entry
	err := s.pool.QueryRow(ctx, `
		INSERT INTO repo_whitelist (tenant_id, repository, added_by)
		VALUES ($1, $2, $3)
		RETURNING id, tenant_id, repository, added_by, enabled, created_at, updated_at
	`, tenantID, repository, addedBy).Scan(
		&e.ID, &e.TenantID, &e.Repository, &e.AddedBy,
		&e.Enabled, &e.CreatedAt, &e.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("add to whitelist: %w", err)
	}
	return &e, nil
}

// Remove deletes a whitelist entry by ID, but only if it
// belongs to the specified tenant. Returns true if a row
// was deleted.
func (s *Store) Remove(ctx context.Context, entryID, tenantID string) (bool, error) {
	tag, err := s.pool.Exec(ctx, `
		DELETE FROM repo_whitelist
		WHERE id = $1 AND tenant_id = $2
	`, entryID, tenantID)
	if err != nil {
		return false, fmt.Errorf("remove from whitelist: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}
