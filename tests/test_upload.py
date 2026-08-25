import os
import tempfile
import unittest
from pathlib import Path

from crawl4ai_bedrock_kb.config import PipelineConfig
from crawl4ai_bedrock_kb.upload import upload_prepared_content


class _FakeS3Client:
    """Record upload_file calls instead of contacting Amazon S3."""

    def __init__(self):
        self.uploads: list[tuple[str, str, str]] = []

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))


def _config(**overrides) -> PipelineConfig:
    values = {
        "knowledge_base_id": "kb",
        "data_source_id": "ds",
        "s3_bucket": "bucket",
        "region": "us-east-1",
        "seed_urls": ["https://example.com"],
    }
    values.update(overrides)
    return PipelineConfig(**values)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.output_dir = Path(self._temp.name)

    def _write(self, name: str, body: str = "content") -> Path:
        path = self.output_dir / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_explicit_paths_are_uploaded_under_the_configured_prefix(self):
        markdown = self._write("page.md", "# Page")
        sidecar = self._write("page.md.metadata.json", "{}")
        client = _FakeS3Client()

        count = upload_prepared_content(
            _config(s3_prefix="web-content/"),
            str(self.output_dir),
            s3_client=client,
            paths=[markdown, sidecar],
        )

        self.assertEqual(count, 2)
        keys = [key for _, _, key in client.uploads]
        self.assertEqual(keys, ["web-content/page.md", "web-content/page.md.metadata.json"])
        self.assertEqual({bucket for _, bucket, _ in client.uploads}, {"bucket"})

    def test_directory_scan_uploads_only_supported_files(self):
        self._write("page.md")
        self._write("page.md.metadata.json", "{}")
        self._write("notes.txt")            # unsupported suffix is ignored by the scan
        client = _FakeS3Client()

        count = upload_prepared_content(_config(), str(self.output_dir), s3_client=client)

        self.assertEqual(count, 2)
        self.assertNotIn("notes.txt", [os.path.basename(name) for name, _, _ in client.uploads])

    def test_file_outside_the_output_directory_is_rejected(self):
        nested = self.output_dir / "nested"
        nested.mkdir()
        outside = nested / "page.md"
        outside.write_text("# Page", encoding="utf-8")
        client = _FakeS3Client()

        with self.assertRaises(ValueError):
            upload_prepared_content(
                _config(), str(self.output_dir), s3_client=client, paths=[outside]
            )
        self.assertEqual(client.uploads, [])

    def test_unsupported_suffix_in_explicit_paths_is_rejected(self):
        unsupported = self._write("notes.txt")
        client = _FakeS3Client()

        with self.assertRaises(ValueError):
            upload_prepared_content(
                _config(), str(self.output_dir), s3_client=client, paths=[unsupported]
            )
        self.assertEqual(client.uploads, [])

    def test_missing_explicit_path_raises_file_not_found(self):
        client = _FakeS3Client()

        with self.assertRaises(FileNotFoundError):
            upload_prepared_content(
                _config(),
                str(self.output_dir),
                s3_client=client,
                paths=[self.output_dir / "absent.md"],
            )
        self.assertEqual(client.uploads, [])

    def test_missing_output_directory_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            upload_prepared_content(
                _config(), str(self.output_dir / "does-not-exist"), s3_client=_FakeS3Client()
            )

    def test_validated_prefix_without_trailing_slash_gets_one(self):
        markdown = self._write("page.md")
        client = _FakeS3Client()
        # Loaded configuration is always validated, which normalizes the prefix.
        config = _config(s3_prefix="custom")
        config.validate()

        upload_prepared_content(
            config, str(self.output_dir), s3_client=client, paths=[markdown]
        )

        self.assertEqual(client.uploads[0][2], "custom/page.md")


if __name__ == "__main__":
    unittest.main()
