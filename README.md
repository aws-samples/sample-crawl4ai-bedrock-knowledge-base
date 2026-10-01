# Prepare web content for Amazon Bedrock Knowledge Bases with Crawl4AI

> **Important:** This sample demonstrates one approach for preparing web content and ingesting
> it into an Amazon Bedrock Knowledge Base. Security is a shared responsibility between AWS and
> the customer. Customer responsibilities include conducting independent security assessments,
> implementing controls appropriate for their use case and data classification, and maintaining
> compliance with organizational requirements. See the
> [AWS Shared Responsibility Model](https://aws.amazon.com/compliance/shared-responsibility-model/).

This repository is the companion code for the AWS blog post *"Prepare web content for Amazon Bedrock
Knowledge Bases with Crawl4AI."* It contains a small, config-driven Python pipeline that:

1. **Prepares** each configured URL with [Crawl4AI](https://github.com/unclecode/crawl4ai)
   (headless browser and JavaScript rendering), preferring fit Markdown produced by a pruning
   filter and optionally selecting a page region with CSS.
2. **Enriches** each document with an Amazon Bedrock-compatible `.metadata.json` sidecar.
3. **Uploads** the Markdown and sidecars to the Amazon S3 bucket wired to your knowledge base.
4. **Ingests** the content by starting (and optionally waiting on) a Bedrock Knowledge Base
   ingestion job.

Amazon Bedrock Knowledge Bases does the heavy lifting downstream — chunking, embedding, vector
indexing, metadata filtering, and retrieval. This pipeline only prepares input.

> This is **batch ingestion of known web properties**, not real-time web access at inference time.

## When to use this sample

For most public websites, start with the [Amazon Bedrock Web Crawler data source
connector](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-webcrawler.html) in an
[Amazon Bedrock Managed Knowledge Base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-build-managed.html)
(referred to here as the **Bedrock Web Crawler**). It requires no crawler infrastructure and
provides seed URL and sitemap crawling, crawl scope and URL filters, rate limiting, robots.txt
compliance, sign-in options, and incremental sync.

Use this content-preparation sample when you need more control over what reaches the knowledge
base: a CSS selector for targeted extraction, boilerplate removal, or custom metadata on each
document before Amazon Bedrock Knowledge Bases ingests it through Amazon S3. Each `seed_urls` entry starts a breadth-first traversal. Depth, a
global per-run page cap, same-origin page/path/host scope, and include/exclude patterns keep discovery
bounded while allowing large sites to contribute thousands of relevant pages. The sample does not
implement authenticated sessions. For sites that require sign-in, evaluate the managed
[Bedrock Web Crawler authentication options](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-webcrawler.html)
first, which include basic, form-based, and SAML authentication. If you extend this sample with
authentication, store credentials in AWS Secrets Manager and perform a separate security review.

The sample works with a managed knowledge base or a customer-managed knowledge base, as long as the
knowledge base uses an Amazon S3 data source. Both types use the same ingestion calls
(`StartIngestionJob` and `GetIngestionJob`) and accept the same sidecar format.

## Architecture

![Architecture diagram showing an Amazon EventBridge schedule starting an AWS Fargate task that crawls
public websites through an internet gateway, writes prepared Markdown and metadata to Amazon S3, and
starts Amazon Bedrock Knowledge Bases ingestion into a vector store for retrieval by a generative AI
application.](docs/architecture.png)

The numbered steps in the diagram map to the following workflow:

1. Amazon EventBridge starts the Amazon ECS task on AWS Fargate on the configured schedule.
2. The task crawls the public websites you configured and prepares Markdown with a metadata sidecar
   for each page.
3. The task uploads the prepared files to the Amazon S3 bucket that backs the knowledge base data
   source.
4. The task starts an Amazon Bedrock Knowledge Bases ingestion job.
5. Amazon Bedrock Knowledge Bases reads the new and changed objects, parses them, and applies your
   configured chunking strategy.
6. It creates embeddings and indexes them in the knowledge base's vector store, which Amazon Bedrock
   manages for a managed knowledge base.
7. Your generative AI application calls `Retrieve` to get relevant chunks. To get a generated
   response with citations, it calls `AgenticRetrieveStream` for a managed knowledge base or
   `RetrieveAndGenerate` for a customer-managed knowledge base.

The task reads its non-secret pipeline configuration from AWS Systems Manager Parameter Store at
startup. The diagram shows the scheduled deployment in [`deploy/`](deploy/). The Quick Start below runs
the same steps 2 through 4 from your own machine, without EventBridge, Fargate, or a VPC.

| Component | Service | Role |
| --- | --- | --- |
| Content preparation | Crawl4AI (any Python runtime) | Render and extract clean Markdown + metadata |
| Staging | Amazon S3 | Data source bucket for the knowledge base |
| Ingestion & retrieval | Amazon Bedrock Knowledge Bases | Chunk, embed, index, and serve grounded answers |

## Prerequisites

- One of the following Amazon Bedrock knowledge bases:
  - **A managed knowledge base** (recommended) in a Region where
    [managed knowledge bases are available](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-regions.html).
    See [Create a managed knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html)
    and the [Amazon S3 connector](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-s3.html).
    On the data source, leave **Metadata files prefix** empty, because the pipeline writes each
    metadata sidecar alongside its document.
  - **An existing customer-managed knowledge base.** To add an Amazon S3 data source, see
    [Connect to Amazon S3 for your knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html).
    The pipeline writes a metadata sidecar for every document, so confirm that your vector store
    can store and filter those attributes, as described in
    [Metadata and filtering](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-config.html).
    For example, an Amazon OpenSearch Serverless vector index must use the `faiss` engine. An
    Amazon Aurora vector index needs a custom metadata column or a column for each metadata
    attribute.
- An Amazon S3 data source in that knowledge base whose status is `AVAILABLE`. It can be a new
  data source or one you already use. It must use the bucket set in `s3_bucket`. If the data
  source filters content by prefix or file pattern, the filters must allow the files that the
  pipeline writes under `s3_prefix` (default `web-content/`).
- Python 3.10 or later.
- AWS credentials configured (for example via `aws configure`) with the permissions in
  [`iam/pipeline-policy.json`](iam/pipeline-policy.json).
- Authorization to crawl the target websites, consistent with the
  [Amazon Acceptable Use Policy](https://aws.amazon.com/aup/).

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/aws-samples/sample-crawl4ai-bedrock-knowledge-base.git
cd sample-crawl4ai-bedrock-knowledge-base
pip install -r requirements.txt
crawl4ai-setup            # downloads the Playwright browser binaries

# 2. Configure (copy the example and fill in your values)
cp config/pipeline.example.yaml config/pipeline.yaml
#   edit config/pipeline.yaml: knowledge_base_id, data_source_id, s3_bucket, region, seed_urls

# 3. Run the full pipeline (crawl -> upload -> ingest, waits for completion)
python scripts/run_pipeline.py --config config/pipeline.yaml
```

Preview a crawl without touching AWS:

```bash
python scripts/run_pipeline.py --config config/pipeline.yaml --dry-run
```

## Running stages individually

```bash
python scripts/crawl.py   --config config/pipeline.yaml   # crawl -> local Markdown + sidecars
python scripts/upload.py  --config config/pipeline.yaml   # upload prepared files to S3
python scripts/ingest.py  --config config/pipeline.yaml   # start + poll the ingestion job
```

Add `--no-wait` to `ingest.py` or `run_pipeline.py` to start ingestion without polling, and
`--verbose` to any script for DEBUG logs.

## Running the tests

The tests use the standard library `unittest` module, so no extra test dependencies are needed. Run
them from the repository root:

```bash
python -m unittest discover -v
```

To run a single module, for example the upload tests:

```bash
python -m unittest tests.test_upload -v
```

The suite is offline: AWS clients are injected or patched, so no credentials or network access are
required and no AWS charges are incurred.

## Project structure

```
config/    Pipeline configuration (copy pipeline.example.yaml -> pipeline.yaml)
src/       crawl4ai_bedrock_kb package: config, crawl, upload, ingest, pipeline
scripts/   CLI entrypoints (run_pipeline, crawl, upload, ingest, container_entrypoint)
iam/       Least-privilege IAM policy template and guidance
deploy/    Optional: run the pipeline on AWS Fargate on a schedule (CDK)
docs/      Architecture diagram used in the README
tests/     Offline unit tests (standard library unittest)
Dockerfile Container image used by the optional AWS Fargate deployment
```

## Running it on AWS (optional)

The Quick Start above runs the method from any machine with Python and credentials. To run it
**in AWS on a schedule** instead — so nothing depends on a workstation — use the CDK app in
[`deploy/`](deploy/). It provisions an EventBridge-scheduled **AWS Fargate** task (ARM64) that
runs this same pipeline in a container, with a least-privilege task role. See
[`deploy/README.md`](deploy/README.md) for details.

## Configuration reference

All values live in `config/pipeline.yaml`. Nothing customer-specific is hardcoded in source.

| Key | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `knowledge_base_id` | string | yes | — | Target Bedrock Knowledge Base ID. |
| `data_source_id` | string | yes | — | S3 data source ID within the knowledge base. |
| `s3_bucket` | string | yes | — | Bucket configured as the knowledge base S3 data source. |
| `region` | string | yes | — | AWS Region of the knowledge base and bucket. |
| `seed_urls` | list | yes | — | Starting URLs for breadth-first traversal (must be HTTP(S)). |
| `s3_prefix` | string | no | `web-content/` | Key prefix for uploaded files. |
| `metadata_attributes` | map | no | `{}` | Static string, finite number, boolean, or string-list metadata used for retrieval filtering. |
| `crawl.max_depth` | int | no | `2` | Link levels followed from each seed; `0` processes only seeds. |
| `crawl.max_pages` | int | no | `1000` | Global page-attempt cap across all seeds in one run. |
| `crawl.scope` | string | no | `path` | `page`, `path`, or `host`; every mode stays on the seed origin, and path matching observes segment boundaries. |
| `crawl.include_patterns` | list | no | `[]` | Optional Crawl4AI URL globs or regexes allowed during discovery. |
| `crawl.exclude_patterns` | list | no | `[]` | Optional Crawl4AI URL globs or regexes rejected during discovery. |
| `crawl.css_selector` | string/null | no | `null` | Optional CSS selector applied to every page, such as `main, article`. |
| `crawl.request_delay_seconds` | float | no | `1.0` | Request pacing delay; configured seeds are also separated by this delay. |
| `crawl.delay_before_return_html` | float | no | `2.0` | Seconds to let client-side JS render. |
| `crawl.check_robots_txt` | bool | no | `true` | Skip URLs disallowed by `robots.txt`. |
| `crawl.page_timeout_ms` | int | no | `60000` | Per-page navigation timeout (ms). |
| `crawl.word_count_threshold` | int | no | `50` | Minimum words retained in candidate content blocks. |

Top-level keys can be overridden with YAML-encoded environment variables named
`CRAWL4AI_KB_<KEY>`. For example, use `CRAWL4AI_KB_REGION=us-east-1` or
`CRAWL4AI_KB_SEED_URLS='["https://www.example.com/services"]'`. Nested `crawl` settings
are configured in the YAML file.

## How metadata reaches retrieval

Each Markdown file `page.md` gets a sidecar named `page.md.metadata.json` (the full source
filename with `.metadata.json` appended — the naming Amazon Bedrock requires), stored next to the
document. The sidecar holds `source_url`, `title`, ISO and epoch crawl timestamps, `content_type`,
plus supported custom attributes. Each value uses the typed attribute format, for example
`{"value": {"type": "STRING", "stringValue": "web"}}`, which both managed and customer-managed
knowledge bases accept for Amazon S3 data sources.

After ingestion, you can filter retrieval results on these attributes. For a managed knowledge base,
put the filter in `managedSearchConfiguration`, use `equals`, `greaterThan`, `lessThan`, `in`, or
`notIn` (`startsWith` and `stringContains` aren't supported), and pass number values as integers,
because decimal values are rejected. For a customer-managed knowledge base, put it in
`vectorSearchConfiguration`; supported operators depend on the vector store. Retrieved results,
including those cited in generated responses, carry `source_url` in their metadata; your
application can render it as the user-facing source link. Metadata filters improve retrieval
precision but are not an authorization boundary.

## Security

- IAM is least-privilege: S3 access is scoped to the data source bucket/prefix, and Bedrock
  access is scoped to one knowledge base ARN (see [`iam/`](iam/)). No `InvokeModel` or `Retrieve`
  is granted to the pipeline.
- `config/pipeline.yaml`, `prepared_content/`, and `deploy/cdk.context.json` are git-ignored.
  Verify they are untracked before publishing or sharing a checkout.
- Enable `crawl.check_robots_txt: true` and confirm you are authorized to crawl each target site.
- Amazon S3 encrypts new objects with SSE-S3 by default. If the bucket uses an AWS KMS customer
  managed key, grant the uploader and the knowledge base service role the required AWS KMS
  permissions in both IAM and the key policy.
- Do not place credentials, cookies, or other secrets in CDK context or the plaintext SSM pipeline
  configuration. See [SECURITY.md](SECURITY.md) for shared-responsibility guidance.

## Repeated runs and cleanup

The full pipeline uploads only files produced by its current crawl, so unrelated Markdown left in
`prepared_content/` is not uploaded. The standalone `scripts/upload.py` command intentionally
uploads every supported file in its selected directory.

Uploads are additive: removing a URL from `seed_urls` does not delete an object uploaded by an
earlier run. Delete obsolete objects under `s3://<s3_bucket>/<s3_prefix>` and run ingestion again
when you want them removed from the knowledge base.

The local quick-start path creates no standalone AWS infrastructure. To remove its ingested data:

- Delete the objects it wrote under `s3://<s3_bucket>/<s3_prefix>` and re-sync the data source, or
- Delete the knowledge base / data source if it was created only for this walkthrough.

If you deployed the optional CDK stack, also run `cd deploy` followed by `cdk destroy`. This does
not delete the knowledge base, source bucket, ingested objects, CDK bootstrap assets, or the
cluster's Container Insights log group.

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `Configuration error: ... is required` | A required key is missing or still a placeholder in `pipeline.yaml`. |
| Crawl produces 0 files | Pages need more render time (`delay_before_return_html`) or are blocked by `robots.txt`. |
| Ingestion job `FAILED` | Check the sidecar names (`*.md.metadata.json`) and that files are under the configured prefix. |
| `AccessDenied` on ingest | Attach `iam/pipeline-policy.json` (with placeholders replaced) to the running principal. |

## Acknowledgments

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the MIT-0 License. See [LICENSE](LICENSE).
