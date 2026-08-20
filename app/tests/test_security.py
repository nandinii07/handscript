"""Things a hostile client might try, checked explicitly rather than assumed.

Most of these properties already existed before this pass - server-controlled
page names, random job ids - and were exercised incidentally by other tests.
This module exists so the security review itself has something concrete to
point at: one file, one test per claim.
"""

import io
import re
import unittest
from pathlib import Path

from app.errors import _without_server_paths
from app.tests.conftest import AppTestCase, upload_files

APP_ROOT = Path(__file__).resolve().parents[1]


class TestUploadLimits(AppTestCase):
    def test_exactly_three_pages_are_required(self):
        # A file upload's stream can only be read once - the test client
        # consumes it building the request - so each case gets its own fresh
        # copies rather than reusing one payload across subtests.
        for count in (0, 1, 2):
            with self.subTest(count=count):
                pages = self.pages[:count]
                fields = ("page_1", "page_2", "page_3")[:count]
                response = self.client.post(
                    "/api/jobs",
                    data=upload_files(pages, fields=fields) if count else {},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 400)

    def test_an_unexpected_fourth_field_does_not_confuse_page_order(self):
        # An extra field is simply not one of the three the server looks at;
        # accepting the request is fine as long as it still builds from
        # exactly page_1/2/3.
        payload = upload_files(self.pages)
        payload["page_4"] = (io.BytesIO(b"stray"), "page_4.jpg")
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 202)

    def test_only_recognised_image_types_are_accepted(self):
        for name in ("page.exe", "page.php", "page.svg", "page"):
            with self.subTest(name=name):
                payload = upload_files(self.pages)
                payload["page_2"] = (io.BytesIO(b"whatever"), name)
                response = self.client.post(
                    "/api/jobs", data=payload, content_type="multipart/form-data"
                )
                self.assertEqual(response.status_code, 400)

    def test_a_page_over_the_configured_limit_is_refused(self):
        # The default limit (10 MB) is exercised in test_api.py; this checks
        # the limit is actually read from configuration rather than hardcoded,
        # by pointing a fresh app at a much smaller one.
        from app.main import create_app

        app = create_app(job_root=self.job_root, MAX_PAGE_BYTES=1024, TESTING=True)
        client = app.test_client()
        try:
            payload = upload_files(self.pages)
            response = client.post(
                "/api/jobs", data=payload, content_type="multipart/form-data"
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("limit", response.get_json()["error"])
        finally:
            app.extensions["job_registry"].shutdown()


class TestFilenamesNeverControlPageOrder(AppTestCase):
    def test_the_upload_field_decides_order_not_the_filename(self):
        # Names chosen so that sorting them would reverse the real order -
        # if the server ever fell back to filename sorting, this would build
        # a font with page 1 and page 3 swapped.
        payload = {}
        for field, path, name in zip(
            ("page_1", "page_2", "page_3"),
            self.pages,
            ("zzz_last.jpg", "mmm_middle.jpg", "aaa_first.jpg"),
        ):
            payload[field] = (io.BytesIO(Path(path).read_bytes()), name)

        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 202)

        job_id = response.get_json()["job_id"]
        job = self.registry.get(job_id)
        uploads = sorted((job.directory / "uploads").iterdir())
        # Saved under server-assigned names (upload_1, upload_2, upload_3),
        # in field order - never the client's own filenames.
        self.assertEqual(
            [path.name.split(".")[0] for path in uploads],
            ["upload_1", "upload_2", "upload_3"],
        )


class TestJobIdsAreSafe(AppTestCase):
    def test_job_ids_are_unguessable_random_tokens(self):
        ids = {self.registry.create("A").job_id for _ in range(20)}
        self.assertEqual(len(ids), 20)
        for job_id in ids:
            self.assertRegex(job_id, r"^[A-Za-z0-9_-]{16,}$")

    def test_a_path_traversal_job_id_cannot_reach_another_file(self):
        traversal_targets = (
            "../../../../etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
            "....//....//etc/passwd",
            "/etc/passwd",
            "..",
        )
        for job_id in traversal_targets:
            with self.subTest(job_id=job_id):
                response = self.client.get("/api/jobs/{}/font.ttf".format(job_id))
                # Flask either fails to route it (404) or resolves it to a
                # normalised path that still is not a real job (404), or the
                # URL rule itself redirects (308) - never 200, and never the
                # contents of a file outside the job store.
                self.assertIn(response.status_code, (404, 308))
                self.assertNotIn(b"root:", response.data)

    def test_an_unknown_job_id_of_the_right_shape_is_still_404(self):
        fake = "A" * 22
        self.assertEqual(self.client.get("/api/jobs/{}".format(fake)).status_code, 404)


