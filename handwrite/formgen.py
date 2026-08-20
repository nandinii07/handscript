"""Generate the printable handwriting sample form.

The form is a multi-page PDF: one page per entry in ``handwrite.characters.PAGES``.
Each page draws a `cols x rows` grid of boxes, with the character the user
should write printed as a small label underneath the box.

IMPORTANT: the printed label is only a guide for the human filling in the
form. SHEETtoPNG never reads it. Once scanned, a box is identified purely by
its position (row/column) on the page, and that position is looked up in
`characters.PAGES` to find the matching Unicode character - exactly like the
original single-page form worked, just extended to more than one page.

Every page is laid out on the SAME reference grid (see REFERENCE_ROWS), so a
box is physically the same size on page 2 as it is on page 1. That matters
more than it looks: `PNGtoSVG.pngToBmp` scales every cropped box to a fixed
100x100 bitmap, so boxes of a different shape would hand FontForge glyphs
stretched by a different amount, and the new characters would come out visibly
wider or thinner than the Latin ones.
"""

import os

from PIL import Image, ImageDraw, ImageFont

from handwrite.characters import PAGES

DPI = 150
PAGE_WIDTH = int(8.27 * DPI)  # A4 portrait, in pixels
PAGE_HEIGHT = int(11.69 * DPI)
MARGIN = int(0.5 * DPI)
TITLE_HEIGHT = int(0.9 * DPI)
LABEL_HEIGHT = int(0.3 * DPI)
CELL_GAP = int(0.12 * DPI)

# Distance from the bottom of a box to where its label is drawn.
LABEL_GAP = 4

# The grid every page is measured against. A page may use fewer columns or
# rows than this (page 2 only needs 5 rows), but never a different cell size:
# cell width/height are always computed from these numbers, so a box is
# identical on every page. These are the original page-1 numbers, which keeps
# page 1 pixel-for-pixel the same as it has always been - and therefore keeps
# the bearing/kerning values in default.json valid.
REFERENCE_COLS = 8
REFERENCE_ROWS = 10

# Fonts that can render every label this form needs (Greek, math operators,
# arrows). Tried in order; the first one that loads AND covers all the labels
# wins. DejaVu first because that is what the form was originally designed
# with, then the usual broad-coverage fonts on macOS and Windows.
FONT_CANDIDATES = [
    # Linux
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    # macOS
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
    ("/Library/Fonts/Arial Unicode.ttf", None),
    (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    ),
    # Windows
    ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
    ("C:\\Windows\\Fonts\\seguisym.ttf", None),
]

# Escape hatch when none of the above exist: point this at any .ttf that
# covers the character set.
FONT_ENV_VAR = "HANDWRITE_FORM_FONT"

# A codepoint no real font has a glyph for. Anything that renders identically
# to this is being drawn as .notdef ("tofu"), i.e. it is missing.
_UNMAPPED_CODEPOINT = "\uffff"


class FormFontNotFound(Exception):
    """Raised when no available font can render the form's labels."""


