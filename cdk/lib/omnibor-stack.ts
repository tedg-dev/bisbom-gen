import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecs_patterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';

import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export class OmniborStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const ghcrOwner = this.node.tryGetContext('ghcrOwner') ?? 'kkaple';

    // GHCR registry credentials (created via CLI, not in CDK)
    const ghcrSecret = secretsmanager.Secret.fromSecretNameV2(
      this, 'GhcrCredentials', 'ghcr-credentials',
    );

    // ================================================================
    // VPC — public + private subnets, NAT gateway for Fargate egress
    // ================================================================

    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
      ],
    });

    // ================================================================
    // ECS Cluster + Cloud Map namespace for service discovery
    // ================================================================

    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
    });

    const namespace = new servicediscovery.PrivateDnsNamespace(
      this, 'Namespace', {
        name: 'omnibor.local',
        vpc,
      },
    );

    // ================================================================
    // S3 — SPDX artifact storage
    // ================================================================

    // Bucket already exists in this account — import by name
    const bucket = s3.Bucket.fromBucketName(
      this, 'ArtifactBucket',
      `omnibor-spdx-artifacts-${this.account}`,
    );

    // ================================================================
    // SQS — Phase 2 trigger queue
    // ================================================================

    const dlq = new sqs.Queue(this, 'Phase2DLQ', {
      retentionPeriod: cdk.Duration.days(14),
    });

    const queue = new sqs.Queue(this, 'Phase2Queue', {
      visibilityTimeout: cdk.Duration.minutes(15),
      deadLetterQueue: {
        maxReceiveCount: 3,
        queue: dlq,
      },
    });

    // NOTE: S3 event notification (phase1_manifest.json -> SQS) must be
    // configured manually since the bucket is imported, not CDK-managed.
    // aws s3api put-bucket-notification-configuration ...

    // ================================================================
    // DynamoDB — SPDX index + dependency graph
    // ================================================================

    // Tables already exist in this account — import by name
    const indexTable = dynamodb.Table.fromTableName(
      this, 'SpdxIndexTable', 'SpdxIndexTable',
    );

    const graphTable = dynamodb.Table.fromTableName(
      this, 'SpdxDependencyGraph', 'SpdxDependencyGraph',
    );

    // ================================================================
    // NATS — JetStream message broker (VPC-internal only)
    // ================================================================

    const natsTaskDef = new ecs.FargateTaskDefinition(this, 'NatsTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
    });

    natsTaskDef.addContainer('nats', {
      image: ecs.ContainerImage.fromRegistry('nats:2.10-alpine'),
      command: ['--jetstream', '--store_dir', '/data', '--http_port', '8222'],
      portMappings: [
        { containerPort: 4222, protocol: ecs.Protocol.TCP },
        { containerPort: 8222, protocol: ecs.Protocol.TCP },
      ],
      logging: ecs.LogDrivers.awsLogs({
        logGroup: new logs.LogGroup(this, 'NatsLogs', {
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        streamPrefix: 'nats',
      }),
    });

    const natsSg = new ec2.SecurityGroup(this, 'NatsSg', {
      vpc,
      description: 'NATS server - accepts client connections on 4222',
    });

    new ecs.FargateService(this, 'NatsService', {
      cluster,
      taskDefinition: natsTaskDef,
      desiredCount: 1,
      securityGroups: [natsSg],
      assignPublicIp: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      cloudMapOptions: {
        name: 'nats',
        cloudMapNamespace: namespace,
        dnsRecordType: servicediscovery.DnsRecordType.A,
      },
    });

    // ================================================================
    // Operator — presigned URL broker + Phase 2 orchestrator + notifier
    // ================================================================

    const operatorTaskDef = new ecs.FargateTaskDefinition(this, 'OperatorTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
    });

    // Grant the operator access to S3, SQS, DynamoDB, ECS
    bucket.grantReadWrite(operatorTaskDef.taskRole);
    queue.grantConsumeMessages(operatorTaskDef.taskRole);
    indexTable.grantReadWriteData(operatorTaskDef.taskRole);
    graphTable.grantReadWriteData(operatorTaskDef.taskRole);

    // Allow operator to launch Phase 2 ECS tasks
    operatorTaskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:RunTask', 'ecs:DescribeTasks', 'iam:PassRole'],
        resources: ['*'],
      }),
    );

    operatorTaskDef.addContainer('operator', {
      image: ecs.ContainerImage.fromRegistry(
        `ghcr.io/${ghcrOwner}/omnibor-operator:dev`,
        { credentials: ghcrSecret },
      ),
      containerName: 'operator',
      portMappings: [
        { containerPort: 8080, protocol: ecs.Protocol.TCP },
      ],
      environment: {
        SQS_QUEUE_URL: queue.queueUrl,
        S3_BUCKET: bucket.bucketName,
        DYNAMO_TABLE: indexTable.tableName,
        DYNAMO_GRAPH_TABLE: graphTable.tableName,
        ECS_CLUSTER: cluster.clusterName,
        NATS_URL: 'nats://nats.omnibor.local:4222',
        OIDC_ISSUERS: [
          'https://token.actions.githubusercontent.com',
          'https://gh-xr.scm.engit.cisco.com/_services/token',
        ].join(','),
      },
      logging: ecs.LogDrivers.awsLogs({
        logGroup: new logs.LogGroup(this, 'OperatorLogs', {
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        streamPrefix: 'operator',
      }),
    });

    // ALB-fronted Fargate service — provides the stable DNS name
    const operatorService = new ecs_patterns.ApplicationLoadBalancedFargateService(
      this, 'OperatorService', {
        cluster,
        taskDefinition: operatorTaskDef,
        desiredCount: 1,
        publicLoadBalancer: true,
        assignPublicIp: false,
        listenerPort: 80,
      },
    );

    // Health check on the operator HTTP port
    operatorService.targetGroup.configureHealthCheck({
      path: '/healthz',
      port: '8080',
    });

    // Allow operator -> NATS
    natsSg.addIngressRule(
      operatorService.service.connections.securityGroups[0],
      ec2.Port.tcp(4222),
      'Operator to NATS',
    );

    // ================================================================
    // Phase 2 task definition (launched by operator, not always-on)
    // ================================================================

    const phase2TaskDef = new ecs.FargateTaskDefinition(this, 'Phase2TaskDef', {
      cpu: 2048,
      memoryLimitMiB: 4096,
    });

    bucket.grantReadWrite(phase2TaskDef.taskRole);

    phase2TaskDef.addContainer('sidecar', {
      image: ecs.ContainerImage.fromRegistry(
        `ghcr.io/${ghcrOwner}/omnibor-sidecar:dev`,
        { credentials: ghcrSecret },
      ),
      logging: ecs.LogDrivers.awsLogs({
        logGroup: new logs.LogGroup(this, 'Phase2Logs', {
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        streamPrefix: 'phase2',
      }),
    });

    // ================================================================
    // SBOM Tree generator — SQS consumer (always-on)
    // ================================================================

    const sbomTreeQueue = new sqs.Queue(this, 'SbomTreeQueue', {
      visibilityTimeout: cdk.Duration.minutes(5),
    });

    const sbomTreeTaskDef = new ecs.FargateTaskDefinition(this, 'SbomTreeTaskDef', {
      cpu: 256,
      memoryLimitMiB: 512,
    });

    bucket.grantReadWrite(sbomTreeTaskDef.taskRole);
    graphTable.grantReadData(sbomTreeTaskDef.taskRole);
    sbomTreeQueue.grantConsumeMessages(sbomTreeTaskDef.taskRole);

    sbomTreeTaskDef.addContainer('sbom-tree', {
      image: ecs.ContainerImage.fromRegistry(
        `ghcr.io/${ghcrOwner}/omnibor-sbom-tree:dev`,
        { credentials: ghcrSecret },
      ),
      environment: {
        SQS_SBOM_TREE_URL: sbomTreeQueue.queueUrl,
        S3_BUCKET: bucket.bucketName,
        DYNAMO_GRAPH_TABLE: graphTable.tableName,
      },
      logging: ecs.LogDrivers.awsLogs({
        logGroup: new logs.LogGroup(this, 'SbomTreeLogs', {
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        streamPrefix: 'sbom-tree',
      }),
    });

    new ecs.FargateService(this, 'SbomTreeService', {
      cluster,
      taskDefinition: sbomTreeTaskDef,
      desiredCount: 1,
      assignPublicIp: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    // ================================================================
    // Outputs
    // ================================================================

    new cdk.CfnOutput(this, 'OperatorURL', {
      value: `http://${operatorService.loadBalancer.loadBalancerDnsName}`,
      description: 'Operator ALB DNS - use as OPERATOR_URL in CI workflows',
    });

    new cdk.CfnOutput(this, 'NatsEndpoint', {
      value: 'nats://nats.omnibor.local:4222',
      description: 'NATS endpoint (VPC-internal only)',
    });

    new cdk.CfnOutput(this, 'ArtifactBucketName', {
      value: bucket.bucketName,
      description: 'S3 bucket for SPDX artifacts',
    });

    new cdk.CfnOutput(this, 'Phase2QueueURL', {
      value: queue.queueUrl,
      description: 'SQS queue URL polled by the operator',
    });

    new cdk.CfnOutput(this, 'ClusterName', {
      value: cluster.clusterName,
      description: 'ECS cluster name for service updates',
    });

    new cdk.CfnOutput(this, 'GhcrOwner', {
      value: ghcrOwner,
      description: 'GHCR namespace used for container images',
    });
  }
}
