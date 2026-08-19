import os
import json
import shutil
import tempfile
import unittest
from unittest import mock

from handwrite import SHEETtoPNG, SVGtoTTF, PNGtoSVG
from handwrite.svgtottf import FontForgeNotFound

from tests.fontmetrics import metrics

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

    def _config_with(self, **typography):
        """Write a copy of the test config with typography_parameters patched."""
        with open(self.config) as config_file:
            config = json.load(config_file)
        config["typography_parameters"].update(typography)

        path = os.path.join(self.temp, "patched.json")
        with open(path, "w") as patched:
            json.dump(config, patched)
        return path

    def test_explicit_kerning_table_is_accepted(self):
        # autokern false takes the offsets straight from the config instead of
        # letting FontForge work them out. Nothing exercised this branch, so a
        # config that turned autokerning off was untested.
        with open(self.config) as config_file:
            kerning = json.load(config_file)["typography_parameters"]["kerning_table"]
        kerning["autokern"] = False

        config = self._config_with(kerning_table=kerning)
        self.converter.convert(
            self.characters_dir, self.temp, config, {"filename": "Explicit"}
        )

        self.assertTrue(os.path.exists(os.path.join(self.temp, "Explicit.ttf")))

    def test_glyphs_without_a_tuned_bearing_fall_back_to_the_default(self):
        # Everything not named in the bearing table - which is every Greek
        # letter, operator and arrow - must still get a sensible bearing
        # rather than whatever the traced outline happened to have.
        default = 200
        config = self._config_with(bearing_table={"Default": [default, default]})
        self.converter.convert(
            self.characters_dir, self.temp, config, {"filename": "Defaulted"}
        )

        font = os.path.join(self.temp, "Defaulted.ttf")
        self.assertTrue(os.path.exists(font))

        measured = metrics(font, "Aaj.%")
        self.assertTrue(measured, "no glyphs could be read back from the font")
        for character, (_, left_bearing) in measured.items():
            with self.subTest(character=character):
                # Exact equality is not safe: FontForge rounds the outline to
                # integer units, which moves the bearing by a few.
                self.assertAlmostEqual(left_bearing, default, delta=15)

    def test_output_directory_is_created_if_missing(self):
        # A first-time user points --output at a directory that does not exist
        # yet. FontForge does not create it, and used to fail with a bare
        # "Font generation failed".
        missing = os.path.join(self.temp, "does", "not", "exist")
        self.assertFalse(os.path.exists(missing))

        self.converter.convert(self.characters_dir, missing, self.config, self.metadata)

        self.assertTrue(os.path.exists(os.path.join(missing, "CustomFont.ttf")))

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
