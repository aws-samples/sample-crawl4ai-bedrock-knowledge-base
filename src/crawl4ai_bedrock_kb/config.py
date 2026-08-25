"""Configuration loading and validation for the content preparation pipeline."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

_ENV_PREFIX = "CRAWL4AI_KB_"
_ENV_CONTROL_KEYS = {"config_path", "config_ssm"}
_RESERVED_METADATA_KEYS = {
    "source_url",
    "title",
    "crawled_at",
    "crawled_at_epoch",
    "content_type",
}


class ConfigError(ValueError):
    """Raised when the pipeline configuration is missing or invalid."""


@dataclass
class CrawlSettings:
    """Settings that control extraction and deep traversal from each seed URL."""

    css_selector: str | None = None
    request_delay_seconds: float = 1.0
    delay_before_return_html: float = 2.0
    check_robots_txt: bool = True
    page_timeout_ms: int = 60_000
    word_count_threshold: int = 50
    max_depth: int = 2
    max_pages: int = 1000
    scope: str = "path"
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Validate crawl settings, raising :class:`ConfigError` on failure."""
        if self.css_selector is not None and (
            not isinstance(self.css_selector, str) or not self.css_selector.strip()
        ):
            raise ConfigError("crawl.css_selector must be a non-empty string or null")
        for key in ("request_delay_seconds", "delay_before_return_html"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"crawl.{key} must be a number >= 0")
            if not math.isfinite(value) or value < 0:
                raise ConfigError(f"crawl.{key} must be a finite number >= 0")
        if not isinstance(self.check_robots_txt, bool):
            raise ConfigError("crawl.check_robots_txt must be a boolean")
        if (
            isinstance(self.page_timeout_ms, bool)
            or not isinstance(self.page_timeout_ms, int)
            or self.page_timeout_ms < 1000
        ):
            raise ConfigError("crawl.page_timeout_ms must be an integer >= 1000")
        if (
            isinstance(self.word_count_threshold, bool)
            or not isinstance(self.word_count_threshold, int)
            or self.word_count_threshold < 0
        ):
            raise ConfigError("crawl.word_count_threshold must be an integer >= 0")
        if (
            isinstance(self.max_depth, bool)
            or not isinstance(self.max_depth, int)
            or self.max_depth < 0
        ):
            raise ConfigError("crawl.max_depth must be an integer >= 0")
        if (
            isinstance(self.max_pages, bool)
            or not isinstance(self.max_pages, int)
            or self.max_pages < 1
        ):
            raise ConfigError("crawl.max_pages must be an integer >= 1")
        if self.scope not in {"page", "path", "host"}:
            raise ConfigError("crawl.scope must be one of: page, path, host")
        for key in ("include_patterns", "exclude_patterns"):
            value = getattr(self, key)
            if not isinstance(value, list) or any(
                not isinstance(pattern, str) or not pattern.strip() for pattern in value
            ):
                raise ConfigError(f"crawl.{key} must be a list of non-empty strings")


@dataclass
class PipelineConfig:
    """Validated top-level pipeline configuration."""

    knowledge_base_id: str
    data_source_id: str
    s3_bucket: str
    region: str
    seed_urls: list[str]
    s3_prefix: str = "web-content/"
    metadata_attributes: dict[str, Any] = field(default_factory=dict)
    crawl: CrawlSettings = field(default_factory=CrawlSettings)

    def validate(self) -> None:
        """Validate the full configuration and normalize its S3 prefix."""
        required = {
            "knowledge_base_id": self.knowledge_base_id,
            "data_source_id": self.data_source_id,
            "s3_bucket": self.s3_bucket,
            "region": self.region,
        }
        for key, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"config: {key!r} is required and must be a string")
            if value.strip().startswith("<") or "REPLACE" in value.upper():
                raise ConfigError(
                    f"config: {key!r} still contains a placeholder value ({value!r}); "
                    "set it to a real value from your AWS account"
                )

        if not isinstance(self.seed_urls, list) or not self.seed_urls:
            raise ConfigError("config: 'seed_urls' must contain at least one URL")
        for url in self.seed_urls:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise ConfigError(
                    f"config: seed URL {url!r} must be a string starting with http:// or https://"
                )

        if not isinstance(self.s3_prefix, str):
            raise ConfigError("config: 's3_prefix' must be a string")
        if not self.s3_prefix.endswith("/"):
            self.s3_prefix = f"{self.s3_prefix}/"

        self._validate_metadata()
        self.crawl.validate()

    def _validate_metadata(self) -> None:
        if not isinstance(self.metadata_attributes, dict):
            raise ConfigError("config: 'metadata_attributes' must be a mapping")
        for key, value in self.metadata_attributes.items():
            if not isinstance(key, str):
                raise ConfigError("config: metadata attribute keys must be strings")
            if key in _RESERVED_METADATA_KEYS:
                raise ConfigError(f"config: metadata attribute {key!r} is reserved")
            valid = isinstance(value, (str, bool))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    valid = math.isfinite(value)
                except OverflowError:
                    valid = False
            if isinstance(value, list):
                valid = all(isinstance(item, str) for item in value)
            if not valid:
                raise ConfigError(
                    f"config: metadata attribute {key!r} must be a string, finite "
                    "number, boolean, or list of strings"
                )


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply YAML-parsed ``CRAWL4AI_KB_*`` top-level overrides."""
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        config_key = env_key[len(_ENV_PREFIX) :].lower()
        if config_key in _ENV_CONTROL_KEYS:
            continue
        try:
            raw[config_key] = yaml.safe_load(env_value)
        except yaml.YAMLError as exc:
            raise ConfigError(f"environment variable {env_key} is not valid YAML: {exc}") from exc
    return raw


def load_config(path: str) -> PipelineConfig:
    """Load and validate pipeline configuration from a YAML file."""
    if not os.path.isfile(path):
        raise ConfigError(
            f"config file not found: {path!r}. Copy config/pipeline.example.yaml "
            "to config/pipeline.yaml and fill in your values."
        )

    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file {path!r} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path!r} must contain a top-level mapping")

    raw = _apply_env_overrides(raw)
    known_top_fields = set(PipelineConfig.__dataclass_fields__)
    unknown_top = [key for key in raw if key not in known_top_fields]
    if unknown_top:
        names = ", ".join(repr(key) for key in sorted(unknown_top, key=str))
        raise ConfigError(f"config: unknown top-level key(s): {names}")

    crawl_raw = raw.pop("crawl", {}) or {}
    if not isinstance(crawl_raw, dict):
        raise ConfigError("config: 'crawl' must be a mapping")
    known_crawl_fields = set(CrawlSettings.__dataclass_fields__)
    unknown_crawl = [key for key in crawl_raw if key not in known_crawl_fields]
    if unknown_crawl:
        names = ", ".join(repr(key) for key in sorted(unknown_crawl, key=str))
        raise ConfigError(f"config: unknown crawl key(s): {names}")

    try:
        config = PipelineConfig(crawl=CrawlSettings(**crawl_raw), **raw)
    except TypeError as exc:
        raise ConfigError(f"config: missing or invalid top-level field: {exc}") from exc
    config.validate()
    return config
