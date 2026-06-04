# S3 Federated Uploads — Phase 1 Artifacts to S3 and Phase 2 Fargate Operator

## Table of Contents

- [Overview](#overview)
- [S3 Path Structure](#s3-path-structure)
  - [Workflow ↔ Operator Contract](#workflow--operator-contract)
- [AWS Setup](#aws-setup)
  - [Step 1: Create the S3 Bucket](#step-1-create-the-s3-bucket)
  - [Step 2: Create the OIDC Identity Provider](#step-2-create-the-oidc-identity-provider)
  - [Step 3: Create the IAM Role](#step-3-create-the-iam-role)
- [GitHub Actions Workflow](#github-actions-workflow)
  - [Triggering the Workflow](#triggering-the-workflow)
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
  - [Post-Processing Options](#post-processing-options)
  - [CDK Addition](#cdk-addition)
  - [Extending the Operator](#extending-the-operator)
- [SPDX Indexing via DynamoDB](#spdx-indexing-via-dynamodb)
  - [DynamoDB Table Schema](#dynamodb-table-schema)
  - [Client Lookup](#client-lookup)
  - [Dependency Graph Table (`SpdxDependencyGraph`)](#dependency-graph-table-spdxdependencygraph)
- [SBOM Tree Generator](#sbom-tree-generator)
  - [Architecture](#sbom-tree-architecture)
  - [SQS Queue](#sbom-tree-sqs-queue)
  - [Output Format](#output-format)
  - [Running the sbom-tree Worker](#running-the-sbom-tree-worker)
- [GitHub Actions → Jenkins: What Changes](#github-actions--jenkins-what-changes)
  - [What the GHA Workflow Does Today](#what-the-gha-workflow-does-today)
  - [Changes Needed for Jenkins](#changes-needed-for-jenkins)
  - [What Does NOT Change](#what-does-not-change)
  - [Minimal Jenkinsfile Skeleton](#minimal-jenkinsfile-skeleton)
  - [Diagram Recommendation](#diagram-recommendation)
- [Appendix: Multiple OIDC Providers (GitHub.com + GitHub Enterprise)](#appendix-multiple-oidc-providers-githubcom--github-enterprise)

## Overview

Changes include:
- S3 replaces GitHub Actions artifacts as the transport between Phase 1 Phase 2. 
- Introduction of human readable (JSON) tree based dependency output for heirarchical dependency tracking


This models the enterprise deployment pattern: the build site pushes
Phase 1 artifacts to S3, and a separate analysis service pulls from S3 to
run Phase 2 (SPDX generation).

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
| **GitHub Actions workflow** | Produces the S3 path (uploads Phase 1 artifacts) | typically `build.yml`  in each repo |
| **Operator** | Consumes the S3 path (downloads artifacts, runs Phase 2) | `operator/internal/consumer/consumer.go` |

**Producer side (workflow):** The workflow constructs the job directory
from `github.repository`, a UTC timestamp, the first 12 characters of
`github.sha`, and `github.run_id`:

```yaml
env:
  S3_BUCKET: omnibor-spdx-artifacts
  S3_REPO: ${{ github.repository }}    # e.g., kkaple/WebGoat

steps:
  - run: |
      TS=$(date -u +%Y%m%d-%H%M%S)
      SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-12)
      JOB_ID="${TS}_${SHORT_SHA}_${{ github.run_id }}"
      S3_PATH="s3://${S3_BUCKET}/${S3_REPO}/${JOB_ID}"
      aws s3 cp spdx-output/ "${S3_PATH}/phase1/" --recursive
```

**Consumer side (operator):** When S3 event notifications arrive via SQS,
the operator extracts the first 3 path components as the **job prefix**:

```
S3 key: kkaple/WebGoat/20260603-153000_8c3a1710b358_26894443338/phase1/.../manifest.json
                │          │                    │
                └──────────┴────────────────────┘
                     job prefix (3 parts)
                   owner / repo / job_id
```

The operator then uses this prefix to locate `phase1/`, `build/`, and
`spdx/` subdirectories. **Both sides must agree on this 3-part structure.**
This is a convention that must be understood by the build engineers managing the repo
which want to use build based SBOMs.

**Checklist when onboarding a new repo:**

1. Set `S3_REPO: ${{ github.repository }}` (not a hardcoded path)
2. Construct `JOB_ID` as `<TS>_<sha12>_<run_id>` (single directory, no nested levels)
3. Set upload to `s3://<bucket>/<S3_REPO>/<JOB_ID>/phase1/`
5. Validate that `${{ github.repository }}` matches the expected format (e.g., `<owner>/<repo>`)
6. (TBD) Validate that `${{ github.repository }}` matches the current set used by the trust policy


## AWS Setup

### Step 1: Create the S3 Bucket

```bash
aws s3api create-bucket --bucket omnibor-spdx-artifacts --region us-east-1
```

### Step 2: Create the OIDC Identity Provider

This allows GitHub Actions to authenticate with AWS without long-lived keys:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### Step 3: Create the IAM Role

**Trust policy** (`/tmp/trust-policy.json`):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::930218373905:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": [
          "repo:tedg-dev/omnibor-*-testapp:*",
          "repo:CiscoSecurityServices/*:*",
          "repo:gh-xr.scm.engit.cisco.com/*:*"
        ]
      }
    }
  }]
}
```

The `StringLike` wildcard array allows any of the following to assume this role:

- `tedg-dev/omnibor-*-testapp` — any OmniBOR testapp repo under `tedg-dev`
- `CiscoSecurityServices/*` — any repo under the `CiscoSecurityServices` GitHub org
- `gh-xr.scm.engit.cisco.com/*` — any repo on the Cisco GitHub Enterprise instance

**Note:** The Cisco GHE instance (`gh-xr.scm.engit.cisco.com`) may require a
separate OIDC provider if its issuer URL differs from `token.actions.githubusercontent.com`.
Verify the OIDC issuer URL for your GHE instance before adding it.
See Appendix for examples of multiple OIDC providers.  If there are multiple issuers there 
may be another caveat to work through in that the S3 bucket naming convention potentially 
could conflict if two different GHE instances have identical names for owner/repo.  This 
should only mean that their artifacts would be stored in the same S3 bucket, which is 
probably not a big deal.

Create the role:

```bash
aws iam create-role \
  --role-name github-actions-s3 \
  --assume-role-policy-document file:///tmp/trust-policy.json
```

**S3 permissions policy** (`/tmp/s3-policy.json`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::omnibor-spdx-artifacts/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::omnibor-spdx-artifacts"
    }
  ]
}
```

Attach the policy:

```bash
aws iam put-role-policy \
  --role-name github-actions-s3 \
  --policy-name s3-spdx-access \
  --policy-document file:///tmp/s3-policy.json
```

## GitHub Actions Workflow

The WebGoat `build.yml` workflow is the reference implementation. The
`phase1-s3` job runs after the main build succeeds: it verifies the
taxonomy of the build results via the Phase 1 sidecar, then uploads to S3.

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
        inputs:
            upload_build_output:
                description: "Include JARs and class files in S3 upload"
                type: boolean
                default: false

concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

permissions:
    id-token: write   # OIDC for AWS
    contents: read
    packages: read

env:
    SIDECAR_IMAGE: ghcr.io/kkaple/omnibor-sidecar:dev
    MVN_VER: "3.9.8"
    S3_BUCKET: omnibor-spdx-artifacts
    S3_REPO: ${{ github.repository }}

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

            -   name: "Phase 1: Build result processing via sidecar"
                run: |
                    mkdir -p "${{ github.workspace }}/spdx-output"
                    docker run --rm \
                      -v "${{ github.workspace }}:/workspace/repos/WebGoat" \
                      -v "${{ github.workspace }}/spdx-output:/workspace/output" \
                      -e OMNIBOR_MODE=sidecar \
                      "$SIDECAR_IMAGE" \
                      python3 /workspace/app/analyze.py \
                        --repo WebGoat \
                        --mode sidecar \
                        --phase build \
                        --skip-clone

            -   name: Configure AWS credentials (OIDC)
                uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502  # v4
                with:
                    role-to-assume: arn:aws:iam::930218373905:role/github-actions-s3
                    aws-region: us-east-1

            -   name: Upload Phase 1 artifacts to S3
                run: |
                    SHORT_SHA=$(echo "${{ github.sha }}" | cut -c1-12)
                    JOB_ID="${{ env.TS }}_${SHORT_SHA}_${{ github.run_id }}"
                    S3_PATH="s3://${{ env.S3_BUCKET }}/${{ env.S3_REPO }}/${JOB_ID}"
                    echo "JOB_ID=${JOB_ID}" >> "$GITHUB_ENV"
                    echo "S3_PATH=${S3_PATH}" >> "$GITHUB_ENV"
                    echo "[INFO] Uploading Phase 1 artifacts to ${S3_PATH}/phase1/"
                    aws s3 cp spdx-output/ "${S3_PATH}/phase1/" --recursive

            -   name: Upload build output to S3
                if: ${{ github.event_name == 'push' || inputs.upload_build_output }}
                run: |
                    echo "[INFO] Uploading build output to ${{ env.S3_PATH }}/build/"
                    aws s3 cp target/ "${{ env.S3_PATH }}/build/" --recursive

            -   name: Verify S3 upload
                run: |
                    echo "=== S3 contents ==="
                    aws s3 ls "${{ env.S3_PATH }}/" --recursive
                    echo ""
                    echo "=== Phase 2 can pull from ==="
                    echo "  Phase 1: ${{ env.S3_PATH }}/phase1/"
                    echo "  Build:   ${{ env.S3_PATH }}/build/"
```

### What's OmniBOR-specific?

The standard Maven build (`mvn package`) is unchanged. The following
steps are additions for OmniBOR SBOM generation and are not part of
a typical Java CI workflow:

| Lines | Step | Purpose |
|-------|------|---------|
| 23–26 | `permissions: id-token: write` | OIDC token for AWS — not needed by a standard build |
| 28–32 | `env: SIDECAR_IMAGE`, `S3_BUCKET`, `S3_REPO` | OmniBOR sidecar image and S3 destination |
| 80–81 | Set timestamp | Generates the `TS` component of the S3 job ID |
| 99–107 | Login to GHCR + pull sidecar | Fetches the OmniBOR sidecar container image |
| 109–121 | Phase 1: Build result processing | Runs the sidecar to extract dependency tree, treedb, and manifest |
| 123–127 | Configure AWS credentials (OIDC) | Assumes the `github-actions-s3` IAM role via OIDC federation |
| 129–137 | Upload Phase 1 artifacts to S3 | Constructs the 3-part job ID and uploads to `s3://<bucket>/<owner>/<repo>/<job_id>/phase1/` |
| 139–143 | Upload build output to S3 | Optionally uploads JARs and class files for Phase 2 analysis |
| 145–152 | Verify S3 upload | Lists uploaded contents for debugging |

A repo that only needs a standard Maven build would have none of
these steps. They can be added to any existing `build.yml` without
modifying the build itself.

### Triggering the Workflow

```bash
# Push to main triggers automatically after build succeeds
# Manual dispatch:
gh workflow run build.yml -R kkaple/WebGoat -f upload_build_output=true
```

## Phase 2 Consumer Architecture

### Event-Driven Flow

```
GitHub Actions (Build + Phase 1)
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
loop:
    msg := sqs.ReceiveMessage(queue, waitTimeSeconds=20)
    if msg == nil: continue

    // Parse S3 event → extract key
    // e.g., kkaple/WebGoat/20260603-153000_8c3a1710b358_269444/phase1/.../manifest.json
    s3Key := parseS3Key(msg)
    jobPrefix := extractJobPrefix(s3Key)  // "kkaple/WebGoat/20260603-..."

    // Launch Phase 2 ECS task with environment overrides
    ecs.RunTask({
        taskDefinition: "omnibor-phase2",
        overrides: {
            containerOverrides: [{
                environment: [
                    {S3_INPUT_PATH:  "s3://bucket/" + jobPrefix + "/phase1/"},
                    {S3_OUTPUT_PATH: "s3://bucket/" + jobPrefix + "/spdx/"},
                    {REPO_NAME:      repoFromPrefix(jobPrefix)},
                ],
            }],
        },
    })

    // Optionally wait for task completion, then delete SQS message
    sqs.DeleteMessage(msg)
```

## ECS Deployment via AWS CDK

### Architecture

```
GitHub Actions (Build + Phase 1)
    │
    ▼
S3 bucket
    │
    ├── Event Notification
    ▼
SQS queue
    │
    ▼
ECS Fargate Service (operator microservice) ← long-running, 1 task
    │
    │  calls ecs:RunTask
    ▼
ECS Fargate Task (omnibor-sidecar)        ← ephemeral, per-job
    │
    │  reads Phase 1 from S3, writes SPDX back to S3
    ▼
S3 bucket (spdx/ prefix)
```

Fargate is a launch type within ECS — not a separate service. Any ECS
cluster supports both Fargate and EC2 launch types. If the target
environment is an existing ECS cluster with EC2 instances, Phase 2 tasks
can run on either launch type (one-line CDK change).

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
  visibilityTimeout: cdk.Duration.minutes(15),  // must exceed Phase 2 runtime
  retentionPeriod: cdk.Duration.days(7),
  deadLetterQueue: {
    queue: new sqs.Queue(this, 'Phase1DLQ', {
      queueName: 'omnibor-phase1-dlq',
      retentionPeriod: cdk.Duration.days(14),
    }),
    maxReceiveCount: 3,  // retry 3 times, then DLQ
  },
});

// Only fire on phase1_manifest.json — signals Phase 1 is complete
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

// ── Operator microservice (long-running service) ──
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
    SUBNET_IDS: '',       // populated via CDK tokens
    SECURITY_GROUP: '',   // populated via CDK tokens
  },
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
  // Environment variables set at RunTask time by the operator microservice:
  //   S3_INPUT_PATH, S3_OUTPUT_PATH, MANIFEST_PATH, REPO_NAME
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
// Operator: read SQS, read/write S3, launch ECS tasks
queue.grantConsumeMessages(operatorTaskDef.taskRole);
bucket.grantRead(operatorTaskDef.taskRole);
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
  description: 'Operator — egress only',
});

new ecs.FargateService(this, 'OperatorService', {
  cluster,
  taskDefinition: operatorTaskDef,
  desiredCount: 1,
  assignPublicIp: true,  // or use NAT gateway
  securityGroups: [sg],
});
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **SQS filter on `phase1_manifest.json` suffix** | Only fires once per Phase 1 run, not per file |
| **Dead letter queue** | Failed Phase 2 jobs don't disappear silently |
| **Visibility timeout > Phase 2 runtime** | Prevents duplicate launches |
| **Separate task definitions** | Operator is small (256 CPU); Phase 2 needs more compute |
| **Fargate (not EC2)** | No cluster management; pay per task-second |
| **Phase 2 reads/writes S3 directly** | No shared filesystem needed |

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
Operator microservice #2 (or same operator, second goroutine)
    │
    ▼
Post-processing actions
```

### Post-Processing Options

- **Vulnerability scan** — feed SPDX to Grype, Trivy, or OSV
- **Policy check** — verify license compliance, banned packages
- **Notification** — Slack/Teams alert, GitHub commit status update
- **Database ingest** — store SBOM metadata in a DB for querying
- **Dashboard update** — push to a web UI or API
- **Comparison** — diff against golden files or previous SPDX

### CDK Addition

```typescript
const spdxQueue = new sqs.Queue(this, 'SpdxCompleteQueue', {
  queueName: 'omnibor-spdx-complete',
  visibilityTimeout: cdk.Duration.minutes(5),
});

bucket.addEventNotification(
  s3.EventType.OBJECT_CREATED,
  new s3n.SqsDestination(spdxQueue),
  { suffix: '.spdx.json' },
);
```

### Extending the Operator

Currently the operator is a single threaded prototype.  This will need to change in the move to an official ECS platform and real repositories.

**Option A: Single binary, multiple goroutines:**

```go
go pollQueue(phase1Queue, handlePhase1)  // launches Phase 2 container
go pollQueue(spdxQueue,   handleSPDX)    // post-processing actions
```

**Option B: Separate service** — independent scaling and different
compute/reliability requirements.

You can chain as many stages as needed — each writes to S3, each S3
event triggers the next queue. S3 serves as the data bus for the
entire event-driven pipeline.

---

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
    │  (matches <jar_stem>_analyzed.spdx.json, <jar_stem>_build.spdx.json,
    │   <jar_stem>-sbom-tree.json)
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

Both SHA-1 (40 hex chars) and SHA-256 (64 hex chars) are independently
unique, so the key is self-discriminating by length. Two items are written
per artifact — both contain identical S3 URIs and metadata. This doubles
storage per artifact (~1 KB total) but enables lookup by either hash
without a GSI.

Because the `SpdxIndexTable` now stores the S3 location of the
sbom-tree JSON, the `SpdxDependencyGraph` table items can be assigned
a DynamoDB TTL in the future. Once expired, the dependency graph can
be reconstructed on demand from the sbom-tree JSON in S3.

### Client Lookup

A downstream consumer queries by any SHA (SHA-256 or SHA-1) to get
SPDX locations:

```go
result, err := dynamoClient.GetItem(ctx, &dynamodb.GetItemInput{
    TableName: aws.String("SpdxIndexTable"),
    Key: map[string]types.AttributeValue{
        "ArtifactSHA": &types.AttributeValueMemberS{Value: shaHex},
    },
})
```

The caller does not need to know the hash algorithm — both SHA-1 and
SHA-256 resolve to the same S3 URIs. If the item exists,
`AnalyzedSpdxS3`, `BuildSpdxS3`, and `SbomTreeS3` contain full S3 URIs.

### CDK Table Definition

```typescript
const spdxIndexTable = new dynamodb.Table(this, 'SpdxIndexTable', {
  partitionKey: { name: 'ArtifactSHA', type: dynamodb.AttributeType.STRING },
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: dynamoKey,
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  pointInTimeRecovery: true,
  removalPolicy: retainData ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
});
```

Follows the scan-service `Data` stack pattern (`ScansTable`, `ToolsTable`)
with KMS encryption, on-demand billing, and environment-aware retention.

### Source Code

The `spdx-indexing` Go module lives at `spdx-indexing/` alongside the
operator:

```
spdx-indexing/
├── cmd/main.go                    # CLI entry point
├── internal/indexer/
│   ├── indexer.go                 # Manifest reader, S3 lister, DynamoDB writer
│   └── graph.go                   # Dependency graph extraction (BFS, adjacency list)
├── go.mod
└── go.sum
```

It accepts a manifest path (local or `s3://`), S3 bucket, job prefix,
DynamoDB table name, and optional graph table — all configurable via
flags or environment variables.

| Flag / Env Var | Description |
|---|---|
| `-manifest` | Path to `phase1_manifest.json` (local or `s3://`) |
| `-bucket` / `S3_BUCKET` | S3 bucket containing SPDX output |
| `-table` / `DYNAMO_TABLE` | DynamoDB table for SPDX index records |
| `-graph-table` / `DYNAMO_GRAPH_TABLE` | DynamoDB table for dependency graph (optional) |
| `-prefix` / `JOB_PREFIX` | S3 job prefix |
| `-dry-run` | Log what would be indexed without writing |

### Dependency Graph Table (`SpdxDependencyGraph`)

A second DynamoDB table stores the full package dependency graph
extracted from the SPDX `DEPENDS_ON` relationships. This enables
depth-based dependency lookups: "What are the direct dependencies
of this binary?" or "Show me the full transitive tree."

#### Why a separate table?

The `SpdxIndexTable` is a fast key-value lookup — "does SPDX exist
for this binary?" It must stay lean. The dependency graph can contain
hundreds of packages (WebGoat has 160) and would bloat the index
record. Separating concerns keeps the index fast and the graph
queryable independently.

#### Segmented adjacency list design

Each package is stored as its own DynamoDB item to avoid the 400 KB
item size limit. Growth adds more items, not bigger items.

| Attribute | Type | Role |
|-----------|------|------|
| `ArtifactSHA` | String | Partition key — groups all nodes for one artifact |
| `SK` | String | Sort key — `depth#N#PURL` enables range queries |
| `purl` | String | Package URL (e.g. `pkg:maven/org.springframework/spring-core@6.2.7`) |
| `name` | String | Package name |
| `version` | String | Package version |
| `supplier` | String | Maven groupId / organization |
| `scope` | String | Maven scope (compile, runtime, provided) |
| `depth` | Number | Distance from root (0 = root, 1 = direct, 2+ = transitive) |
| `parent` | String | Parent PURL, or null for root |
| `children` | List\<String\> | Child PURLs (direct dependents of this node) |

#### Example items

```json
{
  "ArtifactSHA": "a88ab4a1...",
  "SK": "depth#0#pkg:maven/WebGoat/webgoat@2025.4",
  "purl": "pkg:maven/WebGoat/webgoat@2025.4",
  "name": "webgoat",
  "version": "2025.4",
  "depth": 0,
  "parent": null,
  "children": [
    "pkg:maven/org.springframework.boot/spring-boot-starter-web@3.5.6",
    "pkg:maven/org.apache.commons/commons-exec@1.5.0"
  ]
}

{
  "ArtifactSHA": "a88ab4a1...",
  "SK": "depth#1#pkg:maven/org.springframework.boot/spring-boot-starter-web@3.5.6",
  "purl": "pkg:maven/org.springframework.boot/spring-boot-starter-web@3.5.6",
  "name": "spring-boot-starter-web",
  "version": "3.5.6",
  "supplier": "org.springframework.boot",
  "scope": "compile",
  "depth": 1,
  "parent": "pkg:maven/WebGoat/webgoat@2025.4",
  "children": [
    "pkg:maven/org.springframework.boot/spring-boot-starter@3.5.6",
    "pkg:maven/org.springframework.boot/spring-boot@3.5.6"
  ]
}
```

#### Depth-based query API

The `depth` parameter controls how many levels of the dependency
tree to return:

| `depth` value | Returns | Use case |
|---------------|---------|----------|
| `1` | Root + direct dependencies | "What does this binary directly depend on?" |
| `2` | Root + direct + their children | Two-level vulnerability blast radius |
| `N` | Root + N levels deep | Configurable depth traversal |
| `0` | All levels (full transitive closure) | Complete dependency tree |

```go
// depth=1 — direct dependencies only
result, _ := dynamoClient.Query(ctx, &dynamodb.QueryInput{
    TableName:              aws.String("SpdxDependencyGraph"),
    KeyConditionExpression: aws.String(
        "ArtifactSHA = :sha AND SK BETWEEN :d0 AND :d1"),
    ExpressionAttributeValues: map[string]types.AttributeValue{
        ":sha": &types.AttributeValueMemberS{Value: shaHex},
        ":d0":  &types.AttributeValueMemberS{Value: "depth#0"},
        ":d1":  &types.AttributeValueMemberS{Value: "depth#1\xff"},
    },
})

// depth=0 — full tree (all levels)
result, _ := dynamoClient.Query(ctx, &dynamodb.QueryInput{
    TableName:              aws.String("SpdxDependencyGraph"),
    KeyConditionExpression: aws.String("ArtifactSHA = :sha"),
    ExpressionAttributeValues: map[string]types.AttributeValue{
        ":sha": &types.AttributeValueMemberS{Value: shaHex},
    },
})
```

#### Size characteristics

Each item is 300–500 bytes (one package node + child PURLs as
strings). No single item can exceed the 400 KB limit.

| Project size | Packages | Total storage per artifact |
|--------------|----------|---------------------------|
| Small library | 20 | ~10 KB |
| WebGoat | 160 | ~80 KB |
| Large Spring app | 500 | ~250 KB |
| Monorepo uber-jar | 1,500 | ~750 KB |

#### CDK table definition

```typescript
const spdxGraphTable = new dynamodb.Table(this, 'SpdxDependencyGraph', {
  partitionKey: { name: 'ArtifactSHA', type: dynamodb.AttributeType.STRING },
  sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: dynamoKey,
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  pointInTimeRecovery: true,
  removalPolicy: retainData ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
});
```

#### Complete lookup flow

```
1. GetItem(SpdxIndexTable, ArtifactSHA=<any hash>)
   → S3 URIs, repo name, VCS URI        (existence check)

2. Query(SpdxDependencyGraph, ArtifactSHA=<sha256>, depth=N)
   → Package nodes at requested depth   (dependency tree)
```

Two DynamoDB calls max. No scans, no joins. The depth query uses
the sort key range to return only the requested levels — DynamoDB
handles pagination automatically for large result sets.

#### Future: SHA-256 enrichment for dependency packages

Currently, only the root artifact has SHA-1 and SHA-256 checksums.
Dependency packages are identified by PURL. A future enhancement will
compute checksums for each dependency JAR from `.m2/repository` during
Phase 1 and enrich `maven_deps.json`, enabling full SHA-based
cross-linking between artifacts.

---

## SBOM Tree Generator

The `sbom-tree` module generates a nested JSON representation of the
full dependency tree from the `SpdxDependencyGraph` DynamoDB table.
It runs as an SQS-driven worker — the operator publishes a message
after dependency graph indexing, and the worker picks it up, queries
DynamoDB, reconstructs the tree, and uploads the result to S3.

### Architecture {#sbom-tree-architecture}

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

### End-to-End Post-Phase 2 Pipeline

```
Phase 2 completes
    │
    ▼
SPDX files written to S3
    │
    ▼
spdx-indexing (inline in operator)
    ├─ Write SpdxIndexTable records (artifact → S3 URIs)
    ├─ Parse build SPDX, BFS depth, write SpdxDependencyGraph nodes
    └─ Publish SQS message to omnibor-sbom-tree-requests
          │
          ▼
    sbom-tree worker (separate process)
          ├─ Query DynamoDB for full tree
          ├─ Build nested JSON
          └─ Upload <artifact>-sbom-tree.json to S3
```

### SQS Queue {#sbom-tree-sqs-queue}

| Attribute | Value |
|---|---|
| Queue name | `omnibor-sbom-tree-requests` |
| Region | `us-east-1` |
| Queue URL | `https://sqs.us-east-1.amazonaws.com/930218373905/omnibor-sbom-tree-requests` |

#### SQS message format

```json
{
  "artifactSHA": "a614855c7fe1679db2b9cf8bd518e5c52c544b9db4020b38180aca21db2b7ef4",
  "artifactSHA1": "e3b0c44298fc1c149afbf4c8996fb924",
  "artifactName": "webgoat-2025.4-SNAPSHOT",
  "jobPrefix": "java/WebGoat/abc123/42",
  "bucket": "omnibor-spdx-artifacts",
  "graphTable": "SpdxDependencyGraph"
}
```

The operator publishes this message after `IndexGraph` succeeds.
SQS visibility timeout handles retries — if the worker fails, the
message reappears for retry.

### Output Format

The output is a nested JSON tree using `dependency` as the
relationship field name. Uploaded to
`s3://<bucket>/<jobPrefix>/spdx/<artifactName>-sbom-tree.json`.

```json
{
  "artifactSHA": "a614855c...",
  "artifactName": "webgoat-2025.4-SNAPSHOT",
  "generatedAt": "2026-06-02T21:10:12.365219Z",
  "root": {
    "purl": "pkg:maven/WebGoat/webgoat",
    "name": "webgoat",
    "version": "2025.4",
    "supplier": "NOASSERTION",
    "depth": 0,
    "dependency": [
      {
        "purl": "pkg:maven/org.apache.commons/commons-exec@1.5.0",
        "name": "commons-exec",
        "version": "1.5.0",
        "supplier": "org.apache.commons",
        "scope": "compile",
        "depth": 1,
        "dependency": []
      },
      {
        "purl": "pkg:maven/org.springframework.boot/spring-boot-starter-web@3.5.6",
        "name": "spring-boot-starter-web",
        "version": "3.5.6",
        "supplier": "org.springframework.boot",
        "scope": "compile",
        "depth": 1,
        "dependency": [
          { "...nested transitive dependencies..." }
        ]
      }
    ]
  },
  "stats": {
    "totalPackages": 161,
    "maxDepth": 7,
    "directDependencies": 38
  }
}
```

### Source Code

```
sbom-tree/
├── cmd/main.go                        # Dual-mode entry point (SQS consumer or one-shot CLI)
├── internal/
│   ├── consumer/consumer.go           # SQS polling and message dispatch
│   └── treegen/treegen.go             # DynamoDB query, tree reconstruction, S3 upload
├── go.mod
└── go.sum
```

### Running the sbom-tree Worker

**SQS consumer mode** (production — polls for messages):

```bash
AWS_PROFILE=kak-cli \
SQS_SBOM_TREE_URL="https://sqs.us-east-1.amazonaws.com/930218373905/omnibor-sbom-tree-requests" \
go run cmd/main.go
```

**One-shot mode** (debugging — generates a single tree):

```bash
AWS_PROFILE=kak-cli \
go run cmd/main.go \
  -once \
  -sha <artifact-sha256> \
  -name <artifact-name> \
  -prefix <job-prefix> \
  -bucket omnibor-spdx-artifacts \
  -graph-table SpdxDependencyGraph
```

### Operator Configuration

To enable sbom-tree publishing, add `SQS_SBOM_TREE_URL` to the
operator's environment:

```bash
AWS_PROFILE=kak-cli \
SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/930218373905/omnibor-phase1-notifications" \
S3_BUCKET="omnibor-spdx-artifacts" \
SIDECAR_IMAGE="ghcr.io/kkaple/omnibor-sidecar:dev" \
DYNAMO_TABLE="SpdxIndexTable" \
DYNAMO_GRAPH_TABLE="SpdxDependencyGraph" \
SQS_SBOM_TREE_URL="https://sqs.us-east-1.amazonaws.com/930218373905/omnibor-sbom-tree-requests" \
go run cmd/operator/main.go
```

The operator logs confirmation at startup:

```
[INFO] SPDX indexing enabled (table: SpdxIndexTable)
[INFO] Dependency graph indexing enabled (table: SpdxDependencyGraph)
[INFO] sbom-tree publishing enabled (queue: https://sqs...omnibor-sbom-tree-requests)
```

---

## GitHub Actions → Jenkins: What Changes

This section documents what would change if a target repository (e.g.,
WebGoat) used **Jenkins** instead of GitHub Actions as its build system.
The key takeaway is that the entire downstream pipeline (S3 → operator →
Phase 2 → indexing → sbom-tree) is **CI-system-agnostic by design** — it
triggers off S3 events, not CI webhooks.

### What the GHA Workflow Does Today

The `phase1-s3` job in the WebGoat workflow performs:

1. **Build** — Maven package inside a Temurin JDK 25 Docker container
2. **GHCR login** — pull the `omnibor-sidecar` image
3. **Phase 1** — run the sidecar container to generate SPDX + manifest
4. **AWS auth** — OIDC federation (`id-token: write` → `role-to-assume`)
5. **S3 upload** — push Phase 1 artifacts to
   `s3://omnibor-spdx-artifacts/{repo}/{jobId}/phase1/`

Phase 2 is then triggered by the operator consuming S3 event
notifications — it has no awareness of which CI system produced the
artifacts.

### Changes Needed for Jenkins

#### Jenkinsfile replaces the GHA workflow

A mechanical translation of GHA YAML to Jenkinsfile Groovy:

| GHA concept | Jenkins equivalent |
|---|---|
| `on: push/pull_request` | Multibranch pipeline + webhook trigger |
| `workflow_dispatch` | `parameters { booleanParam(...) }` |
| `concurrency` group | `options { disableConcurrentBuilds() }` |
| Matrix builds | `parallel` stages or matrix directive (Declarative) |
| `actions/checkout` | `checkout scm` (automatic in multibranch) |
| `actions/setup-java` | `tools { jdk 'temurin-25' }` or Docker agent |

#### AWS authentication — the biggest change

GHA uses OIDC federation (`id-token: write`). Jenkins options:

- **Jenkins OIDC plugin** — Jenkins can also federate via OIDC to AWS
  IAM, but requires the Jenkins instance to be registered as an OIDC
  identity provider in IAM (new IAM OIDC provider + trust policy
  statement, similar to the GHE pattern in the Appendix)
- **IAM instance profile** — if Jenkins runs on EC2, attach the S3
  role directly to the instance (simplest, no credentials to manage)
- **Stored credentials** — `withCredentials([[$class:
  'AmazonWebServicesCredentialsBinding']])` using the AWS Credentials
  plugin (least ideal, requires static access keys)

#### GHCR image pull

Jenkins needs a Docker registry credential:

- Store GHCR PAT in Jenkins Credentials store
- Use `docker.withRegistry('https://ghcr.io', 'ghcr-cred-id')` or
  `withCredentials` to authenticate before pulling

#### S3 upload

Two options:

- **AWS CLI** — same `aws s3 cp` commands as GHA, if credentials are
  available in the shell environment
- **Pipeline AWS Steps plugin** — `s3Upload` step for a more
  Jenkins-native approach

#### Job ID construction

GHA uses `${{ github.sha }}` and `${{ github.run_id }}`. Jenkins
equivalents:

- `env.GIT_COMMIT` (or `sh(returnStdout: true, script: 'git rev-parse HEAD')`)
- `env.BUILD_NUMBER`

The S3 path convention `{datetime}_{sha12}_{buildId}` is preserved.

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
        S3_BUCKET     = 'omnibor-spdx-artifacts'
        S3_REPO       = 'kkaple/WebGoat'
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
        stage('Phase 1') {
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
                sh '''
                    mkdir -p spdx-output
                    docker run --rm \
                      -v "$WORKSPACE:/workspace/repos/WebGoat" \
                      -v "$WORKSPACE/spdx-output:/workspace/output" \
                      -e OMNIBOR_MODE=sidecar \
                      $SIDECAR_IMAGE \
                      python3 /workspace/app/analyze.py \
                        --repo WebGoat --mode sidecar \
                        --phase build --skip-clone
                '''
            }
        }
        stage('S3 Upload') {
            steps {
                // Option A: IAM instance profile (no explicit credentials)
                // Option B: withAWS(role:...) or withCredentials([...])
                sh '''
                    SHORT_SHA=$(git rev-parse --short=12 HEAD)
                    TS=$(date -u +%Y%m%d-%H%M%S)
                    JOB_ID="${TS}_${SHORT_SHA}_${BUILD_NUMBER}"
                    S3_PATH="s3://$S3_BUCKET/$S3_REPO/${JOB_ID}"
                    echo "[INFO] Uploading to ${S3_PATH}/phase1/"
                    aws s3 cp spdx-output/ "${S3_PATH}/phase1/" --recursive
                '''
            }
        }
    }
}
```

### Diagram Recommendation

A separate draw.io diagram is **not required**. The existing diagram
(`gh-aws-corona.drawio`) already separates the "Build Site" swim lane
from the "AWS Cloud" swim lane. The only difference for Jenkins is the
contents of the Build Site lane:

- The lane title changes from "Build Site (GitHub Actions)" to
  "Build Site (Jenkins)"
- The "OIDC Auth" box changes to the Jenkins-appropriate credential
  mechanism (instance profile, OIDC plugin, or stored credentials)
- All boxes inside the "AWS Cloud" lane remain identical

If a Jenkins-specific diagram is desired in the future, the recommended
approach is to add a **second page (tab)** within the same
`gh-aws-corona.drawio` file named "Jenkins Variant" that duplicates only
the Build Site lane with Jenkins-specific labels. This avoids
maintaining two separate files while keeping both variants accessible.

---

## Appendix: Multiple OIDC Providers (GitHub.com + GitHub Enterprise)

GitHub.com and GitHub Enterprise Server (GHE) have **separate OIDC issuer
URLs**. Each issuer requires its own IAM OIDC Identity Provider in AWS,
and the trust policy needs a separate `Statement` block per provider.

### Step 1: Create OIDC Providers for Each Issuer

**GitHub.com** (already created above):

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

**Cisco GitHub Enterprise** — replace the thumbprint with the actual value
from your GHE instance's TLS certificate chain:

```bash
aws iam create-open-id-connect-provider \
  --url https://gh-xr.scm.engit.cisco.com/_services/token \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list <GHE_THUMBPRINT>
```

To obtain the GHE thumbprint:

```bash
# Fetch the TLS certificate chain and extract the root CA thumbprint
openssl s_client -connect gh-xr.scm.engit.cisco.com:443 -servername gh-xr.scm.engit.cisco.com \
  </dev/null 2>/dev/null | openssl x509 -fingerprint -noout \
  | tr -d ':' | cut -d= -f2 | tr 'A-F' 'a-f'
```

### Step 2: Trust Policy with Multiple Principals

Each OIDC provider gets its own `Statement` block. A single statement
cannot reference two different `Federated` principals.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GitHubComOIDC",
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::930218373905:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": [
            "repo:tedg-dev/omnibor-*-testapp:*",
            "repo:CiscoSecurityServices/*:*"
          ]
        }
      }
    },
    {
      "Sid": "CiscoGHEOIDC",
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::930218373905:oidc-provider/gh-xr.scm.engit.cisco.com/_services/token"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "gh-xr.scm.engit.cisco.com/_services/token:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "gh-xr.scm.engit.cisco.com/_services/token:sub": [
            "repo:*/*:*"
          ]
        }
      }
    }
  ]
}
```

### Key Differences from Single-Provider Setup

| Aspect | Single provider | Multiple providers |
|--------|----------------|--------------------|
| **OIDC providers** | 1 `create-open-id-connect-provider` call | 1 per issuer |
| **Trust policy statements** | 1 statement | 1 per provider (different `Principal`) |
| **Condition keys** | Prefixed with `token.actions.githubusercontent.com:` | Prefixed with each provider's issuer hostname |
| **Thumbprints** | GitHub.com's known thumbprint | Must be obtained per GHE instance |
| **S3 permissions** | Unchanged | Unchanged — same role, same S3 policy |

### Updating the Live Policy

After editing the trust policy JSON:

```bash
aws iam update-assume-role-policy \
  --role-name github-actions-s3 \
  --policy-document file:///tmp/trust-policy.json
```

The S3 permissions policy does not change — it grants access to the bucket
regardless of which OIDC provider authenticated the caller. Only the trust
policy (who can *assume* the role) needs per-provider statements.

### GHE OIDC Issuer URL

The issuer URL for GitHub Enterprise Server is typically:

```
https://<GHE_HOSTNAME>/_services/token
```

Verify by checking your GHE instance's Actions OIDC configuration, or
by inspecting the `iss` claim in a token from a GHE Actions workflow:

```yaml
- name: Debug OIDC token
  run: |
    TOKEN=$(curl -sS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
      "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com")
    echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '.iss, .sub'
```

---

## Production Sub-Issues (gambit#10786)

| # | Title | Issue |
|---|-------|-------|
| 1 | Deploy Phase 2 into existing scan-service VPC | [#10888](https://github.com/CiscoSecurityServices/gambit/issues/10888) |
| 2 | S3 Bucket + SQS Event Plumbing for Phase 1 Intake | [#10889](https://github.com/CiscoSecurityServices/gambit/issues/10889) |
| 3 | OIDC Federation + IAM Roles | [#10890](https://github.com/CiscoSecurityServices/gambit/issues/10890) |
| 4 | ECS Cluster + Fargate Task Definitions | [#10891](https://github.com/CiscoSecurityServices/gambit/issues/10891) |
| 5 | Container Image Registry + CI Pipeline | [#10892](https://github.com/CiscoSecurityServices/gambit/issues/10892) |
| 6 | DynamoDB SPDX Index Table | [#10894](https://github.com/CiscoSecurityServices/gambit/issues/10894) |
| 7 | Operator Worker Pool for Concurrent Phase 2 Processing | [#10901](https://github.com/CiscoSecurityServices/gambit/issues/10901) |
| 8 | AWS Auto Scaling for Operator Instances Based on SQS Queue Depth | [#10902](https://github.com/CiscoSecurityServices/gambit/issues/10902) |
| 9 | AWS Auto Scaling for sbom-tree Instances Based on SQS Queue Depth | [#10903](https://github.com/CiscoSecurityServices/gambit/issues/10903) |
| 10 | Containerize sbom-tree Worker (Dockerfile + ECR + CI) | [#10904](https://github.com/CiscoSecurityServices/gambit/issues/10904) |
| 11 | Containerize spdx-indexing CLI (Dockerfile + ECR + CI) | [#10905](https://github.com/CiscoSecurityServices/gambit/issues/10905) |
