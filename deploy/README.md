# Deploy: run the crawler on AWS Fargate (optional)

The repository root demonstrates the method from a machine with Python and AWS credentials. This optional AWS CDK app runs the same pipeline on a schedule so it does not depend on a workstation.

It provisions:

- An Amazon ECS task on AWS Fargate and an Amazon EventBridge schedule.
- A task role limited to `s3:PutObject` on one prefix, `bedrock:StartIngestionJob` and `bedrock:GetIngestionJob` on one knowledge base, and `ssm:GetParameter` on one parameter.
- A plaintext AWS Systems Manager Parameter Store parameter containing non-secret pipeline configuration.
- A no-ingress task security group, 30-day application logs, and Container Insights.
- A VPC with flow logs when `vpcId` is not supplied.

```text
EventBridge schedule -> Fargate task -> S3 (.md + .md.metadata.json)
                                      -> Amazon Bedrock Knowledge Bases ingestion
```

## Why Fargate

Fargate is a good fit for scheduled browser jobs that may need more runtime or sustained resources than a short function invocation. It has no instances to manage and incurs task compute charges only while tasks run. This sample defaults to ARM64.

AWS Lambda container images can include headless Chromium, but Lambda has a 15-minute invocation limit. Lambda can still be appropriate for bounded crawls that fit that limit. Long-running or continuous crawls may be better suited to Fargate or Amazon EC2.

## Prerequisites

- Node.js and the AWS CDK Toolkit CLI. The CDK CLI is versioned separately from `aws-cdk-lib`
  (the CLI is on the `2.1xxx.x` line), so it does not share the library's version number. It must be
  new enough to read the cloud assembly this app synthesizes: `aws-cdk-lib==2.262.0` (see
  [`requirements.txt`](requirements.txt)) requires CDK CLI `>= 2.1138.0`, and an older CLI fails with
  a cloud assembly schema version mismatch. Check with `cdk --version` and install a compatible,
  pinned version, for example `npm install -g aws-cdk@2.1138.0`. Bump this pin when you upgrade
  `aws-cdk-lib`.
- Python 3.10 or later.
- A Docker-compatible container engine that is **running**, because CDK builds the crawler image
  locally. Verify with `docker info`.
