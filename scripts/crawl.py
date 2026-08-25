#!/usr/bin/env python3
"""Crawl only: extract content to local Markdown + metadata sidecars.

Usage:
    python scripts/crawl.py --config config/pipeline.yaml --output-dir prepared_content
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401

from crawl4ai_bedrock_kb.config import ConfigError, load_config  # noqa: E402
from crawl4ai_bedrock_kb.crawl import crawl_and_prepare  # noqa: E402


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

    written = asyncio.run(crawl_and_prepare(config, args.output_dir))
    print(f"Prepared {len(written)} file(s) in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
