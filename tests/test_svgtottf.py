import os
import shutil
import tempfile
import unittest
from unittest import mock

from handwrite import SHEETtoPNG, SVGtoTTF, PNGtoSVG
from handwrite.svgtottf import FontForgeNotFound

NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)


@NEEDS_FONT_TOOLS
class TestSVGtoTTF(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.characters_dir = tempfile.mkdtemp(dir=self.temp)
        self.sheet_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_data",
            "sheettopng",
            "excellent.jpg",
        )
        self.config = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_data",
            "config_data",
            "default.json",
        )
        SHEETtoPNG().convert(self.sheet_path, self.characters_dir, self.config)
        PNGtoSVG().convert(directory=self.characters_dir)
        self.converter = SVGtoTTF()
        self.metadata = {"filename": "CustomFont"}

    def tearDown(self):
        shutil.rmtree(self.temp)

    def test_convert(self):
        self.converter.convert(
            self.characters_dir, self.temp, self.config, self.metadata
        )
        self.assertTrue(os.path.exists(os.path.join(self.temp, "CustomFont.ttf")))

    def test_convert_duplicate(self):
        fake_ttf = tempfile.NamedTemporaryFile(
            suffix=".ttf", dir=self.temp, delete=False
        )
        fake_ttf.close()  # Doesn't keep open
        os.rename(fake_ttf.name, os.path.join(self.temp, "MyFont.ttf"))
        self.converter.convert(self.characters_dir, self.temp, self.config)
        self.assertTrue(os.path.exists(os.path.join(self.temp, "MyFont (1).ttf")))
        self.converter.convert(self.characters_dir, self.temp, self.config)
        self.assertTrue(os.path.exists(os.path.join(self.temp, "MyFont (1) (1).ttf")))

    def test_glyph_without_an_outline_is_reported(self):
        # The full two-page glyph list against a page-1-only directory: the
        # error has to name the character that has no traced outline rather
        # than producing a font with a blank glyph.
        full_config = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "handwrite",
            "default.json",
        )
        with self.assertRaises(Exception) as caught:
            self.converter.convert(self.characters_dir, self.temp, full_config)
        self.assertIn("No traced outline", str(caught.exception))


class TestMissingFontForge(unittest.TestCase):
    """Runs everywhere: a missing FontForge must be reported, not ignored."""

    def test_missing_fontforge_is_reported_clearly(self):
        directory = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, {"PATH": ""}):
                with self.assertRaises(FontForgeNotFound) as caught:
                    SVGtoTTF().convert(directory, directory, "config.json")
            message = str(caught.exception)
            self.assertIn("not installed", message)
            self.assertIn("fontforge.org", message)
        finally:
            shutil.rmtree(directory)


if __name__ == "__main__":
    unittest.main()