def _render(font, character, size):
    """Draw one character on a blank tile and return the raw pixels."""
    tile = Image.new("L", (size * 3, size * 3), 0)
    ImageDraw.Draw(tile).text((size // 2, size // 2), character, fill=255, font=font)
    return tile.tobytes()


def _missing_glyphs(font, characters, size):
    """Return the characters `font` has no glyph for.

    PIL will happily draw a missing character as .notdef and report success,
    which is exactly how a form full of empty or identical boxes gets
    generated without anyone noticing. Rendering a codepoint no font can have
    a glyph for gives us the shape of "missing", and anything that matches it
    is missing too.
    """
    missing = _render(font, _UNMAPPED_CODEPOINT, size)
    return [c for c in characters if _render(font, c, size) == missing]


def resolve_fonts(required_characters, font_path=None):
    """Pick a font that can draw every label, and return (label, title) fonts.

    Public because the test suite draws stand-in "filled in" pages with the
    same font this module prints labels with, and hardcoding a path in two
    places is how the two drift apart.

    Parameters
    ----------
    required_characters : iterable of str
        Every character that will be printed as a label.
    font_path : str, optional
        Explicit .ttf to use, overriding the search.

    Returns
    -------
    tuple
        ``(label_font, title_font)``.

    Raises
    ------
    FormFontNotFound
        If no candidate font exists, or none covers the character set. The
        old behaviour here was to fall back to PIL's built-in bitmap font,
        which cannot draw Greek or math symbols at any size - so the form
        was generated looking fine and was unusable.
    """
    label_size, title_size = int(0.16 * DPI), int(0.4 * DPI)
    required_characters = list(required_characters)

    explicit = font_path or os.environ.get(FONT_ENV_VAR)
    candidates = [(explicit, None)] if explicit else list(FONT_CANDIDATES)

    tried, incomplete = [], []
    for regular, bold in candidates:
        try:
            label_font = ImageFont.truetype(regular, label_size)
        except OSError:
            tried.append(regular)
            continue

        missing = _missing_glyphs(label_font, required_characters, label_size)
        if missing:
            incomplete.append((regular, missing))
            continue

        try:
            title_font = ImageFont.truetype(bold or regular, title_size)
        except OSError:
            title_font = ImageFont.truetype(regular, title_size)
        return label_font, title_font

    message = [
        "No font available that can print this form's labels.",
        "Tried: {}.".format(", ".join(tried) or "none"),
    ]
    for path, missing in incomplete:
        message.append(
            "{} is missing {}.".format(
                path, " ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
            )
        )
    message.append(
        "Install DejaVu Sans, or set {}=/path/to/font.ttf to a font covering "
        "Greek letters, math operators and arrows.".format(FONT_ENV_VAR)
    )
    raise FormFontNotFound(" ".join(message))


def cell_geometry():
    """Return ``(cell_width, cell_height, box_height)`` for the reference grid.

    Shared with the tests so that a synthetic "filled in" page cannot drift
    away from the page this module actually prints.
    """
    grid_width = PAGE_WIDTH - 2 * MARGIN
    grid_height = PAGE_HEIGHT - TITLE_HEIGHT - MARGIN

    cell_width = (grid_width - (REFERENCE_COLS - 1) * CELL_GAP) // REFERENCE_COLS
    cell_height = (grid_height - (REFERENCE_ROWS - 1) * CELL_GAP) // REFERENCE_ROWS
    return cell_width, cell_height, cell_height - LABEL_HEIGHT


def iter_boxes(page):
    """Yield ``(index, x0, y0, x1, y1)`` for every box on `page`.

    Boxes come out in the same left-to-right, top-to-bottom order that
    `SHEETtoPNG.detect_characters` sorts scanned boxes into, which is what
    makes "box number N holds character N" true on both sides.
    """
    cols, rows = page["cols"], page["rows"]
    if cols > REFERENCE_COLS or rows > REFERENCE_ROWS:
        raise ValueError(
            "Page grid {}x{} does not fit the {}x{} reference grid.".format(
                cols, rows, REFERENCE_COLS, REFERENCE_ROWS
            )
        )

    cell_width, cell_height, box_height = cell_geometry()
    for index in range(cols * rows):
        row, col = divmod(index, cols)
        x0 = MARGIN + col * (cell_width + CELL_GAP)
        y0 = TITLE_HEIGHT + row * (cell_height + CELL_GAP)
        yield index, x0, y0, x0 + cell_width, y0 + box_height


def _below_baseline_lift(bbox, font):
    """Return how far to lift a label whose ink sits below the baseline.

    Labels are positioned from the font's ascender line, which puts every
    ordinary glyph's ink near the middle of the label band. A glyph drawn
    entirely at or below the baseline lands right at the bottom of that band
    instead: on the printed form the underscore came out as a low, detached
    rule that reads as a stray line rather than as the character's name.

    Lifting such a label until its ink is centred in the band puts it back in
    line with its neighbours. Ordinary glyphs return 0 and are drawn exactly
    where they always were - in the full 191 character set the underscore is
    the only label this applies to.

    This affects the printed label only. Nothing about how a handwritten
    underscore is scanned, traced or built into the font goes through here.
    """
    ascent, _descent = font.getmetrics()
    if bbox[1] < ascent:
        return 0

    ink_centre = LABEL_GAP + (bbox[1] + bbox[3]) / 2
    return -round(ink_centre - LABEL_HEIGHT / 2)


def _draw_page(page_number, total_pages, page, label_font, title_font):
    """Render a single form page (one PIL Image) for the given page definition."""
    chars = page["chars"]

    img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(img)

    title = "Handwrite - Page {} of {}".format(page_number, total_pages)
    draw.text((MARGIN, MARGIN // 2), title, fill="black", font=title_font)

    cell_width, _, box_height = cell_geometry()

    for index, x0, y0, x1, y1 in iter_boxes(page):
        if index < len(chars):
            # A real box: draw the border, a faint writing baseline, and the
            # character label underneath it.
            draw.rectangle([x0, y0, x1, y1], outline="black", width=2)

            baseline_y = y0 + int(box_height * 0.72)
            draw.line(
                [x0 + 4, baseline_y, x1 - 4, baseline_y],
                fill=(200, 200, 200),
                width=1,
            )

            label = chr(chars[index])
            bbox = draw.textbbox((0, 0), label, font=label_font)
            label_w = bbox[2] - bbox[0]
            label_x = x0 + (cell_width - label_w) // 2
            label_y = y1 + LABEL_GAP + _below_baseline_lift(bbox, label_font)
            draw.text((label_x, label_y), label, fill="black", font=label_font)
        else:
            # Leftover box on this page (cols*rows > number of characters).
            # IMPORTANT: the border must still be solid black, same as a
            # real box - SHEETtoPNG detects boxes purely from their black
            # outline, so a lighter outline here would make it invisible to
            # contour detection and throw off the row/column count. Only the
            # interior "do not write here" cross is drawn lighter, since box
            # *content* is never used to find the boxes, only the border.
            draw.rectangle([x0, y0, x1, y1], outline="black", width=2)
            draw.line([x0, y0, x1, y1], fill=(200, 200, 200), width=1)
            draw.line([x0, y1, x1, y0], fill=(200, 200, 200), width=1)

    return img


def generate_form(
    output_path="handwrite_sample_extended.pdf", pages=None, font_path=None
):
    """Render the full multi-page handwriting form to a single PDF file.

    Parameters
    ----------
    output_path : str
        Where to write the generated PDF.
    pages : list of dict, optional
        Defaults to ``handwrite.characters.PAGES``. Each entry needs
        ``cols``, ``rows`` and ``chars`` keys.
    font_path : str, optional
        Font to print the labels with. Defaults to searching
        ``FONT_CANDIDATES`` / the ``HANDWRITE_FORM_FONT`` environment
        variable.

    Returns
    -------
    str
        The output_path that was written to.

    Raises
    ------
    FormFontNotFound
        If no font is available that can draw every label.
    """
    if pages is None:
        pages = PAGES

    labels = [chr(c) for page in pages for c in page["chars"]]
    label_font, title_font = resolve_fonts(labels, font_path)

    images = [
        _draw_page(i + 1, len(pages), page, label_font, title_font)
        for i, page in enumerate(pages)
    ]

    # Pillow lazily registers its format plugins (JPEG, etc.) the first time
    # Image.open()/Image.init() runs. Since this script only ever calls
    # Image.new()/save(), make sure that registration has happened - the PDF
    # writer needs the JPEG encoder available even for a lossless save.
    Image.init()

    first_page, remaining_pages = images[0], images[1:]
    first_page.save(output_path, save_all=True, append_images=remaining_pages)
    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate the printable handwriting sample form."
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default="handwrite_sample_extended.pdf",
        help="PDF file to write (default: %(default)s)",
    )
    parser.add_argument(
        "--font",
        default=None,
        help="Font used to print the character labels (default: auto-detect)",
    )
    args = parser.parse_args()

    written_path = generate_form(args.output_path, font_path=args.font)
    print("Wrote {}".format(os.path.abspath(written_path)))


if __name__ == "__main__":
    main()
