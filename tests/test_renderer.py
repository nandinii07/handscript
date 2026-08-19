import os
import re
import base64
import shutil
import tempfile
import unittest

from handwrite.notation import parse, Token, NotationError, NORMAL, SUPER, SUB
from handwrite.renderer import (
    tokens_to_html,
    render_html,
    render_to_file,
    FontNotFound,
    FONT_FAMILY,
    SCRIPT_SCALE,
    SUPER_RAISE,
    SUB_DROP,
)

# A real .ttf produced by the handwriting pipeline (form -> PNG -> SVG -> TTF),
# covering the full Phase 1 character set. Using a real font means these tests
# exercise the same @font-face embedding path a user would.
SAMPLE_FONT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_data", "renderer", "sample.ttf"
)

# Every example the project is required to render.
REQUIRED_EXAMPLES = [
    "E = mc^2",
    "H_2O",
    "CO_2",
    "SO_4^{2-}",
    "Ca_3(PO_4)_2",
    "x^2 + y^2 = z^2",
    "F = ma",
    "λ = h/p",
    "Δx",
    "v_0",
    "v_0^2",
]


class TestTokensToHTML(unittest.TestCase):
    """Tests for turning tokens into an HTML fragment."""

    def test_normal_text_has_no_span(self):
        self.assertEqual(tokens_to_html([Token("F = ma", NORMAL)]), "F = ma")

    def test_superscript_uses_sup_class(self):
        self.assertEqual(
            tokens_to_html([Token("2", SUPER)]), '<span class="sup">2</span>'
        )

    def test_subscript_uses_sub_class(self):
        self.assertEqual(
            tokens_to_html([Token("2", SUB)]), '<span class="sub">2</span>'
        )

    def test_tokens_render_in_reading_order(self):
        # SO_4^{2-} puts the subscript before the superscript, matching how
        # the formula is normally written.
        self.assertEqual(
            tokens_to_html(parse("SO_4^{2-}")),
            'SO<span class="sub">4</span><span class="sup">2-</span>',
        )

    def test_html_special_characters_are_escaped(self):
        # '&' is part of the handwriting form's character set, so it must be
        # escaped rather than emitted raw into the page.
        self.assertEqual(tokens_to_html([Token("a & b", NORMAL)]), "a &amp; b")
        self.assertEqual(
            tokens_to_html([Token("&", SUPER)]), '<span class="sup">&amp;</span>'
        )