- AWS credentials for the target account and Region.
- A bootstrapped CDK environment.
- An Amazon Bedrock knowledge base (managed or customer-managed) and an Amazon S3 data source that
  meet the [prerequisites in the main README](../README.md#prerequisites). In this app, the
  `s3Bucket` and `s3Prefix` context keys set the bucket and prefix.

Two notes for non-default environments:

- **Container architecture.** This sample defaults to `cpuArchitecture=ARM64`. Building that image
  on an x86_64 host requires QEMU emulation through Docker buildx. If the build fails on a platform
  error, either configure buildx or deploy with `-c cpuArchitecture=X86_64`.
- **Alternative runtimes.** CDK invokes the `docker` binary by default. For Podman or Finch, set
  `CDK_DOCKER=podman` (or `finch`). Give the container VM at least 4 GB of memory, because the image
  installs Playwright and Chromium and can run out of memory on smaller defaults.

## Deploy

```bash
cd deploy
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cdk bootstrap aws://ACCOUNT_ID/REGION

cdk deploy \
  -c knowledgeBaseId=ABCDEFGHIJ \
  -c dataSourceId=KLMNOPQRST \
  -c s3Bucket=amzn-s3-demo-bucket \
  -c 'seedUrls=["https://www.example.com/services"]' \
  -c maxDepth=1 \
  -c maxPages=25 \
  -c crawlScope=path \
  -c scheduleExpression="rate(24 hours)"
```

Replace `ACCOUNT_ID`, `REGION`, and the deployment example values before running the commands. Specifying the bootstrap environment explicitly avoids synthesizing the app while `cdk.json` still contains required placeholders.

The stack name is fixed as `Crawl4aiBedrockKbCrawler`, so another `cdk deploy` in the same account and Region updates that stack, even with different context values.

Keep the virtual environment active for every `cdk` command in the terminal. The CDK CLI runs
`python app.py`, so an inactive environment surfaces as `ModuleNotFoundError: No module named 'aws_cdk'`.

## Troubleshooting deployment

| Symptom | Fix |
| --- | --- |
| `Cloud assembly schema version mismatch` | The CDK CLI is older than the schema this app synthesizes. Install a compatible, pinned CLI, e.g. `npm install -g aws-cdk@2.1138.0` (the CLI is versioned separately from `aws-cdk-lib`, on the `2.1xxx.x` line). |
| `Cannot connect to the Docker daemon` | Start your container engine, then confirm with `docker info`. |
| `ModuleNotFoundError: No module named 'aws_cdk'` | Activate the virtual environment in the same terminal, then rerun the command. |
| Image build fails with `exec format error` or another platform or QEMU error | Configure Docker buildx for cross-architecture builds, or deploy with `-c cpuArchitecture=X86_64`. |
| Image build is killed or runs out of memory | Allocate at least 4 GB of memory to the container VM. |
| CDK cannot find `docker` when using Podman or Finch | Set `CDK_DOCKER=podman` or `CDK_DOCKER=finch`. |
| `DEPRECATED: The legacy builder is deprecated` | Informational only. If the build still fails, check that the daemon is running. |
| Missing required context key errors | Pass `knowledgeBaseId`, `dataSourceId`, `s3Bucket`, and `seedUrls` with `-c`, or set them in `cdk.json`. |

## Configuration

| Context key | Required | Default | Description |
| --- | --- | --- | --- |
| `knowledgeBaseId` | yes | — | Target knowledge base ID. |
| `dataSourceId` | yes | — | Amazon S3 data source ID. |
| `s3Bucket` | yes | — | Bucket configured as that data source. |
| `seedUrls` | yes | — | JSON list of HTTP(S) starting points for breadth-first traversal. |
| `s3Prefix` | no | `web-content/` | Upload prefix; the stack normalizes a trailing slash. |
| `scheduleExpression` | no | `rate(24 hours)` | EventBridge `rate(...)` or `cron(...)` expression. |
| `taskCpu` | no | `2048` | Fargate CPU units. |
| `taskMemory` | no | `4096` | Fargate memory in MiB. |
| `cpuArchitecture` | no | `ARM64` | Exactly `ARM64` or `X86_64`. |
| `vpcId` | no | new VPC | Existing VPC to import without modification. |
| `egressMode` | no | `public` | For a new VPC: `public` or `nat`. |
| `privateEndpoints` | no | `false` | For a new NAT VPC only, add one S3 gateway and five interface endpoints. |
| `metadataAttributes` | no | `{"content_category": "web"}` | Static metadata added to each document. Do not use it as authorization. |
| `cssSelector` | no | `null` | Optional selector applied to every page, such as `main, article`. |
| `crawlRequestDelaySeconds` | no | `1.0` | Nonnegative request pacing delay; seeds are also separated by this delay. |
| `maxDepth` | no | `2` | Link levels followed from each seed; `0` processes only seeds. |
| `maxPages` | no | `1000` | Global page-attempt cap across all seeds in one task run. |
| `crawlScope` | no | `path` | `page`, `path`, or `host`; every mode stays on the seed origin, and path matching observes segment boundaries. |
| `includePatterns` | no | `[]` | JSON list of Crawl4AI URL globs or regexes allowed during discovery. |
| `excludePatterns` | no | `[]` | JSON list of Crawl4AI URL globs or regexes rejected during discovery. |

The stack strictly validates required identifiers, seed URLs, architecture, egress mode, endpoint combinations, and deep-crawl controls. Other AWS constraints, such as supported Fargate CPU/memory pairs and schedule syntax, are validated during CDK synthesis or deployment. `privateEndpoints=true` cannot be combined with `vpcId` because this stack never changes an imported VPC.

## Monitoring and production considerations

- **Task failures.** The container exit code and the `crawler` CloudWatch log stream report each run.
  To be notified without checking manually, alarm on ECS task state change events for this cluster in
  Amazon EventBridge, or on a metric filter over the log group.
- **GuardDuty Runtime Monitoring.** If GuardDuty manages its security agent for Fargate in your
  account, it adds a sidecar container to each task. The execution role that CDK generates pulls
  images only from the CDK bootstrap repository, so the sidecar fails with
  `CannotPullContainerError`. Runtime Monitoring doesn't prevent the task from running, so the
  crawler still runs. To monitor these tasks, grant the execution role the Amazon ECR permissions
  in [Prerequisites for container image access](https://docs.aws.amazon.com/guardduty/latest/ug/prereq-runtime-monitoring-ecs-support.html).
- **Retries.** The pipeline uses the boto3 default retry behavior. Production workloads that see
  throttling can raise it, for example `Config(retries={"max_attempts": 5, "mode": "standard"})`.
- **Cost.** Charges accrue for Fargate task time while a run is active, CloudWatch Logs storage, and
  any NAT gateway or interface endpoints you enable. A short daily ARM64 task is inexpensive, but
  confirm against [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/) for your Region and
  task size.

## Networking and cost

The task crawls public websites, so it needs real internet egress. Interface VPC endpoints reach AWS services only; they do not replace an internet gateway or NAT gateway for external websites.

Choose one topology:

- **`egressMode=public` (default):** creates public subnets with an internet gateway and no NAT gateway. The task receives a public IP. Its security group has no inbound rules. This is the lowest-cost sample mode but requires the account to permit public task egress.
- **`egressMode=nat`:** creates public and private-with-egress subnets with one NAT gateway. The task uses private subnets without a public IP. One NAT gateway is a cost-conscious sample default, not a multi-AZ egress design; production workloads that require Availability Zone resilience should evaluate one NAT gateway per AZ or another resilient egress architecture.
- **`egressMode=nat -c privateEndpoints=true`:** additionally creates an S3 gateway endpoint and interface endpoints for `ecr.api`, `ecr.dkr`, CloudWatch Logs, SSM, and `bedrock-agent`. One endpoint security group permits TCP 443 only from the crawler task security group. NAT remains necessary for public websites. Interface endpoints have hourly and data-processing charges.
- **`vpcId=vpc-xxxx`:** imports a VPC without modifying routes, endpoints, flow logs, or security controls. The task prefers private-with-egress subnets and otherwise uses public subnets. You are responsible for internet egress and connectivity to ECR, CloudWatch Logs, SSM, Amazon S3, and the Agents for Amazon Bedrock build-time API. If the VPC has interface endpoints with private DNS for any of these services, the task's requests go to those endpoints, so their security groups must allow inbound TCP 443 from the crawler task security group. Endpoints that use the VPC's default security group don't allow this by default. Verify VPC flow logs and retention separately if your controls require them.

A task that cannot reach ECR may fail while pulling its image; one that cannot reach CloudWatch Logs may fail before the application starts. Inspect stopped-task details, the `crawler` CloudWatch log stream, and the EventBridge rule target rather than relying on a single fixed error string.

A newly created VPC counts against the regional VPC quota. If the account has reached its quota, use an appropriate existing VPC or request a quota increase.

## Security notes

- The container runs as UID 10001, and the task definition also sets that user.
- The task security group has no inbound rules. Unrestricted outbound access is intentional because configured websites can resolve to arbitrary public addresses.
- Only the SSM parameter name appears in the task definition. The task reads the parameter value at runtime with exactly `ssm:GetParameter`.
- The SSM parameter is a plaintext `StringParameter`. Do not store passwords, cookies, tokens, or other secrets in CDK context or this parameter. This sample does not implement authenticated crawling.
- The stack creates flow logs only for a VPC it owns. It does not alter an imported VPC.
- `cdk-nag` AWS Solutions checks run during synthesis. Suppressions are resource-scoped in `cdk_nag_suppressions.py`.

## Trigger a run on demand

The task runs on the configured schedule. To run it immediately, use the Amazon ECS console and select the generated cluster, task definition, subnets, and crawler security group. You can also copy the EventBridge target network configuration into `aws ecs run-task`.

Monitor both the `crawler` container exit code and its CloudWatch log stream. A successful task reports `job_status: COMPLETE`. `FAILED`, `STOPPED`, and `TIMED_OUT` return a nonzero container exit code.

## Repeated runs

The full pipeline uploads only files generated by the current task. It does not delete objects written by earlier configurations. If you remove or change a URL, delete the obsolete object and matching `.md.metadata.json` sidecar from the configured prefix, then start another ingestion job.

## Clean up

```bash
cd deploy
cdk destroy
```

This removes stack-owned schedules, IAM roles, task definitions, the cluster, SSM parameter, log groups, security groups, and the VPC when the stack created it, and schedules the stack's AWS KMS key for deletion. An imported VPC is not modified or deleted. The command does not delete the knowledge base, source bucket, ingested objects, or container assets retained in the CDK bootstrap repository. It also leaves the Container Insights log group whose name starts with `/aws/ecs/containerinsights/Crawl4aiBedrockKbCrawler-`, which Container Insights creates outside the stack.