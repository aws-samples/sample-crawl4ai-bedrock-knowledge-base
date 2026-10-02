"""Deep-crawl configured seeds into Markdown and Bedrock metadata sidecars."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import posixpath
import re
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse, urlsplit, urlunsplit

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.deep_crawling.filters import FilterChain, URLFilter, URLPatternFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from crawl4ai_bedrock_kb.config import PipelineConfig

logger = logging.getLogger(__name__)

_METADATA_SUFFIX = ".metadata.json"
_MAX_SIDECAR_BYTES = 10 * 1024
_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _normalized_host(url: str) -> str:
    """Return a case-insensitive, IDNA-normalized hostname without a trailing dot."""
    try:
        hostname = urlsplit(url).hostname
    except (TypeError, ValueError):
        return ""
    if not hostname:
        return ""
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    return hostname.lower().rstrip(".")


def _normalized_path(url: str) -> str:
    """Normalize escaped and dot path segments for safe subtree comparisons."""
    try:
        path = unquote(urlsplit(url).path or "/")
    except (TypeError, ValueError):
        return "/"
    path = "/" + path.lstrip("/")
    normalized = posixpath.normpath(path)
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _canonical_url(url: str) -> str:
    """Canonicalize a web URL for cross-seed deduplication."""
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return ""
    scheme = parsed.scheme.lower()
    host = _normalized_host(url)
    if not scheme or not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host_part = f"[{host}]" if ":" in host else host
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host_part if port is None or default_port else f"{host_part}:{port}"
    path = quote(_normalized_path(url), safe="/!$&'()*+,;=:@-._~")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _normalized_origin(url: str) -> str:
    """Return the canonical HTTP(S) origin, including a non-default port."""
    canonical_url = _canonical_url(url)
    if not canonical_url:
        return ""
    canonical = urlsplit(canonical_url)
    if canonical.scheme not in {"http", "https"} or not canonical.netloc:
        return ""
    return f"{canonical.scheme}://{canonical.netloc}"


class SeedScopeFilter(URLFilter):
    """Restrict discovered URLs to the seed origin and configured page/path scope."""

    def __init__(self, seed_url: str, scope: str):
        super().__init__(name="seed-scope")
        self.seed_url = _canonical_url(seed_url)
        self.seed_origin = _normalized_origin(seed_url)
        self.seed_path = _normalized_path(seed_url)
        self.scope = scope

    def apply(self, url: str) -> bool:
        candidate_origin = _normalized_origin(url)
        if self.scope == "page":
            passed = _canonical_url(url) == self.seed_url
        elif not candidate_origin or candidate_origin != self.seed_origin:
            passed = False
        elif self.scope == "host":
            passed = True
        else:
            candidate_path = _normalized_path(url)
            root = self.seed_path.rstrip("/") or "/"
            passed = root == "/" or candidate_path == root or candidate_path.startswith(f"{root}/")
        self._update_stats(passed)
        return passed


def _base_name(url: str) -> str:
    """Build a deterministic base name safe on Windows and POSIX filesystems."""
    # Short, non-cryptographic digest that only disambiguates output filenames
    # when two URLs slugify to the same value. Not a security control.
    url_hash = hashlib.sha256(url.encode(), usedforsecurity=False).hexdigest()[:12]
    path = unquote(urlparse(url).path).strip("/") or "index"
    slug = _WINDOWS_UNSAFE.sub("_", path).strip(" .") or "index"
    return f"{slug[:80].rstrip(' .')}_{url_hash}"


def _typed_attributes(metadata: dict[str, object]) -> dict[str, dict[str, object]]:
    """Wrap each value in the typed attribute format used by S3 metadata sidecars.

    Managed and customer-managed knowledge bases both accept this format for Amazon S3
    data sources, so the same sidecar works with either knowledge base type.
    """
    typed: dict[str, dict[str, object]] = {}
    for key, value in metadata.items():
        if isinstance(value, bool):
            attribute: dict[str, object] = {"type": "BOOLEAN", "booleanValue": value}
        elif isinstance(value, (int, float)):
            attribute = {"type": "NUMBER", "numberValue": value}
        elif isinstance(value, list):
            attribute = {"type": "STRING_LIST", "stringListValue": value}
        else:
            attribute = {"type": "STRING", "stringValue": str(value)}
        typed[key] = {"value": attribute}
    return typed


def _write_document(
    output_dir: str,
    base_name: str,
    markdown: str,
    metadata: dict[str, object],
) -> tuple[str, str]:
    """Write a Markdown file and its exact ``.md.metadata.json`` sidecar."""
    md_name = f"{base_name}.md"
    md_path = os.path.join(output_dir, md_name)
    meta_path = os.path.join(output_dir, f"{md_name}{_METADATA_SUFFIX}")
    sidecar = json.dumps(
        {"metadataAttributes": _typed_attributes(metadata)},
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    sidecar_size = len(sidecar.encode("utf-8"))
    if sidecar_size > _MAX_SIDECAR_BYTES:
        raise ValueError(
            f"metadata sidecar for {md_name!r} is {sidecar_size} bytes; "
            f"maximum is {_MAX_SIDECAR_BYTES} bytes"
        )

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    with open(meta_path, "w", encoding="utf-8") as handle:
        handle.write(sidecar)
    return md_path, meta_path


def _result_list(result: object) -> list[object]:
    """Normalize Crawl4AI single results, deep lists, and result containers."""
    if isinstance(result, (list, tuple)):
        return list(result)
    try:
        return list(iter(result))
    except TypeError:
        return [result]


def _filter_chain(config: PipelineConfig, seed: str) -> FilterChain:
    filters: list[URLFilter] = [SeedScopeFilter(seed, config.crawl.scope)]
    if config.crawl.include_patterns:
        filters.append(URLPatternFilter(config.crawl.include_patterns))
    if config.crawl.exclude_patterns:
        filters.append(URLPatternFilter(config.crawl.exclude_patterns, reverse=True))
    return FilterChain(filters)


async def crawl_and_prepare(config: PipelineConfig, output_dir: str) -> list[str]:
    """Deep-crawl each seed while enforcing one global per-run page cap."""
    os.makedirs(output_dir, exist_ok=True)
    browser_config = BrowserConfig(headless=True, java_script_enabled=True)
    common_run_settings = {
        "markdown_generator": DefaultMarkdownGenerator(content_filter=PruningContentFilter()),
        "excluded_tags": ["nav", "header", "footer", "aside"],
        "css_selector": config.crawl.css_selector,
        "delay_before_return_html": config.crawl.delay_before_return_html,
        "check_robots_txt": config.crawl.check_robots_txt,
        "page_timeout": config.crawl.page_timeout_ms,
        "word_count_threshold": config.crawl.word_count_threshold,
        "cache_mode": CacheMode.BYPASS,
        "mean_delay": config.crawl.request_delay_seconds,
        "max_range": 0,
        "semaphore_count": 1,
    }

    written: list[str] = []
    seen_urls: set[str] = set()
    pages_crawled = 0
    pages_prepared = 0
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for index, seed in enumerate(config.seed_urls):
            if pages_crawled >= config.crawl.max_pages:
                break
            canonical_seed = _canonical_url(seed)
            if canonical_seed in seen_urls:
                logger.info("Skipping duplicate seed %s", seed)
                continue
            if index and config.crawl.request_delay_seconds:
                await asyncio.sleep(config.crawl.request_delay_seconds)

            remaining = config.crawl.max_pages - pages_crawled
            strategy = BFSDeepCrawlStrategy(
                max_depth=config.crawl.max_depth,
                max_pages=remaining,
                filter_chain=_filter_chain(config, seed),
            )
            run_config = CrawlerRunConfig(
                **common_run_settings,
                deep_crawl_strategy=strategy,
            )
            run_result = await crawler.arun(url=seed, config=run_config)
            for result in _result_list(run_result):
                if pages_crawled >= config.crawl.max_pages:
                    break
                pages_crawled += 1
                requested_url = result.url
                source_url = getattr(result, "redirected_url", None) or requested_url
                if not SeedScopeFilter(seed, config.crawl.scope).apply(source_url):
                    logger.warning(
                        "Skipping out-of-scope result %s (requested as %s).",
                        source_url,
                        requested_url,
                    )
                    continue
                canonical = _canonical_url(source_url)
                if canonical in seen_urls:
                    logger.info("Skipping duplicate crawled URL %s", source_url)
                    continue
                seen_urls.add(canonical)
                if not result.success or not result.markdown:
                    logger.warning("No usable content for %s (skipped).", source_url)
                    continue

                md_result = result.markdown
                markdown = (
                    getattr(md_result, "fit_markdown", None)
                    or getattr(md_result, "raw_markdown", None)
                    or (md_result if isinstance(md_result, str) else "")
                )
                if not markdown:
                    logger.warning("No usable Markdown for %s (skipped).", source_url)
                    continue

                page_meta = result.metadata or {}
                crawled_at = datetime.now(timezone.utc)
                metadata = {
                    "source_url": source_url,
                    "title": page_meta.get("title") or urlparse(source_url).path or source_url,
                    "crawled_at": crawled_at.isoformat(),
                    "crawled_at_epoch": crawled_at.timestamp(),
                    "content_type": "web_page",
                    **config.metadata_attributes,
                }
                md_path, meta_path = _write_document(
                    output_dir, _base_name(source_url), markdown, metadata
                )
                written.extend([md_path, meta_path])
                pages_prepared += 1
                logger.info("Prepared %s -> %s", source_url, os.path.basename(md_path))

    logger.info(
        "Crawl complete: %d page(s) crawled, %d page(s) prepared.",
        pages_crawled,
        pages_prepared,
    )
    return written