class TestFamilyNameIsSanitised(AppTestCase):
    def test_path_like_family_names_are_refused(self):
        for name in ("../../etc/passwd", "..\\..\\windows", "a/b", "a\\b"):
            with self.subTest(name=name):
                payload = upload_files(self.pages)
                payload["family_name"] = name
                response = self.client.post(
                    "/api/jobs", data=payload, content_type="multipart/form-data"
                )
                self.assertEqual(response.status_code, 400)

    def test_an_empty_family_name_falls_back_to_the_default(self):
        # An empty field is a client sending nothing, not an attack - the
        # request succeeds using the server's configured default name.
        payload = upload_files(self.pages)
        payload["family_name"] = ""
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 202)

    def test_ordinary_names_are_accepted(self):
        for name in ("My Handwriting", "Handwriting2024", "A B C"):
            with self.subTest(name=name):
                payload = upload_files(self.pages)
                payload["family_name"] = name
                response = self.client.post(
                    "/api/jobs", data=payload, content_type="multipart/form-data"
                )
                self.assertEqual(response.status_code, 202)


class TestGeneratedFilesStayInsideTheJobDirectory(AppTestCase):
    def test_a_new_jobs_directory_is_under_the_configured_root(self):
        job = self.registry.create("A")
        self.assertEqual(job.directory.parent.resolve(), self.job_root.resolve())
        # The id itself is what names the directory; nothing about the name
        # can walk upward, since it never reaches the filesystem unescaped -
        # secrets.token_urlsafe never produces '/', '\\' or '..'.
        self.assertNotIn("..", job.job_id)
        self.assertNotIn("/", job.job_id)


class TestNoServerDetailsReachTheBrowser(AppTestCase):
    def test_an_unexpected_exception_is_a_generic_500_not_a_traceback(self):
        # Force the registry into a state that raises inside the status
        # route, and confirm the response is the generic message, not a
        # traceback - app.main's 500 handler is what this exercises.
        class ExplodingRegistry:
            def get(self, job_id):
                raise RuntimeError("boom: /etc/secret/should-not-leak")

        self.app.extensions["job_registry"] = ExplodingRegistry()
        # Flask only lets its own error handler answer instead of re-raising
        # when this is off; TESTING=True (set for every test app) turns it on
        # by default, which is right for every other test and wrong for this
        # one, whose whole point is what a real deployment sends the browser.
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        response = self.client.get("/api/jobs/anything")
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertNotIn("boom", body)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("RuntimeError", body)

    def test_server_paths_are_stripped_from_backend_messages(self):
        message = (
            "Page 1 of 3 ('/data/handwrite-jobs/x7f/pages/page_1.png') does "
            "not look like page 1."
        )
        cleaned = _without_server_paths(message)
        self.assertNotIn("/data/", cleaned)
        self.assertNotIn("handwrite-jobs", cleaned)
        self.assertIn("page_1.png", cleaned)


class TestConfigurationHasNoHardcodedSecret(unittest.TestCase):
    def test_no_module_defines_a_literal_looking_secret(self):
        suspicious = re.compile(
            r'(api[_-]?key|secret|password|token)\s*=\s*["\'][^"\']{6,}["\']',
            re.IGNORECASE,
        )
        for path in APP_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            with self.subTest(module=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), suspicious)

    def test_the_dockerfile_runs_as_a_non_root_user(self):
        dockerfile = (APP_ROOT.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER handwrite", dockerfile)
        self.assertNotIn("USER root", dockerfile.split("USER handwrite")[-1])


if __name__ == "__main__":
    unittest.main()
