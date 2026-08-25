import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawl4ai_bedrock_kb.config import (
    ConfigError,
    CrawlSettings,
    PipelineConfig,
    load_config,
)

_CONFIG = """knowledge_base_id: kb

data_source_id: ds
s3_bucket: bucket
region: us-east-1
seed_urls: [https://original.example]
"""


class ConfigTests(unittest.TestCase):
    def test_environment_list_override_is_yaml_parsed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(_CONFIG, encoding="utf-8")
            override = '["https://one.example", "https://two.example"]'
            with patch.dict(os.environ, {"CRAWL4AI_KB_SEED_URLS": override}):
                config = load_config(str(path))
        self.assertEqual(config.seed_urls, ["https://one.example", "https://two.example"])

    def test_deep_crawl_defaults_are_conservative(self):
        settings = CrawlSettings()
        settings.validate()
        self.assertEqual(settings.max_depth, 2)
        self.assertEqual(settings.max_pages, 1000)
        self.assertEqual(settings.scope, "path")
        self.assertEqual(settings.include_patterns, [])
        self.assertEqual(settings.exclude_patterns, [])

    def test_deep_crawl_values_load_from_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                _CONFIG
                + """crawl:
  max_depth: 5
  max_pages: 2500
  scope: host
  include_patterns: ['*.html']
  exclude_patterns: ['*/private/*']
""",
                encoding="utf-8",
            )
            config = load_config(str(path))
        self.assertEqual(config.crawl.max_depth, 5)
        self.assertEqual(config.crawl.max_pages, 2500)
        self.assertEqual(config.crawl.scope, "host")
        self.assertEqual(config.crawl.include_patterns, ["*.html"])
        self.assertEqual(config.crawl.exclude_patterns, ["*/private/*"])

    def test_invalid_deep_crawl_settings_are_rejected(self):
        invalid_values = [
            ("max_depth", -1, "max_depth"),
            ("max_depth", True, "max_depth"),
            ("max_pages", 0, "max_pages"),
            ("max_pages", 1.5, "max_pages"),
            ("scope", "domain", "scope"),
            ("include_patterns", "*.html", "include_patterns"),
            ("exclude_patterns", [""], "exclude_patterns"),
        ]
        for field_name, value, message in invalid_values:
            with self.subTest(field_name=field_name, value=value):
                settings = CrawlSettings()
                setattr(settings, field_name, value)
                with self.assertRaisesRegex(ConfigError, message):
                    settings.validate()

    def test_reserved_metadata_is_rejected(self):
        config = PipelineConfig(
            knowledge_base_id="kb",
            data_source_id="ds",
            s3_bucket="bucket",
            region="us-east-1",
            seed_urls=["https://example.com"],
            metadata_attributes={"source_url": "override"},
        )
        with self.assertRaisesRegex(ConfigError, "reserved"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
