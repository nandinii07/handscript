"""End to end tests for the `handwrite-render` command.

The renderer itself is covered by test_renderer.py; what is checked here is
the command wrapped around it - argument handling, reading formulas from a
file, and reporting user mistakes as a short message rather than a traceback.

These need no potrace or FontForge: rendering only reads an existing .ttf.
"""

import os
import shutil
import tempfile
import unittest
import subprocess

from handwrite.render_cli import DEMO_FORMULAS

SAMPLE_FONT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_data", "renderer", "sample.ttf"
)


def run_render(*arguments):
    """Run the command and return the completed process (never raises)."""
    return subprocess.run(
        ["handwrite-render"] + list(arguments), capture_output=True, text=True
    )


class TestRenderCLI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.output = os.path.join(self.directory, "out.html")

    def tearDown(self):
        shutil.rmtree(self.directory)

    def read_output(self):
        with open(self.output, encoding="utf-8") as output_file:
            return output_file.read()

    def test_renders_formulas_given_on_the_command_line(self):
        result = run_render(
            "--font", SAMPLE_FONT, "--output", self.output, "E = mc^2", "H_2O"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(self.output))

        page = self.read_output()
        self.assertIn("@font-face", page)
        self.assertIn('<span class="sup">2</span>', page)
        self.assertIn('<span class="sub">2</span>', page)
        self.assertEqual(page.count('<div class="formula">'), 2)

    def test_reports_what_it_wrote(self):
        result = run_render(
            "--font", SAMPLE_FONT, "--output", self.output, "x^2", "y_1"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.output, result.stdout)
        self.assertIn("2 line(s)", result.stdout)

    def test_reads_formulas_from_a_file(self):
        source = os.path.join(self.directory, "formulas.txt")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("E = mc^2\n\nSO_4^{2-}\nλ = h/p\n")

        result = run_render(
            "--font", SAMPLE_FONT, "--input", source, "--output", self.output
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        page = self.read_output()
        # Blank lines are skipped, so three formulas from four lines.
        self.assertEqual(page.count('<div class="formula">'), 3)
        self.assertIn("λ", page)

    def test_renders_the_demo_set_when_no_formulas_are_given(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_output().count('<div class="formula">'), len(DEMO_FORMULAS)
        )

    def test_font_size_is_applied(self):
        result = run_render(
            "--font", SAMPLE_FONT, "--output", self.output, "--font-size", "72", "x^2"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("font-size: 72px", self.read_output())

    def test_font_is_required(self):
        result = run_render("x^2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--font", result.stderr)

    def test_missing_font_is_reported_without_a_traceback(self):
        result = run_render(
            "--font",
            os.path.join(self.directory, "nope.ttf"),
            "--output",
            self.output,
            "x^2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertIn("Font file not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.exists(self.output))

    def test_malformed_notation_is_reported_without_a_traceback(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output, "x^")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.exists(self.output))

    def test_nested_script_is_reported_without_a_traceback(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output, "x^{a^2}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nested", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class TestRenderCLIStructures(unittest.TestCase):
    """The new structures have to work from the command line too."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.output = os.path.join(self.directory, "out.html")

    def tearDown(self):
        shutil.rmtree(self.directory)

    def read_output(self):
        with open(self.output, encoding="utf-8") as output_file:
            return output_file.read()

    def test_fraction_radical_and_limits_render(self):
        result = run_render(
            "--font",
            SAMPLE_FONT,
            "--output",
            self.output,
            "{a}/{b}",
            "√{x+1}",
            "Σ__{i=1}^^{n}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        page = self.read_output()
        self.assertIn('<span class="frac">', page)
        self.assertIn('<span class="radicand">', page)
        self.assertIn('<span class="stack">', page)

    def test_a_character_the_font_lacks_is_warned_about(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output, "x 漢")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Warning:", result.stderr)
        self.assertIn("漢", result.stderr)

    def test_strict_refuses_instead_of_warning(self):
        result = run_render(
            "--font", SAMPLE_FONT, "--output", self.output, "--strict", "x 漢"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_structure_is_reported_without_a_traceback(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output, "x^^n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class TestRenderCLIMalformedFractions(unittest.TestCase):
    """A half-written fraction must fail the command, not print braces."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.output = os.path.join(self.directory, "out.html")

    def tearDown(self):
        shutil.rmtree(self.directory)

    def test_each_malformed_form_is_reported_and_writes_nothing(self):
        for source in ("{a}/{b", "{a}/", "{a}/{", "{a}/x"):
            with self.subTest(source=source):
                result = run_render(
                    "--font", SAMPLE_FONT, "--output", self.output, source
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(os.path.exists(self.output))

    def test_a_valid_fraction_still_renders(self):
        result = run_render("--font", SAMPLE_FONT, "--output", self.output, "{a}/{b}")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.output, encoding="utf-8") as handle:
            self.assertIn('<span class="frac">', handle.read())


if __name__ == "__main__":
    unittest.main()
