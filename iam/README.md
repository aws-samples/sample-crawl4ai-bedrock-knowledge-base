# IAM permissions for the pipeline

The principal running the local pipeline needs the following scoped permissions. The optional
Fargate deployment creates its own task role with these actions plus `ssm:GetParameter` on the
single stack-owned configuration parameter:

| Action | Why |
| --- | --- |
| `s3:PutObject` | Upload prepared Markdown and `.metadata.json` sidecars to the bucket wired to the knowledge base S3 data source. The pipeline only writes; it does not read or list S3. |
| `bedrock:StartIngestionJob` | Trigger ingestion after upload. |
| `bedrock:GetIngestionJob` | Poll ingestion job status until it completes. |

## Using the policy

`pipeline-policy.json` is a least-privilege policy template. Replace every `<REPLACE_WITH_...>`
placeholder with your values, then attach it:

```bash
# Replace placeholders (example using your own values), then:
aws iam put-role-policy \
  --role-name <your-pipeline-role> \
  --policy-name crawl4ai-bedrock-kb-pipeline \
  --policy-document file://iam/pipeline-policy.json
```

## Required bucket policy: deny non-HTTPS access

The pipeline calls Amazon S3 over HTTPS through boto3, but that only governs this client. Enforce
encryption in transit for every principal with a bucket policy that denies requests made without TLS:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnencryptedTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::<REPLACE_WITH_BUCKET_NAME>",
        "arn:aws:s3:::<REPLACE_WITH_BUCKET_NAME>/*"
      ],
      "Condition": { "Bool": { "aws:SecureTransport": "false" } }
    }
  ]
}
```

Apply it to the bucket configured as the knowledge base data source. Both the bucket ARN and the
object ARN are required, because the two cover bucket-level and object-level requests respectively.

## Scoping notes

- The S3 statement is scoped to the single data source bucket and the configured key prefix.
  Narrow the prefix (`<REPLACE_WITH_PREFIX>`) to exactly the path this pipeline writes to.
- The Bedrock statement is scoped to a single knowledge base ARN. It does **not** grant
  `bedrock:Retrieve` — querying the knowledge base is a separate concern handled by your
  application's role.
- This policy grants no `bedrock:InvokeModel`; embedding and generation are performed by the
  knowledge base service role, not by the pipeline.
- This policy grants no AWS KMS actions. If the bucket uses SSE-KMS with a customer managed key,
  also allow `kms:GenerateDataKey` on that key in both the principal's IAM policy and the key
  policy. Multipart uploads also need `kms:Decrypt`; boto3 uses multipart upload for files of
  8 MB or larger by default. The Fargate task role that the CDK stack creates has no AWS KMS
  permissions either. See
  [Using server-side encryption with AWS KMS keys (SSE-KMS)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html).
