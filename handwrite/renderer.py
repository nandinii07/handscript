"""Render parsed notation as HTML styled with the user's personalized font.

This is the second half of the notation layer. ``notation.py`` decides *what
level* each piece of text sits at; this module decides *how* that level is
drawn, and it does so with plain CSS.

Why CSS rather than new glyphs: a superscript two and an ordinary two are the
same handwritten shape at a different size and height. So instead of asking
the user to write a separate superscript two, we take their ordinary "2"
glyph out of the generated font and let the browser scale and shift it. That
is the whole trick, and it is why the handwriting form never needs
superscript or subscript boxes.

The generated HTML is self-contained: the .ttf is embedded directly into the
file as a base64 ``@font-face`` source, so the HTML can be emailed, moved or
opened offline and still show the user's handwriting.
"""

import os
import html
import base64
import warnings

from handwrite.notation import (
    parse,
    rendered_characters,
    Fraction,
    Radical,
    Stack,
    RADICAL_SIGN,
    SUPER,
    SUB,
)
from handwrite.fontinfo import missing_characters

# ---------------------------------------------------------------------------
# Typography settings. These are the only numbers that control how a
# superscript or subscript looks, so they are kept together and named.
# They are in `em`, i.e. relative to the surrounding text size.
# ---------------------------------------------------------------------------

# How much smaller a raised/lowered character is than normal text.
SCRIPT_SCALE = 0.62

# How far a superscript is pushed up, and a subscript pushed down. These are
# measured in em of the *small* text, so the shift actually seen on the page
# is roughly SCRIPT_SCALE times these numbers.
SUPER_RAISE = 0.62
SUB_DROP = 0.28

# The generated fonts use a fairly wide space glyph (half an em) on top of the
# per-glyph side bearings, which leaves gaps around "=" and similar looking
# too airy. A small negative word-spacing pulls words back together. Raise
# towards 0 if a particular font already looks well spaced.
WORD_SPACING = -0.12

# How much smaller the halves of a fraction, and anything set over or under a
# base, are drawn than the text around them. Larger than SCRIPT_SCALE because
# these are read as content in their own right, not as a modifier on a base.
STACKED_SCALE = 0.78

# Thickness of the fraction bar and the line over a radicand, in em, so it
# grows with the text. Handwriting is not a hairline, and a thin browser rule
# beside it looks mechanical.
RULE_THICKNESS = 0.055

# Internal name the embedded font is registered under. The name is arbitrary
# because the font travels inside the HTML file itself.
FONT_FAMILY = "HandwriteUserFont"

CSS_TEMPLATE = """
@font-face {{
    font-family: '{family}';
    src: url(data:font/ttf;base64,{font_data}) format('truetype');
}}

body {{
    background: #ffffff;
    color: #111111;
    margin: 40px;
    font-family: '{family}', serif;
}}

.formula {{
    font-size: {font_size}px;
    line-height: 1.6;
    word-spacing: {word_spacing}em;
    white-space: pre-wrap;
}}

/* A raised character: smaller, and lifted above the baseline. */
.sup {{
    font-size: {script_scale}em;
    vertical-align: {super_raise}em;
}}

/* A lowered character: smaller, and dropped below the baseline. */
.sub {{
    font-size: {script_scale}em;
    vertical-align: -{sub_drop}em;
}}

/* A stacked fraction. The two halves are ordinary lines of handwriting; the
   rule between them is drawn by the browser, because a stretched glyph would
   have to be distorted to reach across. */
.frac {{
    display: inline-block;
    vertical-align: middle;
    text-align: center;
    font-size: {stacked_scale}em;
    line-height: 1.15;
}}

.frac .num {{
    display: block;
    padding: 0 0.15em;
    border-bottom: {rule_thickness}em solid currentColor;
}}

.frac .den {{
    display: block;
    padding: 0 0.15em;
}}

/* A radical: the handwritten sign, then the radicand under its own rule. */
.radical .radicand {{
    border-top: {rule_thickness}em solid currentColor;
    padding: 0 0.1em 0 0.05em;
    margin-left: 0.02em;
}}

/* Something set above and/or below a base, for limits and accents. */
.stack {{
    display: inline-block;
    vertical-align: middle;
    text-align: center;
    line-height: 1.05;
}}

.stack .over,
.stack .under {{
    display: block;
    font-size: {stacked_scale}em;
}}

.stack .base {{
    display: block;
}}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""

# Which CSS class each token level maps to. NORMAL has no class because
# baseline text needs no adjustment at all.
LEVEL_CLASSES = {SUPER: "sup", SUB: "sub"}


class FontNotFound(Exception):
    """Raised when the personalized .ttf to render with cannot be found."""


class MissingGlyphWarning(UserWarning):
    """Warns that a character will not be drawn in the user's handwriting."""


