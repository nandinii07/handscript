"""Configuration read from the environment, and its effect on a real app."""

import unittest
from pathlib import Path
from unittest import mock

from app.config import load_settings


class TestLoadSettings(unittest.TestCase):
    def test_defaults_with_nothing_set(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.job_root, Path("/tmp/handwrite-jobs"))
        self.assertEqual(settings.job_ttl_hours, 24.0)
        self.assertEqual(settings.max_upload_mb, 10.0)
        self.assertEqual(settings.build_timeout, 120.0)
        self.assertEqual(settings.max_workers, 3)
        self.assertEqual(settings.font_family, "MyHandwriting")

    def test_every_documented_variable_is_actually_read(self):
        environment = {
            "HANDWRITE_JOB_ROOT": "/data/jobs",
            "HANDWRITE_JOB_TTL_HOURS": "48",
            "HANDWRITE_MAX_UPLOAD_MB": "5",
            "HANDWRITE_BUILD_TIMEOUT": "90",
            "HANDWRITE_MAX_WORKERS": "2",
            "HANDWRITE_FONT_FAMILY": "CustomHand",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.job_root, Path("/data/jobs"))
        self.assertEqual(settings.job_ttl_hours, 48.0)
        self.assertEqual(settings.max_upload_mb, 5.0)
        self.assertEqual(settings.build_timeout, 90.0)
        self.assertEqual(settings.max_workers, 2)
        self.assertEqual(settings.font_family, "CustomHand")

    def test_derived_limits_are_computed_from_the_per_page_limit(self):
        with mock.patch.dict(
            "os.environ", {"HANDWRITE_MAX_UPLOAD_MB": "2"}, clear=True
        ):
            settings = load_settings()
        self.assertEqual(settings.max_page_bytes, 2 * 1024 * 1024)
        self.assertGreater(settings.max_content_length, settings.max_page_bytes * 3)

    def test_env_example_documents_every_variable_settings_reads(self):
        # A variable added to config.py without a line in .env.example would
        # be undiscoverable by anyone deploying this from the README alone.
        root = Path(__file__).resolve().parents[2]
        example = (root / ".env.example").read_text(encoding="utf-8")
        for name in (
            "HANDWRITE_JOB_ROOT",
            "HANDWRITE_JOB_TTL_HOURS",
            "HANDWRITE_MAX_UPLOAD_MB",
            "HANDWRITE_BUILD_TIMEOUT",
            "HANDWRITE_MAX_WORKERS",
            "HANDWRITE_FONT_FAMILY",
        ):
            with self.subTest(name=name):
                self.assertIn(name, example)


if __name__ == "__main__":
    unittest.main()
