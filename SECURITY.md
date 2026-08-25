# Security

## Reporting a vulnerability

Do not report security vulnerabilities through a public GitHub issue.

Report potential vulnerabilities to AWS through the [AWS vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/). Include the repository name, affected component, reproduction steps, and potential impact.

## Shared responsibility

This sample is provided for educational purposes. Before using it with production or sensitive data, review the [AWS Shared Responsibility Model](https://aws.amazon.com/compliance/shared-responsibility-model/) and apply controls appropriate for your workload.

You are responsible for:

- Confirming that you are authorized to crawl each configured website.
- Reviewing crawled content before ingestion and preventing sensitive data from entering the knowledge base.
- Restricting IAM access to the configured Amazon S3 prefix, SSM parameter, and knowledge base.
- Securing network egress, logs, Amazon S3 encryption, and any customer-managed AWS KMS keys.
- Treating metadata filters as retrieval controls, not as an authorization boundary.
- Keeping credentials, session cookies, and other secrets out of CDK context, the plaintext SSM configuration parameter, source files, and container images.

The companion pipeline does not implement authenticated crawling. If you extend it to do so, store credentials in AWS Secrets Manager and perform a separate security review.

## Accepted risks

The following design choices are intentional for this sample. They are documented here so reviewers and operators can make an informed decision before using it with production data.

### Public task IP and unrestricted egress (default `egressMode=public`)

A web crawler must reach arbitrary public websites whose IP addresses cannot be enumerated in advance, so the Fargate task's security group allows all outbound traffic. In the default `egressMode=public` topology the task also runs in a public subnet and receives a public IP for internet egress.

This is scoped by the following controls:

- The task security group has **no inbound rules**, so nothing on the internet can initiate a connection to the task.
- Egress is only exercised by the crawler reaching the websites you configure.
- Operators who require stricter egress can deploy with `egressMode=nat` (private subnets behind a NAT gateway, no public IP) and optionally `privateEndpoints=true` to reach AWS services over interface endpoints. NAT is still required for reaching public websites.

### Plaintext AWS Systems Manager (SSM) configuration parameter

The stack stores the pipeline configuration in a plaintext SSM `StringParameter`, not a `SecureString`. The parameter holds only **non-secret** operational configuration: knowledge base and data source IDs, the target bucket and prefix, seed URLs, and crawl tuning values.

- No passwords, session cookies, API tokens, or other secrets are stored in this parameter or in CDK context. The task authenticates to AWS with its IAM task role and does not perform authenticated crawling.
- Read access is restricted to the task role with exactly `ssm:GetParameter` on that one parameter.
- If you extend the pipeline so that its configuration must carry a secret, switch to a `SecureString` parameter or AWS Secrets Manager and grant the corresponding decrypt permission, then perform a separate security review.
