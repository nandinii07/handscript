"""The public `handscript` package: its own tests, separate from the
pipeline's own test suite (which is unchanged and keeps testing the pipeline
directly). These exercise the same real Potrace/FontForge build a user's
`HandScript().create_font(...)` call would - nothing here is mocked - using
the project's existing synthetic-page fixture so the tests can run without a
real scanned image.
"""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from handwrite.characters import EXISTING_CHARS, PAGES

from handscript import (
    HandScript,
    HandScriptConfig,
    HandScriptResult,
    InvalidInputError,
    NotationSyntaxError,
)
from handscript.cli import build_parser
from handscript.glyphs import characters, expected_characters, page_count

from tests.test_sheettopng import render_synthetic_page

NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)


def _build_pages(directory: Path):
    pages = []
    for index, page in enumerate(PAGES):
        source = render_synthetic_page(page, index)
        target = directory / "page_{}.png".format(index + 1)
        shutil.copyfile(source, target)
        pages.append(target)
    return pages


class TestGlyphs(unittest.TestCase):
    def test_page_count_matches_the_pipelines_own_page_layout(self):
        self.assertEqual(page_count(), len(PAGES))

    def test_expected_characters_matches_the_existing_character_set(self):
        self.assertEqual(expected_characters(0), characters(EXISTING_CHARS))


class TestCreateFontInputValidation(unittest.TestCase):
    """Errors that do not need Potrace/FontForge at all - wrong arguments."""

    def setUp(self):
        self.hs = HandScript()

    def test_neither_input_dir_nor_input_path_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            self.hs.create_font(output_path="out/font.ttf")

    def test_both_input_dir_and_input_path_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            self.hs.create_font(
                input_dir=".", input_path="x.png", output_path="out/font.ttf"
            )

    def test_missing_output_path_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            self.hs.create_font(input_dir=".")

    def test_a_nonexistent_input_directory_is_rejected(self):
        with self.assertRaises(InvalidInputError):
            self.hs.create_font(
                input_dir="/no/such/directory/handscript-test",
                output_path="out/font.ttf",
            )


@NEEDS_FONT_TOOLS
class TestCreateFontEndToEnd(unittest.TestCase):
    """The real pipeline, run through the public HandScript API."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = Path(tempfile.mkdtemp())
        cls.pages_dir = cls.fixtures / "handwriting"
        cls.pages_dir.mkdir()
        _build_pages(cls.pages_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fixtures, ignore_errors=True)

    def setUp(self):
        self.output_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_a_font_is_built_at_the_exact_output_path_given(self):
        hs = HandScript()
        output_path = self.output_dir / "my_handwriting.ttf"

        result = hs.create_font(
            input_dir=str(self.pages_dir), output_path=str(output_path)
        )

        self.assertIsInstance(result, HandScriptResult)
        self.assertEqual(result.font_path, output_path)
        self.assertTrue(output_path.exists())
        self.assertEqual(output_path.read_bytes()[:4], b"\x00\x01\x00\x00")

    def test_the_family_name_defaults_to_the_output_filename(self):
        hs = HandScript()
        output_path = self.output_dir / "TestFamily.ttf"

        result = hs.create_font(
            input_dir=str(self.pages_dir), output_path=str(output_path)
        )

        self.assertEqual(result.family_name, "TestFamily")

    def test_an_explicit_family_name_overrides_the_filename(self):
        hs = HandScript()
        output_path = self.output_dir / "irrelevant_filename.ttf"

        result = hs.create_font(
            input_dir=str(self.pages_dir),
            output_path=str(output_path),
            family_name="Explicit Family",
        )

        self.assertEqual(result.family_name, "Explicit Family")

    def test_a_config_default_family_name_is_used_when_none_is_given_per_call(self):
        hs = HandScript(HandScriptConfig(family_name="From Config"))
        output_path = self.output_dir / "irrelevant.ttf"

        result = hs.create_font(
            input_dir=str(self.pages_dir), output_path=str(output_path)
        )

        self.assertEqual(result.family_name, "From Config")

    def test_keep_intermediates_leaves_the_traced_files_on_disk(self):
        hs = HandScript()
        output_path = self.output_dir / "font.ttf"
        keep_dir = self.output_dir / "work"

        result = hs.create_font(
            input_dir=str(self.pages_dir),
            output_path=str(output_path),
            keep_intermediates=str(keep_dir),
        )

        self.assertEqual(result.intermediates_dir, keep_dir)
        self.assertTrue(any(keep_dir.rglob("*.svg")))

    def test_render_and_check_coverage_work_against_the_built_font(self):
        hs = HandScript()
        output_path = self.output_dir / "font.ttf"
        result = hs.create_font(
            input_dir=str(self.pages_dir), output_path=str(output_path)
        )

        self.assertEqual(hs.check_coverage("E = mc^2", result.font_path), [])

        html_path = hs.render(
            "E = mc^2", result.font_path, self.output_dir / "out.html"
        )
        self.assertTrue(Path(html_path).exists())
        self.assertIn("@font-face", Path(html_path).read_text(encoding="utf-8"))

        fragment = hs.render_fragment("E = mc^2")
        self.assertIn("mc", fragment)

    def test_bad_notation_raises_the_public_exception_type(self):
        hs = HandScript()
        with self.assertRaises(NotationSyntaxError):
            hs.render_fragment("a^")


class TestCLI(unittest.TestCase):
    """Argument parsing and wiring, without re-running the real pipeline
    (TestCreateFontEndToEnd already does that, through the same HandScript
    class this CLI calls)."""

    def test_build_requires_output(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["build", "some/dir"])

    def test_build_parses_into_the_expected_arguments(self):
        parser = build_parser()
        args = parser.parse_args(
            ["build", "handwriting/", "--output", "out/font.ttf", "--family", "Mine"]
        )
        self.assertEqual(args.input, "handwriting/")
        self.assertEqual(args.output, "out/font.ttf")
        self.assertEqual(args.family, "Mine")
        self.assertIs(args.func.__name__, "_cmd_build")

    def test_version_flag_exits_cleanly(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)

    def test_glyphs_command_prints_the_character_set(self):
        parser = build_parser()
        args = parser.parse_args(["glyphs", "--page", "1"])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = args.func(args)
        self.assertEqual(exit_code, 0)
        self.assertIn("Page 1 of {}".format(page_count()), buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
