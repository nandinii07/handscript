"""End-to-end example: handwriting scans in, a font and a rendered formula out.

Real use
--------
Print `handwrite_sample_extended.pdf` (or run `handscript glyphs` to see what
each page expects), fill it in by hand, scan or photograph each page, put the
three images in one directory, then::

    python examples/basic_usage.py path/to/your/scanned/pages/

Running this file with no arguments
------------------------------------
With no arguments, this script generates a *synthetic* stand-in for filled-in
pages instead of using a real scan, purely so the example is runnable
end-to-end without a scanner or real handwriting sample on hand. It reuses
the project's own test fixture generator (`tests/test_sheettopng`) to do
that - it is not part of the HandScript API, and a real project would not
import it; it exists only to make this example self-contained. Point the
script at a real directory of scans (see above) to see it work on actual
handwriting.

Either way, this script uses nothing but the public `handscript` API:
`HandScript.create_font`, `.check_coverage`, and `.render`.
"""

import sys
import tempfile
from pathlib import Path

from handscript import HandScript


def synthetic_input_directory() -> Path:
    """A directory of computer-drawn stand-in pages, for a runnable demo."""
    # Imported here, not at module level, so `from handscript import
    # HandScript` above is the only import a real user of this example needs
    # to care about - this one is a repository-local test helper.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from handwrite.characters import PAGES
    from tests.test_sheettopng import render_synthetic_page

    directory = Path(tempfile.mkdtemp()) / "synthetic_handwriting"
    directory.mkdir()
    for index, page in enumerate(PAGES):
        source = render_synthetic_page(page, index)
        target = directory / "page_{}.png".format(index + 1)
        target.write_bytes(Path(source).read_bytes())
    return directory


def main() -> None:
    if len(sys.argv) > 1:
        input_dir = Path(sys.argv[1])
        print("Using scanned pages from {}".format(input_dir))
    else:
        print(
            "No input directory given - generating a synthetic sample so "
            "this example runs end-to-end. Pass a real directory of scans "
            "to build from your own handwriting instead."
        )
        input_dir = synthetic_input_directory()

    output_dir = Path(tempfile.mkdtemp()) / "handscript-example-output"
    output_dir.mkdir()
    font_path = output_dir / "my_handwriting.ttf"

    hs = HandScript()

    print("Building a font from {} ...".format(input_dir))
    result = hs.create_font(
        input_dir=str(input_dir),
        output_path=str(font_path),
        family_name="My Handwriting",
    )
    print("Built {} (family {!r}).".format(result.font_path, result.family_name))

    formula = "E = mc^2"
    missing = hs.check_coverage(formula, result.font_path)
    if missing:
        print("Font is missing glyphs for: {}".format(" ".join(missing)))
    else:
        print("Font can draw every character in {!r}.".format(formula))

    html_path = hs.render(
        [formula, "H_2O", "x^2 + y^2 = z^2"],
        result.font_path,
        output_dir / "formulas.html",
    )
    print("Rendered notation to {}".format(html_path))
    print("Open it in a browser, or use the browser's Print dialog to get a PDF.")


if __name__ == "__main__":
    main()
