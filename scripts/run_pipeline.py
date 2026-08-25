#!/usr/bin/env python3
"""Run the full crawl -> upload -> ingest pipeline from a config file.

Usage:
    python scripts/run_pipeline.py --config config/pipeline.yaml
    python scripts/run_pipeline.py --config config/pipeline.yaml --no-wait
    python scripts/run_pipeline.py --config config/pipeline.yaml --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import _bootstrap  # noqa: F401  (side effect: sets up sys.path)

from crawl4ai_bedrock_kb.config import ConfigError, load_config  # noqa: E402
from crawl4ai_bedrock_kb.crawl import crawl_and_prepare  # noqa: E402
from crawl4ai_bedrock_kb.pipeline import run_pipeline  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config/pipeline.yaml",
        help="Path to the pipeline YAML config (default: config/pipeline.yaml).",
    )
    parser.add_argument(
        "--output-dir",
        default="prepared_content",
        help="Local directory for prepared content (default: prepared_content).",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Start the ingestion job but do not poll for completion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl and write files locally, but skip S3 upload and ingestion.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable DEBUG logging."
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint. Returns a process exit code."""
    args = _parse_args()
    _bootstrap.configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 3

    if args.dry_run:
        written = asyncio.run(crawl_and_prepare(config, args.output_dir))
        print(
            f"[dry-run] Prepared {len(written)} file(s) in {args.output_dir}; "
            "skipped upload and ingestion."
        )
        return 0

    summary = asyncio.run(
        run_pipeline(config, args.output_dir, wait=not args.no_wait)
    )
    print("Pipeline summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if not args.no_wait and summary.get("job_status") != "COMPLETE":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
