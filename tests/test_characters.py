"""Invariants of the character set itself.

This module is the single source of truth for "box number N on page P is
character X". Everything downstream - the printed form, box detection, the
glyph list in default.json - trusts it, so the properties it has to keep are
asserted here rather than assumed.
"""

import unittest

from handwrite.characters import (
    EXISTING_CHARS,
    NEW_CHARS,
    EXTENDED_CHARS,
    ALL_CHARS,
    PAGE_1,
    PAGE_2,
    PAGE_3,
    PAGES,
)

EXPECTED_TOTAL = 191


class TestCharacterCounts(unittest.TestCase):
    def test_group_sizes(self):
        self.assertEqual(len(EXISTING_CHARS), 80)
        self.assertEqual(len(NEW_CHARS), 33)
        self.assertEqual(len(EXTENDED_CHARS), 78)

    def test_total_character_count(self):
        self.assertEqual(len(ALL_CHARS), EXPECTED_TOTAL)

    def test_no_duplicate_codepoints(self):
        duplicates = sorted({chr(c) for c in ALL_CHARS if ALL_CHARS.count(c) > 1})
        self.assertEqual(duplicates, [], "repeated characters: {}".format(duplicates))

    def test_every_codepoint_is_a_positive_integer(self):
        for codepoint in ALL_CHARS:
            self.assertIsInstance(codepoint, int)
            self.assertGreater(codepoint, 0)


class TestAppendOnlyOrdering(unittest.TestCase):
    """Pages 1 and 2 must never shift, or existing filled forms stop matching."""

    def test_all_chars_is_the_pages_concatenated(self):
        self.assertEqual(ALL_CHARS, EXISTING_CHARS + NEW_CHARS + EXTENDED_CHARS)

    def test_the_first_113_characters_are_untouched(self):
        self.assertEqual(ALL_CHARS[:80], EXISTING_CHARS)
        self.assertEqual(ALL_CHARS[80:113], NEW_CHARS)

    def test_page_boundaries_sit_where_they_always_did(self):
        # Anchors, so a reordering inside a group is caught too.
        self.assertEqual(ALL_CHARS[0], ord("A"))
        self.assertEqual(ALL_CHARS[79], ord("]"))
        self.assertEqual(ALL_CHARS[80], ord("α"))
        self.assertEqual(ALL_CHARS[112], ord("°"))
        self.assertEqual(ALL_CHARS[113], ord("ζ"))
        self.assertEqual(ALL_CHARS[-1], ord("≫"))

    def test_new_characters_are_all_at_the_end(self):
        self.assertEqual(ALL_CHARS[113:], EXTENDED_CHARS)


class TestPageLayout(unittest.TestCase):
    def test_three_pages(self):
        self.assertEqual(PAGES, [PAGE_1, PAGE_2, PAGE_3])

    def test_page_grids(self):
        self.assertEqual((PAGE_1["cols"], PAGE_1["rows"]), (8, 10))
        self.assertEqual((PAGE_2["cols"], PAGE_2["rows"]), (8, 5))
        self.assertEqual((PAGE_3["cols"], PAGE_3["rows"]), (8, 10))

    def test_used_and_unused_boxes_per_page(self):
        expected = {0: (80, 0), 1: (33, 7), 2: (78, 2)}
        for index, page in enumerate(PAGES):
            with self.subTest(page=index + 1):
                boxes = page["cols"] * page["rows"]
                used = len(page["chars"])
                self.assertEqual((used, boxes - used), expected[index])

    def test_page_three_has_78_used_and_2_unused_boxes(self):
        boxes = PAGE_3["cols"] * PAGE_3["rows"]
        self.assertEqual(boxes, 80)
        self.assertEqual(len(PAGE_3["chars"]), 78)
        self.assertEqual(boxes - len(PAGE_3["chars"]), 2)

    def test_no_page_asks_for_more_boxes_than_it_has(self):
        for index, page in enumerate(PAGES):
            with self.subTest(page=index + 1):
                self.assertLessEqual(len(page["chars"]), page["cols"] * page["rows"])

    def test_unused_boxes_can_only_be_at_the_end(self):
        """The characters of a page are a gapless run from box 0.

        SHEETtoPNG.save_images pairs characters with detected boxes in order,
        so a hole anywhere but the tail would file every later character
        under the wrong codepoint.
        """
        for index, page in enumerate(PAGES):
            with self.subTest(page=index + 1):
                self.assertTrue(
                    all(isinstance(c, int) for c in page["chars"]),
                    "a placeholder in the middle of a page would shift the " "mapping",
                )
                self.assertEqual(len(page["chars"]), len(list(page["chars"])))


if __name__ == "__main__":
    unittest.main()
