"""Command line entry point for rendering notation in a personalized font.

Installed as the ``handwrite-render`` command. It is deliberately kept apart
from ``handwrite.cli`` (which builds the font from a scanned form) because
the two steps are independent: you build your font once, then render as many
formulas with it as you like.

Examples
--------
Render a couple of formulas straight from the shell::

    handwrite-render --font MyFont.ttf "E = mc^2" "H_2O"

Render every line of a text file::

    handwrite-render --font MyFont.ttf --input assignment.txt --output out.html
"""

import sys
import argparse

from handwrite.notation import NotationError
from handwrite.renderer import render_to_file, FontNotFound

# Shown when the user runs the command with no formulas at all, so the demo
# is always one command away.
DEMO_FORMULAS = [
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


def read_lines(path):
    """Read non-empty lines from a text file, one formula per line."""
    with open(path, encoding="utf-8") as input_file:
        return [line.rstrip("\n") for line in input_file if line.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Render scientific notation using your handwriting font."
    )
    parser.add_argument(
        "formulas",
        nargs="*",
        help='Formulas to render, e.g. "E = mc^2". '
        "If none are given, a built-in demo set is rendered.",
    )
    parser.add_argument(
        "--font", required=True, help="Path to your generated .ttf font file"
    )
    parser.add_argument(
        "--output",
        default="notation.html",
        help="HTML file to write (default: %(default)s)",
    )
    parser.add_argument(
        "--input", default=None, help="Read formulas from a text file, one per line"
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=48,
        help="Size of normal text in pixels (default: %(default)s)",
    )

    args = parser.parse_args()

    if args.input:
        formulas = read_lines(args.input)
    elif args.formulas:
        formulas = args.formulas
    else:
        formulas = DEMO_FORMULAS

    # Bad notation and a missing font are ordinary user mistakes, so report
    # them as a short message instead of a Python traceback.
    try:
        output_path = render_to_file(
            formulas, args.font, args.output, font_size=args.font_size
        )
    except (NotationError, FontNotFound) as error:
        sys.exit("Error: {}".format(error))

    print("Wrote {} ({} line(s)).".format(output_path, len(formulas)))
    print("Open it in a browser; use the browser's Print dialog to get a PDF.")
