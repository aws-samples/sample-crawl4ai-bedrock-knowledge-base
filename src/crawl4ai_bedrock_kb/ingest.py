"""Trigger and monitor Amazon Bedrock Knowledge Base ingestion jobs.

After prepared content is uploaded to Amazon S3, an ingestion job tells the
knowledge base to chunk, embed, and index the new documents using its configured
strategy. This module starts the job and optionally polls until it completes.
"""

from __future__ import annotations

import logging
import time

import boto3

from crawl4ai_bedrock_kb.config import PipelineConfig

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {"COMPLETE", "FAILED", "STOPPED"}
_DEFAULT_POLL_SECONDS = 15
_DEFAULT_TIMEOUT_SECONDS = 30 * 60


def start_ingestion_job(
    config: PipelineConfig,
    client: object | None = None,
) -> str:
    """Start a Bedrock Knowledge Base ingestion job.

    Args:
        config: Validated pipeline configuration.
        client: Optional boto3 ``bedrock-agent`` client (injected for testing).

    Returns:
        The ingestion job ID.
    """
    agent = client or boto3.client("bedrock-agent", region_name=config.region)
    response = agent.start_ingestion_job(
        knowledgeBaseId=config.knowledge_base_id,
        dataSourceId=config.data_source_id,
    )
    job = response["ingestionJob"]
    logger.info(
        "Started ingestion job %s (status: %s)",
        job["ingestionJobId"],
        job["status"],
    )
    return job["ingestionJobId"]


def wait_for_ingestion_job(
    config: PipelineConfig,
    job_id: str,
    client: object | None = None,
    poll_seconds: int = _DEFAULT_POLL_SECONDS,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Poll an ingestion job until it reaches a terminal state or times out.

    Args:
        config: Validated pipeline configuration.
        job_id: The ingestion job ID to poll.
        client: Optional boto3 ``bedrock-agent`` client (injected for testing).
        poll_seconds: Seconds to wait between polls.
        timeout_seconds: Maximum seconds to wait before giving up.

    Returns:
        The terminal job status (``COMPLETE``, ``FAILED``, or ``STOPPED``), or
        ``TIMED_OUT`` if the timeout is reached.
    """
    agent = client or boto3.client("bedrock-agent", region_name=config.region)
    deadline = time.monotonic() + timeout_seconds
    status = "STARTING"

    while time.monotonic() < deadline:
        response = agent.get_ingestion_job(
            knowledgeBaseId=config.knowledge_base_id,
            dataSourceId=config.data_source_id,
            ingestionJobId=job_id,
        )
        job = response["ingestionJob"]
        status = job["status"]
        if status in _TERMINAL_STATES:
            stats = job.get("statistics", {})
            failure_reasons = job.get("failureReasons", [])
            logger.info("Ingestion job %s finished: %s %s", job_id, status, stats)
            if failure_reasons:
                logger.error(
                    "Ingestion job %s failure reasons: %s",
                    job_id,
                    failure_reasons,
                )
            return status
        logger.info("Ingestion job %s status: %s", job_id, status)
        time.sleep(poll_seconds)

    logger.warning(
        "Timed out after %ds waiting for ingestion job %s (last status: %s)",
        timeout_seconds,
        job_id,
        status,
    )
    return "TIMED_OUT"
