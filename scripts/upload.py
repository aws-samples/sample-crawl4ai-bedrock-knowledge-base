#!/usr/bin/env python3
"""Upload only: push prepared content to the S3 knowledge base data source.

Usage:
    python scripts/upload.py --config config/pipeline.yaml --output-dir prepared_content
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from crawl4ai_bedrock_kb.config import ConfigError, load_config  # noqa: E402
from crawl4ai_bedrock_kb.upload import upload_prepared_content  # noqa: E402


def main() -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/pipeline.yaml")
    parser.add_argument("--output-dir", default="prepared_content")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    _bootstrap.configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 3

    count = upload_prepared_content(config, args.output_dir)
    print(f"Uploaded {count} object(s) to s3://{config.s3_bucket}/{config.s3_prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
