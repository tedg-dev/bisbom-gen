package oidc

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/MicahParks/keyfunc/v2"
	"github.com/golang-jwt/jwt/v5"
)

// Validator verifies GitHub Actions OIDC tokens using JWKS
// endpoints and checks claims against the configured policy.
type Validator struct {
	cfg   *Config
	mu    sync.RWMutex
	jwks  map[string]*keyfunc.JWKS // issuer URL → cached JWKS
}

// NewValidator creates a Validator for the given OIDC config.
// Call Close() when done to release JWKS refresh goroutines.
func NewValidator(cfg *Config) *Validator {
	return &Validator{
		cfg:  cfg,
		jwks: make(map[string]*keyfunc.JWKS),
	}
}

// Close stops background JWKS refresh goroutines.
func (v *Validator) Close() {
	v.mu.Lock()
	defer v.mu.Unlock()
	for _, j := range v.jwks {
		j.EndBackground()
	}
}

// ValidateToken parses and validates an OIDC token string.
// It returns the parsed claims or an error with a reason code.
func (v *Validator) ValidateToken(ctx context.Context, tokenStr string) (*Claims, error) {
	// Peek at the unverified issuer to select the right JWKS
	parser := jwt.NewParser(jwt.WithoutClaimsValidation())
	unverified := &Claims{}
	if _, _, err := parser.ParseUnverified(tokenStr, unverified); err != nil {
		return nil, &ValidationError{Reason: ReasonInvalidSignature, Err: err}
	}

	issuer := ""
	if issuers, _ := unverified.GetIssuer(); issuers != "" {
		issuer = issuers
	}

	if !v.cfg.IsKnownIssuer(issuer) {
		return nil, &ValidationError{
			Reason: ReasonUnknownIssuer,
			Err:    fmt.Errorf("issuer %q not configured", issuer),
		}
	}

	jwksFunc, err := v.getJWKS(issuer)
	if err != nil {
		return nil, &ValidationError{
			Reason: ReasonInvalidSignature,
			Err:    fmt.Errorf("failed to fetch JWKS for %s: %w", issuer, err),
		}
	}

	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenStr, claims, jwksFunc,
		jwt.WithIssuer(issuer),
		jwt.WithExpirationRequired(),
	)
	if err != nil {
		if strings.Contains(err.Error(), "expired") {
			return nil, &ValidationError{Reason: ReasonExpiredToken, Err: err}
		}
		return nil, &ValidationError{Reason: ReasonInvalidSignature, Err: err}
	}

	if !token.Valid {
		return nil, &ValidationError{
			Reason: ReasonInvalidSignature,
			Err:    fmt.Errorf("token is not valid"),
		}
	}

	// Check audience if configured
	if v.cfg.Audience != "" {
		aud, _ := claims.GetAudience()
		found := false
		for _, a := range aud {
			if a == v.cfg.Audience {
				found = true
				break
			}
		}
		if !found {
			return nil, &ValidationError{
				Reason: ReasonInvalidAudience,
				Err:    fmt.Errorf("audience %v does not contain %q", aud, v.cfg.Audience),
			}
		}
	}

	return claims, nil
}

// ValidateOwnership checks whether the token originates from
// Cisco-controlled infrastructure using the 3-tier check:
//   - Tier 1: trusted GHE issuer (auto-pass)
//   - Tier 2: enterprise claim in allowlist
//   - Tier 3: repository_owner in org allowlist
func (v *Validator) ValidateOwnership(claims *Claims) error {
	issuer, _ := claims.GetIssuer()

	// Tier 1: trusted GHE issuer — all repos are Cisco-controlled
	if v.cfg.IsTrustedIssuer(issuer) {
		return nil
	}

	// Tier 2: enterprise claim (EMU / Enterprise Cloud)
	if claims.Enterprise != "" {
		for _, e := range v.cfg.EnterpriseAllowlist {
			if claims.Enterprise == e {
				return nil
			}
		}
		return &ValidationError{
			Reason: ReasonEnterpriseNotAllowed,
			Err:    fmt.Errorf("enterprise %q not in allowlist", claims.Enterprise),
		}
	}

	// Tier 3: org allowlist (legacy github.com orgs)
	for _, org := range v.cfg.OrgAllowlist {
		if claims.RepositoryOwner == org {
			return nil
		}
	}

	return &ValidationError{
		Reason: ReasonOrgNotAllowed,
		Err: fmt.Errorf("repository_owner %q not in org allowlist",
			claims.RepositoryOwner),
	}
}

// ValidateSub checks that the token's sub claim matches the
// requested repository, preventing token reuse across repos.
func (v *Validator) ValidateSub(claims *Claims, requestedRepo string) error {
	expectedPrefix := fmt.Sprintf("repo:%s:", requestedRepo)
	sub, _ := claims.GetSubject()
	if !strings.HasPrefix(sub, expectedPrefix) {
		return &ValidationError{
			Reason: ReasonSubMismatch,
			Err: fmt.Errorf("sub %q does not match repo %q",
				sub, requestedRepo),
		}
	}
	return nil
}

// getJWKS returns a cached JWKS keyfunc for the given issuer,
// fetching and caching it on first use.
func (v *Validator) getJWKS(issuer string) (jwt.Keyfunc, error) {
	v.mu.RLock()
	if j, ok := v.jwks[issuer]; ok {
		v.mu.RUnlock()
		return j.Keyfunc, nil
	}
	v.mu.RUnlock()

	v.mu.Lock()
	defer v.mu.Unlock()

	// Double-check after acquiring write lock
	if j, ok := v.jwks[issuer]; ok {
		return j.Keyfunc, nil
	}

	jwksURL := strings.TrimSuffix(issuer, "/") + "/.well-known/jwks"
	j, err := keyfunc.Get(jwksURL, keyfunc.Options{
		RefreshInterval: 1 * time.Hour,
		RefreshTimeout:  10 * time.Second,
	})
	if err != nil {
		return nil, err
	}

	v.jwks[issuer] = j
	return j.Keyfunc, nil
}
