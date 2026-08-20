"""Building the same handwriting twice must produce the same font.

Without this, nothing about a generated font can be regression tested: every
build differed, so there was no way to tell a real change in the outlines from
a new timestamp. Three things varied between builds - a random uuid in the
UniqueID, and the two timestamps FontForge writes into `head` and `FFTM`.
"""

import os
import json
import shutil
import tempfile
import unittest

from handwrite import SHEETtoPNG, PNGtoSVG, SVGtoTTF
from handwrite.svgtottf import source_digest
from handwrite.characters import EXISTING_CHARS

from tests.fontmetrics import name_records

NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)

UNIQUE_ID = 3  # name id of the UniqueID record

TEST_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data")
CONFIG = os.path.join(TEST_DATA, "config_data", "default.json")
SHEET = os.path.join(TEST_DATA, "sheettopng", "excellent.jpg")


class TestSourceDigest(unittest.TestCase):
    """The digest replaces a random uuid, so it has to behave like an id."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory)

    def write_outline(self, codepoint, content):
        folder = os.path.join(self.directory, str(codepoint))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "{}.svg".format(codepoint)), "w") as outline:
            outline.write(content)

    def test_same_outlines_give_the_same_digest(self):
        self.write_outline(65, "<svg>A</svg>")
        self.write_outline(66, "<svg>B</svg>")

        first = source_digest(self.directory, [65, 66])
        second = source_digest(self.directory, [65, 66])
        self.assertEqual(first, second)

    def test_changed_handwriting_gives_a_different_digest(self):
        # Two people's fonts must not share a UniqueID, or they collide in
        # the operating system's font cache. This is what the uuid was for.
        self.write_outline(65, "<svg>A</svg>")
        before = source_digest(self.directory, [65])

        self.write_outline(65, "<svg>A but written differently</svg>")
        self.assertNotEqual(before, source_digest(self.directory, [65]))

    def test_different_glyph_sets_give_different_digests(self):
        self.write_outline(65, "<svg>A</svg>")
        self.write_outline(66, "<svg>B</svg>")

        self.assertNotEqual(
            source_digest(self.directory, [65]),
            source_digest(self.directory, [65, 66]),
        )

    def test_glyph_order_does_not_matter(self):
        self.write_outline(65, "<svg>A</svg>")
        self.write_outline(66, "<svg>B</svg>")

        self.assertEqual(
            source_digest(self.directory, [65, 66]),
            source_digest(self.directory, [66, 65]),
        )

    def test_missing_outlines_are_skipped_rather_than_raising(self):
        # add_glyphs reports the missing outline with a much better message,
        # so the digest must not fail first.
        self.write_outline(65, "<svg>A</svg>")
        self.assertTrue(source_digest(self.directory, [65, 9999]))

    def test_digest_is_short_and_hex(self):
        self.write_outline(65, "<svg>A</svg>")
        digest = source_digest(self.directory, [65])
        self.assertEqual(len(digest), 16)
        int(digest, 16)  # raises if it is not hexadecimal


@NEEDS_FONT_TOOLS
class TestReproducibleBuilds(unittest.TestCase):
    """Two builds of one set of outlines, compared byte for byte."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.mkdtemp()
        cls.characters = os.path.join(cls.temp, "characters")

        SHEETtoPNG().convert(SHEET, cls.characters, CONFIG)
        PNGtoSVG().convert(directory=cls.characters)

        converter = SVGtoTTF()
        cls.first = os.path.join(cls.temp, "first")
        cls.second = os.path.join(cls.temp, "second")
        converter.convert(cls.characters, cls.first, CONFIG, {"filename": "Repeat"})
        converter.convert(cls.characters, cls.second, CONFIG, {"filename": "Repeat"})

        cls.first_font = os.path.join(cls.first, "Repeat.ttf")
        cls.second_font = os.path.join(cls.second, "Repeat.ttf")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp)

    def read(self, path):
        with open(path, "rb") as font:
            return font.read()

    def test_both_builds_produced_a_font(self):
        self.assertTrue(os.path.exists(self.first_font))
        self.assertTrue(os.path.exists(self.second_font))

    def test_the_two_builds_are_byte_identical(self):
        self.assertEqual(self.read(self.first_font), self.read(self.second_font))

    def test_the_unique_id_is_derived_from_the_outlines(self):
        # Not merely stable - a hardcoded constant would also be stable, and
        # would put every user's font under the same id.
        with open(CONFIG) as config_file:
            glyphs = json.load(config_file)["glyphs"]

        expected = source_digest(self.characters, glyphs)
        unique_id = name_records(self.first_font)[UNIQUE_ID]

        self.assertIn(expected, unique_id)
        self.assertEqual(unique_id, name_records(self.second_font)[UNIQUE_ID])

    def test_the_unique_id_is_not_a_uuid(self):
        # A uuid4 contains hyphens in a fixed pattern; the digest never does.
        unique_id = name_records(self.first_font)[UNIQUE_ID]
        self.assertNotRegex(unique_id, r"[0-9a-f]{8}-[0-9a-f]{4}-")


if __name__ == "__main__":
    unittest.main()
