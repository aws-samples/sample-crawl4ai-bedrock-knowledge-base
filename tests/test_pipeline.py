import unittest
from unittest.mock import AsyncMock, patch

from crawl4ai_bedrock_kb.config import PipelineConfig
from crawl4ai_bedrock_kb.pipeline import run_pipeline


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_files_written_by_current_crawl_are_uploaded(self):
        config = PipelineConfig(
            knowledge_base_id="kb",
            data_source_id="ds",
            s3_bucket="bucket",
            region="us-east-1",
            seed_urls=["https://example.com"],
        )
        written = ["out/current.md", "out/current.md.metadata.json"]
        with (
            patch(
                "crawl4ai_bedrock_kb.pipeline.crawl_and_prepare",
                new=AsyncMock(return_value=written),
            ),
            patch(
                "crawl4ai_bedrock_kb.pipeline.upload_prepared_content",
                return_value=2,
            ) as upload,
            patch(
                "crawl4ai_bedrock_kb.pipeline.start_ingestion_job",
                return_value="job",
            ),
        ):
            summary = await run_pipeline(config, "out", wait=False)
        upload.assert_called_once_with(config, "out", paths=written)
        self.assertEqual(summary["objects_uploaded"], 2)


if __name__ == "__main__":
    unittest.main()
