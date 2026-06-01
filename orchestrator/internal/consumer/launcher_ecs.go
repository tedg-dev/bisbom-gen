package consumer

import (
	"context"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	ecstypes "github.com/aws/aws-sdk-go-v2/service/ecs/types"

	"github.com/tedg-dev/omnibor-analysis/orchestrator/internal/config"
)

// ECSLauncher runs Phase 2 by calling the ECS RunTask API.
//
// How it works:
//  1. The orchestrator does NOT download artifacts to local disk.
//     Instead, it passes S3 paths as environment variable overrides
//     to the ECS task.
//  2. ECS launches a new Fargate (or EC2) task using the pre-registered
//     task definition (e.g., "omnibor-phase2").
//  3. The Phase 2 container starts, downloads artifacts from S3 itself,
//     runs SPDX generation, and uploads results back to S3.
//  4. The orchestrator optionally waits for the task to complete before
//     acknowledging the SQS message.
//
// Key differences from DockerLauncher:
//   - No local disk needed — S3 is the only shared state
//   - No Docker socket needed — uses AWS API
//   - Each Phase 2 job gets its own isolated compute (CPU, memory)
//   - AWS handles scheduling, networking, and container lifecycle
//   - Task logs go to CloudWatch (configured in the task definition)
//
// Requirements:
//   - ECS cluster with Fargate or EC2 capacity
//   - Task definition registered (image, CPU, memory, log config)
//   - IAM role on the orchestrator's task with ecs:RunTask, ecs:DescribeTasks,
//     and iam:PassRole permissions
//   - Phase 2 task role with S3 read/write permissions
//   - VPC subnets and security group for awsvpc networking
//
// Best for: production ECS/Fargate deployments.
type ECSLauncher struct {
	cfg       *config.Config
	ecsClient *ecs.Client
}

// NewECSLauncher creates an ECSLauncher with an ECS client.
func NewECSLauncher(cfg *config.Config, awsCfg aws.Config) *ECSLauncher {
	return &ECSLauncher{
		cfg:       cfg,
		ecsClient: ecs.NewFromConfig(awsCfg),
	}
}

// Launch starts a Phase 2 ECS task and waits for it to complete.
func (e *ECSLauncher) Launch(ctx context.Context, job *Phase2Job) error {
	s3Input := fmt.Sprintf("s3://%s/%s/phase1/", job.S3Bucket, job.JobPrefix)
	s3Output := fmt.Sprintf("s3://%s/%s/spdx/", job.S3Bucket, job.JobPrefix)

	subnets := strings.Split(e.cfg.ECSSubnets, ",")

	log.Printf("[INFO] Launching ECS task: cluster=%s task-def=%s",
		e.cfg.ECSCluster, e.cfg.ECSTaskDefinition)
	log.Printf("[INFO]   S3 input:  %s", s3Input)
	log.Printf("[INFO]   S3 output: %s", s3Output)

	// RunTask launches a new task instance from the registered task definition.
	// The containerOverrides pass S3 paths so the Phase 2 container knows
	// where to download artifacts from and where to upload SPDX results.
	runOut, err := e.ecsClient.RunTask(ctx, &ecs.RunTaskInput{
		Cluster:        &e.cfg.ECSCluster,
		TaskDefinition: &e.cfg.ECSTaskDefinition,
		LaunchType:     ecstypes.LaunchTypeFargate,
		Count:          aws.Int32(1),

		// awsvpc networking — required for Fargate.
		// Each task gets its own ENI in the specified subnets.
		NetworkConfiguration: &ecstypes.NetworkConfiguration{
			AwsvpcConfiguration: &ecstypes.AwsVpcConfiguration{
				Subnets:        subnets,
				SecurityGroups: []string{e.cfg.ECSSecurityGroup},
				AssignPublicIp: ecstypes.AssignPublicIpEnabled,
			},
		},

		// Override the container's environment variables at launch time.
		// The task definition defines the base image and resource limits;
		// these overrides customize each run with the specific S3 paths.
		Overrides: &ecstypes.TaskOverride{
			ContainerOverrides: []ecstypes.ContainerOverride{
				{
					Name: aws.String("sidecar"),
					Environment: []ecstypes.KeyValuePair{
						{Name: aws.String("S3_INPUT_PATH"), Value: &s3Input},
						{Name: aws.String("S3_OUTPUT_PATH"), Value: &s3Output},
						{Name: aws.String("REPO_NAME"), Value: &job.RepoName},
						{Name: aws.String("S3_BUCKET"), Value: &job.S3Bucket},
						{Name: aws.String("OMNIBOR_MODE"), Value: aws.String("sidecar")},
					},
				},
			},
		},
	})
	if err != nil {
		return fmt.Errorf("ecs RunTask: %w", err)
	}

	if len(runOut.Tasks) == 0 {
		if len(runOut.Failures) > 0 {
			f := runOut.Failures[0]
			return fmt.Errorf("ecs RunTask failed: %s — %s",
				aws.ToString(f.Reason), aws.ToString(f.Detail))
		}
		return fmt.Errorf("ecs RunTask returned no tasks and no failures")
	}

	taskARN := aws.ToString(runOut.Tasks[0].TaskArn)
	log.Printf("[INFO] ECS task started: %s", taskARN)

	// Wait for the task to complete. ECS tasks transition through:
	// PROVISIONING → PENDING → RUNNING → DEPROVISIONING → STOPPED
	return e.waitForTask(ctx, taskARN)
}

// waitForTask polls ECS DescribeTasks until the task reaches STOPPED state.
func (e *ECSLauncher) waitForTask(ctx context.Context, taskARN string) error {
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}

		out, err := e.ecsClient.DescribeTasks(ctx, &ecs.DescribeTasksInput{
			Cluster: &e.cfg.ECSCluster,
			Tasks:   []string{taskARN},
		})
		if err != nil {
			log.Printf("[WARN] DescribeTasks: %v", err)
			continue
		}

		if len(out.Tasks) == 0 {
			return fmt.Errorf("task %s not found", taskARN)
		}

		task := out.Tasks[0]
		status := aws.ToString(task.LastStatus)
		log.Printf("[INFO] Task %s status: %s", taskARN, status)

		if status == "STOPPED" {
			// Check exit code of the sidecar container
			for _, container := range task.Containers {
				if aws.ToString(container.Name) == "sidecar" {
					if container.ExitCode != nil && *container.ExitCode != 0 {
						return fmt.Errorf("sidecar exited with code %d: %s",
							*container.ExitCode, aws.ToString(container.Reason))
					}
				}
			}

			stopReason := aws.ToString(task.StoppedReason)
			if stopReason != "" {
				log.Printf("[INFO] Task stopped reason: %s", stopReason)
			}
			return nil
		}
	}
}
