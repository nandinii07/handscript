import unittest

from handwrite.notation import (
    parse,
    describe,
    Token,
    NotationError,
    NORMAL,
    SUPER,
    SUB,
)


class TestNotationParser(unittest.TestCase):
    """Tests for the notation parser (the ^ and _ syntax)."""

    def test_single_character_superscript(self):
        self.assertEqual(
            parse("x^2"),
            [Token("x", NORMAL), Token("2", SUPER)],
        )

    def test_single_character_subscript(self):
        self.assertEqual(
            parse("H_2O"),
            [Token("H", NORMAL), Token("2", SUB), Token("O", NORMAL)],
        )

    def test_grouped_superscript(self):
        # Braces make the whole group one superscript...
        self.assertEqual(
            parse("x^{10}"),
            [Token("x", NORMAL), Token("10", SUPER)],
        )

    def test_ungrouped_marker_takes_only_one_character(self):
        # ...whereas without braces only the first character is raised,
        # which is the behaviour LaTeX users expect.
        self.assertEqual(
            parse("x^10"),
            [Token("x", NORMAL), Token("1", SUPER), Token("0", NORMAL)],
        )

    def test_grouped_subscript(self):
        self.assertEqual(
            parse("A_{ij}"),
            [Token("A", NORMAL), Token("ij", SUB)],
        )

    def test_subscript_and_superscript_on_same_base(self):
        self.assertEqual(
            parse("x_1^2"),
            [Token("x", NORMAL), Token("1", SUB), Token("2", SUPER)],
        )

    def test_grouped_superscript_after_subscript(self):
        self.assertEqual(
            parse("SO_4^{2-}"),
            [Token("SO", NORMAL), Token("4", SUB), Token("2-", SUPER)],
        )

    def test_repeated_subscripts_with_brackets(self):
        self.assertEqual(
            parse("Ca_3(PO_4)_2"),
            [
                Token("Ca", NORMAL),
                Token("3", SUB),
                Token("(PO", NORMAL),
                Token("4", SUB),
                Token(")", NORMAL),
                Token("2", SUB),
            ],
        )

    def test_multiple_superscripts_in_one_line(self):
        self.assertEqual(
            parse("x^2 + y^2 = z^2"),
            [
                Token("x", NORMAL),
                Token("2", SUPER),
                Token(" + y", NORMAL),
                Token("2", SUPER),
                Token(" = z", NORMAL),
                Token("2", SUPER),
            ],
        )

    def test_plain_text_is_a_single_token(self):
        # Text with no markers should not be split up unnecessarily.
        self.assertEqual(parse("F = ma"), [Token("F = ma", NORMAL)])

    def test_extended_characters_pass_through_unchanged(self):
        # Greek letters and operators from the Phase 1 form are ordinary
        # text as far as the parser is concerned.
        self.assertEqual(parse("λ = h/p"), [Token("λ = h/p", NORMAL)])
        self.assertEqual(parse("Δx"), [Token("Δx", NORMAL)])
        self.assertEqual(parse("α ± √2 → ∞"), [Token("α ± √2 → ∞", NORMAL)])

    def test_empty_input(self):
        self.assertEqual(parse(""), [])

    def test_braces_are_ordinary_characters_away_from_a_marker(self):
        # '{' and '}' are glyphs the form collects, so they must survive as
        # text unless they directly follow a ^ or _.
        self.assertEqual(parse("f{x}"), [Token("f{x}", NORMAL)])

    def test_required_syntax(self):
        # The exact set of forms Phase 2 is required to support.
        required = {
            "x^2": [Token("x", NORMAL), Token("2", SUPER)],
            "H_2O": [Token("H", NORMAL), Token("2", SUB), Token("O", NORMAL)],
            "x_1^2": [Token("x", NORMAL), Token("1", SUB), Token("2", SUPER)],
            "x^{10}": [Token("x", NORMAL), Token("10", SUPER)],
            "A_{ij}": [Token("A", NORMAL), Token("ij", SUB)],
            "SO_4^{2-}": [Token("SO", NORMAL), Token("4", SUB), Token("2-", SUPER)],
        }
        for source, expected in required.items():
            with self.subTest(source=source):
                self.assertEqual(parse(source), expected)

    def test_describe_is_readable(self):
        self.assertEqual(describe(parse("x^2")), "'x'(normal) '2'(super)")


class TestMalformedNotation(unittest.TestCase):
    """Bad input must be rejected, never quietly rendered as something else."""

    def test_marker_with_nothing_after_it_raises(self):
        with self.assertRaises(NotationError):
            parse("x^")
        with self.assertRaises(NotationError):
            parse("x_")

    def test_unclosed_group_raises(self):
        with self.assertRaises(NotationError):
            parse("x^{12")

    def test_empty_group_raises(self):
        with self.assertRaises(NotationError):
            parse("x^{}")

    def test_whitespace_only_group_raises(self):
        # Used to produce a raised space - visually a silent no-op.
        with self.assertRaises(NotationError):
            parse("x^{ }")

    def test_nested_script_raises(self):
        # Would otherwise render the literal text "a^2" in superscript.
        with self.assertRaises(NotationError) as caught:
            parse("x^{a^2}")
        self.assertIn("nested", str(caught.exception))

        with self.assertRaises(NotationError):
            parse("x_{a_2}")

    def test_marker_applied_to_marker_raises(self):
        # Would otherwise render a raised literal '^'.
        with self.assertRaises(NotationError):
            parse("x^^2")
        with self.assertRaises(NotationError):
            parse("x_^2")

    def test_error_messages_point_at_the_problem(self):
        with self.assertRaises(NotationError) as caught:
            parse("x^")
        self.assertIn("position 1", str(caught.exception))

    def test_notation_error_is_a_value_error(self):
        # Callers that only care about "bad input" can catch ValueError.
        self.assertTrue(issubclass(NotationError, ValueError))


if __name__ == "__main__":
    unittest.main()
