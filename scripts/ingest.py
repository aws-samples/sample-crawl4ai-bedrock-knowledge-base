#!/usr/bin/env python3
"""Ingest only: start (and optionally wait for) a Bedrock KB ingestion job.

Usage:
    python scripts/ingest.py --config config/pipeline.yaml
    python scripts/ingest.py --config config/pipeline.yaml --no-wait
"""

from __future__ import annotations

import argparse
import sys

import _bootstrap  # noqa: F401

from crawl4ai_bedrock_kb.config import ConfigError, load_config  # noqa: E402
from crawl4ai_bedrock_kb.ingest import (  # noqa: E402
    start_ingestion_job,
    wait_for_ingestion_job,
)


def main() -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/pipeline.yaml")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    _bootstrap.configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 3

    job_id = start_ingestion_job(config)
    print(f"Started ingestion job: {job_id}")

    if not args.no_wait:
        status = wait_for_ingestion_job(config, job_id)
        print(f"Ingestion job {job_id} finished with status: {status}")
        if status != "COMPLETE":
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
