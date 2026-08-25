"""Resource-scoped cdk-nag suppressions for the crawler stack."""

from __future__ import annotations

from aws_cdk import aws_ecs as ecs
from cdk_nag import NagSuppressions
from constructs import Construct


def apply_suppressions(stack: Construct) -> None:
    """Suppress only reviewed findings on the exact affected resources."""
    task_definition = stack.node.find_child("CrawlerTask")
    if not isinstance(task_definition, ecs.FargateTaskDefinition):
        raise TypeError("CrawlerTask must be an ECS FargateTaskDefinition")
    execution_role = task_definition.execution_role
    if execution_role is None:
        raise ValueError("CrawlerTask execution role was not created")

    NagSuppressions.add_resource_suppressions(
        execution_role,
        [
            {
                "id": "AwsSolutions-IAM4",
                "reason": (
                    "The ECS execution role uses the standard AWS-managed task "
                    "execution policy for ECR image pulls and CloudWatch Logs delivery."
                ),
            },
            {
                "id": "AwsSolutions-IAM5",
                "reason": (
                    "The ECS execution APIs require narrowly scoped log-stream "
                    "wildcards and ECR authorization requires resource '*'."
                ),
            },
        ],
        apply_to_children=True,
    )
    NagSuppressions.add_resource_suppressions(
        task_definition.task_role,
        [
            {
                "id": "AwsSolutions-IAM5",
                "reason": (
                    "S3 PutObject is restricted to the configured bucket and normalized "
                    "data-source prefix; only object keys beneath that prefix are wildcarded."
                ),
            }
        ],
        apply_to_children=True,
    )
    task_definition_resource = task_definition.node.default_child
    if not isinstance(task_definition_resource, ecs.CfnTaskDefinition):
        raise TypeError("CrawlerTask default child must be an ECS task definition resource")
    NagSuppressions.add_resource_suppressions(
        task_definition_resource,
        [
            {
                "id": "AwsSolutions-ECS2",
                "reason": (
                    "The environment contains only the name of a non-secret SSM parameter; "
                    "its configuration value is fetched at runtime."
                ),
            }
        ],
    )
