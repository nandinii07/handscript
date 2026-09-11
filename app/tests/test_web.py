"""The screens, and the one thing the frontend must not get wrong.

The frontend is a client of the JSON API and nothing more: it does not parse
notation, build fonts or inspect glyphs. These tests check the pages render,
that they point at the real endpoints, and that the handful of numbers the
stylesheet has to share with the backend still agree with it.
"""

import re
import unittest
from pathlib import Path

from app.tests.conftest import NEEDS_FONT_TOOLS, AppTestCase, upload_files

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
TEMPLATES = APP_ROOT / "templates"


class TestLanding(AppTestCase):
    def test_it_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Turn your handwriting", page)
        self.assertIn("Create My Font", page)
        self.assertIn("Download Template", page)

    def test_it_links_to_the_real_template_endpoint(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/api/template.pdf"', page)

    def test_it_shows_a_specimen_in_a_generated_font(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("@font-face", page)
        self.assertIn("/demo-font.ttf", page)

        font = self.client.get("/demo-font.ttf")
        self.assertEqual(font.status_code, 200)
        self.assertEqual(font.data[:4], b"\x00\x01\x00\x00")

    def test_it_does_not_claim_to_use_ai(self):
        page = self.client.get("/").get_data(as_text=True).lower()
        for word in (" ai ", "artificial intelligence", "machine learning", "neural"):
            self.assertNotIn(word, page)


class TestTemplatePage(AppTestCase):
    def test_it_loads_with_the_instructions_that_matter(self):
        page = self.client.get("/template").get_data(as_text=True)
        self.assertEqual(self.client.get("/template").status_code, 200)
        for phrase in (
            "100% scale",
            "dark pen",
            "crossed-out boxes",
            "Do not crop",
            "in order",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, page)

    def test_it_warns_about_the_greek_capitals(self):
        page = self.client.get("/template").get_data(as_text=True)
        # Collapsed, because the sentence wraps in the template source.
        flat = " ".join(page.split())
        self.assertIn("look exactly like Latin letters", flat)
        self.assertIn("Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ", flat)

    def test_the_download_serves_the_committed_pdf(self):
        response = self.client.get("/api/template.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:5], b"%PDF-")
        self.assertEqual(response.data.count(b"/Type /Page\n"), 4)


class TestUploadPage(AppTestCase):
    def test_it_has_three_slots_and_a_disabled_button(self):
        page = self.client.get("/upload").get_data(as_text=True)
        self.assertEqual(page.count('class="slot"'), 3)
        for number in (1, 2, 3):
            self.assertIn('data-slot="{}"'.format(number), page)
        self.assertIn('id="build" disabled', page.replace("\n", " "))

    def test_it_warns_about_page_order(self):
        page = self.client.get("/upload").get_data(as_text=True)
        self.assertIn("Upload your pages in order", page)

    def test_the_button_only_enables_with_three_pages(self):
        script = (STATIC / "js" / "upload.js").read_text(encoding="utf-8")
        self.assertIn("chosen[1] && chosen[2] && chosen[3]", script)

    def test_it_posts_to_the_real_endpoint_with_page_fields(self):
        script = (STATIC / "js" / "upload.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/jobs"', script)
        for field in ("page_1", "page_2", "page_3"):
            self.assertIn('payload.append("{}"'.format(field), script)


class TestBuildPage(AppTestCase):
    def test_an_unknown_job_is_not_found(self):
        self.assertEqual(self.client.get("/build/nope").status_code, 404)

    def test_it_shows_the_real_stages(self):
        job = self.registry.create("Pending")
        page = self.client.get("/build/{}".format(job.job_id)).get_data(as_text=True)
        for stage in (
            "Pages uploaded",
            "Validating handwriting pages",
            "Building your font",
            "Finalising font",
        ):
            with self.subTest(stage=stage):
                self.assertIn(stage, page)

    def test_it_polls_the_real_status_endpoint(self):
        script = (STATIC / "js" / "build.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/jobs/" + jobId)', script)

    def test_it_invents_no_progress_percentage(self):
        script = (STATIC / "js" / "build.js").read_text(encoding="utf-8")
        self.assertNotIn("%", script.replace("100%", ""))
        self.assertNotIn("progress-bar", script)


class TestStudioAccess(AppTestCase):
    def test_an_unknown_job_is_not_found(self):
        self.assertEqual(self.client.get("/studio/nope").status_code, 404)

    def test_an_unfinished_job_is_not_the_studio(self):
        job = self.registry.create("Pending")
        response = self.client.get("/studio/{}".format(job.job_id))
        self.assertEqual(response.status_code, 409)
        self.assertIn("Not ready yet", response.get_data(as_text=True))


@NEEDS_FONT_TOOLS
class TestStudio(AppTestCase):
    """The studio, reached the way a person reaches it."""

    def setUp(self):
        super().setUp()
        response = self.client.post(
            "/api/jobs",
            data=upload_files(self.pages),
            content_type="multipart/form-data",
        )
        self.job_id = response.get_json()["job_id"]
        self.wait_for(self.job_id)
        self.page = self.client.get("/studio/{}".format(self.job_id)).get_data(
            as_text=True
        )

    def test_the_font_is_loaded_through_font_face(self):
        self.assertIn("@font-face", self.page)
        self.assertIn('url("/api/jobs/{}/font.ttf")'.format(self.job_id), self.page)

    def test_ordinary_text_is_rendered_in_the_generated_font(self):
        # The text area and its output use the font directly; no request is
        # made per keystroke.
        self.assertIn('id="text-input"', self.page)
        self.assertIn('id="text-output"', self.page)
        self.assertIn('class="output hand"', self.page)
        script = (STATIC / "js" / "studio.js").read_text(encoding="utf-8")
        self.assertIn("textOutput.textContent = textInput.value", script)

    def test_the_download_button_points_at_this_job(self):
        self.assertIn(
            'href="/api/jobs/{}/font.ttf" download'.format(self.job_id), self.page
        )

    def test_it_shows_a_full_specimen(self):
        for label in (
            "Uppercase",
            "Lowercase",
            "Numbers",
            "Punctuation",
            "Greek small",
            "Greek capital",
            "Maths",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.page)

    def test_it_explains_how_to_install(self):
        self.assertIn("macOS", self.page)
        self.assertIn("Windows", self.page)
        self.assertIn("Font Book", self.page)

    def test_the_formula_preview_uses_the_api(self):
        script = (STATIC / "js" / "studio.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/preview"', script)
        self.assertIn("DEBOUNCE_MS = 250", script)

    def test_the_preview_endpoint_answers_for_this_job(self):
        response = self.client.post(
            "/api/preview", json={"text": "E = mc^2", "job_id": self.job_id}
        )
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn('<span class="sup">2</span>', payload["html"])
        self.assertEqual(payload["missing"], [])

    def test_bad_notation_comes_back_inline_for_the_page_to_show(self):
        payload = self.client.post(
            "/api/preview", json={"text": "{a}/{b", "job_id": self.job_id}
        ).get_json()
        self.assertIsNone(payload["html"])
        self.assertIn("Unclosed", payload["error"])
        self.assertIn('id="formula-error"', self.page)

    def test_missing_glyphs_come_back_for_the_page_to_warn_about(self):
        payload = self.client.post(
            "/api/preview", json={"text": "x 漢", "job_id": self.job_id}
        ).get_json()
        self.assertEqual(payload["missing"], ["漢"])
        self.assertIn('id="formula-missing"', self.page)
        script = (STATIC / "js" / "studio.js").read_text(encoding="utf-8")
        self.assertIn("Your font does not contain", script)


class TestFrontendIsOnlyAClient(unittest.TestCase):
    """The frontend must not grow its own copy of the backend."""

    def test_no_template_or_script_reimplements_the_parser(self):
        for path in list(STATIC.rglob("*.js")) + list(TEMPLATES.rglob("*.html")):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                # A client-side parser would need these; asking the API does not.
                self.assertNotIn("parseNotation", source)
                self.assertNotIn("SUPER_MARKER", source)
                self.assertNotIn("import handwrite", source)

    def test_the_notation_styles_match_the_backend(self):
        """The stylesheet repeats five numbers the renderer owns.

        The preview endpoint returns markup styled by these classes, so the
        two have to agree. They cannot be imported into a stylesheet, so they
        are compared here instead.
        """
        from handwrite.renderer import (
            RULE_THICKNESS,
            SCRIPT_SCALE,
            STACKED_SCALE,
            SUB_DROP,
            SUPER_RAISE,
        )

        css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")

        def rule(selector):
            match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
            self.assertIsNotNone(match, "no CSS rule for " + selector)
            return match.group(1)

        self.assertIn("font-size: {}em".format(SCRIPT_SCALE), rule(".sup"))
        self.assertIn("vertical-align: {}em".format(SUPER_RAISE), rule(".sup"))
        self.assertIn("font-size: {}em".format(SCRIPT_SCALE), rule(".sub"))
        self.assertIn("vertical-align: -{}em".format(SUB_DROP), rule(".sub"))
        self.assertIn("font-size: {}em".format(STACKED_SCALE), rule(".frac"))
        self.assertIn(
            "{}em solid currentColor".format(RULE_THICKNESS), rule(".frac .num")
        )
        self.assertIn(
            "{}em solid currentColor".format(RULE_THICKNESS),
            rule(".radical .radicand"),
        )


@NEEDS_FONT_TOOLS
class TestWholeJourney(AppTestCase):
    """Landing to download, in the order a person would do it."""

    def test_the_complete_flow(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/template").status_code, 200)
        self.assertEqual(self.client.get("/api/template.pdf").status_code, 200)
        self.assertEqual(self.client.get("/upload").status_code, 200)

        created = self.client.post(
            "/api/jobs",
            data=upload_files(self.pages),
            content_type="multipart/form-data",
        )
        self.assertEqual(created.status_code, 202)
        job_id = created.get_json()["job_id"]

        self.assertEqual(self.client.get("/build/{}".format(job_id)).status_code, 200)
        _response, done = self.wait_for(job_id)
        self.assertEqual(done["status"], "completed")

        studio = self.client.get("/studio/{}".format(job_id))
        self.assertEqual(studio.status_code, 200)

        preview = self.client.post(
            "/api/preview",
            json={"text": "{-b ± √{b^2-4ac}}/{2a}", "job_id": job_id},
        ).get_json()
        self.assertIn('<span class="frac">', preview["html"])
        self.assertIsNone(preview["error"])

        download = self.client.get("/api/jobs/{}/font.ttf".format(job_id))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data[:4], b"\x00\x01\x00\x00")

    def test_a_failed_build_shows_the_backend_message(self):
        first, second, third = self.pages
        created = self.client.post(
            "/api/jobs",
            data=upload_files([third, second, first]),
            content_type="multipart/form-data",
        )
        job_id = created.get_json()["job_id"]
        self.assertEqual(self.client.get("/build/{}".format(job_id)).status_code, 200)

        response, done = self.wait_for(job_id)
        self.assertEqual(response.status_code, 422)
        self.assertIn("does not look like page 1", done["error"])
        # The message keeps the useful part and loses the server's path.
        self.assertNotIn("Traceback", done["error"])
        self.assertNotIn("/var/", done["error"])
        self.assertNotIn("/tmp/", done["error"])
        self.assertIn("page_1.png", done["error"])

        self.assertEqual(self.client.get("/studio/{}".format(job_id)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
