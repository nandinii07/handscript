"""The HTTP surface, exercised end to end against the real backend."""

import io
import unittest
from pathlib import Path

from app.tests.conftest import (
    NEEDS_FONT_TOOLS,
    AppTestCase,
    rotate,
    upload_files,
)


class TestCreateJobValidation(AppTestCase):
    """Everything rejected before a build is ever started."""

    def test_three_pages_are_required(self):
        response = self.client.post(
            "/api/jobs",
            data=upload_files(self.pages[:2], fields=("page_1", "page_2")),
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("page_3", response.get_json()["error"])

    def test_no_pages_at_all_is_refused(self):
        response = self.client.post("/api/jobs", data={})
        self.assertEqual(response.status_code, 400)

    def test_a_file_that_is_not_an_image_is_refused(self):
        payload = upload_files(self.pages)
        payload["page_2"] = (io.BytesIO(b"not an image"), "notes.txt")
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not an image", response.get_json()["error"])

    def test_an_oversized_page_is_refused(self):
        payload = upload_files(self.pages)
        payload["page_1"] = (
            io.BytesIO(b"\x89PNG" + b"0" * (11 * 1024 * 1024)),
            "big.png",
        )
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("limit", response.get_json()["error"])

    def test_an_empty_page_is_refused(self):
        payload = upload_files(self.pages)
        payload["page_3"] = (io.BytesIO(b""), "empty.png")
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 400)

    def test_a_silly_font_name_is_refused(self):
        payload = upload_files(self.pages)
        payload["family_name"] = "../../etc/passwd"
        response = self.client.post(
            "/api/jobs", data=payload, content_type="multipart/form-data"
        )
        self.assertEqual(response.status_code, 400)

    def test_a_rejected_upload_leaves_no_job_behind(self):
        self.client.post("/api/jobs", data={})
        self.assertEqual(self.registry.all_jobs(), [])


@NEEDS_FONT_TOOLS
class TestJobLifecycle(AppTestCase):
    def submit(self, pages=None):
        response = self.client.post(
            "/api/jobs",
            data=upload_files(pages or self.pages),
            content_type="multipart/form-data",
        )
        return response, response.get_json()

    def test_a_good_upload_is_accepted_and_builds(self):
        response, payload = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertIn(payload["status"], ("queued", "processing"))
        self.assertIsNone(payload["download_url"])

        _final, done = self.wait_for(payload["job_id"])
        self.assertEqual(done["status"], "completed")
        self.assertIsNone(done["error"])
        self.assertEqual(
            done["download_url"], "/api/jobs/{}/font.ttf".format(payload["job_id"])
        )

    def test_the_finished_font_downloads_as_a_ttf(self):
        _response, payload = self.submit()
        self.wait_for(payload["job_id"])

        download = self.client.get("/api/jobs/{}/font.ttf".format(payload["job_id"]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "font/ttf")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(download.data[:4], b"\x00\x01\x00\x00")

    def test_the_font_contains_every_character(self):
        import tempfile

        from handwrite.characters import ALL_CHARS
        from tests.fontmetrics import mapped_codepoints

        _response, payload = self.submit()
        self.wait_for(payload["job_id"])
        download = self.client.get("/api/jobs/{}/font.ttf".format(payload["job_id"]))

        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as handle:
            handle.write(download.data)
        mapped = mapped_codepoints(handle.name)
        self.assertEqual([c for c in ALL_CHARS if c not in mapped], [])

    def test_swapped_pages_fail_the_job_with_the_backend_message(self):
        first, second, third = self.pages
        _response, payload = self.submit([third, second, first])
        response, done = self.wait_for(payload["job_id"])

        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["error_type"], "PageValidationError")
        self.assertIn("does not look like page 1", done["error"])
        self.assertEqual(response.status_code, 422)

    def test_a_rotated_page_fails_the_job(self):
        turned = rotate(self.pages[0], 90, self.fixtures)
        _response, payload = self.submit([turned] + self.pages[1:])
        response, done = self.wait_for(payload["job_id"])

        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["error_type"], "PageValidationError")
        self.assertEqual(response.status_code, 422)

    def test_a_failed_job_has_no_font_to_download(self):
        first, second, third = self.pages
        _response, payload = self.submit([third, second, first])
        self.wait_for(payload["job_id"])

        download = self.client.get("/api/jobs/{}/font.ttf".format(payload["job_id"]))
        self.assertEqual(download.status_code, 409)


class TestJobAccess(AppTestCase):
    def test_an_unknown_job_is_not_found(self):
        self.assertEqual(self.client.get("/api/jobs/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/nope/font.ttf").status_code, 404)

    def test_a_job_id_cannot_reach_the_filesystem(self):
        for job_id in ("../../etc/passwd", "..%2f..%2fetc", "/etc/passwd"):
            with self.subTest(job_id=job_id):
                response = self.client.get("/api/jobs/{}/font.ttf".format(job_id))
                self.assertIn(response.status_code, (404, 308))

    def test_an_unfinished_job_will_not_serve_a_font(self):
        job = self.registry.create("Pending")
        response = self.client.get("/api/jobs/{}/font.ttf".format(job.job_id))
        self.assertEqual(response.status_code, 409)


class TestPreview(AppTestCase):
    def test_it_renders_supported_structures(self):
        for text, expected in (
            ("E = mc^2", '<span class="sup">2</span>'),
            ("H_2O", '<span class="sub">2</span>'),
            ("{a}/{b}", '<span class="frac">'),
            ("√{x+1}", '<span class="radicand">'),
            ("Σ__{i=1}^^{n}", '<span class="stack">'),
        ):
            with self.subTest(text=text):
                response = self.client.post("/api/preview", json={"text": text})
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertIsNone(payload["error"])
                self.assertIn(expected, payload["html"])

    def test_malformed_notation_comes_back_inline(self):
        response = self.client.post("/api/preview", json={"text": "{a}/{b"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["html"])
        self.assertIn("Unclosed", payload["error"])

    def test_an_unknown_job_is_rejected(self):
        response = self.client.post(
            "/api/preview", json={"text": "x^2", "job_id": "nope"}
        )
        self.assertEqual(response.status_code, 404)

    def test_text_must_be_a_string(self):
        response = self.client.post("/api/preview", json={"text": 42})
        self.assertEqual(response.status_code, 400)


@NEEDS_FONT_TOOLS
class TestPreviewAgainstAFont(AppTestCase):
    def test_missing_glyphs_are_reported(self):
        response = self.client.post(
            "/api/jobs",
            data=upload_files(self.pages),
            content_type="multipart/form-data",
        )
        job_id = response.get_json()["job_id"]
        self.wait_for(job_id)

        clean = self.client.post(
            "/api/preview", json={"text": "E = mc^2", "job_id": job_id}
        ).get_json()
        self.assertEqual(clean["missing"], [])

        uncovered = self.client.post(
            "/api/preview", json={"text": "x 漢", "job_id": job_id}
        ).get_json()
        self.assertEqual(uncovered["missing"], ["漢"])


class TestTemplate(AppTestCase):
    def test_it_serves_the_committed_four_page_training_sheet(self):
        response = self.client.get("/api/template.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertEqual(response.data[:5], b"%PDF-")
        self.assertEqual(response.data.count(b"/Type /Page\n"), 4)

    def test_it_is_the_file_from_the_repository(self):
        committed = Path(self.app.config["TEMPLATE_PATH"]).read_bytes()
        self.assertEqual(self.client.get("/api/template.pdf").data, committed)


class TestHealth(AppTestCase):
    def test_health_endpoint(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)


if __name__ == "__main__":
    unittest.main()
