"""Focused built-in unittest coverage for CDK context validation."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
if str(_DEPLOY) not in sys.path:
    sys.path.insert(0, str(_DEPLOY))

import app as deploy_app  # noqa: E402
from stacks.crawler_stack import CrawlerStack  # noqa: E402


class _Node:
    def __init__(self, context):
        self.context = context

    def try_get_context(self, key):
        return self.context.get(key)


class _App:
    def __init__(self, context):
        self.node = _Node(context)


class DeployConfigTests(unittest.TestCase):
    def _context(self, **overrides):
        context = {
            "knowledgeBaseId": "KB123",
            "dataSourceId": "DS123",
            "s3Bucket": "example-bucket",
            "seedUrls": ["https://example.com/start"],
        }
        context.update(overrides)
        return context

    def test_private_endpoints_cli_booleans_are_strict(self):
        public = deploy_app._load_config(_App(self._context(privateEndpoints="false")))
        self.assertIs(public["privateEndpoints"], False)
        private = deploy_app._load_config(
            _App(self._context(privateEndpoints="true", egressMode="nat"))
        )
        self.assertIs(private["privateEndpoints"], True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            deploy_app._load_config(_App(self._context(privateEndpoints="yes")))

    def test_invalid_architecture_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            deploy_app._load_config(_App(self._context(cpuArchitecture="arm64")))

    def test_deep_crawl_context_defaults_and_cli_values(self):
        defaults = deploy_app._load_config(_App(self._context()))
        self.assertEqual(defaults["maxDepth"], 2)
        self.assertEqual(defaults["maxPages"], 1000)
        self.assertEqual(defaults["crawlScope"], "path")
        self.assertEqual(defaults["includePatterns"], [])
        self.assertEqual(defaults["excludePatterns"], [])

        explicit = deploy_app._load_config(
            _App(
                self._context(
                    maxDepth="3",
                    maxPages="25",
                    crawlScope="host",
                    includePatterns='["https://example.com/*"]',
                    excludePatterns='["*/private/*"]',
                )
            )
        )
        self.assertEqual(explicit["maxDepth"], 3)
        self.assertEqual(explicit["maxPages"], 25)
        self.assertEqual(explicit["crawlScope"], "host")
        self.assertEqual(explicit["includePatterns"], ["https://example.com/*"])
        self.assertEqual(explicit["excludePatterns"], ["*/private/*"])

    def test_invalid_deep_crawl_context_is_rejected(self):
        invalid = (
            {"maxDepth": -1},
            {"maxDepth": 1.5},
            {"maxPages": 0},
            {"maxPages": "1.5"},
            {"crawlScope": "domain"},
            {"includePatterns": "*.html"},
            {"excludePatterns": [""]},
        )
        for overrides in invalid:
            with (
                self.subTest(overrides=overrides),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                deploy_app._load_config(_App(self._context(**overrides)))

    def test_deep_crawl_context_is_serialized_for_the_container(self):
        config = deploy_app._load_config(
            _App(
                self._context(
                    maxDepth=1,
                    maxPages=10,
                    crawlScope="path",
                    includePatterns=["*/departments/public-service/*"],
                    excludePatterns=["*/archive/*"],
                )
            )
        )
        serialized = CrawlerStack._build_pipeline_config_json(
            SimpleNamespace(region="us-east-1"), config
        )
        crawl = json.loads(serialized)["crawl"]
        self.assertEqual(crawl["max_depth"], 1)
        self.assertEqual(crawl["max_pages"], 10)
        self.assertEqual(crawl["scope"], "path")
        self.assertEqual(crawl["include_patterns"], ["*/departments/public-service/*"])
        self.assertEqual(crawl["exclude_patterns"], ["*/archive/*"])


if __name__ == "__main__":
    unittest.main()