class TestRenderHTML(unittest.TestCase):
    """Tests for building the full HTML page."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_page_is_well_formed(self):
        page = render_html("x^2", SAMPLE_FONT)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("@font-face", page)
        self.assertIn(FONT_FAMILY, page)
        self.assertIn('<span class="sup">2</span>', page)

    def test_font_is_embedded_byte_for_byte(self):
        # The point of embedding is that the HTML works on its own, so check
        # the base64 payload really is the font file.
        page = render_html("x^2", SAMPLE_FONT)
        match = re.search(r"base64,([A-Za-z0-9+/=]+)\)", page)
        self.assertIsNotNone(match, "no base64 font payload found in the page")

        with open(SAMPLE_FONT, "rb") as font_file:
            expected_bytes = font_file.read()
        self.assertEqual(base64.b64decode(match.group(1)), expected_bytes)

    def test_missing_font_raises(self):
        with self.assertRaises(FontNotFound):
            render_html("x^2", os.path.join(self.directory, "does_not_exist.ttf"))

    def test_multiple_formulas_produce_multiple_lines(self):
        page = render_html(["x^2", "H_2O"], SAMPLE_FONT)
        self.assertEqual(page.count('<div class="formula">'), 2)

    def test_single_string_is_accepted(self):
        page = render_html("x^2", SAMPLE_FONT)
        self.assertEqual(page.count('<div class="formula">'), 1)

    def test_font_size_is_applied(self):
        page = render_html("x^2", SAMPLE_FONT, font_size=72)
        self.assertIn("font-size: 72px", page)

    def test_all_required_examples_render(self):
        page = render_html(REQUIRED_EXAMPLES, SAMPLE_FONT)
        self.assertEqual(page.count('<div class="formula">'), len(REQUIRED_EXAMPLES))
        # Greek characters must survive into the output as themselves,
        # since they are ordinary glyphs in the personalized font.
        self.assertIn("λ", page)
        self.assertIn("Δ", page)

    def test_malformed_notation_reaches_the_caller(self):
        with self.assertRaises(NotationError):
            render_html("x^{a^2}", SAMPLE_FONT)

    def test_render_to_file_writes_a_usable_page(self):
        output_path = os.path.join(self.directory, "out.html")
        returned_path = render_to_file(REQUIRED_EXAMPLES, SAMPLE_FONT, output_path)

        self.assertEqual(returned_path, output_path)
        self.assertTrue(os.path.exists(output_path))

        with open(output_path, encoding="utf-8") as output_file:
            content = output_file.read()
        self.assertIn("@font-face", content)
        self.assertIn('<span class="sup">2</span>', content)


class TestScriptStyling(unittest.TestCase):
    """The core promise: scripts reuse ordinary glyphs, moved and resized."""

    def setUp(self):
        self.page = render_html(REQUIRED_EXAMPLES + ["x^{10}", "A_{ij}"], SAMPLE_FONT)

    def _rule(self, selector):
        match = re.search(
            re.escape(selector) + r"\s*\{(.*?)\}", self.page, flags=re.DOTALL
        )
        self.assertIsNotNone(match, "no CSS rule for " + selector)
        return match.group(1)

    def test_everything_is_set_in_the_generated_font(self):
        # One @font-face, one family, and the body set in it - so normal text,
        # superscripts and subscripts are all the user's handwriting.
        self.assertEqual(self.page.count("@font-face"), 1)
        self.assertIn("font-family: '{}'".format(FONT_FAMILY), self.page)
        body = self._rule("body")
        self.assertIn(FONT_FAMILY, body)

    def test_scripts_do_not_override_the_font(self):
        # If .sup/.sub set their own font-family, they would stop being the
        # user's handwriting.
        for selector in (".sup", ".sub"):
            self.assertNotIn("font-family", self._rule(selector))

    def test_superscript_is_smaller_and_raised(self):
        rule = self._rule(".sup")
        self.assertIn("font-size: {}em".format(SCRIPT_SCALE), rule)
        self.assertIn("vertical-align: {}em".format(SUPER_RAISE), rule)
        self.assertLess(SCRIPT_SCALE, 1.0)
        self.assertGreater(SUPER_RAISE, 0)

    def test_subscript_is_smaller_and_lowered(self):
        rule = self._rule(".sub")
        self.assertIn("font-size: {}em".format(SCRIPT_SCALE), rule)
        self.assertIn("vertical-align: -{}em".format(SUB_DROP), rule)
        self.assertGreater(SUB_DROP, 0)

    def test_scripts_reuse_the_ordinary_characters(self):
        # No Unicode superscript/subscript codepoints anywhere: the whole
        # point is that a raised "2" is the same handwritten glyph as "2".
        # (U+00B2/U+00B3/U+00B9, U+2070-209F.)
        for character in self.page:
            self.assertNotIn(
                character,
                "²³¹",
                "page uses a dedicated superscript codepoint",
            )
            self.assertFalse(
                0x2070 <= ord(character) <= 0x209F,
                "page uses a dedicated super/subscript codepoint",
            )

    def test_grouped_and_single_scripts_render_the_same_way(self):
        single = tokens_to_html(parse("x^1"))
        grouped = tokens_to_html(parse("x^{10}"))
        self.assertEqual(single, 'x<span class="sup">1</span>')
        self.assertEqual(grouped, 'x<span class="sup">10</span>')

    def test_subscript_and_superscript_on_one_base(self):
        self.assertEqual(
            tokens_to_html(parse("x_1^2")),
            'x<span class="sub">1</span><span class="sup">2</span>',
        )

    def test_spacing_is_declared(self):
        # Word spacing counters the font's wide space glyph; line-height has
        # to leave room for raised and lowered text.
        formula = self._rule(".formula")
        self.assertIn("word-spacing", formula)
        line_height = float(re.search(r"line-height:\s*([\d.]+)", formula).group(1))
        self.assertGreaterEqual(line_height, 1.0 + SCRIPT_SCALE * SUPER_RAISE)


if __name__ == "__main__":
    unittest.main()
