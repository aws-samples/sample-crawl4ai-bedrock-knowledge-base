# Container image for running the Crawl4AI -> Amazon Bedrock Knowledge Base
# pipeline as a scheduled AWS Fargate task. Multi-arch base; build for linux/arm64
# (Graviton) via the CDK image asset for the best price-performance.
#
# Pulled from Amazon ECR Public (the Docker official-images mirror) rather than
# Docker Hub to avoid anonymous Docker Hub pull-rate limits and stay within the
# AWS network. The digest below is identical to the upstream python image; ECR
# Public re-hosts the same content-addressed manifest.
FROM public.ecr.aws/docker/library/python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install Python deps, then the headless Chromium browser plus its OS
# dependencies (apt packages) while still root.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

# Application code (config is supplied at runtime via SSM or a mounted file).
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/

ENV PYTHONPATH=/app/src

# Run as a non-root user (AWS/container security best practice).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

# Lightweight readiness check: confirm the Python runtime and the application
# package (with its config parser) import cleanly. This is a run-to-completion
# batch task, so this is a readiness probe rather than a long-running liveness
# check.
HEALTHCHECK --interval=5m --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import crawl4ai_bedrock_kb.config"]

ENTRYPOINT ["python", "scripts/container_entrypoint.py"]