def tokens_to_html(tokens):
    """Convert parsed tokens into an HTML fragment.

    Each raised or lowered token becomes a ``<span>`` carrying the CSS class
    for its level, so all of the size and position work is left to the
    stylesheet. Normal text is emitted as-is.

    Tokens are rendered in reading order, so ``SO_4^{2-}`` produces the
    subscript and then the superscript side by side, matching how the
    formula is normally written.

    Parameters
    ----------
    tokens : list of Token
        Output of ``handwrite.notation.parse``.

    Returns
    -------
    str
        HTML fragment. All text is escaped, so characters like ``&`` from
        the handwriting form are safe to include.
    """
    pieces = []
    for item in tokens:
        pieces.append(_item_to_html(item))
    return "".join(pieces)


def _item_to_html(item):
    """Render one parsed item, recursing into structures that hold others."""
    if isinstance(item, Fraction):
        return (
            '<span class="frac">'
            '<span class="num">{}</span>'
            '<span class="den">{}</span>'
            "</span>"
        ).format(tokens_to_html(item.numerator), tokens_to_html(item.denominator))

    if isinstance(item, Radical):
        # The sign itself is the user's own glyph; only the line over the
        # radicand is drawn by the browser.
        return (
            '<span class="radical">{sign}'
            '<span class="radicand">{content}</span>'
            "</span>"
        ).format(sign=html.escape(RADICAL_SIGN), content=tokens_to_html(item.radicand))

    if isinstance(item, Stack):
        parts = []
        if item.over:
            parts.append(
                '<span class="over">{}</span>'.format(tokens_to_html(item.over))
            )
        parts.append('<span class="base">{}</span>'.format(_item_to_html(item.base)))
        if item.under:
            parts.append(
                '<span class="under">{}</span>'.format(tokens_to_html(item.under))
            )
        return '<span class="stack">{}</span>'.format("".join(parts))

    text = html.escape(item.text)
    css_class = LEVEL_CLASSES.get(item.level)
    if css_class:
        return '<span class="{}">{}</span>'.format(css_class, text)
    return text


class MissingGlyphs(Exception):
    """Raised when the font has no glyph for a character being rendered."""


def _read_font(font_path):
    """Return the raw bytes of the .ttf to render with."""
    if not os.path.isfile(font_path):
        raise FontNotFound(
            "Font file not found: {}. Generate one first with the "
            "`handwrite` command.".format(font_path)
        )
    with open(font_path, "rb") as font_file:
        return font_file.read()


def check_coverage(sources, font_path):
    """Return the characters in `sources` the font cannot draw.

    The page names the user's font first in the CSS stack, so anything it
    lacks is quietly drawn by some other font. On a page of handwriting that
    stands out badly, and nothing else in the pipeline would mention it.
    """
    if isinstance(sources, str):
        sources = [sources]
    drawn = "".join(rendered_characters(parse(source)) for source in sources)
    return missing_characters(drawn, _read_font(font_path))


def render_html(sources, font_path, font_size=48, title="Handwrite", strict=False):
    """Render one or more notation strings into a complete HTML page.

    Parameters
    ----------
    sources : str or list of str
        Notation to render. A list produces one line per entry.
    font_path : str
        Path to the personalized .ttf produced by the handwriting pipeline.
    font_size : int, default=48
        Size of normal (baseline) text, in pixels.
    title : str
        Page title.
    strict : bool, default=False
        Raise `MissingGlyphs` if the font cannot draw one of the characters,
        rather than warning about it. Either way it is never silent.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    if isinstance(sources, str):
        sources = [sources]

    font_data = _read_font(font_path)

    # Parsed once: the same items are measured for coverage and rendered, so
    # the check is about what actually reaches the page.
    parsed = [parse(source) for source in sources]
    drawn = "".join(rendered_characters(items) for items in parsed)

    missing = missing_characters(drawn, font_data)
    if missing:
        complaint = (
            "The font has no glyph for: {}. These will be drawn in some other "
            "font, which will not look like your handwriting. Collect them on "
            "the form, or leave them out.".format(" ".join(missing))
        )
        if strict:
            raise MissingGlyphs(complaint)
        warnings.warn(complaint, MissingGlyphWarning, stacklevel=2)

    css = CSS_TEMPLATE.format(
        family=FONT_FAMILY,
        font_data=base64.b64encode(font_data).decode("ascii"),
        font_size=font_size,
        script_scale=SCRIPT_SCALE,
        super_raise=SUPER_RAISE,
        sub_drop=SUB_DROP,
        word_spacing=WORD_SPACING,
        stacked_scale=STACKED_SCALE,
        rule_thickness=RULE_THICKNESS,
    )

    lines = [
        '<div class="formula">{}</div>'.format(tokens_to_html(items))
        for items in parsed
    ]

    return HTML_TEMPLATE.format(
        title=html.escape(title), css=css, body="\n".join(lines)
    )


def render_to_file(
    sources, font_path, output_path, font_size=48, title="Handwrite", strict=False
):
    """Render notation and write the resulting HTML page to ``output_path``.

    Returns the path written to, so it can be printed or opened directly.
    """
    page = render_html(
        sources, font_path, font_size=font_size, title=title, strict=strict
    )
    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(page)
    return output_path
