#!/usr/bin/env python3
"""Container entrypoint for the scheduled Fargate task.

Resolves the pipeline configuration at runtime, then runs the full
crawl -> upload -> ingest pipeline. Configuration is resolved in this order:

1. ``CRAWL4AI_KB_CONFIG_SSM`` — name of an AWS Systems Manager (SSM) Parameter
   whose value is the pipeline config (YAML or JSON). This is how the CDK stack
   ships per-customer config without rebuilding the image.
2. ``CRAWL4AI_KB_CONFIG_PATH`` — path to a config file already in the image.
3. ``config/pipeline.yaml`` — default in-image location.

Keeping config out of the image means customers change crawl targets by editing
one SSM parameter, not by rebuilding and redeploying.
"""

from __future__ import annotations

import os
import sys
import tempfile

import _bootstrap  # noqa: F401  (adds src/ to sys.path)

_bootstrap.configure_logging()


def _resolve_config_path() -> str:
    """Return a local path to the pipeline config, fetching from SSM if configured.

    Returns:
        Filesystem path to a readable pipeline config file.
    """
    ssm_name = os.environ.get("CRAWL4AI_KB_CONFIG_SSM")
    if ssm_name:
        import boto3  # imported lazily so local dry-runs need no AWS SDK

        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        ssm = boto3.client("ssm", region_name=region)
        value = ssm.get_parameter(Name=ssm_name)["Parameter"]["Value"]
        # Write to an OS-created temp file (honors TMPDIR) to avoid predictable-path
        # and symlink risks from a world-writable location.
        handle_fd, runtime_config_path = tempfile.mkstemp(
            prefix="pipeline.runtime.", suffix=".yaml"
        )
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(value)
        return runtime_config_path

    return os.environ.get("CRAWL4AI_KB_CONFIG_PATH", "config/pipeline.yaml")


def main() -> int:
    """Entrypoint. Returns a process exit code (0 success, non-zero failure)."""
    import asyncio

    from crawl4ai_bedrock_kb.config import ConfigError, load_config
    from crawl4ai_bedrock_kb.pipeline import run_pipeline

    try:
        config_path = _resolve_config_path()
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 3

    # Stage prepared content in an OS-created temp directory (honors TMPDIR);
    # the task filesystem is ephemeral per run.
    output_dir = tempfile.mkdtemp(prefix="prepared_")
    summary = asyncio.run(run_pipeline(config, output_dir=output_dir, wait=True))
    print("Pipeline summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return 0 if summary.get("job_status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
