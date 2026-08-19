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

from handwrite.notation import parse, SUPER, SUB

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
    for token in tokens:
        text = html.escape(token.text)
        css_class = LEVEL_CLASSES.get(token.level)
        if css_class:
            pieces.append('<span class="{}">{}</span>'.format(css_class, text))
        else:
            pieces.append(text)
    return "".join(pieces)


def _encode_font(font_path):
    """Read a .ttf file and return it base64 encoded for embedding in CSS."""
    if not os.path.isfile(font_path):
        raise FontNotFound(
            "Font file not found: {}. Generate one first with the "
            "`handwrite` command.".format(font_path)
        )
    with open(font_path, "rb") as font_file:
        return base64.b64encode(font_file.read()).decode("ascii")


def render_html(sources, font_path, font_size=48, title="Handwrite"):
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

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    if isinstance(sources, str):
        sources = [sources]

    css = CSS_TEMPLATE.format(
        family=FONT_FAMILY,
        font_data=_encode_font(font_path),
        font_size=font_size,
        script_scale=SCRIPT_SCALE,
        super_raise=SUPER_RAISE,
        sub_drop=SUB_DROP,
        word_spacing=WORD_SPACING,
    )

    lines = [
        '<div class="formula">{}</div>'.format(tokens_to_html(parse(source)))
        for source in sources
    ]

    return HTML_TEMPLATE.format(
        title=html.escape(title), css=css, body="\n".join(lines)
    )


def render_to_file(sources, font_path, output_path, font_size=48, title="Handwrite"):
    """Render notation and write the resulting HTML page to ``output_path``.

    Returns the path written to, so it can be printed or opened directly.
    """
    page = render_html(sources, font_path, font_size=font_size, title=title)
    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(page)
    return output_path
