import os
import json
import unittest

from handwrite.characters import ALL_CHARS, EXISTING_CHARS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_CONFIG = os.path.join(ROOT, "handwrite", "default.json")
LEGACY_TEST_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "test_data",
    "config_data",
    "default.json",
)


def load(path):
    with open(path) as config_file:
        return json.load(config_file)


class TestDefaultConfig(unittest.TestCase):
    """The config's glyph list and the form's character list must agree.

    If they drift, FontForge is asked for a character the form never
    collected (or silently drops one it did).
    """

    def test_package_config_covers_exactly_the_form(self):
        self.assertEqual(load(PACKAGE_CONFIG)["glyphs"], ALL_CHARS)

    def test_legacy_test_config_covers_exactly_page_one(self):
        self.assertEqual(load(LEGACY_TEST_CONFIG)["glyphs"], EXISTING_CHARS)

    def test_every_glyph_gets_a_bearing(self):
        # Characters absent from the table fall back to "Default", so the
        # only thing that must exist is the default itself.
        bearings = load(PACKAGE_CONFIG)["typography_parameters"]["bearing_table"]
        self.assertIn("Default", bearings)
        left, right = bearings["Default"]
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)

    def test_no_glyph_is_pulled_onto_its_neighbour(self):
        # A left side bearing is how far the ink sits from the glyph origin,
        # so a large negative value drags the character backwards onto the one
        # before it. "j" used to be -70, which made "ij" render as one blob in
        # every font the pipeline produced. Small negatives are fine and give
        # handwriting its connected look; deep ones collide.
        bearings = load(PACKAGE_CONFIG)["typography_parameters"]["bearing_table"]
        for key, (left, _) in bearings.items():
            if left is None:
                continue
            with self.subTest(key=key):
                self.assertGreaterEqual(
                    left, -10, "{} overlaps the character before it".format(key)
                )

    def test_autokerning_leaves_a_gap_between_glyphs(self):
        # FontForge packs glyphs until they are this far apart optically. At 0
        # it packs them until they touch, and "ij"/"il"/"in" came out as one
        # blob in every generated font.
        kerning = load(PACKAGE_CONFIG)["typography_parameters"]["kerning_table"]
        if kerning.get("autokern", True):
            self.assertGreater(kerning.get("seperation", 0), 0)

    def test_bearing_keys_are_single_characters_in_the_font(self):
        config = load(PACKAGE_CONFIG)
        glyphs = set(config["glyphs"])
        for key in config["typography_parameters"]["bearing_table"]:
            if key == "Default":
                continue
            with self.subTest(key=key):
                self.assertEqual(len(key), 1)
                self.assertIn(ord(key), glyphs)


if __name__ == "__main__":
    unittest.main()
