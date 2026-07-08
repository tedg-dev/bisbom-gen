package oidc

import (
	"fmt"
	"log"
	"time"
)

// Rejection reason codes logged on every denied token.
const (
	ReasonInvalidSignature      = "invalid_signature"
	ReasonExpiredToken          = "expired_token"
	ReasonUnknownIssuer         = "unknown_issuer"
	ReasonInvalidAudience       = "invalid_audience"
	ReasonEnterpriseNotAllowed  = "enterprise_not_allowed"
	ReasonOrgNotAllowed         = "org_not_allowed"
	ReasonRepoNotWhitelisted    = "repo_not_whitelisted"
	ReasonSubMismatch           = "sub_mismatch"
)

// ValidationError carries a machine-readable reason code
// alongside the human-readable error message.
type ValidationError struct {
	Reason string
	Err    error
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("%s: %v", e.Reason, e.Err)
}

func (e *ValidationError) Unwrap() error {
	return e.Err
}

// LogRejection writes a structured rejection log entry.
// All fields are extracted from token claims — no secrets.
func LogRejection(reason string, claims *Claims) {
	issuer := ""
	if claims != nil {
		issuers, _ := claims.GetIssuer()
		issuer = issuers
	}

	enterprise := ""
	owner := ""
	repo := ""
	actor := ""
	ref := ""
	runnerEnv := ""
	workflowRef := ""
	sub := ""

	if claims != nil {
		enterprise = claims.Enterprise
		owner = claims.RepositoryOwner
		repo = claims.Repository
		actor = claims.Actor
		ref = claims.Ref
		runnerEnv = claims.RunnerEnv
		workflowRef = claims.WorkflowRef
		sub, _ = claims.GetSubject()
	}

	log.Printf("[OIDC REJECT] ts=%s reason=%s iss=%s enterprise=%s owner=%s repo=%s actor=%s ref=%s runner=%s workflow=%s sub=%s",
		time.Now().UTC().Format(time.RFC3339),
		reason,
		issuer,
		enterprise,
		owner,
		repo,
		actor,
		ref,
		runnerEnv,
		workflowRef,
		sub,
	)
}
