"""Glyphs from different form pages must end up the same size.

How large a character comes out depends on how much of its printed box the
writer filled, and that differs from page to page. Measured on a real filled
form: page 1 glyphs had a median ink height of 434 units sitting 66 above the
baseline, while pages 2 and 3 came in around 300 units sitting nearly 300
above it. Greek and mathematical characters therefore printed small and
floating next to the Latin ones.

Each page after the first is corrected by one uniform scale plus a vertical
shift, shared by every glyph on that page.
"""

import os
import json
import shutil
import tempfile
import unittest

from handwrite import SHEETtoPNG, PNGtoSVG, SVGtoTTF
from handwrite.svgtottf import scale_plan
from handwrite.characters import PAGES, ALL_CHARS, EXISTING_CHARS

from tests.fontmetrics import mapped_codepoints, glyph_bounds
from tests.test_sheettopng import render_synthetic_page, CONFIG

NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)

PACKAGE_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "handwrite",
    "default.json",
)


def median_ink_height(bounds, codepoints):
    heights = sorted(
        bounds[c][3] - bounds[c][1]
        for c in codepoints
        if c in bounds and bounds[c][3] > bounds[c][1]
    )
    return heights[len(heights) // 2]


class TestScalePlan(unittest.TestCase):
    """The decision itself, as plain arithmetic - no font needed."""

    def test_first_page_is_never_corrected(self):
        plan = scale_plan([(400, 60), (400, 60)])
        self.assertEqual([entry[0] for entry in plan], [1])

    def test_factor_brings_a_page_to_the_reference_height(self):
        plan = scale_plan([(400, 50), (200, 300)])
        index, factor, from_bottom, to_bottom = plan[0]
        self.assertEqual(index, 1)
        self.assertAlmostEqual(factor, 2.0)
        self.assertEqual(from_bottom, 300)
        self.assertEqual(to_bottom, 50)

    def test_each_page_gets_its_own_factor(self):
        # Pages are corrected independently: one written small and one
        # written nearly right must not share a correction.
        plan = scale_plan([(400, 0), (200, 0), (320, 0)])
        self.assertAlmostEqual(plan[0][1], 2.0)
        self.assertAlmostEqual(plan[1][1], 1.25)

    def test_a_page_already_the_right_size_is_left_alone(self):
        plan = scale_plan([(400, 60), (400, 60)])
        self.assertAlmostEqual(plan[0][1], 1.0)

    def test_absurd_corrections_are_refused(self):
        # Ten times too small is not handwriting written smaller, it is a
        # measurement of something else - forcing it would wreck the font.
        self.assertEqual(scale_plan([(400, 0), (40, 0)]), [])
        self.assertEqual(scale_plan([(40, 0), (400, 0)]), [])

    def test_the_limit_is_configurable(self):
        self.assertEqual(len(scale_plan([(400, 0), (100, 0)], limit=5.0)), 1)
        self.assertEqual(scale_plan([(400, 0), (100, 0)], limit=2.0), [])

    def test_unmeasurable_pages_are_skipped(self):
        self.assertEqual(scale_plan([None, (200, 0)]), [])
        plan = scale_plan([(400, 0), None, (200, 0)])
        self.assertEqual([entry[0] for entry in plan], [2])

    def test_a_single_page_needs_no_plan(self):
        self.assertEqual(scale_plan([(400, 60)]), [])
        self.assertEqual(scale_plan([]), [])

    def test_zero_height_pages_are_skipped(self):
        self.assertEqual(scale_plan([(400, 0), (0, 0)]), [])


@NEEDS_FONT_TOOLS
class TestNormalisedFont(unittest.TestCase):
    """Two fonts from one set of outlines: normalised, and left as traced."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.mkdtemp()
        cls.characters = os.path.join(cls.temp, "characters")

        pages = [render_synthetic_page(page, i) for i, page in enumerate(PAGES)]
        SHEETtoPNG().convert_pages(pages, cls.characters, CONFIG)
        PNGtoSVG().convert(directory=cls.characters)

        groups = [page["chars"] for page in PAGES]
        converter = SVGtoTTF()
        converter.convert(cls.characters, cls.temp, PACKAGE_CONFIG, {"filename": "Raw"})
        converter.convert(
            cls.characters,
            cls.temp,
            PACKAGE_CONFIG,
            {"filename": "Normalised"},
            groups,
        )

        cls.raw = glyph_bounds(os.path.join(cls.temp, "Raw.ttf"))
        cls.normalised_path = os.path.join(cls.temp, "Normalised.ttf")
        cls.normalised = glyph_bounds(cls.normalised_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp)

    def test_the_font_still_contains_every_character(self):
        mapped = mapped_codepoints(self.normalised_path)
        missing = [chr(c) for c in ALL_CHARS if c not in mapped]
        self.assertEqual(missing, [], "font is missing: {}".format(missing))

    def test_reference_page_glyphs_are_untouched(self):
        # Page 1 is the reference, so Latin letters and digits must come out
        # of both builds identical.
        for codepoint in EXISTING_CHARS:
            if codepoint in self.raw and codepoint in self.normalised:
                with self.subTest(character=chr(codepoint)):
                    self.assertEqual(self.raw[codepoint], self.normalised[codepoint])

    def test_later_pages_end_up_the_size_of_the_first(self):
        reference = median_ink_height(self.normalised, PAGES[0]["chars"])
        for index, page in enumerate(PAGES[1:], start=2):
            with self.subTest(page=index):
                height = median_ink_height(self.normalised, page["chars"])
                self.assertAlmostEqual(
                    height / reference,
                    1.0,
                    delta=0.15,
                    msg="page {} is {:.0%} of page 1".format(index, height / reference),
                )

    def test_later_pages_sit_on_the_same_baseline(self):
        def median_bottom(bounds, codepoints):
            bottoms = sorted(
                bounds[c][1]
                for c in codepoints
                if c in bounds and bounds[c][3] > bounds[c][1]
            )
            return bottoms[len(bottoms) // 2]

        reference = median_bottom(self.normalised, PAGES[0]["chars"])
        for index, page in enumerate(PAGES[1:], start=2):
            with self.subTest(page=index):
                bottom = median_bottom(self.normalised, page["chars"])
                # Within a tenth of an em of the reference footing.
                self.assertLess(abs(bottom - reference), 100)

    def test_aspect_ratios_survive(self):
        """Scaling must not stretch anybody.

        Tiny glyphs are excluded: the bounding box stored in the font is
        rounded to whole units, which is a large relative error on a mark
        forty units across and says nothing about the transform.
        """
        for codepoint in ALL_CHARS:
            if codepoint not in self.raw or codepoint not in self.normalised:
                continue
            raw_w = self.raw[codepoint][2] - self.raw[codepoint][0]
            raw_h = self.raw[codepoint][3] - self.raw[codepoint][1]
            new_w = self.normalised[codepoint][2] - self.normalised[codepoint][0]
            new_h = self.normalised[codepoint][3] - self.normalised[codepoint][1]
            if min(raw_w, raw_h) < 60 or min(new_w, new_h) <= 0:
                continue
            with self.subTest(character=chr(codepoint)):
                self.assertAlmostEqual(
                    (new_w / new_h) / (raw_w / raw_h), 1.0, delta=0.10
                )

    def test_nothing_is_scaled_off_the_top_of_the_em(self):
        with open(PACKAGE_CONFIG) as config_file:
            ascent = json.load(config_file)["props"]["ascent"]
        tallest = max(bounds[3] for bounds in self.normalised.values())
        self.assertLessEqual(tallest, ascent)

    def test_without_groups_nothing_is_normalised(self):
        # The plain call has to keep building fonts exactly as before.
        page_two = PAGES[1]["chars"]
        self.assertNotAlmostEqual(
            median_ink_height(self.raw, page_two)
            / median_ink_height(self.raw, PAGES[0]["chars"]),
            1.0,
            delta=0.05,
        )


if __name__ == "__main__":
    unittest.main()
