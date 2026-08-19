"""Parse simple scientific notation into positioned text tokens.

This module is the "notation layer" of the project. It is deliberately
separate from the handwriting pipeline (sheettopng / pngtosvg / svgtottf):
that pipeline turns handwriting into a font, and this module decides where
each typed character should sit once that font is used.

The key idea of the project lives here. We do NOT collect separate
handwriting samples for characters like squared/subscript-two. Instead the
parser marks each character with a *level*:

    normal      - sit on the baseline at full size
    super       - shrink and raise  (written as ^ in the input)
    sub         - shrink and lower  (written as _ in the input)

The renderer then reuses the user's ordinary handwritten glyph and simply
scales/moves it. So one handwritten "2" serves for 2, squared and sub-two.

Supported syntax (a small LaTeX-like subset, NOT a full LaTeX parser):

    x^2             single character superscript
    H_2O            single character subscript
    x_1^2           subscript and superscript on the same base
    x^{10}          grouped superscript, braces hold more than one character
    A_{ij}          grouped subscript
    SO_4^{2-}       both, with a grouped superscript

Anything that is not ^, _ or a group is ordinary text and is emitted
unchanged, so Greek letters, math operators, brackets and arrows from the
extended handwriting form all pass straight through.

The syntax is deliberately small, and the edges of it are defined rather than
left to chance:

* ``{`` and ``}`` are only special immediately after a ``^`` or ``_``.
  Everywhere else they are ordinary characters (the handwriting form collects
  braces as glyphs), so ``f{x}`` is plain text.
* One level only. ``x^{a^2}`` is rejected instead of being rendered as the
  literal text "a^2" at superscript level, because quietly dropping the inner
  marker would produce a wrong-looking formula with no warning.
* Everything rejected raises `NotationError`, never a partial or misleading
  result.
"""

from collections import namedtuple

# The three levels a token can sit at.
NORMAL = "normal"
SUPER = "super"
SUB = "sub"

# A Token is just a piece of text plus the level it should be drawn at.
# Using a namedtuple keeps it lightweight and easy to print/compare in tests.
Token = namedtuple("Token", ["text", "level"])

# The characters that introduce a raised or lowered piece of text.
LEVEL_MARKERS = {"^": SUPER, "_": SUB}

GROUP_OPEN = "{"
GROUP_CLOSE = "}"


class NotationError(ValueError):
    """Raised when the input uses the notation syntax incorrectly."""


def parse(source):
    """Turn a notation string into a flat list of Token objects.

    Parameters
    ----------
    source : str
        Text using the notation syntax, for example ``"SO_4^{2-}"``.

    Returns
    -------
    list of Token
        Tokens in reading order. Consecutive ordinary characters are merged
        into a single NORMAL token so the output stays small and readable.

    Raises
    ------
    NotationError
        If ``^`` or ``_`` has nothing after it, or is applied to another
        marker, or a ``{`` is never closed, or a group is empty, or a group
        contains a further ``^``/``_`` (nesting is not supported).

    Examples
    --------
    >>> describe(parse("x^2"))
    "'x'(normal) '2'(super)"
    >>> describe(parse("H_2O"))
    "'H'(normal) '2'(sub) 'O'(normal)"
    """
    tokens = []
    plain_text = []  # buffer of ordinary characters seen since the last token
    index = 0

    def flush_plain_text():
        """Move any buffered ordinary characters into a NORMAL token."""
        if plain_text:
            tokens.append(Token("".join(plain_text), NORMAL))
            plain_text.clear()

    while index < len(source):
        character = source[index]

        if character in LEVEL_MARKERS:
            # A ^ or _ always applies to whatever comes immediately after it,
            # so anything buffered before it is finished and can be emitted.
            flush_plain_text()
            level = LEVEL_MARKERS[character]
            text, index = _read_target(source, index)
            tokens.append(Token(text, level))
        else:
            plain_text.append(character)
            index += 1

    flush_plain_text()
    return tokens


def _read_target(source, marker_index):
    """Read the text a ``^`` or ``_`` applies to.

    Called with ``marker_index`` pointing at the ``^``/``_`` itself. Returns
    the text that should be raised/lowered, plus the index to carry on
    reading from.

    Following LaTeX, a bare marker takes exactly one character (``x^12`` is
    "x", superscript "1", then a normal "2"), while braces take everything
    up to the closing brace (``x^{12}`` superscripts both digits).

    Malformed input is rejected here rather than being given a best guess, so
    a formula either renders as written or fails with a message pointing at
    the character that caused the problem.
    """
    marker = source[marker_index]
    content_start = marker_index + 1

    if content_start >= len(source):
        raise NotationError(
            "'{}' at position {} has nothing after it.".format(marker, marker_index)
        )

    if source[content_start] == GROUP_OPEN:
        close_index = source.find(GROUP_CLOSE, content_start + 1)
        if close_index == -1:
            raise NotationError(
                "Unclosed '{}' after '{}' at position {}.".format(
                    GROUP_OPEN, marker, marker_index
                )
            )
        text = source[content_start + 1 : close_index]
        if not text.strip():
            raise NotationError(
                "Empty group after '{}' at position {}.".format(marker, marker_index)
            )
        nested = [m for m in LEVEL_MARKERS if m in text]
        if nested:
            # Without this the inner marker would be emitted as a literal
            # character inside the raised text, i.e. "x^{a^2}" would silently
            # render as "a^2" in superscript. One level is all this parser
            # supports, so say so instead.
            raise NotationError(
                "'{}' inside the group after '{}' at position {}: nested "
                "superscripts/subscripts are not supported.".format(
                    nested[0], marker, marker_index
                )
            )
        # Continue reading just past the closing brace.
        return text, close_index + 1

    target = source[content_start]
    if target in LEVEL_MARKERS:
        # "x^^2" - the same silent-nonsense problem as above, one character
        # at a time.
        raise NotationError(
            "'{}' at position {} cannot be applied to '{}'.".format(
                marker, marker_index, target
            )
        )

    # No braces: the marker applies to exactly one character.
    return target, content_start + 1


def describe(tokens):
    """Return a short human readable summary of tokens, handy for debugging.

    Example
    -------
    >>> describe(parse("x^2"))
    "'x'(normal) '2'(super)"
    """
    return " ".join("'{}'({})".format(token.text, token.level) for token in tokens)
