// Package oidc provides GitHub Actions OIDC token validation
// with 3-tier Cisco ownership verification.
package oidc

// IssuerConfig describes a single OIDC issuer.
type IssuerConfig struct {
	URL  string `yaml:"url"`
	Type string `yaml:"type"` // "github.com" or "ghe"
}

// Config holds OIDC validation settings loaded from YAML or
// environment variables. Issuers are the allowed token issuers.
// EnterpriseAllowlist and OrgAllowlist provide the 3-tier
// Cisco ownership check for github.com tokens.
type Config struct {
	Audience            string         `yaml:"audience"`
	Issuers             []IssuerConfig `yaml:"issuers"`
	EnterpriseAllowlist []string       `yaml:"enterprise_allowlist"`
	OrgAllowlist        []string       `yaml:"org_allowlist"`
}

// IssuerURLs returns all configured issuer URLs.
func (c *Config) IssuerURLs() []string {
	urls := make([]string, len(c.Issuers))
	for i, iss := range c.Issuers {
		urls[i] = iss.URL
	}
	return urls
}

// IsKnownIssuer checks whether the given issuer URL is configured.
func (c *Config) IsKnownIssuer(issuer string) bool {
	for _, iss := range c.Issuers {
		if iss.URL == issuer {
			return true
		}
	}
	return false
}

// IsTrustedIssuer checks whether the issuer is a GHE instance
// (Tier 1) where all repos are auto-trusted.
func (c *Config) IsTrustedIssuer(issuer string) bool {
	for _, iss := range c.Issuers {
		if iss.URL == issuer && iss.Type == "ghe" {
			return true
		}
	}
	return false
}
