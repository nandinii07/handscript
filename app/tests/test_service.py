"""The integration boundary: does the application drive the real backend?

Nothing here mocks the backend. A build in these tests runs the same page
validation, extraction, tracing and font generation that a real upload does,
and the assertions are about the font that comes out.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from app import service
from handwrite.characters import ALL_CHARS
from handwrite.notation import NotationError
from handwrite.sheettopng import PageValidationError

from app.tests.conftest import NEEDS_FONT_TOOLS, build_pages, rotate
from tests.fontmetrics import mapped_codepoints

SAMPLE_FONT = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "test_data"
    / "renderer"
    / "sample.ttf"
)


class TestServiceUsesTheRealBackend(unittest.TestCase):
    def test_service_imports_the_handwrite_api(self):
        import app.service as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertIn("from handwrite import", source)

    def test_it_calls_converters_rather_than_the_stages(self):
        # converters() is what runs page validation and passes the per-page
        # glyph groups to the font builder. Driving the stages by hand here
        # would mean reproducing that, and losing it silently if it changed.
        source = Path(service.__file__).read_text(encoding="utf-8")
        self.assertIn("converters(", source)
        self.assertNotIn("SHEETtoPNG(", source)
        self.assertNotIn("SVGtoTTF(", source)


@NEEDS_FONT_TOOLS
class TestBuildFont(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = Path(tempfile.mkdtemp())
        cls.pages = build_pages(cls.fixtures)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fixtures, ignore_errors=True)

    def setUp(self):
        self.job_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.job_dir, ignore_errors=True)

    def test_three_correct_pages_build_a_real_font(self):
        font = service.build_font(self.pages, self.job_dir, "TestHand")

        self.assertTrue(font.exists())
        self.assertEqual(font.name, "TestHand.ttf")
        mapped = mapped_codepoints(str(font))
        missing = [chr(c) for c in ALL_CHARS if c not in mapped]
        self.assertEqual(missing, [], "font is missing: {}".format(missing))

    def test_the_font_lands_inside_the_job_directory(self):
        font = service.build_font(self.pages, self.job_dir, "TestHand")
        self.assertEqual(font.parent, self.job_dir / "font")
        self.assertTrue((self.job_dir / "pages" / "page_1.png").exists())

    def test_pages_are_renamed_by_position_not_by_upload_name(self):
        # A client could call its files anything at all; the backend matches
        # scans to form pages by sorted filename, so the order has to come
        # from the caller.
        oddly_named = []
        for number, source in enumerate(self.pages, start=1):
            target = self.fixtures / "zzz_{}_{}.png".format(4 - number, number)
            shutil.copyfile(source, target)
            oddly_named.append(target)

        font = service.build_font(oddly_named, self.job_dir, "TestHand")
        self.assertTrue(font.exists())
        for number in (1, 2, 3):
            self.assertTrue(
                (self.job_dir / "pages" / "page_{}.png".format(number)).exists()
            )

    def test_swapped_pages_reach_the_backend_and_are_rejected(self):
        first, second, third = self.pages
        with self.assertRaises(PageValidationError) as caught:
            service.build_font([third, second, first], self.job_dir, "TestHand")
        self.assertIn("does not look like page 1", str(caught.exception))

    def test_a_rotated_page_is_rejected(self):
        turned = rotate(self.pages[0], 180, self.fixtures)
        with self.assertRaises(PageValidationError):
            service.build_font([turned] + self.pages[1:], self.job_dir, "TestHand")

    def test_nothing_is_built_when_validation_fails(self):
        """The guard must stop the build, not tidy up after it."""
        first, second, third = self.pages
        with self.assertRaises(PageValidationError):
            service.build_font([third, second, first], self.job_dir, "TestHand")

        font_dir = self.job_dir / "font"
        self.assertEqual(list(font_dir.glob("*.ttf")), [])

    def test_the_wrong_number_of_pages_is_refused(self):
        for pages in (self.pages[:2], self.pages + self.pages[:1]):
            with self.subTest(count=len(pages)):
                with self.assertRaises(ValueError):
                    service.build_font(pages, self.job_dir, "TestHand")

    def test_an_unreadable_image_type_is_refused(self):
        odd = self.fixtures / "page.txt"
        odd.write_text("not an image", encoding="utf-8")
        with self.assertRaises(ValueError):
            service.build_font([odd] + self.pages[1:], self.job_dir, "TestHand")


class TestPreviewHelpers(unittest.TestCase):
    def test_render_fragment_handles_every_supported_structure(self):
        cases = {
            "E = mc^2": '<span class="sup">2</span>',
            "H_2O": '<span class="sub">2</span>',
            "{a}/{b}": '<span class="frac">',
            "√{x+1}": '<span class="radicand">',
            "Σ__{i=1}^^{n}": '<span class="stack">',
            "v^^{→}": '<span class="over">',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(expected, service.render_fragment(text, SAMPLE_FONT))

    def test_malformed_notation_raises_for_the_caller_to_show(self):
        for text in ("x^", "{a}/{b", "x^^n"):
            with self.subTest(text=text):
                with self.assertRaises(NotationError):
                    service.render_fragment(text, SAMPLE_FONT)

    def test_coverage_reports_characters_the_font_lacks(self):
        self.assertEqual(service.coverage("E = mc^2", SAMPLE_FONT), [])
        self.assertEqual(service.coverage("x 漢", SAMPLE_FONT), ["漢"])


if __name__ == "__main__":
    unittest.main()
