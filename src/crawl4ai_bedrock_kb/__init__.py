"""Content preparation pipeline that feeds Crawl4AI output into an Amazon Bedrock Knowledge Base.

This package extracts web content with Crawl4AI, writes clean Markdown plus Amazon
Bedrock-compatible metadata sidecars, uploads them to Amazon S3, and triggers a
Bedrock Knowledge Base ingestion job. All customer-specific values come from a
configuration file so the sample runs unchanged in any AWS account.
"""

from crawl4ai_bedrock_kb.config import PipelineConfig, load_config

__all__ = ["PipelineConfig", "load_config"]
__version__ = "1.0.0"
