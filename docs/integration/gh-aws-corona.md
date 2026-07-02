# S3 Federated Uploads — Presigned URL Broker Architecture

> **Supersedes:** [`deprecated/gh-aws-corona.md`](deprecated/gh-aws-corona.md)
> (direct OIDC federation from CI runners to AWS).
>
> **Tag:** `pre-presigned-url-refactor` marks the last commit before
> this refactor.

## Table of Contents

- [Overview](#overview)
- [Why Presigned URLs Replace Direct OIDC Federation](#why-presigned-urls-replace-direct-oidc-federation)
- [S3 Path Structure](#s3-path-structure)
  - [Workflow ↔ Operator Contract](#workflow--operator-contract)
- [AWS Setup](#aws-setup)
  - [Step 1: Create the S3 Bucket](#step-1-create-the-s3-bucket)
  - [Step 2: Operator IAM Role](#step-2-operator-iam-role)
- [Presigned URL Broker (`/v1/upload-url`)](#presigned-url-broker-v1upload-url)
  - [Endpoint Specification](#endpoint-specification)
  - [OIDC Token Validation](#oidc-token-validation)
  - [Org Enrollment](#org-enrollment)
  - [Presigned URL Generation](#presigned-url-generation)
  - [Security Properties](#security-properties)
- [Sidecar Upload Flow](#sidecar-upload-flow)
  - [Sidecar Responsibilities](#sidecar-responsibilities)
  - [Upload Sequence](#upload-sequence)
- [GitHub Actions Workflow](#github-actions-workflow)
  - [What's OmniBOR-Specific?](#whats-omnibor-specific)
  - [Reference Workflow](#reference-workflow)
  - [Triggering the Workflow](#triggering-the-workflow)
- [Jenkins Variant](#jenkins-variant)
  - [What Changes for Jenkins](#what-changes-for-jenkins)
  - [What Does NOT Change](#what-does-not-change)
  - [Minimal Jenkinsfile Skeleton](#minimal-jenkinsfile-skeleton)
- [Phase 2 Consumer Architecture](#phase-2-consumer-architecture)
  - [Event-Driven Flow](#event-driven-flow)
  - [Container Launch Options](#container-launch-options)
  - [Operator Microservice Logic](#operator-microservice-logic)
- [ECS Deployment via AWS CDK](#ecs-deployment-via-aws-cdk)
  - [Architecture](#architecture)
  - [CDK Stack (TypeScript)](#cdk-stack-typescript)
  - [Key Design Decisions](#key-design-decisions)
  - [Cost Estimate (low volume)](#cost-estimate-low-volume)
- [SPDX Post-Processing Pipeline](#spdx-post-processing-pipeline)
- [SPDX Indexing via DynamoDB](#spdx-indexing-via-dynamodb)
  - [DynamoDB Table Schema](#dynamodb-table-schema)
  - [Client Lookup](#client-lookup)
  - [Dependency Graph Table (`SpdxDependencyGraph`)](#dependency-graph-table-spdxdependencygraph)
- [SBOM Tree Generator](#sbom-tree-generator)
- [Tenant Integration & SBOM Subscriptions](#tenant-integration--sbom-subscriptions)
  - [Tenant Service Overview](#tenant-service-overview)
  - [Tenant ID Without Foreign Keys](#tenant-id-without-foreign-keys)
  - [Upload Authorization vs. SBOM Consumption](#upload-authorization-vs-sbom-consumption)
  - [Operator Database Schema (PostgreSQL)](#operator-database-schema-postgresql)
  - [SBOM Subscription API](#sbom-subscription-api)
  - [Notification Fan-Out Flow](#notification-fan-out-flow)
  - [S3 Storage Is Repo-Scoped, Not Tenant-Scoped](#s3-storage-is-repo-scoped-not-tenant-scoped)
- [Appendix: Migration from Direct OIDC](#appendix-migration-from-direct-oidc)
- [Production Sub-Issues](#production-sub-issues)

## Overview

This document describes the enterprise deployment architecture for
OmniBOR SBOM generation. The system uses a **presigned URL broker**
on the operator to eliminate per-org IAM trust policies, enabling
scalable onboarding across hundreds of GitHub organizations.

Key design points:

- **S3** replaces GitHub Actions artifacts as the transport between
  Phase 1 and Phase 2
- **Presigned URLs** replace direct OIDC federation — the operator
  validates CI tokens and returns scoped, time-limited S3 upload URLs
- **The sidecar handles uploads** — CI workflows no longer need AWS
  credentials or the `aws` CLI
- **Hierarchical SBOM** — nested JSON tree-based dependency output for
  hierarchical dependency tracking
- **Tenant integration** — the operator integrates with the SSVS
  tenant service for multi-tenant isolation; tenant IDs are logical
  partition keys (no cross-database foreign keys)
- **SBOM subscriptions** — tenants opt-in to repos they care about;
  upload authorization (org-scoped) is decoupled from SBOM
  consumption (tenant-scoped), so multiple teams can subscribe to the
  same repo's SBOMs independently

This models the enterprise deployment pattern: the build site runs the
sidecar (Phase 1), the sidecar requests a presigned URL from the
operator, uploads artifacts to S3, and the operator pulls from S3 to
run Phase 2 (SPDX generation). After SPDX is indexed, the operator
notifies all subscribed tenants via NATS.

## Why Presigned URLs Replace Direct OIDC Federation

The [previous architecture](deprecated/gh-aws-corona.md) used direct
OIDC federation between each CI system and AWS IAM. Each GitHub org
needed a `sub` condition entry in the IAM trust policy.

**Problem at scale:** With ~900 organizations, the IAM trust policy
hits the 4,096-character limit. Sharding across multiple IAM roles
creates operational overhead — every new org requires an IAM policy
update.

**Solution:** Move authentication to the operator. The operator already
runs as a long-lived service with an IAM role that has S3 access. By
adding a `/v1/upload-url` endpoint, it becomes a **presigned URL
broker**:

```
┌──────────────────┐   ① OIDC token    ┌──────────────────┐
│  CI Runner       │ ────────────────→  │  Operator        │
│  (sidecar)       │                    │  /v1/upload-url  │
│                  │   ② presigned URLs │                  │
│                  │ ←────────────────  │                  │
│                  │                    └────────┬─────────┘
│                  │   ③ HTTP PUT                │
│                  │ ────────────────→  ┌────────┴─────────┐
└──────────────────┘                    │       S3         │
                                        └──────────────────┘
```

| Aspect | Direct OIDC (deprecated) | Presigned URL broker |
|--------|--------------------------|----------------------|
| **IAM trust policy entries** | 1 per org (doesn't scale) | 0 — operator has 1 role |
| **AWS SDK in CI** | Required (`aws s3 cp`) | Not needed (HTTP PUT) |
| **CI-specific permissions** | `id-token: write` + `role-to-assume` | `id-token: write` only |
| **Org enrollment** | IAM policy JSON edit | Database/config entry |
| **Audit** | CloudTrail (coarse) | Operator logs (fine-grained) |
| **New CI system support** | New IAM OIDC provider | Just present an OIDC token |

## S3 Path Structure

All artifacts for a build are stored under a single job directory:

```
s3://omnibor-spdx-artifacts/<owner>/<repo>/<datetime>_<sha12>_<run_id>/
├── phase1/    ← treedb, dep:tree, manifest (Phase 2 inputs)
├── build/     ← JARs, class files (optional)
└── spdx/      ← all SPDX outputs (flat, colocated)
    ├── <artifact>_build.spdx.json
    ├── <artifact>_analyzed.spdx.json
    ├── <artifact>.spdx.html
    └── <artifact>-sbom-tree.json
```

- **No language prefix** — the repo owner/name provides sufficient context
- **Full repo name** — `<owner>/<repo>` (e.g., `kkaple/WebGoat`) from `github.repository`
- **Job ID** — `<datetime>_<sha12>_<run_id>` is a single directory combining
  UTC timestamp, first 12 chars of commit SHA, and GitHub Actions run ID
- **Flat spdx/** — all SPDX documents, HTML reports, and sbom-tree JSON
  are colocated under one `spdx/` folder
- **run_id** — links back to `https://github.com/<owner>/<repo>/actions/runs/<run_id>`

To list everything for a specific repo:

```bash
aws s3 ls s3://omnibor-spdx-artifacts/kkaple/WebGoat/ --recursive
```

### Workflow ↔ Operator Contract

The S3 path structure is a **contract between two systems**:

| Component | Role | Code location |
|-----------|------|---------------|
| **Sidecar (in CI)** | Produces the S3 path (uploads Phase 1 artifacts via presigned URLs) | sidecar upload module |
| **Operator** | Validates tokens, issues presigned URLs, consumes S3 events | `operator/internal/` |

**Producer side (sidecar):** The sidecar constructs the job directory
from `github.repository`, a UTC timestamp, the first 12 characters of
`github.sha`, and `github.run_id`. It sends these to the operator's
`/v1/upload-url` endpoint and receives scoped presigned URLs.

**Consumer side (operator):** When S3 event notifications arrive via SQS,
the operator extracts the first 3 path components as the **job prefix**:

```
S3 key: kkaple/WebGoat/20260603-153000_8c3a1710b358_26894443338/phase1/.../manifest.json
                │          │                    │
                └──────────┴────────────────────┘
                     job prefix (3 parts)
                   owner / repo / job_id
```

**Checklist when onboarding a new repo:**

1. Ensure the org is enrolled in the operator's allowlist
2. Add the sidecar step to the repo's CI workflow
3. Pass `ACTIONS_ID_TOKEN` and `OPERATOR_URL` to the sidecar
4. The sidecar handles S3 path construction and upload — no AWS CLI needed

## AWS Setup

### Step 1: Create the S3 Bucket

```bash
aws s3api create-bucket --bucket omnibor-spdx-artifacts --region us-east-1
```

### Step 2: Operator IAM Role

The operator is the **only service that needs direct AWS credentials**.
No CI runner, no GitHub Actions workflow, no Jenkins job needs an IAM
role or AWS access keys.

**Operator permissions policy** (`/tmp/operator-policy.json`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ReadWrite",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::omnibor-spdx-artifacts/*"
    },
    {
      "Sid": "S3List",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::omnibor-spdx-artifacts"
    },
    {
      "Sid": "SQS",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:SendMessage"
      ],
      "Resource": [
        "arn:aws:sqs:us-east-1:930218373905:omnibor-phase1-notifications",
        "arn:aws:sqs:us-east-1:930218373905:omnibor-sbom-tree-requests"
      ]
    },
    {
      "Sid": "DynamoDB",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:930218373905:table/SpdxIndexTable",
        "arn:aws:dynamodb:us-east-1:930218373905:table/SpdxDependencyGraph"
      ]
    },
    {
      "Sid": "ECS",
      "Effect": "Allow",
      "Action": ["ecs:RunTask", "ecs:DescribeTasks"],
      "Resource": "*"
    }
  ]
}
```

**Note:** The previous architecture required a separate `github-actions-s3`
IAM role with OIDC trust policies per GitHub org. That role is no longer
needed. The operator's single IAM role handles all S3 access, and
presigned URLs delegate scoped write access to CI callers.

## Presigned URL Broker (`/v1/upload-url`)

The operator exposes a new REST endpoint that accepts a GitHub Actions
(or Jenkins) OIDC token and returns presigned S3 PUT URLs.

### Endpoint Specification

```
POST /v1/upload-url
Authorization: Bearer <OIDC_TOKEN>
Content-Type: application/json

{
  "repo": "kkaple/WebGoat",
  "job_id": "20260701-131500_abc123def456_12345",
  "files": ["phase1.tar.gz", "phase1_manifest.json"]
}
```

**Response (200 OK):**

```json
{
  "urls": {
    "phase1.tar.gz": "https://omnibor-spdx-artifacts.s3.amazonaws.com/kkaple/WebGoat/20260701-.../phase1/phase1.tar.gz?X-Amz-...",
    "phase1_manifest.json": "https://omnibor-spdx-artifacts.s3.amazonaws.com/kkaple/WebGoat/20260701-.../phase1/phase1_manifest.json?X-Amz-..."
  },
  "expires_in": 900,
  "s3_prefix": "kkaple/WebGoat/20260701-131500_abc123def456_12345"
}
```

**Error responses:**

| Status | Meaning |
|--------|---------|
| `401` | Invalid or expired OIDC token |
| `403` | Org not enrolled, or token `sub` doesn't match requested repo |
| `400` | Missing required fields |
| `429` | Rate limit exceeded |

### OIDC Token Validation

The operator validates the GitHub Actions OIDC token:

1. **Fetch JWKS** — download the JSON Web Key Set from the OIDC
   provider's `/.well-known/jwks` endpoint (cached with TTL)
2. **Verify signature** — validate the JWT signature against the JWKS
3. **Check claims:**
   - `iss` — must match a known OIDC issuer (GitHub.com or GHE instance)
   - `aud` — must be the operator's expected audience
   - `exp` — must not be expired
   - `sub` — must match `repo:<owner>/<repo>:*` for the requested repo

```go
// Pseudocode — operator token validation
func validateToken(tokenStr string, requestedRepo string) (*Claims, error) {
    // Fetch and cache JWKS from issuer
    jwks := fetchJWKS(issuerURL + "/.well-known/jwks")

    // Parse and verify JWT
    token, err := jwt.Parse(tokenStr, jwks.Keyfunc)
    if err != nil {
        return nil, fmt.Errorf("invalid token: %w", err)
    }

    claims := token.Claims
    // Verify sub matches requested repo
    expectedSub := fmt.Sprintf("repo:%s:", requestedRepo)
    if !strings.HasPrefix(claims.Sub, expectedSub) {
        return nil, fmt.Errorf("sub %q does not match repo %q", claims.Sub, requestedRepo)
    }

    return claims, nil
}
```

**Supported OIDC issuers:**

| Issuer | URL |
|--------|-----|
| GitHub.com | `https://token.actions.githubusercontent.com` |
| Cisco GHE | `https://gh-xr.scm.engit.cisco.com/_services/token` |
| Jenkins (with OIDC plugin) | Instance-specific |

Adding a new CI system or GHE instance only requires adding its issuer
URL to the operator's config — no IAM changes.

### Org Enrollment

The operator maintains an allowlist of enrolled organizations in
PostgreSQL. Validation logic is **application code, not IAM policy
JSON** — no size limits, no IAM updates, and no per-org trust
policies.

```sql
-- Operator's own Postgres database (separate from tenant-service DB)
CREATE TABLE org_enrollment (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_name    TEXT NOT NULL,
    oidc_issuer TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(org_name, oidc_issuer)
);

CREATE INDEX idx_enrollment_org ON org_enrollment(org_name);
```

Enrollment is **org-scoped, not tenant-scoped**. An org is either
allowed to upload or it isn't — this is a platform-level decision.
Which tenants receive the resulting SBOMs is handled separately by
the [subscription model](#upload-authorization-vs-sbom-consumption).

Wildcard issuers (e.g., internal GHE where all repos are trusted)
are stored as rows with `org_name = '*'`:

```sql
INSERT INTO org_enrollment (org_name, oidc_issuer)
VALUES ('*', 'https://gh-xr.scm.engit.cisco.com/_services/token');
```

The validation query:

```go
var enabled bool
err := db.QueryRow(ctx, `
    SELECT enabled FROM org_enrollment
    WHERE (org_name = $1 OR org_name = '*')
      AND oidc_issuer = $2
      AND enabled = TRUE
    LIMIT 1
`, orgName, issuerURL).Scan(&enabled)
```

### Presigned URL Generation

Each presigned URL is scoped to a single S3 key and expires after 15
minutes:

```go
func generatePresignedURL(bucket, key string) (string, error) {
    presignClient := s3.NewPresignClient(s3Client)
    req, err := presignClient.PresignPutObject(ctx, &s3.PutObjectInput{
        Bucket: aws.String(bucket),
        Key:    aws.String(key),
    }, func(opts *s3.PresignOptions) {
        opts.Expires = 15 * time.Minute
    })
    return req.URL, err
}
```

### Security Properties

| Property | How it's achieved |
|----------|-------------------|
| **No static credentials in CI** | Presigned URLs are temporary (15 min) |
| **No AWS SDK in sidecar** | Upload is a plain HTTP PUT |
| **Path isolation** | Each URL is scoped to one S3 key |
| **No trust policy scaling** | Operator has 1 IAM role; org validation is code |
| **Audit trail** | Operator logs every token validation + URL generation |
| **Revocable** | Remove org from allowlist → immediate denial |
| **CI-system agnostic** | Any system that can present an OIDC token works |

## Sidecar Upload Flow

### Sidecar Responsibilities

In the previous architecture, the CI workflow handled S3 uploads using
the AWS CLI. Now the **sidecar handles everything**:

1. Run Phase 1 analysis (unchanged)
2. Request presigned URLs from the operator
3. Upload artifacts via HTTP PUT
4. Report upload status

### Upload Sequence

```
CI Workflow                    Sidecar Container              Operator              S3
    │                              │                            │                    │
    │  docker run (sidecar)        │                            │                    │
    │ ──────────────────────────→  │                            │                    │
    │                              │                            │                    │
    │                              │  Phase 1 analysis          │                    │
    │                              │  (dep tree, treedb,        │                    │
    │                              │   manifest generation)     │                    │
    │                              │                            │                    │
    │                              │  POST /v1/upload-url       │                    │
    │                              │  + OIDC token              │                    │
    │                              │ ────────────────────────→  │                    │
    │                              │                            │                    │
    │                              │                            │ validate token     │
    │                              │                            │ check enrollment   │
    │                              │                            │ generate URLs      │
    │                              │                            │                    │
    │                              │  presigned URLs            │                    │
    │                              │ ←────────────────────────  │                    │
    │                              │                            │                    │
    │                              │  HTTP PUT (artifacts)      │                    │
    │                              │ ─────────────────────────────────────────────→  │
    │                              │                            │                    │
    │  exit 0                      │                            │                    │
    │ ←────────────────────────    │                            │                    │
```

The sidecar needs two environment variables from the CI workflow:

| Variable | Source | Purpose |
|----------|--------|---------|
| `ACTIONS_ID_TOKEN` | GitHub Actions OIDC token request | Bearer token for `/v1/upload-url` |
| `OPERATOR_URL` | Workflow env or org-level variable | Base URL of the operator (e.g., `https://operator.internal:8080`) |

## GitHub Actions Workflow

### What's OmniBOR-Specific?

The standard Maven build (`mvn package`) is unchanged. The following
steps are additions for OmniBOR SBOM generation:

| Step | Purpose |
|------|---------|
| `permissions: id-token: write` | OIDC token for operator authentication |
| `env: SIDECAR_IMAGE`, `OPERATOR_URL` | Sidecar image and operator endpoint |
| Login to GHCR + pull sidecar | Fetches the OmniBOR sidecar container image |
| Phase 1 + Upload | Sidecar runs analysis AND uploads to S3 via presigned URLs |

**Removed** (compared to deprecated architecture):

- `aws-actions/configure-aws-credentials` — no longer needed
- `aws s3 cp` commands — sidecar handles uploads
- `role-to-assume` — no IAM role assumption from CI
- `S3_BUCKET` env var in workflow — sidecar gets this from operator response

### Reference Workflow

```yaml
name: "Main / Pull requests build"
on:
    pull_request:
        paths-ignore:
            - '.txt'
            - 'LICENSE'
            - 'docs/**'
        branches: [ main ]
    push:
        branches:
            - main
    workflow_dispatch:

concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

permissions:
    id-token: write   # OIDC token for operator
    contents: read
    packages: read

env:
    SIDECAR_IMAGE: ghcr.io/kkaple/omnibor-sidecar:dev
    MVN_VER: "3.9.8"
    OPERATOR_URL: https://operator.internal:8080

jobs:
    # ... pre-commit and build jobs omitted for brevity ...

    # ── Phase 1 + S3 Upload (push to main or manual dispatch only) ──
    phase1-s3:
        if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'
        needs: [ build ]
        runs-on: ubuntu-latest
        steps:
            -   name: Checkout
                uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

            -   name: Get OIDC token
                id: oidc
                uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea  # v7.0.1
                with:
                    script: |
                        const token = await core.getIDToken('omnibor-operator');
                        core.setOutput('token', token);

            -   name: Set timestamp
                run: echo "TS=$(date -u +'%Y%m%d-%H%M%S')" >> "$GITHUB_ENV"

            -   name: Build with Temurin JDK 25
                run: |
                    docker run --rm \
                      -v "${{ github.workspace }}:/project" \
                      -w /project \
                      -e MVN_VER="${{ env.MVN_VER }}" \
                      eclipse-temurin:25-jdk-jammy \
                      bash -c '
                        apt-get update -qq && apt-get install -y -qq curl > /dev/null &&
                        curl -fsSL "https://archive.apache.org/dist/maven/maven-3/${MVN_VER}/binaries/apache-maven-${MVN_VER}-bin.tar.gz" -o /tmp/mvn.tar.gz &&
                        tar xzf /tmp/mvn.tar.gz -C /opt &&
                        export PATH="/opt/apache-maven-${MVN_VER}/bin:$PATH" &&
                        mvn --version &&
                        mvn package -DskipTests -q
                      '

            -   name: Login to GHCR
                uses: docker/login-action@74a5d142397b4f367a81961eba4e8cd7edddf772  # v3.4.0
                with:
                    registry: ghcr.io
                    username: ${{ github.actor }}
                    password: ${{ secrets.GITHUB_TOKEN }}

            -   name: Pull sidecar image
                run: docker pull "$SIDECAR_IMAGE"

            -   name: "Phase 1 + Upload to S3 via presigned URLs"
                run: |
                    SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-12)
                    JOB_ID="${{ env.TS }}_${SHORT_SHA}_${{ github.run_id }}"
                    docker run --rm \
                      -v "${{ github.workspace }}:/workspace/repos/WebGoat" \
                      -v "${{ github.workspace }}/spdx-output:/workspace/output" \
                      -e OMNIBOR_MODE=sidecar \
                      -e OPERATOR_URL="${{ env.OPERATOR_URL }}" \
                      -e OIDC_TOKEN="${{ steps.oidc.outputs.token }}" \
                      -e REPO="${{ github.repository }}" \
                      -e JOB_ID="${JOB_ID}" \
                      "$SIDECAR_IMAGE" \
                      python3 /workspace/app/analyze.py \
                        --repo WebGoat \
                        --mode sidecar \
                        --phase build \
                        --skip-clone \
                        --upload
```

### Triggering the Workflow

```bash
# Push to main triggers automatically after build succeeds
# Manual dispatch:
gh workflow run build.yml -R kkaple/WebGoat
```

## Jenkins Variant

### What Changes for Jenkins

A mechanical translation — the sidecar handles uploads identically
regardless of CI system.

| GHA concept | Jenkins equivalent |
|---|---|
| `on: push/pull_request` | Multibranch pipeline + webhook trigger |
| `workflow_dispatch` | `parameters { booleanParam(...) }` |
| `concurrency` group | `options { disableConcurrentBuilds() }` |
| `actions/checkout` | `checkout scm` (automatic in multibranch) |
| `actions/setup-java` | `tools { jdk 'temurin-25' }` or Docker agent |
| OIDC token via `actions/github-script` | Jenkins OIDC plugin or instance profile |

**AWS authentication is no longer the biggest change.** In the
deprecated architecture, Jenkins needed OIDC federation, instance
profiles, or stored credentials for direct S3 access. Now Jenkins
only needs to pass an OIDC token to the sidecar — the sidecar does
the upload.

For Jenkins without an OIDC plugin, the operator can also accept
an API key as an alternative authentication method.

### What Does NOT Change

- **Sidecar image** — identical `docker run`, same `analyze.py`
  invocation and arguments
- **S3 path structure** — same `{repo}/{jobId}/phase1/` convention;
  the operator parses this, not CI metadata
- **Phase 2 / operator** — completely decoupled; watches S3 events
- **DynamoDB indexing, sbom-tree** — no changes at all
- **Phase 1 manifest format** — `phase1_manifest.json` is unchanged
- **REST API** — queries by `ArtifactSHA`, CI-agnostic

### Minimal Jenkinsfile Skeleton

```groovy
pipeline {
    agent { label 'docker' }
    options { disableConcurrentBuilds() }
    environment {
        SIDECAR_IMAGE = 'ghcr.io/kkaple/omnibor-sidecar:dev'
        OPERATOR_URL  = 'https://operator.internal:8080'
    }
    stages {
        stage('Build') {
            steps {
                sh '''
                    docker run --rm \
                      -v "$WORKSPACE:/project" -w /project \
                      eclipse-temurin:25-jdk-jammy \
                      bash -c 'mvn package -DskipTests -q'
                '''
            }
        }
        stage('Phase 1 + Upload') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'ghcr',
                        usernameVariable: 'GHCR_USER',
                        passwordVariable: 'GHCR_TOKEN'
                    )
                ]) {
                    sh 'echo $GHCR_TOKEN | docker login ghcr.io -u $GHCR_USER --password-stdin'
                    sh 'docker pull $SIDECAR_IMAGE'
                }
                // OIDC token from Jenkins OIDC plugin, or API key
                sh '''
                    SHORT_SHA=$(git rev-parse --short=12 HEAD)
                    TS=$(date -u +%Y%m%d-%H%M%S)
                    JOB_ID="${TS}_${SHORT_SHA}_${BUILD_NUMBER}"
                    docker run --rm \
                      -v "$WORKSPACE:/workspace/repos/WebGoat" \
                      -v "$WORKSPACE/spdx-output:/workspace/output" \
                      -e OMNIBOR_MODE=sidecar \
                      -e OPERATOR_URL="$OPERATOR_URL" \
                      -e OIDC_TOKEN="$OIDC_TOKEN" \
                      -e REPO="kkaple/WebGoat" \
                      -e JOB_ID="$JOB_ID" \
                      $SIDECAR_IMAGE \
                      python3 /workspace/app/analyze.py \
                        --repo WebGoat --mode sidecar \
                        --phase build --skip-clone \
                        --upload
                '''
            }
        }
    }
}
```

## Phase 2 Consumer Architecture

### Event-Driven Flow

```
Sidecar (Phase 1 + upload via presigned URLs)
    │
    ▼
S3 bucket ──► S3 Event Notification ──► SQS queue
                                            │
                                            ▼
                                    Operator microservice (long poll SQS)
                                            │
                                            ▼
                                    Pull Phase 1 artifacts from S3
                                            │
                                            ▼
                                    Launch Phase 2 container
                                            │
                                            ▼
                                    Write SPDX back to S3
```

An operator microservice monitors S3 via SQS long polling. When Phase 1
artifacts land, it launches a Phase 2 container to generate SPDX.

The operator now serves **three roles**:

1. **Presigned URL broker** — validates CI tokens, issues upload URLs
   (new `/v1/upload-url` endpoint)
2. **Phase 2 orchestrator** — polls SQS, downloads Phase 1 from S3,
   launches Phase 2, indexes SPDX (unchanged from previous architecture)
3. **Subscription notifier** — after SPDX indexing, queries
   `repo_subscription` and fans out NATS messages to all subscribed
   tenants (see [Tenant Integration](#tenant-integration--sbom-subscriptions))

### Container Launch Options

- **Docker SDK** (`github.com/docker/docker/client`) — simplest for
  single-host setups. Mount downloaded S3 artifacts into the sidecar.
- **ECS `RunTask`** — AWS-managed containers. The operator microservice
  calls `ecs:RunTask` with the sidecar image and passes the S3 path as
  an environment variable.
- **Local `exec.Command`** — shell out to `docker run` with the same
  sidecar image and volume mounts used in the workflow.

### Operator Microservice Logic

```
// Presigned URL broker
handler("/v1/upload-url"):
    token := request.header("Authorization")
    claims := validateOIDCToken(token)
    if !isEnrolled(claims.org):          // query org_enrollment table
        return 403

    urls := generatePresignedURLs(request.files, request.repo, request.job_id)
    return 200, urls

// Phase 2 orchestrator
loop:
    msg := sqs.ReceiveMessage(queue, waitTimeSeconds=20)
    if msg == nil: continue

    s3Key := parseS3Key(msg)
    jobPrefix := extractJobPrefix(s3Key)
    repoName := repoFromPrefix(jobPrefix)  // e.g. "CiscoSecurityServices/WebGoat"

    ecs.RunTask({
        taskDefinition: "omnibor-phase2",
        overrides: {
            containerOverrides: [{
                environment: [
                    {S3_INPUT_PATH:  "s3://bucket/" + jobPrefix + "/phase1/"},
                    {S3_OUTPUT_PATH: "s3://bucket/" + jobPrefix + "/spdx/"},
                    {REPO_NAME:      repoName},
                ],
            }],
        },
    })

    // After Phase 2 + SPDX indexing completes:
    // Fan out to all subscribed tenants
    tenantIDs := db.Query(`
        SELECT DISTINCT tenant_id FROM repo_subscription
        WHERE repo_pattern = $1
           OR repo_pattern = split_part($1, '/', 1) || '/*'
    `, repoName)

    for _, tenantID := range tenantIDs:
        nats.PublishWithTenant("sbom.produced", {
            tenant_id: tenantID,
            repo:      repoName,
            s3_prefix: jobPrefix,
            spdx_files: listS3Keys(jobPrefix + "/spdx/"),
        })

    sqs.DeleteMessage(msg)
```

## ECS Deployment via AWS CDK

### Architecture

```
Sidecar (Phase 1 + presigned URL upload)
    │
    ▼
S3 bucket
    │
    ├── Event Notification
    ▼
SQS queue
    │
    ▼
ECS Fargate Service (operator: Phase 2 orchestrator + presigned URL broker)
    │
    │  calls ecs:RunTask
    ▼
ECS Fargate Task (omnibor-sidecar)        ← ephemeral, per-job
    │
    │  reads Phase 1 from S3, writes SPDX back to S3
    ▼
S3 bucket (spdx/ prefix)
```

### CDK Stack (TypeScript)

```typescript
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
```

#### S3 + SQS (event plumbing)

```typescript
const bucket = new s3.Bucket(this, 'ArtifactBucket', {
  bucketName: 'omnibor-spdx-artifacts',
  removalPolicy: cdk.RemovalPolicy.RETAIN,
});

const queue = new sqs.Queue(this, 'Phase1Queue', {
  queueName: 'omnibor-phase1-notifications',
  visibilityTimeout: cdk.Duration.minutes(15),
  retentionPeriod: cdk.Duration.days(7),
  deadLetterQueue: {
    queue: new sqs.Queue(this, 'Phase1DLQ', {
      queueName: 'omnibor-phase1-dlq',
      retentionPeriod: cdk.Duration.days(14),
    }),
    maxReceiveCount: 3,
  },
});

bucket.addEventNotification(
  s3.EventType.OBJECT_CREATED,
  new s3n.SqsDestination(queue),
  { suffix: 'phase1_manifest.json' },
);
```

#### ECS Cluster + Task Definitions

```typescript
const vpc = new ec2.Vpc(this, 'Vpc', { maxAzs: 2 });
const cluster = new ecs.Cluster(this, 'Cluster', { vpc });

// ── Operator (presigned URL broker + Phase 2 orchestrator) ──
const operatorTaskDef = new ecs.FargateTaskDefinition(this, 'OperatorTask', {
  memoryLimitMiB: 512,
  cpu: 256,
});

operatorTaskDef.addContainer('operator', {
  image: ecs.ContainerImage.fromRegistry('ghcr.io/tedg-dev/omnibor-operator:latest'),
  environment: {
    SQS_QUEUE_URL: queue.queueUrl,
    ECS_CLUSTER: cluster.clusterArn,
    PHASE2_TASK_DEF: 'omnibor-phase2',
    S3_BUCKET: bucket.bucketName,
    // Presigned URL broker config
    OIDC_ISSUERS: 'https://token.actions.githubusercontent.com,https://gh-xr.scm.engit.cisco.com/_services/token',
    // Postgres (enrollment + subscriptions)
    DATABASE_URL: 'postgres://operator:***@db:5432/operator?sslmode=require',
    // NATS (subscription fan-out notifications)
    NATS_URL: 'nats://nats:4222',
  },
  portMappings: [{ containerPort: 8080 }],
  logging: ecs.LogDrivers.awsLogs({
    logGroup: new logs.LogGroup(this, 'OperatorLogs', {
      retention: logs.RetentionDays.ONE_MONTH,
    }),
    streamPrefix: 'operator',
  }),
});

// ── Phase 2 sidecar (ephemeral task, launched per job) ──
const phase2TaskDef = new ecs.FargateTaskDefinition(this, 'Phase2Task', {
  memoryLimitMiB: 4096,
  cpu: 2048,
  family: 'omnibor-phase2',
});

phase2TaskDef.addContainer('sidecar', {
  image: ecs.ContainerImage.fromRegistry('ghcr.io/tedg-dev/omnibor-sidecar:latest'),
  logging: ecs.LogDrivers.awsLogs({
    logGroup: new logs.LogGroup(this, 'Phase2Logs', {
      retention: logs.RetentionDays.ONE_MONTH,
    }),
    streamPrefix: 'phase2',
  }),
});
```

#### IAM Permissions

```typescript
// Operator: read SQS, read/write S3, launch ECS tasks, generate presigned URLs
queue.grantConsumeMessages(operatorTaskDef.taskRole);
bucket.grantReadWrite(operatorTaskDef.taskRole);
operatorTaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['ecs:RunTask', 'ecs:DescribeTasks'],
  resources: [phase2TaskDef.taskDefinitionArn],
}));
operatorTaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['iam:PassRole'],
  resources: [
    phase2TaskDef.taskRole.roleArn,
    phase2TaskDef.executionRole!.roleArn,
  ],
}));

// Phase 2 sidecar: read + write S3
bucket.grantReadWrite(phase2TaskDef.taskRole);
```

#### Run the Operator as a Service

```typescript
const sg = new ec2.SecurityGroup(this, 'OperatorSg', {
  vpc,
  description: 'Operator — ingress 8080 for presigned URL broker, egress for SQS/S3',
});
sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(8080), 'Presigned URL broker');

new ecs.FargateService(this, 'OperatorService', {
  cluster,
  taskDefinition: operatorTaskDef,
  desiredCount: 1,
  assignPublicIp: true,
  securityGroups: [sg],
});
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Presigned URL broker on the operator** | No new service to deploy; operator already has S3 IAM access |
| **SQS filter on `phase1_manifest.json` suffix** | Only fires once per Phase 1 run, not per file |
| **Dead letter queue** | Failed Phase 2 jobs don't disappear silently |
| **Visibility timeout > Phase 2 runtime** | Prevents duplicate launches |
| **Separate task definitions** | Operator is small (256 CPU); Phase 2 needs more compute |
| **Fargate (not EC2)** | No cluster management; pay per task-second |
| **Port 8080 exposed** | Presigned URL broker needs to be reachable from CI runners |
| **Postgres for enrollment + subscriptions** | Relational queries (pattern matching, tenant lookups); no cross-DB FKs |
| **NATS for fan-out** | Reuses tenant-service messaging; tenant context propagated via headers |

### Cost Estimate (low volume)

| Resource | Estimate |
|----------|----------|
| Operator | ~$9/month (256 CPU, 512 MB, always-on) |
| Phase 2 tasks | ~$0.04 per run (2 vCPU, 4 GB, ~3 min) |
| SQS | Free tier covers up to 1M requests/month |
| S3 | Negligible for SPDX-sized files |

## SPDX Post-Processing Pipeline

A second SQS queue can trigger additional actions when Phase 2 writes
SPDX files back to S3:

```
Phase 2 sidecar writes SPDX to S3
    │
    ├── S3 Event Notification (suffix: .spdx.json)
    ▼
SQS queue #2 (omnibor-spdx-complete)
    │
    ▼
Operator (second goroutine)
    │
    ▼
Post-processing actions
```

Post-processing options:

- **Vulnerability scan** — feed SPDX to Grype, Trivy, or OSV
- **Policy check** — verify license compliance, banned packages
- **Notification** — Slack/Teams alert, GitHub commit status update
- **Database ingest** — store SBOM metadata in a DB for querying
- **Comparison** — diff against golden files or previous SPDX

## SPDX Indexing via DynamoDB

After Phase 2 completes, the `spdx-indexing` service records the S3
locations of generated SPDX documents in a DynamoDB table, keyed by
a generic `ArtifactSHA` partition key. Two items are written per
artifact — one keyed by SHA-256, one by SHA-1 — so downstream
consumers can look up SPDX locations using whichever hash they have
with a single `GetItem` call.

### Data Flow

```
Phase 2 completes → SPDX files written to S3
    │
    ▼
spdx-indexing reads phase1_manifest.json
    │  (extracts artifact SHA-1 and SHA-256 checksums)
    │
    ▼
Lists SPDX files under s3://<bucket>/<jobPrefix>/spdx/
    │
    ▼
Writes TWO DynamoDB items per artifact (one per hash algorithm)
    Key:   ArtifactSHA  (SHA-256 hex or SHA-1 hex)
    Value: { AnalyzedSpdxS3, BuildSpdxS3, SbomTreeS3, ArtifactPath, RepoName, Language, CommitSHA }
```

### DynamoDB Table Schema

| Attribute | Type | Description |
|-----------|------|-------------|
| `ArtifactSHA` | String (partition key) | SHA hex digest — SHA-256 (64 chars) or SHA-1 (40 chars) |
| `AnalyzedSpdxS3` | String | S3 URI to the analyzed SPDX document |
| `BuildSpdxS3` | String | S3 URI to the build SPDX document |
| `SbomTreeS3` | String | S3 URI to the sbom-tree JSON document |
| `ArtifactPath` | String | Original artifact path from the manifest |
| `RepoName` | String | Repository name |
| `Language` | String | Language (e.g. `java`) |
| `CommitSHA` | String | Git commit SHA |

### Client Lookup

```go
result, err := dynamoClient.GetItem(ctx, &dynamodb.GetItemInput{
    TableName: aws.String("SpdxIndexTable"),
    Key: map[string]types.AttributeValue{
        "ArtifactSHA": &types.AttributeValueMemberS{Value: shaHex},
    },
})
```

### Dependency Graph Table (`SpdxDependencyGraph`)

A second DynamoDB table stores the full package dependency graph
extracted from the SPDX `DEPENDS_ON` relationships. Each package is
stored as its own DynamoDB item (segmented adjacency list).

| Attribute | Type | Role |
|-----------|------|------|
| `ArtifactSHA` | String | Partition key — groups all nodes for one artifact |
| `SK` | String | Sort key — `depth#N#PURL` enables range queries |
| `purl` | String | Package URL |
| `name` | String | Package name |
| `version` | String | Package version |
| `depth` | Number | Distance from root (0 = root, 1 = direct, 2+ = transitive) |
| `parent` | String | Parent PURL, or null for root |
| `children` | List\<String\> | Child PURLs |

See [deprecated/gh-aws-corona.md](deprecated/gh-aws-corona.md) for
full examples, depth-based query API, size characteristics, and CDK
table definitions (unchanged).

## SBOM Tree Generator

The `sbom-tree` module generates a nested JSON representation of the
full dependency tree from the `SpdxDependencyGraph` DynamoDB table.

```
Operator (after graph indexing)
    │
    ▼  publishes message
SQS: omnibor-sbom-tree-requests
    │
    ▼  polls
sbom-tree worker
    │
    ├─ Query DynamoDB (SpdxDependencyGraph, full tree, paginated)
    ├─ Reconstruct nested tree from flat adjacency nodes
    ├─ Marshal to JSON → <artifactName>-sbom-tree.json
    └─ Upload to s3://<bucket>/<jobPrefix>/spdx/
```

See [deprecated/gh-aws-corona.md](deprecated/gh-aws-corona.md) for
SQS message format, output JSON format, source code layout, and
operator configuration (unchanged).

## Tenant Integration & SBOM Subscriptions

The operator integrates with the
[SSVS tenant service](../../../tenant-service/README.md) to provide
multi-tenant isolation. Two concerns are deliberately separated:

| Concern | Scope | Question it answers |
|---------|-------|---------------------|
| **Upload authorization** | Org + OIDC issuer | "Is this CI runner allowed to upload?" |
| **SBOM consumption** | Tenant + repo pattern | "Which teams want this repo's SBOMs?" |

### Tenant Service Overview

The tenant service is a multi-tenant identity and access management
system with the following data model:

| Entity | Description |
|--------|-------------|
| **User** | Identity via Cisco Duo SSO (OIDC); auto-provisioned on first login |
| **Tenant** | Organization/workspace (UUID); unit of data isolation |
| **Membership** | User ↔ Tenant with role (`admin`/`member`) and source (`manual`/`oidc_group`) |

Key properties:

- Users authenticate via Cisco Duo SSO; no local passwords
- Every request carries tenant context via `X-SSVS-TENANT-ID` headers
- An nginx gateway verifies JWTs and injects tenant headers; downstream
  services (including the operator) trust headers unconditionally
- The shared `pkg/ssvs` library provides `RequireTenantHeaders()`
  middleware, `TenantID(ctx)` helpers, and NATS context propagation

### Tenant ID Without Foreign Keys

In a microservices architecture with **separate databases per service**,
`tenant_id` cannot be a foreign key to the tenant service's `tenant`
table. Instead, it is a **logical partition key** — a plain UUID column
validated at the transport layer:

| Transport | How tenant_id is validated |
|-----------|--------------------------|
| HTTP (via gateway) | nginx njs verifies JWT → injects `X-SSVS-TENANT-ID` → middleware stores in ctx |
| NATS message | `ssvs.PublishWithTenant()` sets headers → `ssvs.ContextFromMsg()` recovers ctx |
| Service-to-service | Headers propagated explicitly |

The operator's database stores `tenant_id UUID NOT NULL` on
subscription rows — no FK, no cross-database join. The value is
trusted because the gateway already verified it before the request
reached the operator.

```go
// Operator handler — tenant_id comes from verified gateway headers
func (h *Handler) CreateSubscription(w http.ResponseWriter, r *http.Request) {
    tenantID := ssvs.TenantID(r.Context())  // from gateway-injected header
    // ... insert into repo_subscription with tenantID
}
```

### Upload Authorization vs. SBOM Consumption

Upload authorization is **org-scoped** (see [Org Enrollment](#org-enrollment)).
An org is either allowed to upload or it isn't — this is a platform-level
decision independent of tenants.

SBOM consumption is **tenant-scoped**. Multiple tenants can subscribe to
the same repo. When Phase 2 completes, all subscribers are notified:

```
CI builds CiscoSecurityServices/WebGoat
    │
    │ ① Upload authorized (org_enrollment: CiscoSecurityServices is enrolled)
    │
    │ ② Phase 1 → S3 → Phase 2 → SPDX indexed
    │
    │ ③ Fan-out: query repo_subscription for "CiscoSecurityServices/WebGoat"
    │
    ├──→ Tenant A (security team)     → NATS: sbom.produced (tenant_a context)
    ├──→ Tenant B (license team)      → NATS: sbom.produced (tenant_b context)
    └──→ Tenant C (product team)      → NATS: sbom.produced (tenant_c context)
```

Each tenant's sbom-ingest consumer receives the event with its own
tenant context and creates a record in its tenant-scoped `sbom` table.
The SPDX files in S3 are stored **once** — subscriptions control who
gets notified, not where files are stored.

### Operator Database Schema (PostgreSQL)

The operator has its own Postgres database (separate from the
tenant-service database). Two tables handle enrollment and subscriptions:

```sql
-- Who is allowed to upload (org-scoped, platform-level)
CREATE TABLE org_enrollment (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_name    TEXT NOT NULL,            -- GitHub org, or '*' for wildcard
    oidc_issuer TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(org_name, oidc_issuer)
);

CREATE INDEX idx_enrollment_org ON org_enrollment(org_name);

-- Who wants to be notified (tenant-scoped, self-service)
CREATE TABLE repo_subscription (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL,           -- no FK; plain UUID from gateway
    repo_pattern TEXT NOT NULL,           -- "CiscoSecurityServices/WebGoat"
                                          -- or "CiscoSecurityServices/*"
    notify_on    TEXT[] NOT NULL DEFAULT '{spdx_complete}',
    created_by   TEXT NOT NULL,           -- username from gateway header
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, repo_pattern)
);

CREATE INDEX idx_sub_repo ON repo_subscription(repo_pattern);
CREATE INDEX idx_sub_tenant ON repo_subscription(tenant_id);
```

`repo_pattern` supports two granularities:

| Pattern | Matches |
|---------|---------|
| `CiscoSecurityServices/WebGoat` | Exact repo |
| `CiscoSecurityServices/*` | All repos under that org |

### SBOM Subscription API

The operator exposes subscription management endpoints behind the
nginx gateway. Tenant context flows automatically via
`X-SSVS-TENANT-ID`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/v1/subscriptions` | Gateway (tenant-scoped) | List current tenant's subscriptions |
| `POST` | `/v1/subscriptions` | Gateway (tenant admin) | Subscribe to a repo or org pattern |
| `DELETE` | `/v1/subscriptions/{id}` | Gateway (tenant admin) | Remove a subscription |

**Create subscription:**

```
POST /v1/subscriptions
X-SSVS-TENANT-ID: <injected by gateway>
Content-Type: application/json

{
  "repo_pattern": "CiscoSecurityServices/WebGoat",
  "notify_on": ["spdx_complete"]
}
```

**Response (201 Created):**

```json
{
  "id": "a1b2c3d4-...",
  "tenant_id": "t1e2n3a4-...",
  "repo_pattern": "CiscoSecurityServices/WebGoat",
  "notify_on": ["spdx_complete"],
  "created_by": "kak",
  "created_at": "2026-07-01T18:00:00Z"
}
```

**List subscriptions:**

```
GET /v1/subscriptions
X-SSVS-TENANT-ID: <injected by gateway>
```

Returns all subscriptions for the caller's tenant.

### Notification Fan-Out Flow

After SPDX indexing completes for a repo, the operator publishes one
NATS message per subscribed tenant:

```go
// Query all tenants subscribed to this repo
rows, _ := db.Query(ctx, `
    SELECT DISTINCT tenant_id FROM repo_subscription
    WHERE repo_pattern = $1
       OR repo_pattern = split_part($1, '/', 1) || '/*'
`, repoName)

for rows.Next() {
    var tenantID string
    rows.Scan(&tenantID)

    // Build tenant-scoped context (same pattern as gateway injection)
    ctx := ssvs.WithTenantID(context.Background(), tenantID)

    ssvs.PublishWithTenant(js, ctx, "sbom.produced", SBOMProducedEvent{
        Repo:      repoName,
        S3Prefix:  jobPrefix,
        SpdxFiles: spdxFileList,
        CommitSHA: commitSHA,
    })
}
```

The tenant-service's `sbom-ingest` consumer (or a dedicated OmniBOR
consumer) receives the message with tenant context:

```go
js.Subscribe("sbom.produced", func(msg *nats.Msg) {
    ctx := ssvs.ContextFromMsg(context.Background(), msg)
    tenantID := ssvs.TenantID(ctx)

    var event SBOMProducedEvent
    json.Unmarshal(msg.Data, &event)

    // Insert tenant-scoped record — this tenant now "has" this SBOM
    db.Exec(ctx, `
        INSERT INTO sbom (id, tenant_id, format, source, artifact_id, status)
        VALUES ($1, $2, 'spdx', 'omnibor-pipeline', $3, 'available')
    `, uuid.New(), tenantID, event.S3Prefix)
})
```

### S3 Storage Is Repo-Scoped, Not Tenant-Scoped

S3 paths remain **org/repo-scoped**. There is one copy of each SPDX
document in S3 — subscriptions control who gets notified, not where
files live:

```
s3://omnibor-spdx-artifacts/CiscoSecurityServices/WebGoat/<jobId>/spdx/
```

Multiple tenants reference the same S3 locations. The DynamoDB
`SpdxIndexTable` is also shared (keyed by `ArtifactSHA`, not
tenant). Tenant scoping happens at the notification/consumption layer:

| Layer | Scoped by | Storage |
|-------|-----------|---------|
| **Upload auth** (`org_enrollment`) | GitHub org + OIDC issuer | Operator Postgres |
| **Artifacts** (S3, DynamoDB) | Repo (`owner/repo`) | Shared, no tenant scoping |
| **Subscription** (`repo_subscription`) | Tenant | Operator Postgres |
| **Notification** (NATS events) | Tenant | Per-tenant message headers |
| **Consumption** (`sbom` table) | Tenant | Tenant-service Postgres |

This design avoids duplicating SPDX files per tenant and keeps S3
costs proportional to the number of repos, not the number of
subscribing tenants.

---

## Appendix: Migration from Direct OIDC

### Steps to Migrate

1. **Deploy the operator with `/v1/upload-url`** — add the new handler,
   configure OIDC issuer URLs and enrollment backend
2. **Update the sidecar** — add `--upload` mode that requests presigned
   URLs and uploads artifacts
3. **Update CI workflows** — remove `aws-actions/configure-aws-credentials`,
   remove `aws s3 cp`, pass `OIDC_TOKEN` and `OPERATOR_URL` to sidecar
4. **Retire the `github-actions-s3` IAM role** — once all repos use
   presigned URLs, delete the OIDC trust policies and the role

### Backward Compatibility

During migration, both paths can coexist:

- Repos using the old workflow continue to upload via `aws s3 cp`
  with OIDC federation
- Repos using the new workflow upload via sidecar + presigned URLs
- The operator's SQS consumer doesn't care how artifacts arrived in
  S3 — it triggers on S3 events regardless

### Timeline

| Phase | Action |
|-------|--------|
| **Phase A** | Deploy operator with `/v1/upload-url`, keep old OIDC role |
| **Phase B** | Migrate pilot repos (WebGoat, testapps) to presigned URLs |
| **Phase C** | Migrate remaining repos, retire OIDC role |
| **Phase D** | Remove `aws-actions/configure-aws-credentials` from all workflows |

## Production Sub-Issues (gambit#10786)

| # | Title | Issue |
|---|-------|-------|
| 1 | Deploy Phase 2 into existing scan-service VPC | [#10888](https://github.com/CiscoSecurityServices/gambit/issues/10888) |
| 2 | S3 Bucket + SQS Event Plumbing for Phase 1 Intake | [#10889](https://github.com/CiscoSecurityServices/gambit/issues/10889) |
| 3 | Presigned URL Broker on Operator | Replaces OIDC Federation (#10890) |
| 4 | ECS Cluster + Fargate Task Definitions | [#10891](https://github.com/CiscoSecurityServices/gambit/issues/10891) |
| 5 | Container Image Registry + CI Pipeline | [#10892](https://github.com/CiscoSecurityServices/gambit/issues/10892) |
| 6 | DynamoDB SPDX Index Table | [#10894](https://github.com/CiscoSecurityServices/gambit/issues/10894) |
| 7 | Operator Worker Pool for Concurrent Phase 2 Processing | [#10901](https://github.com/CiscoSecurityServices/gambit/issues/10901) |
| 8 | AWS Auto Scaling for Operator Instances Based on SQS Queue Depth | [#10902](https://github.com/CiscoSecurityServices/gambit/issues/10902) |
| 9 | AWS Auto Scaling for sbom-tree Instances Based on SQS Queue Depth | [#10903](https://github.com/CiscoSecurityServices/gambit/issues/10903) |
| 10 | Containerize sbom-tree Worker (Dockerfile + ECR + CI) | [#10904](https://github.com/CiscoSecurityServices/gambit/issues/10904) |
| 11 | Containerize spdx-indexing CLI (Dockerfile + ECR + CI) | [#10905](https://github.com/CiscoSecurityServices/gambit/issues/10905) |
