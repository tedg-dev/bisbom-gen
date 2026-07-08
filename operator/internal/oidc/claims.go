package oidc

import "github.com/golang-jwt/jwt/v5"

// Claims represents the GitHub Actions OIDC token claims.
// Standard JWT claims are embedded; custom GitHub claims
// are explicit fields with JSON tags matching the token payload.
type Claims struct {
	jwt.RegisteredClaims

	// GitHub custom claims
	Actor           string `json:"actor"`
	ActorID         string `json:"actor_id"`
	Enterprise      string `json:"enterprise,omitempty"`
	EnterpriseID    string `json:"enterprise_id,omitempty"`
	Repository      string `json:"repository"`
	RepositoryID    string `json:"repository_id"`
	RepositoryOwner string `json:"repository_owner"`
	RepositoryOwnerID string `json:"repository_owner_id"`
	RepositoryVisibility string `json:"repository_visibility"`
	Ref             string `json:"ref"`
	RefType         string `json:"ref_type"`
	EventName       string `json:"event_name"`
	RunID           string `json:"run_id"`
	RunNumber       string `json:"run_number"`
	RunAttempt      string `json:"run_attempt"`
	RunnerEnv       string `json:"runner_environment"`
	Workflow        string `json:"workflow"`
	WorkflowRef     string `json:"workflow_ref"`
	WorkflowSHA     string `json:"workflow_sha"`
	JobWorkflowRef  string `json:"job_workflow_ref"`
}
