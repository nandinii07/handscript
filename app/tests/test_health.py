"""GET /health - what a container orchestrator polls."""

import unittest
from unittest import mock

from app.tests.conftest import AppTestCase


class TestHealth(AppTestCase):
    def test_it_reports_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")

    def test_the_older_path_still_works(self):
        # Kept as an alias: nothing before this pass called it /health.
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_it_says_whether_the_build_tools_are_present(self):
        payload = self.client.get("/health").get_json()
        self.assertIn("build_tools_available", payload)
        self.assertIsInstance(payload["build_tools_available"], bool)

    def test_it_reveals_no_filesystem_paths(self):
        body = self.client.get("/health").get_data(as_text=True)
        self.assertNotIn("/tmp", body)
        self.assertNotIn(str(self.job_root), body)

    def test_it_reports_missing_tools_without_pretending_they_exist(self):
        with mock.patch("shutil.which", return_value=None):
            payload = self.client.get("/health").get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["build_tools_available"])


if __name__ == "__main__":
    unittest.main()
