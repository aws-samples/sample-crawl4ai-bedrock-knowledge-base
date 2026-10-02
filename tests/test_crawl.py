import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.deep_crawling.filters import URLPatternFilter

from crawl4ai_bedrock_kb.config import CrawlSettings, PipelineConfig
from crawl4ai_bedrock_kb.crawl import (
    SeedScopeFilter,
    _base_name,
    _canonical_url,
    _write_document,
    crawl_and_prepare,
)


class SidecarTests(unittest.TestCase):
    def test_exact_sidecar_name_and_windows_safe_base_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            md_path, metadata_path = _write_document(
                temp_dir, "page", "content", {"title": "Page"}
            )
            self.assertEqual(os.path.basename(md_path), "page.md")
            self.assertEqual(os.path.basename(metadata_path), "page.md.metadata.json")
        base_name = _base_name("https://example.com/a%3Ab%2Ac%3Fd")
        self.assertNotRegex(base_name, r'[<>:"/\\|?*]')

    def test_sidecar_uses_typed_attribute_values(self):
        metadata = {
            "title": "Page",
            "rank": 3,
            "score": 1.5,
            "public": True,
            "tags": ["a", "b"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            _, metadata_path = _write_document(temp_dir, "page", "content", metadata)
            with open(metadata_path, encoding="utf-8") as handle:
                attributes = json.load(handle)["metadataAttributes"]

        self.assertEqual(attributes["title"], {"value": {"type": "STRING", "stringValue": "Page"}})
        self.assertEqual(attributes["rank"], {"value": {"type": "NUMBER", "numberValue": 3}})
        self.assertEqual(attributes["score"], {"value": {"type": "NUMBER", "numberValue": 1.5}})
        self.assertEqual(
            attributes["public"], {"value": {"type": "BOOLEAN", "booleanValue": True}}
        )
        self.assertEqual(
            attributes["tags"],
            {"value": {"type": "STRING_LIST", "stringListValue": ["a", "b"]}},
        )

    def test_sidecar_larger_than_ten_kib_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "maximum is 10240"):
                _write_document(temp_dir, "large", "content", {"value": "x" * 10240})
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "large.md")))


class ScopeFilterTests(unittest.TestCase):
    def test_path_scope_enforces_path_boundary_and_exact_host(self):
        scope_filter = SeedScopeFilter("https://docs.example.com/docs", "path")
        self.assertTrue(scope_filter.apply("https://docs.example.com/docs"))
        self.assertTrue(scope_filter.apply("https://DOCS.example.com/docs/guide"))
        self.assertFalse(scope_filter.apply("https://docs.example.com/docs-old"))
        self.assertFalse(scope_filter.apply("https://docs.example.com/docs%2Dold/page"))
        self.assertFalse(scope_filter.apply("https://docs.example.com/docs/../private"))
        self.assertFalse(scope_filter.apply("https://sub.docs.example.com/docs/guide"))
        self.assertFalse(scope_filter.apply("https://docs.example.com.evil.test/docs/guide"))

    def test_host_scope_accepts_only_the_seed_origin(self):
        scope_filter = SeedScopeFilter("https://Example.com/start", "host")
        self.assertTrue(scope_filter.apply("https://EXAMPLE.COM.:443/elsewhere"))
        self.assertFalse(scope_filter.apply("http://example.com/elsewhere"))
        self.assertFalse(scope_filter.apply("https://example.com:8443/elsewhere"))
        self.assertFalse(scope_filter.apply("https://www.example.com/elsewhere"))
        self.assertFalse(scope_filter.apply("https://notexample.com/elsewhere"))

    def test_page_scope_and_canonical_url_ignore_fragment_and_default_port(self):
        scope_filter = SeedScopeFilter("https://example.com:443/docs#top", "page")
        self.assertTrue(scope_filter.apply("https://EXAMPLE.com/docs#other"))
        self.assertFalse(scope_filter.apply("https://example.com/docs/child"))
        self.assertEqual(
            _canonical_url("https://EXAMPLE.com:443/docs#part"),
            "https://example.com/docs",
        )


class _FakeCrawler:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def arun(self, *, url, config):
        self.calls.append((url, config))
        return self.responses.pop(0)


def _result(url, title, redirected_url=None):
    return SimpleNamespace(
        url=url,
        redirected_url=redirected_url,
        success=True,
        markdown=SimpleNamespace(fit_markdown=f"# {title}", raw_markdown="raw fallback"),
        metadata={"title": title},
    )


