"""Does box number N really hold character N?

The rest of the suite checks that a folder named after a character exists.
That is not the same thing: if box detection shifts by one position, every
folder is still created and every file is still written - they just contain
the wrong picture. The font builds, looks like handwriting, and is silently
wrong from that point on.

These tests close that gap by comparing the *image* extracted for each
character against a freshly drawn reference of the character it claims to be.
The synthetic pages are drawn with a known font, so a correct pipeline must
produce something that matches that same character better than any other.
"""

import os
import shutil
import tempfile
import unittest

from PIL import Image, ImageDraw

from handwrite import formgen
from handwrite.characters import PAGES
from handwrite.sheettopng import SHEETtoPNG

from tests.test_sheettopng import render_synthetic_page, CONFIG

# Side of the square each glyph is normalised into before comparison. Big
# enough to tell characters apart, small enough that antialiasing and a pixel
# of crop drift do not matter.
GRID = 24

INK = 128  # anything darker than this counts as ink


def signature(image):
    """Normalise a glyph image to a comparable ink bitmap.

    Crops to the ink, scales the *longest* side to GRID and centres the
    result, so proportions are preserved: without that, a full stop, a hyphen
    and a vertical bar all stretch into the same filled square and become
    indistinguishable.
    """
    mask = image.convert("L").point(lambda pixel: 255 if pixel < INK else 0)
    box = mask.getbbox()
    if box is None:
        return None

    ink = mask.crop(box)
    scale = GRID / max(ink.width, ink.height)
    resized = ink.resize(
        (max(1, round(ink.width * scale)), max(1, round(ink.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("L", (GRID, GRID), 0)
    canvas.paste(resized, ((GRID - resized.width) // 2, (GRID - resized.height) // 2))

    bits = 0
    for pixel in canvas.getdata():
        bits = (bits << 1) | (1 if pixel > 127 else 0)
    return bits


def difference(one, other):
    """Number of pixels that differ between two signatures."""
    return bin(one ^ other).count("1")


def reference(character, font):
    """Draw a character on a blank tile and return its signature."""
    tile = Image.new("L", (300, 300), 255)
    draw = ImageDraw.Draw(tile)
    box = draw.textbbox((0, 0), character, font=font)
    draw.text(
        (150 - (box[2] - box[0]) / 2 - box[0], 150 - (box[3] - box[1]) / 2 - box[1]),
        character,
        fill=0,
        font=font,
    )
    return signature(tile)


class TestBoxToCharacterMapping(unittest.TestCase):
    """Every extracted image must look like the character it is filed under."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.characters = [code for page in PAGES for code in page["chars"]]

        pages = [render_synthetic_page(page, i) for i, page in enumerate(PAGES)]
        SHEETtoPNG().convert_pages(pages, cls.directory, CONFIG)

        _, _, box_height = formgen.cell_geometry()
        label_font, _ = formgen.resolve_fonts([chr(c) for c in cls.characters])
        ink_font = label_font.font_variant(size=int(box_height * 0.6))

        cls.references = {c: reference(chr(c), ink_font) for c in cls.characters}
        cls.extracted = {}
        for code in cls.characters:
            path = os.path.join(cls.directory, str(code), "{}.png".format(code))
            cls.extracted[code] = signature(Image.open(path))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory)

    def test_no_extracted_glyph_is_blank(self):
        # A blank crop means the box was found but the writing was missed.
        blank = [chr(c) for c, sig in self.extracted.items() if sig is None]
        self.assertEqual(blank, [], "blank extraction for: {}".format(blank))

    def test_each_box_maps_to_its_own_character(self):
        """No other character may match an extracted glyph better than its own.

        Equal matches are allowed: in most fonts a capital I and a lower case
        l really are the same shape, and demanding a strict win would be
        asserting something about the font rather than about the pipeline.
        """
        for code in self.characters:
            with self.subTest(character=chr(code)):
                own = difference(self.extracted[code], self.references[code])
                best = min(
                    difference(self.extracted[code], self.references[other])
                    for other in self.characters
                )
                self.assertEqual(
                    own,
                    best,
                    "extracted image for {!r} looks more like {!r}".format(
                        chr(code),
                        next(
                            chr(other)
                            for other in self.characters
                            if difference(self.extracted[code], self.references[other])
                            == best
                        ),
                    ),
                )

    def test_a_shifted_mapping_would_be_detected(self):
        """Negative control: prove the comparison above can actually fail.

        A test that says "correct is correct" is worthless unless wrong is
        also detectably wrong. Comparing every glyph against the *next*
        character's reference simulates a one-position detection shift, which
        must come out strictly worse than the true pairing.
        """
        for index, code in enumerate(self.characters[:-1]):
            neighbour = self.characters[index + 1]
            with self.subTest(character=chr(code)):
                self.assertGreater(
                    difference(self.extracted[code], self.references[neighbour]),
                    difference(self.extracted[code], self.references[code]),
                )

    def test_every_expected_character_was_produced(self):
        produced = sorted(int(name) for name in os.listdir(self.directory))
        self.assertEqual(produced, sorted(self.characters))


if __name__ == "__main__":
    unittest.main()
