"""End-to-end orchestration: crawl -> upload -> ingest.

Ties the three stages together so a single call runs the full content preparation
and ingestion flow. Each stage can also be run independently via the CLI scripts.
"""

from __future__ import annotations

import logging

from crawl4ai_bedrock_kb.config import PipelineConfig
from crawl4ai_bedrock_kb.crawl import crawl_and_prepare
from crawl4ai_bedrock_kb.ingest import start_ingestion_job, wait_for_ingestion_job
from crawl4ai_bedrock_kb.upload import upload_prepared_content

logger = logging.getLogger(__name__)


async def run_pipeline(
    config: PipelineConfig,
    output_dir: str,
    wait: bool = True,
) -> dict[str, object]:
    """Run the full crawl -> upload -> ingest pipeline.

    Args:
        config: Validated pipeline configuration.
        output_dir: Local directory for prepared content.
        wait: Whether to poll the ingestion job until it completes.

    Returns:
        A summary dict with ``files_written``, ``objects_uploaded``, ``job_id``,
        and (when ``wait`` is True) ``job_status``.
    """
    written = await crawl_and_prepare(config, output_dir)
    if not written:
        logger.warning("No content prepared; skipping upload and ingestion.")
        return {"files_written": 0, "objects_uploaded": 0, "job_id": None}

    uploaded = upload_prepared_content(config, output_dir, paths=written)
    job_id = start_ingestion_job(config)

    summary: dict[str, object] = {
        "files_written": len(written),
        "objects_uploaded": uploaded,
        "job_id": job_id,
    }

    if wait:
        summary["job_status"] = wait_for_ingestion_job(config, job_id)

    return summary