class DeepCrawlTests(unittest.IsolatedAsyncioTestCase):
    async def test_deep_results_use_result_url_deduplicate_and_obey_global_cap(self):
        duplicate = "https://EXAMPLE.com:443/docs/a#fragment"
        responses = [
            [
                _result("https://example.com/docs", "Seed"),
                _result("https://example.com/docs/a", "A"),
            ],
            [
                _result(duplicate, "Duplicate A"),
                _result("https://example.com/other/b", "B"),
                _result("https://example.com/other/overflow", "Overflow"),
            ],
        ]
        crawler = _FakeCrawler(responses)
        config = PipelineConfig(
            knowledge_base_id="kb",
            data_source_id="ds",
            s3_bucket="bucket",
            region="us-east-1",
            seed_urls=["https://example.com/docs", "https://example.com/other"],
            crawl=CrawlSettings(
                request_delay_seconds=1.25,
                max_depth=3,
                max_pages=4,
                scope="host",
                include_patterns=["https://example.com/*"],
                exclude_patterns=["*/private/*"],
            ),
        )
        config.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("crawl4ai_bedrock_kb.crawl.AsyncWebCrawler", return_value=crawler),
                patch("crawl4ai_bedrock_kb.crawl.asyncio.sleep") as sleep,
            ):
                written = await crawl_and_prepare(config, temp_dir)

            self.assertEqual(len(written), 6)
            sleep.assert_awaited_once_with(1.25)
            sidecars = [path for path in written if path.endswith(".metadata.json")]
            source_urls = []
            for path in sidecars:
                with open(path, encoding="utf-8") as handle:
                    attributes = json.load(handle)["metadataAttributes"]
                    source_urls.append(attributes["source_url"]["value"]["stringValue"])

        self.assertEqual(
            source_urls,
            [
                "https://example.com/docs",
                "https://example.com/docs/a",
                "https://example.com/other/b",
            ],
        )
        self.assertNotIn(duplicate, source_urls)
        self.assertEqual(len(crawler.calls), 2)
        first_config = crawler.calls[0][1]
        second_config = crawler.calls[1][1]
        self.assertEqual(first_config.mean_delay, 1.25)
        self.assertEqual(first_config.max_range, 0)
        self.assertEqual(first_config.semaphore_count, 1)
        self.assertIsInstance(first_config.deep_crawl_strategy, BFSDeepCrawlStrategy)
        self.assertEqual(first_config.deep_crawl_strategy.max_depth, 3)
        self.assertEqual(first_config.deep_crawl_strategy.max_pages, 4)
        self.assertEqual(second_config.deep_crawl_strategy.max_pages, 2)
        filters = first_config.deep_crawl_strategy.filter_chain.filters
        self.assertIsInstance(filters[0], SeedScopeFilter)
        self.assertIsInstance(filters[1], URLPatternFilter)
        self.assertIsInstance(filters[2], URLPatternFilter)

    async def test_redirects_are_rechecked_and_effective_url_is_metadata_source(self):
        crawler = _FakeCrawler(
            [[
                _result(
                    "https://example.com/docs/escape",
                    "Outside",
                    redirected_url="https://evil.example/private",
                ),
                _result(
                    "https://example.com/docs/old",
                    "Final",
                    redirected_url="https://example.com/docs/final",
                ),
            ]]
        )
        config = PipelineConfig(
            knowledge_base_id="kb",
            data_source_id="ds",
            s3_bucket="bucket",
            region="us-east-1",
            seed_urls=["https://example.com/docs"],
            crawl=CrawlSettings(request_delay_seconds=0, max_depth=1, max_pages=2),
        )
        config.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("crawl4ai_bedrock_kb.crawl.AsyncWebCrawler", return_value=crawler):
                written = await crawl_and_prepare(config, temp_dir)
            self.assertEqual(len(written), 2)
            metadata_path = next(path for path in written if path.endswith(".metadata.json"))
            with open(metadata_path, encoding="utf-8") as handle:
                attributes = json.load(handle)["metadataAttributes"]
                source_url = attributes["source_url"]["value"]["stringValue"]

        self.assertEqual(source_url, "https://example.com/docs/final")


if __name__ == "__main__":
    unittest.main()
