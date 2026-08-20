import os
import shutil
import tempfile
import unittest

from PIL import Image, ImageDraw

from handwrite import formgen
from handwrite.sheettopng import SHEETtoPNG, SheetDetectionError, ALL_CHARS
from handwrite.characters import EXISTING_CHARS, NEW_CHARS, PAGES

CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_data",
    "config_data",
    "default.json",
)


def render_synthetic_page(page, page_index):
    """Draw a clean, computer-generated stand-in for a filled-in form page.

    Not meant to look like real handwriting - just enough ink in each box for
    contour detection and cropping to have something to find, so tests can run
    without a real scanned fixture image.

    The box positions come from `formgen` itself rather than being recomputed
    here, so this can never disagree with the form that is actually printed.
    The heading is drawn for the same reason: the real form prints one above
    the grid, and page validation uses it to tell an upright scan from an
    upside down one, so a stand-in without it would not be a stand-in.
    """
    chars = page["chars"]
    _, _, box_height = formgen.cell_geometry()

    try:
        label_font, title_font = formgen.resolve_fonts([chr(c) for c in chars])
    except formgen.FormFontNotFound as error:
        # No font on this machine can draw Greek/math labels, so there is no
        # way to fake a filled-in page. Nothing is broken - skip.
        raise unittest.SkipTest(str(error))
    ink_font = label_font.font_variant(size=int(box_height * 0.6))

    image = Image.new("RGB", (formgen.PAGE_WIDTH, formgen.PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    draw.text(
        (formgen.MARGIN, formgen.MARGIN // 2),
        "Handwrite - Page {} of {}".format(page_index + 1, len(PAGES)),
        fill="black",
        font=title_font,
    )

    for index, x0, y0, x1, y1 in formgen.iter_boxes(page):
        draw.rectangle([x0, y0, x1, y1], outline="black", width=2)
        if index < len(chars):
            char = chr(chars[index])
            bbox = draw.textbbox((0, 0), char, font=ink_font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(
                (
                    x0 + (x1 - x0 - text_w) // 2 - bbox[0],
                    y0 + (y1 - y0 - text_h) // 2 - bbox[1],
                ),
                char,
                fill="black",
                font=ink_font,
            )

    path = os.path.join(tempfile.mkdtemp(), "synthetic_page_{}.png".format(page_index))
    image.save(path)
    return path


class TestSHEETtoPNG(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.sheets_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_data" + os.sep + "sheettopng",
        )
        self.converter = SHEETtoPNG()

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_convert(self):
        # Single (legacy, page-1-only) sheet input. `convert()` defaults to
        # EXISTING_CHARS, so it should only ever produce the original
        # 80-character set, never the new Phase 1 characters.
        excellent_scan = os.path.join(self.sheets_path, "excellent.jpg")
        self.converter.convert(excellent_scan, self.directory, CONFIG)
        for i in EXISTING_CHARS:
            self.assertTrue(
                os.path.exists(os.path.join(self.directory, f"{i}", f"{i}.png"))
            )
        # None of the new (Phase 1) characters should have been produced.
        for i in NEW_CHARS:
            self.assertFalse(os.path.exists(os.path.join(self.directory, f"{i}")))

    def test_convert_pages(self):
        # Multi-page (extended) form input: one synthetically "filled" image
        # per page. Confirms every character in ALL_CHARS - old and new - ends
        # up in exactly one correctly-named folder.
        page_paths = [
            render_synthetic_page(page, index) for index, page in enumerate(PAGES)
        ]

        self.converter.convert_pages(page_paths, self.directory, CONFIG)

        produced = sorted(int(d) for d in os.listdir(self.directory))
        self.assertEqual(produced, sorted(ALL_CHARS))

    def test_convert_pages_wrong_sheet_count_raises(self):
        with self.assertRaises(ValueError):
            self.converter.convert_pages(["only_one_page.png"], self.directory, CONFIG)

    def test_a_directory_is_not_accepted_as_a_sheet(self):
        with self.assertRaises(IsADirectoryError):
            self.converter.convert(self.sheets_path, self.directory, CONFIG)

    def test_unreadable_sheet_raises_a_clear_error(self):
        missing = os.path.join(self.directory, "not_an_image.jpg")
        with self.assertRaises(SheetDetectionError) as caught:
            self.converter.convert(missing, self.directory, CONFIG)
        self.assertIn("Could not read", str(caught.exception))

    def test_too_few_boxes_raises_a_clear_error(self):
        # A page drawn with a 2x2 grid, then processed as if it were the full
        # 8x10 form: detection must say so rather than raising IndexError.
        blank = Image.new("RGB", (600, 600), "white")
        draw = ImageDraw.Draw(blank)
        for row in range(2):
            for col in range(2):
                x0, y0 = 50 + col * 250, 50 + row * 250
                draw.rectangle([x0, y0, x0 + 200, y0 + 200], outline="black", width=2)
        path = os.path.join(self.directory, "too_few.png")
        blank.save(path)

        with self.assertRaises(SheetDetectionError) as caught:
            self.converter.convert(path, self.directory, CONFIG)
        message = str(caught.exception)
        self.assertIn("expected 80", message)
        self.assertIn("threshold_value", message)


class TestFormGeometry(unittest.TestCase):
    """The printed form's geometry is part of the pipeline's correctness."""

    def test_every_page_uses_identically_sized_boxes(self):
        # PNGtoSVG scales each cropped box to a fixed 100x100 bitmap, so boxes
        # of different shapes would stretch page-2 glyphs by a different
        # amount than page-1 glyphs and the Greek/math characters would come
        # out visibly wider than the Latin ones.
        sizes = set()
        for page in PAGES:
            for _, x0, y0, x1, y1 in formgen.iter_boxes(page):
                sizes.add((x1 - x0, y1 - y0))
        self.assertEqual(len(sizes), 1, "boxes differ in size across pages")

    def test_boxes_stay_on_the_page(self):
        for page in PAGES:
            for _, x0, y0, x1, y1 in formgen.iter_boxes(page):
                self.assertGreaterEqual(x0, 0)
                self.assertGreaterEqual(y0, 0)
                self.assertLessEqual(x1, formgen.PAGE_WIDTH)
                self.assertLessEqual(y1, formgen.PAGE_HEIGHT)

    def test_page_grid_must_fit_the_reference_grid(self):
        oversized = {"cols": 9, "rows": 10, "chars": [65]}
        with self.assertRaises(ValueError):
            list(formgen.iter_boxes(oversized))

    def test_each_page_has_a_box_for_every_character(self):
        for page in PAGES:
            self.assertGreaterEqual(page["cols"] * page["rows"], len(page["chars"]))


if __name__ == "__main__":
    unittest.main()
