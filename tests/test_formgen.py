"""Tests for generating the printable handwriting form.

The geometry of the grid is covered in test_sheettopng.py, because that is
where it has to agree with box detection. What is checked here is the part
that had no coverage at all: actually producing the PDF, and refusing to
produce a useless one when no available font can draw the labels.
"""

import os
import sys
import shutil
import tempfile
import unittest
import subprocess
from unittest import mock

from PIL import Image, ImageDraw

from handwrite import formgen
from handwrite.characters import PAGES, PAGE_3, ALL_CHARS

# A codepoint in the Private Use Area: no real font has a glyph for it, so a
# page asking for it can never be drawn.
UNDRAWABLE = 0xE000


class TestGenerateForm(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.output = os.path.join(self.directory, "form.pdf")

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_writes_a_pdf(self):
        returned = formgen.generate_form(self.output)

        self.assertEqual(returned, self.output)
        self.assertTrue(os.path.exists(self.output))
        with open(self.output, "rb") as pdf:
            self.assertEqual(pdf.read(5), b"%PDF-")
        self.assertGreater(os.path.getsize(self.output), 1000)

    def test_writes_one_page_per_form_page(self):
        formgen.generate_form(self.output)
        with open(self.output, "rb") as pdf:
            content = pdf.read()
        self.assertEqual(content.count(b"/Type /Page\n"), len(PAGES))

    def test_honours_a_custom_page_list(self):
        single = [{"cols": 2, "rows": 2, "chars": [ord("A"), ord("B")]}]
        formgen.generate_form(self.output, pages=single)

        with open(self.output, "rb") as pdf:
            self.assertEqual(pdf.read(5), b"%PDF-")

    def test_pages_are_a4_at_the_configured_dpi(self):
        # 8.27 x 11.69 inches is A4; the scanned form's geometry depends on it.
        self.assertEqual(formgen.PAGE_WIDTH, int(8.27 * formgen.DPI))
        self.assertEqual(formgen.PAGE_HEIGHT, int(11.69 * formgen.DPI))

    def test_drawn_page_is_the_expected_size(self):
        label_font, title_font = formgen.resolve_fonts(
            [chr(c) for c in PAGES[0]["chars"]]
        )
        page = formgen._draw_page(1, 2, PAGES[0], label_font, title_font)

        self.assertIsInstance(page, Image.Image)
        self.assertEqual(page.size, (formgen.PAGE_WIDTH, formgen.PAGE_HEIGHT))

    def test_boxes_are_actually_drawn_on_the_page(self):
        # Box detection depends on solid black borders being present, so a
        # page of pure white would silently break the whole pipeline.
        label_font, title_font = formgen.resolve_fonts(
            [chr(c) for c in PAGES[1]["chars"]]
        )
        page = formgen._draw_page(2, 2, PAGES[1], label_font, title_font).convert("L")

        dark = sum(1 for pixel in page.getdata() if pixel < 128)
        self.assertGreater(dark, 1000, "page 2 appears to be blank")


class TestLabelPlacement(unittest.TestCase):
    """Where a label's ink actually lands on the printed page.

    The underscore used to print as a detached rule near the bottom of the
    label band, far below its neighbours, and read as a stray line rather than
    as the name of the character to write.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = PAGE_3
        labels = [chr(c) for c in cls.page["chars"]]
        label_font, title_font = formgen.resolve_fonts(labels)
        cls.image = formgen._draw_page(3, 3, cls.page, label_font, title_font)
        cls.grey = cls.image.convert("L")

    def label_ink(self, character):
        """Return (top, bottom) of the label's ink, measured from its box."""
        index = self.page["chars"].index(ord(character))
        for box_index, x0, y0, x1, y1 in formgen.iter_boxes(self.page):
            if box_index != index:
                continue
            strip = self.grey.crop((x0, y1 + 1, x1, y1 + formgen.LABEL_HEIGHT))
            box = strip.point(lambda p: 255 if p < 128 else 0).getbbox()
            self.assertIsNotNone(box, "no label ink under {!r}".format(character))
            return box[1] + 1, box[3] + 1
        self.fail("{!r} is not on this page".format(character))

    def test_underscore_label_is_clear_of_the_box_border(self):
        top, _bottom = self.label_ink("_")
        self.assertGreaterEqual(top, 3, "underscore label touches the border")

    def test_underscore_label_sits_in_line_with_its_neighbours(self):
        # '*', '^' and '~' share row 5 with '_'. Comparing against real
        # neighbours keeps this honest if the label font ever changes.
        underscore = self.label_ink("_")
        centre = sum(underscore) / 2

        for neighbour in ("*", "^", "~"):
            with self.subTest(neighbour=neighbour):
                low, high = self.label_ink(neighbour)
                self.assertGreaterEqual(
                    centre,
                    low - 4,
                    "underscore sits above {!r}".format(neighbour),
                )
                self.assertLessEqual(
                    centre,
                    high + 4,
                    "underscore sits below {!r}".format(neighbour),
                )

    def test_underscore_label_stays_inside_the_label_band(self):
        # Drifting past the band would push it towards the next row of boxes.
        top, bottom = self.label_ink("_")
        self.assertLess(bottom, formgen.LABEL_HEIGHT)

    def test_ordinary_labels_are_not_moved(self):
        # The lift is meant to apply to the underscore alone; every other
        # glyph must be drawn exactly where it always was.
        label_font, _ = formgen.resolve_fonts(["A"])
        drawing = ImageDraw.Draw(Image.new("L", (10, 10)))
        for character in "AaΓ∫.,-~*^…":
            with self.subTest(character=character):
                bbox = drawing.textbbox((0, 0), character, font=label_font)
                self.assertEqual(formgen._below_baseline_lift(bbox, label_font), 0)

    def test_the_underscore_is_the_only_label_that_is_lifted(self):
        label_font, _ = formgen.resolve_fonts([chr(c) for c in ALL_CHARS])
        drawing = ImageDraw.Draw(Image.new("L", (10, 10)))
        lifted = [
            chr(c)
            for c in ALL_CHARS
            if formgen._below_baseline_lift(
                drawing.textbbox((0, 0), chr(c), font=label_font), label_font
            )
        ]
        self.assertEqual(lifted, ["_"])


class TestFormGenCommand(unittest.TestCase):
    """`python -m handwrite.formgen` is the documented way to make a form."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_module_entry_point_writes_a_pdf(self):
        output = os.path.join(self.directory, "cli_form.pdf")
        result = subprocess.run(
            [sys.executable, "-m", "handwrite.formgen", output],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(output))
        self.assertIn(output, result.stdout)
        with open(output, "rb") as pdf:
            self.assertEqual(pdf.read(5), b"%PDF-")

    def test_module_entry_point_rejects_an_unusable_font(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "handwrite.formgen",
                os.path.join(self.directory, "unused.pdf"),
                "--font",
                "/no/such/font.ttf",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No font available", result.stderr)


class TestFontResolution(unittest.TestCase):
    """The form is useless if the labels cannot be drawn, so say so loudly."""

    def test_resolves_a_font_for_the_real_character_set(self):
        labels = [chr(c) for page in PAGES for c in page["chars"]]
        label_font, title_font = formgen.resolve_fonts(labels)

        self.assertIsNotNone(label_font)
        self.assertIsNotNone(title_font)

    def test_raises_when_no_candidate_font_exists(self):
        with mock.patch.object(formgen, "FONT_CANDIDATES", []):
            with mock.patch.dict(os.environ, {formgen.FONT_ENV_VAR: ""}, clear=False):
                os.environ.pop(formgen.FONT_ENV_VAR, None)
                with self.assertRaises(formgen.FormFontNotFound):
                    formgen.resolve_fonts(["A"])

    def test_raises_when_the_font_cannot_draw_a_character(self):
        with self.assertRaises(formgen.FormFontNotFound) as caught:
            formgen.resolve_fonts(["A", chr(UNDRAWABLE)])
        self.assertIn("missing", str(caught.exception))

    def test_explicit_font_path_that_does_not_exist_is_reported(self):
        with self.assertRaises(formgen.FormFontNotFound):
            formgen.resolve_fonts(["A"], font_path="/no/such/font.ttf")

    def test_generate_form_refuses_a_page_it_cannot_label(self):
        undrawable_page = [{"cols": 2, "rows": 2, "chars": [UNDRAWABLE]}]
        with self.assertRaises(formgen.FormFontNotFound):
            formgen.generate_form(
                os.path.join(tempfile.mkdtemp(), "x.pdf"), pages=undrawable_page
            )


if __name__ == "__main__":
    unittest.main()
