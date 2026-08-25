"""Upload prepared content to the Amazon S3 knowledge base data source."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

import boto3

from crawl4ai_bedrock_kb.config import PipelineConfig

logger = logging.getLogger(__name__)

_UPLOAD_SUFFIXES = (".md", ".metadata.json")


def upload_prepared_content(
    config: PipelineConfig,
    local_dir: str,
    s3_client: object | None = None,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> int:
    """Upload prepared files, optionally restricted to explicit current-run paths.

    Every selected file must exist directly under ``local_dir``. With no explicit
    paths, all supported files directly in that directory are uploaded for the
    standalone upload workflow.
    """
    root = Path(local_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"prepared content directory not found: {local_dir!r}")

    if paths is None:
        candidates = [path for path in root.iterdir() if path.name.endswith(_UPLOAD_SUFFIXES)]
    else:
        candidates = [Path(path).resolve() for path in paths]

    selected: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved.parent != root:
            raise ValueError(f"prepared file must be directly under {local_dir!r}: {path}")
        if not resolved.is_file():
            raise FileNotFoundError(f"prepared file not found: {path}")
        if not resolved.name.endswith(_UPLOAD_SUFFIXES):
            raise ValueError(f"unsupported prepared file type: {resolved.name!r}")
        selected.append(resolved)

    client = s3_client or boto3.client("s3", region_name=config.region)
    for local_path in sorted(selected, key=lambda path: path.name):
        key = f"{config.s3_prefix}{local_path.name}"
        client.upload_file(str(local_path), config.s3_bucket, key)
        logger.debug("Uploaded s3://%s/%s", config.s3_bucket, key)

    count = len(selected)
    logger.info(
        "Uploaded %d object(s) to s3://%s/%s", count, config.s3_bucket, config.s3_prefix
    )
    return count
