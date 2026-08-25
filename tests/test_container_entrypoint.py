"""Coverage for the container entrypoint's runtime config resolution.

Focuses on the security-relevant behavior that the SSM-sourced configuration is
written to an OS-created temporary file rather than a fixed, predictable
``/tmp`` path.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import container_entrypoint  # noqa: E402


class ResolveConfigPathTests(unittest.TestCase):
    def test_ssm_value_is_written_to_an_ephemeral_tempfile(self):
        fake_ssm = MagicMock()
        fake_ssm.get_parameter.return_value = {
            "Parameter": {"Value": "seed_urls: [https://example.com]\n"}
        }
        with (
            patch.dict(os.environ, {"CRAWL4AI_KB_CONFIG_SSM": "my-param"}, clear=True),
            patch("boto3.client", return_value=fake_ssm) as client,
        ):
            path = container_entrypoint._resolve_config_path()
        try:
            self.assertTrue(os.path.exists(path))
            # mkstemp randomizes the filename, so it is never a fixed, predictable name.
            self.assertNotEqual(os.path.basename(path), "pipeline.runtime.yaml")
            self.assertTrue(path.endswith(".yaml"))
            # The temp file lives under the OS temp dir (honors TMPDIR).
            self.assertEqual(
                os.path.dirname(os.path.realpath(path)),
                os.path.realpath(tempfile.gettempdir()),
            )
            with open(path, encoding="utf-8") as handle:
                self.assertIn("https://example.com", handle.read())
            client.assert_called_once()
            fake_ssm.get_parameter.assert_called_once_with(Name="my-param")
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_explicit_config_path_is_used_when_ssm_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ["CRAWL4AI_KB_CONFIG_PATH"] = "/etc/pipeline/config.yaml"
            self.assertEqual(
                container_entrypoint._resolve_config_path(),
                "/etc/pipeline/config.yaml",
            )

    def test_default_config_path_when_nothing_is_set(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                container_entrypoint._resolve_config_path(),
                "config/pipeline.yaml",
            )


if __name__ == "__main__":
    unittest.main()
