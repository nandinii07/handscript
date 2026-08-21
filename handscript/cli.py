"""The ``handscript`` command line tool.

    handscript build ./handwriting --output ./my_handwriting.ttf
    handscript render ./my_handwriting.ttf "E = mc^2" "H_2O"
    handscript coverage ./my_handwriting.ttf "SO_4^{2-}"
    handscript glyphs

Installed as the ``handscript`` console script (see pyproject.toml). Every
subcommand is a thin argument-parsing layer over :class:`handscript.HandScript`
- nothing here talks to the pipeline directly.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from typing import List, Optional

from handscript import HandScript, HandScriptConfig, __version__
from handscript.exceptions import HandScriptError
from handscript.glyphs import PAGES, expected_characters
from handwrite.renderer import MissingGlyphWarning


def _read_lines(path: str) -> List[str]:
    with open(path, encoding="utf-8") as input_file:
        return [line.rstrip("\n") for line in input_file if line.strip()]


def _cmd_build(args: argparse.Namespace) -> int:
    hs = HandScript(
        HandScriptConfig(
            family_name=args.family,
            style=args.style,
            pipeline_config_path=args.config,
        )
    )
    import os

    kwargs = {
        "output_path": args.output,
        "keep_intermediates": args.keep_intermediates,
    }
    if os.path.isdir(args.input):
        kwargs["input_dir"] = args.input
    else:
        kwargs["input_path"] = args.input

    result = hs.create_font(**kwargs)
    print("Wrote {} (family {!r}).".format(result.font_path, result.family_name))
    if result.intermediates_dir:
        print("Intermediate files kept in {}.".format(result.intermediates_dir))
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    hs = HandScript(HandScriptConfig(notation_font_size=args.font_size))

    if args.input:
        formulas = _read_lines(args.input)
    elif args.formulas:
        formulas = args.formulas
    else:
        formulas = [
            "E = mc^2",
            "H_2O",
            "SO_4^{2-}",
            "x^2 + y^2 = z^2",
        ]

    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always", MissingGlyphWarning)
        output_path = hs.render(
            formulas,
            args.font,
            args.output,
            font_size=args.font_size,
            strict=args.strict,
        )
    for warning in raised:
        print("Warning: {}".format(warning.message), file=sys.stderr)

    print("Wrote {} ({} line(s)).".format(output_path, len(formulas)))
    print("Open it in a browser; use the browser's Print dialog to get a PDF.")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    hs = HandScript()
    missing = hs.check_coverage(args.text, args.font)
    if missing:
        print("Missing glyphs for: {}".format(" ".join(missing)))
        return 1
    print("Every character in the given text has a glyph in this font.")
    return 0


def _cmd_glyphs(args: argparse.Namespace) -> int:
    if args.page is not None:
        pages = [args.page - 1]
    else:
        pages = range(len(PAGES))

    for index in pages:
        chars = expected_characters(index)
        print("Page {} of {} ({} characters):".format(index + 1, len(PAGES), len(chars)))
        print("  {}".format(chars))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handscript",
        description="Turn scanned handwriting into a font, and typeset "
        "scientific notation in it.",
    )
    parser.add_argument(
        "--version", action="version", version="handscript {}".format(__version__)
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="Build a font from scanned handwriting"
    )
    build.add_argument(
        "input",
        help="Directory of scanned page images (extended form), or a single "
        "scanned page image (original form)",
    )
    build.add_argument(
        "--output", required=True, help="Where to write the finished .ttf"
    )
    build.add_argument("--family", default=None, help="Font family name")
    build.add_argument("--style", default=None, help="Font style name")
    build.add_argument(
        "--config", default=None, help="Use a custom pipeline configuration file"
    )
    build.add_argument(
        "--keep-intermediates",
        default=None,
        help="Keep per-character PNGs and traced SVGs in this directory "
        "instead of discarding them after the build",
    )
    build.set_defaults(func=_cmd_build)

    render = subparsers.add_parser(
        "render", help="Typeset notation in a font HandScript built"
    )
    render.add_argument("font", help="Path to a font built with `handscript build`")
    render.add_argument(
        "formulas",
        nargs="*",
        help='Notation to render, e.g. "E = mc^2". If none are given and '
        "--input is not set, a small demo set is rendered.",
    )
    render.add_argument(
        "--output",
        default="notation.html",
        help="HTML file to write (default: %(default)s)",
    )
    render.add_argument(
        "--input", default=None, help="Read formulas from a text file, one per line"
    )
    render.add_argument(
        "--font-size",
        type=int,
        default=48,
        help="Size of normal text in pixels (default: %(default)s)",
    )
    render.add_argument(
        "--strict",
        action="store_true",
        help="Fail if the font cannot draw a character, instead of warning",
    )
    render.set_defaults(func=_cmd_render)

    coverage = subparsers.add_parser(
        "coverage", help="Check whether a font can draw every character in some text"
    )
    coverage.add_argument("font", help="Path to a font built with `handscript build`")
    coverage.add_argument("text", nargs="+", help="Notation to check")
    coverage.set_defaults(func=_cmd_coverage)

    glyphs = subparsers.add_parser(
        "glyphs", help="List the characters HandScript expects on each form page"
    )
    glyphs.add_argument(
        "--page", type=int, default=None, help="Show only this page (1-based)"
    )
    glyphs.set_defaults(func=_cmd_glyphs)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        sys.exit(args.func(args))
    except HandScriptError as error:
        sys.exit("Error: {}".format(error))


if __name__ == "__main__":
    main()
