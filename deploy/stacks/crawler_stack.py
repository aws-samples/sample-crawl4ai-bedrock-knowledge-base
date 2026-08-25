"""CDK stack for the scheduled Crawl4AI Fargate task."""

from __future__ import annotations

import json
import os
from typing import Any

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CrawlerStack(Stack):
    """Run the crawler on a schedule and write prepared content to a Bedrock KB source."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        config = dict(config)
        prefix = str(config.get("s3Prefix", "web-content/"))
        config["s3Prefix"] = prefix if prefix.endswith("/") else f"{prefix}/"
        egress_mode = config.get("egressMode", "public")
        create_endpoints = config.get("privateEndpoints", False)
        imported_vpc = bool(config.get("vpcId"))

        # Customer-managed KMS key used to encrypt this stack's CloudWatch log
        # groups: the application logs and, for a stack-created VPC, the VPC flow
        # logs. Rotation is enabled to satisfy AWS Solutions (cdk-nag) checks.
        log_encryption_key = kms.Key(
            self,
            "LogEncryptionKey",
            description="CMK for the Crawl4AI crawler's CloudWatch log groups.",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # CloudWatch Logs encrypts and decrypts log data on the service's behalf,
        # so the key policy must grant the Region's Logs service principal. The
        # encryption-context condition scopes that grant to log groups in this
        # account and Region and uses a wildcard ARN to avoid a circular
        # dependency with the log groups that reference this key.
        log_encryption_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudWatchLogsEncryption",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
                actions=[
                    "kms:Encrypt*",
                    "kms:Decrypt*",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:Describe*",
                ],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": (
                            f"arn:{self.partition}:logs:{self.region}:"
                            f"{self.account}:log-group:*"
                        )
                    }
                },
            )
        )

        vpc = self._resolve_vpc(config.get("vpcId"), egress_mode, log_encryption_key)

        # Created before endpoints so endpoint ingress can name this SG as its only source.
        # allow_all_outbound is intentional: the task crawls configured public websites, which
        # resolve to arbitrary public addresses that cannot be enumerated ahead of time. There
        # are no inbound rules, so nothing can initiate a connection to the task.
        task_security_group = ec2.SecurityGroup(
            self,
            "CrawlerSg",
            vpc=vpc,
            description="No-ingress security group for the Crawl4AI Fargate task.",
            allow_all_outbound=True,
        )
        if create_endpoints:
            endpoint_security_group = ec2.SecurityGroup(
                self,
                "EndpointSg",
                vpc=vpc,
                description="HTTPS from the crawler task to private service endpoints only.",
                allow_all_outbound=False,
            )
            endpoint_security_group.add_ingress_rule(
                task_security_group,
                ec2.Port.tcp(443),
                "Allow HTTPS only from the crawler task security group",
            )
            self._add_vpc_endpoints(vpc, endpoint_security_group)

        cluster = ecs.Cluster(
            self,
            "CrawlerCluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )
        log_group = logs.LogGroup(
            self,
            "CrawlerLogs",
            encryption_key=log_encryption_key,
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        config_param = ssm.StringParameter(
            self,
            "PipelineConfig",
            string_value=self._build_pipeline_config_json(config),
            description="Crawl4AI to Bedrock KB pipeline configuration (JSON).",
        )

        architecture = config.get("cpuArchitecture", "ARM64")
        cpu_architecture = (
            ecs.CpuArchitecture.ARM64
            if architecture == "ARM64"
            else ecs.CpuArchitecture.X86_64
        )
        task_definition = ecs.FargateTaskDefinition(
            self,
            "CrawlerTask",
            cpu=int(config.get("taskCpu", 2048)),
            memory_limit_mib=int(config.get("taskMemory", 4096)),
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=cpu_architecture,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        image_platform = (
            ecr_assets.Platform.LINUX_ARM64
            if architecture == "ARM64"
            else ecr_assets.Platform.LINUX_AMD64
        )
        task_definition.add_container(
            "crawler",
            image=ecs.ContainerImage.from_asset(
                _REPO_ROOT,
                file="Dockerfile",
                platform=image_platform,
            ),
            logging=ecs.LogDriver.aws_logs(stream_prefix="crawler", log_group=log_group),
            environment={"CRAWL4AI_KB_CONFIG_SSM": config_param.parameter_name},
            user="10001",
        )
        self._grant_task_permissions(task_definition, config, config_param)

        subnet_selection = self._egress_subnets(vpc, imported_vpc, egress_mode)
        selected_subnets = vpc.select_subnets(
            subnet_type=subnet_selection.subnet_type
        ).subnet_ids
        assign_public_ip = subnet_selection.subnet_type == ec2.SubnetType.PUBLIC

        # Define the target role explicitly so no unnecessary ecs:TagResource wildcard
        # is generated for a target that does not apply tags.
        schedule_role = iam.Role(
            self,
            "ScheduleRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        schedule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[task_definition.task_definition_arn],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        pass_role_arns = [task_definition.task_role.role_arn]
        if task_definition.execution_role is not None:
            pass_role_arns.append(task_definition.execution_role.role_arn)
        schedule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=pass_role_arns,
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )
        events.CfnRule(
            self,
            "CrawlSchedule",
            schedule_expression=str(config.get("scheduleExpression", "rate(24 hours)")),
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    id="CrawlerTaskTarget",
                    arn=cluster.cluster_arn,
                    role_arn=schedule_role.role_arn,
                    ecs_parameters=events.CfnRule.EcsParametersProperty(
                        task_definition_arn=task_definition.task_definition_arn,
                        launch_type="FARGATE",
                        task_count=1,
                        network_configuration=events.CfnRule.NetworkConfigurationProperty(
                            aws_vpc_configuration=events.CfnRule.AwsVpcConfigurationProperty(
                                assign_public_ip="ENABLED" if assign_public_ip else "DISABLED",
                                security_groups=[task_security_group.security_group_id],
                                subnets=selected_subnets,
                            )
                        ),
                    ),
                )
            ],
        )

    def _resolve_vpc(
        self, vpc_id: str | None, egress_mode: str, log_encryption_key: kms.IKey
    ) -> ec2.IVpc:
        """Import a customer VPC or create the selected public/NAT topology."""
        if vpc_id:
            return ec2.Vpc.from_lookup(self, "ImportedVpc", vpc_id=vpc_id)

        if egress_mode == "nat":
            vpc = ec2.Vpc(
                self,
                "CrawlerVpc",
                max_azs=2,
                nat_gateways=1,
                subnet_configuration=[
                    ec2.SubnetConfiguration(
                        name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                    ),
                    ec2.SubnetConfiguration(
                        name="private",
                        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                        cidr_mask=24,
                    ),
                ],
            )
        else:
            vpc = ec2.Vpc(
                self,
                "CrawlerVpc",
                max_azs=2,
                nat_gateways=0,
                subnet_configuration=[
                    ec2.SubnetConfiguration(
                        name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                    )
                ],
            )
        # Send flow logs to a KMS-encrypted CloudWatch log group instead of the
        # default unencrypted, auto-created group.
        flow_log_group = logs.LogGroup(
            self,
            "FlowLogGroup",
            encryption_key=log_encryption_key,
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        vpc.add_flow_log(
            "FlowLog",
            destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_log_group),
        )
        return vpc

    def _add_vpc_endpoints(
        self, vpc: ec2.IVpc, endpoint_security_group: ec2.ISecurityGroup
    ) -> None:
        """Add one S3 gateway and five interface endpoints with one explicit SG."""
        vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        interface_services = {
            "EcrApiEndpoint": ec2.InterfaceVpcEndpointAwsService.ECR,
            "EcrDkrEndpoint": ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            "LogsEndpoint": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "SsmEndpoint": ec2.InterfaceVpcEndpointAwsService.SSM,
            "BedrockAgentEndpoint": ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT,
        }
        for endpoint_id, service in interface_services.items():
            vpc.add_interface_endpoint(
                endpoint_id,
                service=service,
                security_groups=[endpoint_security_group],
                open=False,
            )

    def _egress_subnets(
        self, vpc: ec2.IVpc, imported: bool, egress_mode: str
    ) -> ec2.SubnetSelection:
        """Choose customer-managed private subnets when available, otherwise configured ones."""
        if imported and vpc.private_subnets:
            return ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
        if not imported and egress_mode == "nat":
            return ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
        return ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)

    def _grant_task_permissions(
        self,
        task_definition: ecs.FargateTaskDefinition,
        config: dict[str, Any],
        config_param: ssm.StringParameter,
    ) -> None:
        """Grant only S3 writes, KB ingestion, and one SSM parameter read."""
        bucket = config["s3Bucket"]
        prefix = config["s3Prefix"]
        knowledge_base_id = config["knowledgeBaseId"]
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                sid="WritePreparedContentToDataSourceBucket",
                effect=iam.Effect.ALLOW,
                actions=["s3:PutObject"],
                resources=[f"arn:{self.partition}:s3:::{bucket}/{prefix}*"],
            )
        )
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                sid="TriggerAndMonitorKnowledgeBaseIngestion",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:StartIngestionJob", "bedrock:GetIngestionJob"],
                resources=[
                    f"arn:{self.partition}:bedrock:{self.region}:{self.account}:"
                    f"knowledge-base/{knowledge_base_id}"
                ],
            )
        )
        task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                sid="ReadPipelineConfig",
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter"],
                resources=[config_param.parameter_arn],
            )
        )

    def _build_pipeline_config_json(self, config: dict[str, Any]) -> str:
        """Serialize the validated runtime configuration stored in SSM."""
        pipeline_config = {
            "knowledge_base_id": config["knowledgeBaseId"],
            "data_source_id": config["dataSourceId"],
            "s3_bucket": config["s3Bucket"],
            "region": self.region,
            "s3_prefix": config["s3Prefix"],
            "seed_urls": config["seedUrls"],
            "metadata_attributes": config.get("metadataAttributes", {}),
            "crawl": {
                "css_selector": config.get("cssSelector"),
                "request_delay_seconds": config.get("crawlRequestDelaySeconds", 1.0),
                "max_depth": config.get("maxDepth", 2),
                "max_pages": config.get("maxPages", 1000),
                "scope": config.get("crawlScope", "path"),
                "include_patterns": config.get("includePatterns", []),
                "exclude_patterns": config.get("excludePatterns", []),
                "check_robots_txt": True,
            },
        }
        return json.dumps(pipeline_config, indent=2)
