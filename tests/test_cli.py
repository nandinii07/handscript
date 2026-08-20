import os
import shutil
import tempfile
import unittest
import subprocess

from handwrite.characters import EXISTING_CHARS, ALL_CHARS, PAGES

from tests.test_sheettopng import render_synthetic_page
from tests.fontmetrics import mapped_codepoints

# The font stages shell out to potrace and FontForge. Where those are not
# installed the pipeline cannot run at all, so skip rather than fail - but the
# tests below that check for *clear errors* still run everywhere.
NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)


def run_handwrite(*arguments):
    """Run the CLI and return the completed process (never raises)."""
    return subprocess.run(
        ["handwrite"] + list(arguments), capture_output=True, text=True
    )


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.file_dir = os.path.dirname(os.path.abspath(__file__))
        self.temp_dir = tempfile.mkdtemp()
        self.sheets_dir = os.path.join(self.file_dir, "test_data", "sheettopng")
        self.excellent = os.path.join(self.sheets_dir, "excellent.jpg")
        self.config_dir = os.path.join(self.file_dir, "test_data", "config_data")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @NEEDS_FONT_TOOLS
    def test_single_input(self):
        # Check working with excellent input and no optional parameters
        result = run_handwrite(self.excellent, self.temp_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "MyFont.ttf")))

    @NEEDS_FONT_TOOLS
    def test_single_input_with_optional_parameters(self):
        # Check working with optional parameters
        result = run_handwrite(
            self.excellent,
            self.temp_dir,
            "--directory",
            self.temp_dir,
            "--config",
            os.path.join(self.config_dir, "default.json"),
            "--filename",
            "CustomFont",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for i in EXISTING_CHARS:
            for suffix in [".bmp", ".png", ".svg"]:
                self.assertTrue(
                    os.path.exists(os.path.join(self.temp_dir, f"{i}", f"{i}{suffix}"))
                )
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, "CustomFont.ttf")))

    @NEEDS_FONT_TOOLS
    def test_extended_two_page_form_builds_every_glyph(self):
        """End to end over both form pages: 113 characters in, one font out."""
        pages_dir = os.path.join(self.temp_dir, "pages")
        os.makedirs(pages_dir)
        for index, page in enumerate(PAGES):
            shutil.copy(
                render_synthetic_page(page, index),
                os.path.join(pages_dir, "page_{}.png".format(index + 1)),
            )

        work_dir = os.path.join(self.temp_dir, "work")
        result = run_handwrite(
            pages_dir, self.temp_dir, "--directory", work_dir, "--filename", "Extended"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        for codepoint in ALL_CHARS:
            self.assertTrue(
                os.path.exists(
                    os.path.join(work_dir, str(codepoint), f"{codepoint}.svg")
                ),
                "no traced outline for {!r}".format(chr(codepoint)),
            )

        font = os.path.join(self.temp_dir, "Extended.ttf")
        self.assertTrue(os.path.exists(font))

        # The .ttf is the product, so check the font itself contains every
        # character rather than trusting that the SVGs made it in.
        mapped = mapped_codepoints(font)
        missing = [chr(c) for c in ALL_CHARS if c not in mapped]
        self.assertEqual(missing, [], "font is missing: {}".format(missing))

    def test_directory_with_wrong_page_count_fails_clearly(self):
        # test_data/sheettopng holds a single page-1 scan, but a directory is
        # read as the pages of one form, which needs one image per page.
        result = run_handwrite(self.sheets_dir, self.temp_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one per form page", result.stderr)

    def test_empty_directory_fails_clearly(self):
        empty = os.path.join(self.temp_dir, "empty")
        os.makedirs(empty)
        result = run_handwrite(empty, self.temp_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No page image files found", result.stderr)

    def test_config_directory_fails_clearly(self):
        result = run_handwrite(
            self.excellent, self.temp_dir, "--config", self.config_dir
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("should not be a directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
