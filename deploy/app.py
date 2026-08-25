#!/usr/bin/env python3
"""CDK app entrypoint for the scheduled Fargate crawler.

Reads customer configuration from CDK context (``cdk.json`` or ``-c key=value``),
validates the required values with friendly errors, and synthesizes the
:class:`CrawlerStack`. Deploy with:

    cd deploy
    pip install -r requirements.txt
    cdk deploy \
      -c knowledgeBaseId=XXXX -c dataSourceId=YYYY \
      -c s3Bucket=my-kb-bucket -c 'seedUrls=["https://www.example.com/faq"]'
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Any
from urllib.parse import urlsplit

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks
from cdk_nag_suppressions import apply_suppressions
from stacks.crawler_stack import CrawlerStack

_REQUIRED_KEYS = ("knowledgeBaseId", "dataSourceId", "s3Bucket", "seedUrls")


def _fail(message: str) -> None:
    """Exit with a concise deployment-configuration error."""
    sys.stderr.write(f"{message}\n")
    raise SystemExit(2)


def _get_context(app: cdk.App, key: str) -> Any:
    """Return context, decoding JSON-encoded lists and maps from the CLI."""
    value = app.node.try_get_context(key)
    if isinstance(value, str) and value and value[0] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_bool(value: Any, key: str) -> bool:
    """Parse only actual booleans or the exact CDK CLI strings true/false."""
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    _fail(f"Context key {key!r} must be a boolean (true or false).")


def _parse_nonnegative_number(value: Any, key: str) -> int | float:
    """Parse a finite nonnegative number, including a numeric CLI string."""
    if isinstance(value, bool):
        _fail(f"Context key {key!r} must be a finite number >= 0.")
    parsed: int | float
    if isinstance(value, (int, float)):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            _fail(f"Context key {key!r} must be a finite number >= 0.")
    else:
        _fail(f"Context key {key!r} must be a finite number >= 0.")
    if not math.isfinite(parsed) or parsed < 0:
        _fail(f"Context key {key!r} must be a finite number >= 0.")
    return parsed


def _parse_integer(value: Any, key: str, minimum: int) -> int:
    """Parse an integer CLI context value and enforce its lower bound."""
    if isinstance(value, bool):
        _fail(f"Context key {key!r} must be an integer >= {minimum}.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            _fail(f"Context key {key!r} must be an integer >= {minimum}.")
    else:
        _fail(f"Context key {key!r} must be an integer >= {minimum}.")
    if parsed < minimum:
        _fail(f"Context key {key!r} must be an integer >= {minimum}.")
    return parsed


def _parse_string_list(value: Any, key: str) -> list[str]:
    """Validate a JSON list containing only non-empty strings."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        _fail(f"Context key {key!r} must be a JSON list of non-empty strings.")
    return value


def _load_config(app: cdk.App) -> dict[str, Any]:
    """Collect, strictly validate, and normalize deployment context."""
    keys = (
        "knowledgeBaseId",
        "dataSourceId",
        "s3Bucket",
        "s3Prefix",
        "seedUrls",
        "scheduleExpression",
        "taskCpu",
        "taskMemory",
        "cpuArchitecture",
        "vpcId",
        "egressMode",
        "privateEndpoints",
        "metadataAttributes",
        "cssSelector",
        "crawlRequestDelaySeconds",
        "maxDepth",
        "maxPages",
        "crawlScope",
        "includePatterns",
        "excludePatterns",
    )
    config = {
        key: value
        for key in keys
        if (value := _get_context(app, key)) is not None
    }

    missing = [key for key in _REQUIRED_KEYS if not config.get(key)]
    if missing:
        _fail(
            "Missing required context key(s): "
            + ", ".join(missing)
            + ". Pass them via cdk.json or -c."
        )

    for key in ("knowledgeBaseId", "dataSourceId", "s3Bucket"):
        value = config[key]
        if not isinstance(value, str) or not value.strip():
            _fail(f"Context key {key!r} must be a non-empty string.")
        if value.startswith("<") or "REPLACE" in value.upper():
            _fail(f"Context key {key!r} still holds a placeholder ({value!r}).")

    seed_urls = config["seedUrls"]
    if not isinstance(seed_urls, list) or not seed_urls:
        _fail("Context key 'seedUrls' must be a non-empty JSON list of HTTP(S) URLs.")
    for url in seed_urls:
        if not isinstance(url, str):
            _fail("Every 'seedUrls' entry must be an HTTP(S) URL string.")
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            _fail(f"Invalid seed URL {url!r}; expected an absolute HTTP(S) URL.")

    architecture = config.get("cpuArchitecture", "ARM64")
    if architecture not in ("ARM64", "X86_64"):
        _fail("Context key 'cpuArchitecture' must be exactly 'ARM64' or 'X86_64'.")
    config["cpuArchitecture"] = architecture

    egress_mode = config.get("egressMode", "public")
    if egress_mode not in ("public", "nat"):
        _fail("Context key 'egressMode' must be exactly 'public' or 'nat'.")
    config["egressMode"] = egress_mode

    private_endpoints = _parse_bool(config.get("privateEndpoints", False), "privateEndpoints")
    config["privateEndpoints"] = private_endpoints
    if private_endpoints and config.get("vpcId"):
        _fail(
            "'privateEndpoints=true' cannot be used with imported 'vpcId'; "
            "the stack does not modify imported VPCs."
        )
    if private_endpoints and egress_mode != "nat":
        _fail("'privateEndpoints=true' requires 'egressMode=nat'.")

    metadata = config.get("metadataAttributes", {})
    if not isinstance(metadata, dict):
        _fail("Context key 'metadataAttributes' must be a JSON map.")
    config["metadataAttributes"] = metadata

    selector = config.get("cssSelector")
    if selector is not None and (not isinstance(selector, str) or not selector.strip()):
        _fail("Context key 'cssSelector' must be a non-empty string when set.")

    config["crawlRequestDelaySeconds"] = _parse_nonnegative_number(
        config.get("crawlRequestDelaySeconds", 1.0), "crawlRequestDelaySeconds"
    )
    config["maxDepth"] = _parse_integer(config.get("maxDepth", 2), "maxDepth", 0)
    config["maxPages"] = _parse_integer(config.get("maxPages", 1000), "maxPages", 1)

    scope = config.get("crawlScope", "path")
    if scope not in ("page", "path", "host"):
        _fail("Context key 'crawlScope' must be exactly 'page', 'path', or 'host'.")
    config["crawlScope"] = scope
    config["includePatterns"] = _parse_string_list(
        config.get("includePatterns", []), "includePatterns"
    )
    config["excludePatterns"] = _parse_string_list(
        config.get("excludePatterns", []), "excludePatterns"
    )

    prefix = config.get("s3Prefix", "web-content/")
    if not isinstance(prefix, str):
        _fail("Context key 's3Prefix' must be a string.")
    config["s3Prefix"] = prefix if prefix.endswith("/") else f"{prefix}/"
    return config


def main() -> None:
    """Synthesize the CDK app."""
    app = cdk.App()
    config = _load_config(app)

    # Enforce AWS Solutions security best practices (cdk-nag).
    cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION"),
    )

    stack = CrawlerStack(
        app,
        "Crawl4aiBedrockKbCrawler",
        config=config,
        env=env,
        description="Scheduled Fargate crawler feeding an Amazon Bedrock Knowledge Base.",
    )
    apply_suppressions(stack)

    app.synth()


if __name__ == "__main__":
    main()
