"""The only module in the application that talks to the handwriting backend.

Everything the application does with handwriting goes through the three
functions below. Nothing else imports `handwrite`, so the whole integration
is one small file you can read in a minute - and if the backend ever changes,
this is the only place that has to notice.

The backend is used exactly as it is. In particular the page images are
handed to `converters()`, which is what runs page validation and what knows
to pass the per-page glyph groups on to the font builder. Calling the stages
individually would mean reproducing that here, and getting it subtly wrong
would silently cost either the validation or the size normalisation.
"""

import shutil
from pathlib import Path
from typing import List, Sequence

from handwrite import check_coverage, converters, parse
from handwrite.renderer import tokens_to_html

# What the backend's own scan reader can open. The application never trusts a
# client-supplied filename, but the extension still has to be one of these for
# the image to be readable at all.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

PAGE_COUNT = 3


def build_font(page_paths: Sequence[Path], job_dir: Path, family_name: str) -> Path:
    """Build a handwriting font from three filled-in form pages.

    Parameters
    ----------
    page_paths
        The three page images, already in page order. Whatever they were
        called on the way in, they are copied to page_1, page_2 and page_3
        here: the backend matches scans to form pages by sorted filename, so
        the order has to be decided by the caller rather than by the client.
    job_dir
        Directory for this build. Pages, intermediate files and the finished
        font all live underneath it.
    family_name
        Font family, which is also the name of the .ttf.

    Returns
    -------
    Path
        The generated .ttf.

    Raises
    ------
    Backend exceptions are deliberately not caught: PageValidationError,
    SheetDetectionError, PotraceNotFound, FontForgeFailed and the rest carry
    messages written for the person who has to fix the problem, and the API
    layer maps them by type.
    """
    if len(page_paths) != PAGE_COUNT:
        raise ValueError(
            "Expected {} page images, got {}.".format(PAGE_COUNT, len(page_paths))
        )

    pages_dir = job_dir / "pages"
    work_dir = job_dir / "work"
    font_dir = job_dir / "font"
    for directory in (pages_dir, work_dir, font_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for number, source in enumerate(page_paths, start=1):
        suffix = Path(source).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError("Unsupported image type: {}".format(suffix or "none"))
        shutil.copyfile(source, pages_dir / "page_{}{}".format(number, suffix))

    converters(
        str(pages_dir),
        str(font_dir),
        directory=str(work_dir),
        metadata={"filename": family_name},
    )
    return font_dir / "{}.ttf".format(family_name)


def render_fragment(text: str, font_path: Path) -> str:
    """Render one line of notation as an HTML fragment.

    A fragment rather than a whole page: the font is served once at its own
    URL and applied with @font-face, so re-sending it base64-encoded on every
    keystroke would be absurd. `NotationError` is left to the caller, which
    shows it beside the input rather than treating it as a failure.
    """
    return tokens_to_html(parse(text))


def coverage(text: str, font_path: Path) -> List[str]:
    """Return the characters of `text` this font has no glyph for."""
    return check_coverage(text, str(font_path))
