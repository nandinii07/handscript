"""Fractions, radicals, and things set over or under a base.

These are the only pieces of the notation that are not a straight run of
characters. Everything here is additive: a formula that used none of them
parses to exactly the same flat list of Tokens it always did, which the
existing test modules still assert.
"""

import os
import re
import shutil
import tempfile
import unittest
import warnings

from handwrite.notation import (
    parse,
    rendered_characters,
    Token,
    Fraction,
    Radical,
    Stack,
    NotationError,
    NORMAL,
    SUPER,
    SUB,
)
from handwrite.renderer import (
    tokens_to_html,
    render_html,
    check_coverage,
    MissingGlyphs,
    MissingGlyphWarning,
)

SAMPLE_FONT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_data", "renderer", "sample.ttf"
)


def quiet(function, *args, **kwargs):
    """Call something that may warn about coverage, ignoring the warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MissingGlyphWarning)
        return function(*args, **kwargs)


class TestExistingNotationUnaffected(unittest.TestCase):
    """The new structures must not disturb anything that already worked."""

    def test_ordinary_formulas_are_still_flat_tokens(self):
        for source in ("E = mc^2", "H_2O", "SO_4^{2-}", "Ca_3(PO_4)_2", "x_1^2"):
            with self.subTest(source=source):
                self.assertTrue(all(isinstance(i, Token) for i in parse(source)))

    def test_a_lone_slash_is_still_division(self):
        self.assertEqual(parse("λ = h/p"), [Token("λ = h/p", NORMAL)])

    def test_a_bare_radical_sign_is_still_a_character(self):
        self.assertEqual(parse("√2"), [Token("√2", NORMAL)])

    def test_braces_away_from_a_marker_are_still_literal(self):
        self.assertEqual(parse("f{x}"), [Token("f{x}", NORMAL)])
        self.assertEqual(parse("{1,2}"), [Token("{1,2}", NORMAL)])

    def test_a_group_not_followed_by_a_slash_is_literal(self):
        self.assertEqual(parse("{a} b"), [Token("{a} b", NORMAL)])


class TestFractions(unittest.TestCase):
    def test_simple_fraction(self):
        self.assertEqual(
            parse("{a}/{b}"),
            [Fraction([Token("a", NORMAL)], [Token("b", NORMAL)])],
        )

    def test_fraction_halves_may_contain_scripts(self):
        parsed = parse("{x^2}/{y_1}")
        self.assertEqual(parsed[0].numerator, [Token("x", NORMAL), Token("2", SUPER)])
        self.assertEqual(parsed[0].denominator, [Token("y", NORMAL), Token("1", SUB)])

    def test_fraction_within_a_sentence(self):
        parsed = parse("v = {d}/{t} exactly")
        self.assertEqual(parsed[0], Token("v = ", NORMAL))
        self.assertIsInstance(parsed[1], Fraction)
        self.assertEqual(parsed[2], Token(" exactly", NORMAL))

    def test_nested_fraction(self):
        parsed = parse("{{a}/{b}}/{c}")
        self.assertIsInstance(parsed[0], Fraction)
        self.assertIsInstance(parsed[0].numerator[0], Fraction)

    def test_fraction_renders_as_two_stacked_halves(self):
        markup = tokens_to_html(parse("{a}/{b}"))
        self.assertIn('<span class="frac">', markup)
        self.assertIn('<span class="num">a</span>', markup)
        self.assertIn('<span class="den">b</span>', markup)

    def test_empty_half_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("{}/{b}")
        with self.assertRaises(NotationError):
            parse("{a}/{ }")


class TestMalformedFractions(unittest.TestCase):
    """A half-written fraction must complain, not print its own braces.

    A group followed by a slash is the point of no return: before it the
    braces may still be ordinary characters, after it the only thing the
    input can be is a fraction. Falling back to literal text past that point
    was the one place this notation rendered something the writer plainly did
    not mean.
    """

    def test_unclosed_denominator(self):
        with self.assertRaises(NotationError) as caught:
            parse("{a}/{b")
        self.assertIn("Unclosed", str(caught.exception))

    def test_nothing_after_the_slash(self):
        with self.assertRaises(NotationError) as caught:
            parse("{a}/")
        self.assertIn("denominator", str(caught.exception))

    def test_bare_opening_brace_after_the_slash(self):
        with self.assertRaises(NotationError):
            parse("{a}/{")

    def test_denominator_not_in_braces(self):
        with self.assertRaises(NotationError):
            parse("{a}/x")

    def test_denominator_braces_do_not_balance(self):
        with self.assertRaises(NotationError):
            parse("{a}/{{b}")

    def test_the_error_says_where(self):
        with self.assertRaises(NotationError) as caught:
            parse("x = {a}/{b")
        self.assertIn("position 4", str(caught.exception))

    def test_a_group_without_a_slash_is_still_ordinary_text(self):
        # The commitment is to the slash, not to the brace, so text that
        # merely contains braces is unaffected.
        for source in ("f{x}", "{1,2}", "{a} b", "{lim} x"):
            with self.subTest(source=source):
                self.assertEqual(parse(source), [Token(source, NORMAL)])

    def test_malformed_fractions_produce_no_html(self):
        for source in ("{a}/{b", "{a}/", "{a}/{", "{a}/x"):
            with self.subTest(source=source):
                with self.assertRaises(NotationError):
                    quiet(render_html, source, SAMPLE_FONT)


class TestRadicals(unittest.TestCase):
    def test_radical_with_a_group(self):
        self.assertEqual(parse("√{x+1}"), [Radical([Token("x+1", NORMAL)])])

    def test_radicand_may_contain_scripts(self):
        parsed = parse("√{x^2}")
        self.assertEqual(parsed[0].radicand, [Token("x", NORMAL), Token("2", SUPER)])

    def test_radical_uses_the_handwritten_sign(self):
        markup = tokens_to_html(parse("√{2}"))
        # The sign is the user's own glyph, not a drawn shape.
        self.assertIn("√", markup)
        self.assertIn('<span class="radicand">2</span>', markup)

    def test_radical_inside_a_fraction(self):
        parsed = parse("{√{2}}/{2}")
        self.assertIsInstance(parsed[0].numerator[0], Radical)

    def test_unclosed_radicand_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("√{x+1")

    def test_empty_radicand_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("√{}")


class TestOverAndUnder(unittest.TestCase):
    def test_something_set_over_a_base(self):
        self.assertEqual(
            parse("v^^{→}"),
            [Stack(Token("v", NORMAL), [Token("→", NORMAL)], [])],
        )

    def test_something_set_under_a_base(self):
        self.assertEqual(
            parse("x__{n}"),
            [Stack(Token("x", NORMAL), [], [Token("n", NORMAL)])],
        )

    def test_both_limits_land_on_one_stack(self):
        parsed = parse("Σ__{i=1}^^{n}")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].base, Token("Σ", NORMAL))
        self.assertEqual(parsed[0].under, [Token("i=1", NORMAL)])
        self.assertEqual(parsed[0].over, [Token("n", NORMAL)])

    def test_order_of_the_two_markers_does_not_matter(self):
        self.assertEqual(parse("Σ^^{n}__{i=1}"), parse("Σ__{i=1}^^{n}"))

    def test_only_the_last_character_becomes_the_base(self):
        parsed = parse("lim__{x→0}")
        self.assertEqual(parsed[0], Token("li", NORMAL))
        self.assertEqual(parsed[1].base, Token("m", NORMAL))

    def test_stack_renders_over_base_under_in_order(self):
        markup = tokens_to_html(parse("Σ__{i=1}^^{n}"))
        self.assertLess(markup.index('class="over"'), markup.index('class="base"'))
        self.assertLess(markup.index('class="base"'), markup.index('class="under"'))

    def test_a_marker_with_nothing_before_it_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("^^{n}")

    def test_repeating_the_same_marker_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("x^^{a}^^{b}")

    def test_marker_without_a_group_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("x^^n")

    def test_empty_group_is_rejected(self):
        with self.assertRaises(NotationError):
            parse("x^^{}")

    def test_a_braced_base_covers_a_whole_word(self):
        # Without this the limit would hang under the "m" of "lim" alone.
        parsed = parse("{lim}__{x→0}")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].base, Token("lim", NORMAL))
        self.assertEqual(parsed[0].under, [Token("x→0", NORMAL)])

    def test_a_braced_base_takes_both_markers(self):
        parsed = parse("{max}__{i}^^{n}")
        self.assertEqual(parsed[0].base, Token("max", NORMAL))
        self.assertEqual(parsed[0].over, [Token("n", NORMAL)])

    def test_a_braced_base_must_be_one_run_of_text(self):
        with self.assertRaises(NotationError):
            parse("{x^2}__{n}")

    def test_a_group_before_no_marker_is_still_literal(self):
        self.assertEqual(parse("{lim} x"), [Token("{lim} x", NORMAL)])


class TestRenderedCharacters(unittest.TestCase):
    """What actually reaches the page, as opposed to what was typed."""

    def test_markers_and_braces_are_not_drawn(self):
        self.assertEqual(rendered_characters(parse("x^2")), "x2")
        self.assertEqual(rendered_characters(parse("{a}/{b}")), "ab")

    def test_a_radical_draws_its_sign(self):
        self.assertEqual(rendered_characters(parse("√{2}")), "√2")

    def test_stack_contents_are_counted(self):
        self.assertEqual(rendered_characters(parse("Σ__{i}^^{n}")), "Σni")


class TestFontCoverage(unittest.TestCase):
    """A character the font lacks must never be swapped out silently."""

    def test_a_font_that_covers_everything_reports_nothing(self):
        self.assertEqual(check_coverage("E = mc^2", SAMPLE_FONT), [])

    def test_notation_characters_are_not_reported(self):
        # '^', '_' and braces are consumed by the parser, so whether the font
        # has them is irrelevant.
        self.assertEqual(check_coverage("x^{10} H_2O", SAMPLE_FONT), [])

    def test_an_uncollected_character_is_reported(self):
        # A Han character is certainly not on the handwriting form.
        self.assertEqual(check_coverage("x 漢", SAMPLE_FONT), ["漢"])

    def test_rendering_warns_about_it(self):
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always", MissingGlyphWarning)
            render_html("x 漢", SAMPLE_FONT)
        self.assertEqual(len(raised), 1)
        self.assertIn("漢", str(raised[0].message))

    def test_strict_mode_refuses_to_render(self):
        with self.assertRaises(MissingGlyphs):
            render_html("x 漢", SAMPLE_FONT, strict=True)

    def test_clean_input_does_not_warn(self):
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always", MissingGlyphWarning)
            render_html(["E = mc^2", "H_2O", "SO_4^{2-}"], SAMPLE_FONT)
        self.assertEqual(raised, [])


class TestStructuresInAPage(unittest.TestCase):
    """The structures have to survive into a real, well-formed page."""

    def setUp(self):
        self.page = quiet(
            render_html,
            ["{a}/{b}", "√{x+1}", "Σ__{i=1}^^{n}", "v^^{→}"],
            SAMPLE_FONT,
        )

    def test_every_structure_has_a_stylesheet_rule(self):
        for selector in (
            ".frac",
            ".frac .num",
            ".frac .den",
            ".radical .radicand",
            ".stack",
            ".stack .base",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.page)

    def test_the_page_is_still_well_formed(self):
        self.assertIn("<!DOCTYPE html>", self.page)
        self.assertEqual(self.page.count("<body>"), 1)
        self.assertEqual(self.page.count("</body>"), 1)
        self.assertEqual(
            self.page.count("<span"),
            self.page.count("</span>"),
            "unbalanced spans",
        )
        self.assertEqual(self.page.count("<div"), self.page.count("</div>"))

    def test_one_line_per_formula(self):
        self.assertEqual(self.page.count('<div class="formula">'), 4)

    def test_structures_still_use_the_embedded_font(self):
        # No structure may introduce a font-family of its own.
        for rule in re.findall(r"\.(?:frac|radical|stack)[^{]*\{([^}]*)\}", self.page):
            self.assertNotIn("font-family", rule)

    def test_the_rules_scale_with_the_text(self):
        # Bars measured in em, so they thicken with the font size rather than
        # staying a hairline on a large page.
        for rule in re.findall(r"\.frac \.num\s*\{([^}]*)\}", self.page):
            self.assertIn("em solid", rule)


if __name__ == "__main__":
    unittest.main()
