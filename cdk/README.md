# CDK — OmniBOR ECS Infrastructure

AWS CDK stack for deploying the OmniBOR SBOM pipeline services on ECS Fargate.

## What It Creates

| Resource | Description |
|----------|-------------|
| **VPC** | 2 AZs, public + private subnets, 1 NAT gateway |
| **ECS Cluster** | Fargate-only cluster (`omnibor`) |
| **Cloud Map** | Private DNS namespace (`omnibor.local`) for service discovery |
| **S3 Bucket** | `omnibor-spdx-artifacts-<account>` for SPDX output |
| **SQS Queues** | Phase 2 trigger queue + SBOM tree queue + dead letter queue |
| **DynamoDB** | `SpdxIndexTable` + `SpdxDependencyGraph` (on-demand billing) |
| **NATS** | Fargate service with JetStream, registered as `nats.omnibor.local` |
| **Operator** | Fargate service behind ALB — presigned URL broker + Phase 2 orchestrator |
| **Phase 2** | Task definition only (launched on-demand by operator) |
| **SBOM Tree** | Fargate service — SQS consumer for tree generation |
| **ALB** | Public load balancer — provides stable DNS for operator |

## Prerequisites

1. **Node.js 18+**: `brew install node`
2. **AWS CDK CLI**: installed via `package.json` devDependency
3. **AWS credentials**: `duo-sso --profile ted-admin` (sessions expire hourly)

## Quick Start

```bash
cd cdk

# Install dependencies (one-time)
npm install

# Bootstrap CDK in your AWS account (one-time per account+region)
npx cdk bootstrap

# Preview what will be created
npx cdk diff

# Deploy (uses your GHCR namespace for container images)
npx cdk deploy -c ghcrOwner=kkaple
```

## After Deploy

The stack outputs the ALB DNS name:

```
Outputs:
  OmniBor.OperatorURL = http://omnibor-op-xxxxx.us-east-1.elb.amazonaws.com
```

Use this as `OPERATOR_URL` in CI workflows.

## Update Services (after pushing new images)

```bash
# Push new image
GHCR_OWNER=kkaple make push-omnibor-operator

# Tell ECS to pull the new image
aws ecs update-service --cluster omnibor --service <service-name> --force-new-deployment
```

## Destroy

```bash
npx cdk destroy
```

S3 bucket and DynamoDB tables have `RETAIN` policy — they survive stack deletion
to prevent accidental data loss. Delete them manually if needed.

## Cost Estimate (dev)

| Resource | Estimate |
|----------|----------|
| NAT Gateway | ~$32/month + data |
| ALB | ~$16/month |
| Operator (256 CPU, 512 MB) | ~$9/month |
| NATS (256 CPU, 512 MB) | ~$9/month |
| SBOM Tree (256 CPU, 512 MB) | ~$9/month |
| Phase 2 tasks (on-demand) | ~$0.04/run |
| DynamoDB (on-demand) | < $1/month |
| SQS | Free tier |
| S3 | < $1/month |
| **Total** | **~$77/month** |

The NAT gateway is the largest cost. To reduce: use VPC endpoints for S3/DynamoDB/SQS
(eliminates NAT traffic for AWS service calls) or use public subnets for Fargate
tasks with `assignPublicIp: true` (eliminates NAT entirely, less secure).
