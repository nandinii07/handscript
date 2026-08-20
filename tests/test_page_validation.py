"""A scan must be the page it is being read as, the right way up.

Page 1 and page 3 both hold eighty boxes in an eight by ten grid, so
swapping them used to be accepted: every box was found, every folder was
written, and each character was filed under its neighbour's codepoint. The
font built, installed, and was entirely wrong. A page turned upside down did
the same thing.

Nothing here reads the printed characters. Three things about the form give
the page away on their own: the shape of the grid, the heading printed above
it, and how many boxes each page leaves crossed out at the end - none on page
1, seven on page 2, two on page 3.
"""

import os
import shutil
import tempfile
import unittest

from PIL import Image

from handwrite import formgen
from handwrite.characters import PAGES, ALL_CHARS
from handwrite.sheettopng import SHEETtoPNG, PageValidationError

from tests.test_sheettopng import render_synthetic_page, CONFIG


def rotated(path, degrees, directory):
    """Save a rotated copy of a page and return its path."""
    output = os.path.join(directory, "rotated_{}.png".format(degrees))
    Image.open(path).rotate(degrees, expand=True).save(output)
    return output


class TestPageValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.pages = [
            render_synthetic_page(page, index) for index, page in enumerate(PAGES)
        ]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory)

    def setUp(self):
        self.output = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.output)

    def convert(self, sheets):
        SHEETtoPNG().convert_pages(sheets, self.output, CONFIG)

    def test_correct_order_is_accepted(self):
        self.convert(self.pages)
        produced = sorted(int(name) for name in os.listdir(self.output))
        self.assertEqual(produced, sorted(ALL_CHARS))

    def test_pages_one_and_three_swapped_are_rejected(self):
        first, second, third = self.pages
        with self.assertRaises(PageValidationError) as caught:
            self.convert([third, second, first])
        self.assertIn("does not look like page 1", str(caught.exception))

    def test_page_two_in_the_wrong_position_is_rejected(self):
        first, second, third = self.pages
        with self.assertRaises(PageValidationError):
            self.convert([second, first, third])

    def test_page_three_in_position_two_is_rejected(self):
        first, second, third = self.pages
        with self.assertRaises(PageValidationError):
            self.convert([first, third, second])

    def test_a_page_rotated_90_is_rejected(self):
        turned = rotated(self.pages[0], 90, self.output)
        with self.assertRaises(PageValidationError) as caught:
            self.convert([turned] + self.pages[1:])
        self.assertIn("grid", str(caught.exception))

    def test_a_page_rotated_270_is_rejected(self):
        turned = rotated(self.pages[0], 270, self.output)
        with self.assertRaises(PageValidationError):
            self.convert([turned] + self.pages[1:])

    def test_a_page_rotated_180_is_rejected(self):
        # Upside down keeps the grid shape, so the heading gives it away.
        turned = rotated(self.pages[0], 180, self.output)
        with self.assertRaises(PageValidationError) as caught:
            self.convert([turned] + self.pages[1:])
        self.assertIn("upside down", str(caught.exception))

    def test_the_last_page_upside_down_is_rejected(self):
        turned = rotated(self.pages[2], 180, self.output)
        with self.assertRaises(PageValidationError):
            self.convert(self.pages[:2] + [turned])

    def test_nothing_is_extracted_when_validation_fails(self):
        """The guard has to run before any character is written.

        Otherwise a rejected run still leaves a directory of wrongly filed
        images for the next stage to build a font from.
        """
        first, second, third = self.pages
        for sheets in (
            [third, second, first],
            [rotated(first, 180, self.output)] + self.pages[1:],
        ):
            with self.subTest(sheets=sheets):
                target = tempfile.mkdtemp()
                try:
                    with self.assertRaises(PageValidationError):
                        SHEETtoPNG().convert_pages(sheets, target, CONFIG)
                    self.assertEqual(os.listdir(target), [])
                finally:
                    shutil.rmtree(target)

    def test_the_error_names_the_page_and_the_file(self):
        first, second, third = self.pages
        with self.assertRaises(PageValidationError) as caught:
            self.convert([third, second, first])
        message = str(caught.exception)
        self.assertIn("Page 1 of 3", message)
        self.assertIn(os.path.basename(third), message)
        self.assertIn("page order", message)


class TestValidationOfIndividualPages(unittest.TestCase):
    """validate_page on its own, so each signal can be checked in isolation."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.pages = [
            render_synthetic_page(page, index) for index, page in enumerate(PAGES)
        ]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory)

    def test_each_page_validates_in_its_own_slot(self):
        for index, (sheet, page) in enumerate(zip(self.pages, PAGES), start=1):
            with self.subTest(page=index):
                SHEETtoPNG().validate_page(sheet, page, index, len(PAGES))

    def test_no_page_validates_in_another_slot(self):
        for index, page in enumerate(PAGES, start=1):
            for other, sheet in enumerate(self.pages, start=1):
                if other == index:
                    continue
                with self.subTest(page=index, sheet=other):
                    with self.assertRaises(PageValidationError):
                        SHEETtoPNG().validate_page(sheet, page, index, len(PAGES))

    def test_trailing_empty_boxes_identify_the_page(self):
        # The counts the guard relies on: page 1 fills every box, page 2
        # leaves seven, page 3 leaves two.
        self.assertEqual(
            [page["cols"] * page["rows"] - len(page["chars"]) for page in PAGES],
            [0, 7, 2],
        )


class TestLegacyWorkflowUnaffected(unittest.TestCase):
    """The original single-sheet workflow must keep working untouched."""

    def setUp(self):
        self.output = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.output)

    def test_single_sheet_conversion_is_not_validated(self):
        # The one page form is the old workflow, and its scans predate the
        # heading and crossed-box conventions the guard relies on.
        sheet = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_data",
            "sheettopng",
            "excellent.jpg",
        )
        SHEETtoPNG().convert(sheet, self.output, CONFIG)
        self.assertTrue(os.listdir(self.output))


if __name__ == "__main__":
    unittest.main()
