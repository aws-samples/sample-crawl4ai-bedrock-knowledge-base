import unittest

from crawl4ai_bedrock_kb.config import PipelineConfig
from crawl4ai_bedrock_kb.ingest import wait_for_ingestion_job


class FakeAgent:
    def get_ingestion_job(self, **kwargs):
        return {
            "ingestionJob": {
                "status": "STOPPED",
                "failureReasons": ["stopped for testing"],
            }
        }


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.config = PipelineConfig(
            knowledge_base_id="kb",
            data_source_id="ds",
            s3_bucket="bucket",
            region="us-east-1",
            seed_urls=["https://example.com"],
        )

    def test_stopped_is_terminal_and_failure_reasons_are_logged(self):
        with self.assertLogs("crawl4ai_bedrock_kb.ingest", level="ERROR") as logs:
            status = wait_for_ingestion_job(
                self.config, "job", client=FakeAgent(), poll_seconds=0
            )
        self.assertEqual(status, "STOPPED")
        self.assertIn("stopped for testing", " ".join(logs.output))

    def test_timeout_returns_explicit_timed_out_status(self):
        status = wait_for_ingestion_job(
            self.config, "job", client=FakeAgent(), timeout_seconds=0
        )
        self.assertEqual(status, "TIMED_OUT")


if __name__ == "__main__":
    unittest.main()
