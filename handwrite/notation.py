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

Four structures go beyond a single run of characters. Each is built from the
same braces, and each nests:

    {a}/{b}         a stacked fraction
    √{x+1}          a radical, with a line over the radicand
    Σ__{i=1}^^{n}   limits set under and over a base
    v^^{→}          the user's own arrow glyph drawn over the v

``^^`` and ``__`` are spelled as doubled markers because a doubled marker was
previously always an error, so no formula that used to work can quietly
change meaning.

Anything that is not one of those is ordinary text and is emitted unchanged,
so Greek letters, math operators, brackets and arrows from the extended
handwriting form all pass straight through.

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

# The structures below are the only things in the notation that are not a
# straight run of characters. Each holds *lists of items*, where an item is
# either a Token or another structure, so they nest. Ordinary formulas never
# produce any of them and come out as the same flat list of Tokens as always.
Fraction = namedtuple("Fraction", ["numerator", "denominator"])
Radical = namedtuple("Radical", ["radicand"])
Stack = namedtuple("Stack", ["base", "over", "under"])

# The characters that introduce a raised or lowered piece of text.
LEVEL_MARKERS = {"^": SUPER, "_": SUB}

# Doubled markers put something above or below what precedes it. They are
# spelled this way because a doubled marker was previously always an error,
# so no formula that used to work can change meaning.
OVER_MARKER = "^^"
UNDER_MARKER = "__"

# The square root sign, which the form collects as an ordinary glyph. Followed
# by a group it draws a proper radical with a line over the radicand.
RADICAL_SIGN = "√"

# Between two groups this makes a stacked fraction: {a}/{b}. On its own it is
# still an ordinary divide, so "h/p" is unaffected.
FRACTION_SLASH = "/"

GROUP_OPEN = "{"
GROUP_CLOSE = "}"


class NotationError(ValueError):
    """Raised when the input uses the notation syntax incorrectly."""


def parse(source):
    """Turn a notation string into a list of items in reading order.

    Parameters
    ----------
    source : str
        Text using the notation syntax, for example ``"SO_4^{2-}"``.

    Returns
    -------
    list
        Tokens in reading order, with a Fraction, Radical or Stack wherever
        the source used one. Consecutive ordinary characters are merged into
        a single NORMAL token so the output stays small and readable, and a
        formula using none of the structures comes out as a flat list of
        Tokens exactly as it always did.

    Raises
    ------
    NotationError
        If ``^`` or ``_`` has nothing after it, or is applied to another
        marker, or a ``{`` is never closed, or a group is empty, or a group
        contains a further ``^``/``_`` (nesting is not supported), or a
        doubled marker has nothing to sit over.

    Examples
    --------
    >>> describe(parse("x^2"))
    "'x'(normal) '2'(super)"
    >>> describe(parse("H_2O"))
    "'H'(normal) '2'(sub) 'O'(normal)"
    """
    items = []
    plain_text = []  # buffer of ordinary characters seen since the last item
    index = 0

    def flush_plain_text():
        """Move any buffered ordinary characters into a NORMAL token."""
        if plain_text:
            items.append(Token("".join(plain_text), NORMAL))
            del plain_text[:]

    def take_base(marker):
        """Remove and return the thing a doubled marker applies to."""
        if plain_text:
            character = plain_text.pop()
            flush_plain_text()  # whatever came before it is finished
            return Token(character, NORMAL)
        if items:
            return items.pop()
        raise NotationError(
            "'{}' has nothing before it to sit over or under.".format(marker)
        )

    while index < len(source):
        character = source[index]
        pair = source[index : index + 2]

        if pair in (OVER_MARKER, UNDER_MARKER):
            content, index = _read_structural_group(source, index + 2, pair)
            base = take_base(pair)
            items.append(_stack(base, pair, parse(content)))

        elif character in LEVEL_MARKERS:
            # A ^ or _ always applies to whatever comes immediately after it,
            # so anything buffered before it is finished and can be emitted.
            flush_plain_text()
            level = LEVEL_MARKERS[character]
            text, index = _read_target(source, index)
            items.append(Token(text, level))

        elif character == RADICAL_SIGN and source[index + 1 : index + 2] == GROUP_OPEN:
            flush_plain_text()
            content, index = _read_structural_group(
                source, index + 1, RADICAL_SIGN, opened=True
            )
            items.append(Radical(parse(content)))

        elif character == GROUP_OPEN:
            fraction = _read_fraction(source, index)
            base_group = None if fraction else _read_base_group(source, index)

            if base_group is not None:
                # A group standing in front of a doubled marker is the base
                # for it, so limits can sit under a whole word: {lim}__{x→0}.
                content, index = base_group
                flush_plain_text()
                items.append(_single_item(content))

            elif fraction is None:
                # Not a fraction, so the brace is an ordinary character, as it
                # has always been. Fall through one character at a time so the
                # contents are read normally.
                plain_text.append(character)
                index += 1
            else:
                numerator, denominator, index = fraction
                flush_plain_text()
                items.append(Fraction(parse(numerator), parse(denominator)))

        else:
            plain_text.append(character)
            index += 1

    flush_plain_text()
    return items


def _stack(base, marker, content):
    """Attach `content` above or below `base`, merging with any existing stack.

    Merging is what lets a large operator carry both limits: the under is
    written first, and the over then lands on the same stack rather than
    wrapping it in a second one.
    """
    if isinstance(base, Stack):
        over, under = base.over, base.under
        base = base.base
    else:
        over, under = [], []

    if marker == OVER_MARKER:
        if over:
            raise NotationError("'{}' is already set over this.".format(OVER_MARKER))
        over = content
    else:
        if under:
            raise NotationError("'{}' is already set under this.".format(UNDER_MARKER))
        under = content

    if not over and not under:
        raise NotationError("'{}' was given nothing to place.".format(marker))
    return Stack(base, over, under)


def _read_structural_group(source, index, marker, opened=False):
    """Read a braced sub-expression, returning its contents and what follows.

    Unlike the group after a ``^`` or ``_``, this one may itself contain
    notation, so braces are counted rather than stopping at the first close.
    """
    if not opened and source[index : index + 1] != GROUP_OPEN:
        raise NotationError(
            "'{}' must be followed by a group in braces.".format(marker)
        )

    group = _read_group(source, index)
    if group is None:
        raise NotationError("Unclosed '{}' after '{}'.".format(GROUP_OPEN, marker))

    content, after = group
    if not content.strip():
        raise NotationError("Empty group after '{}'.".format(marker))
    return content, after


def _read_group(source, open_index):
    """Return (contents, index after the group) for a balanced brace group.

    Returns None when the braces do not balance, so a caller can decide the
    text was never a group at all rather than treating it as an error.
    """
    if source[open_index : open_index + 1] != GROUP_OPEN:
        return None

    depth = 0
    for index in range(open_index, len(source)):
        if source[index] == GROUP_OPEN:
            depth += 1
        elif source[index] == GROUP_CLOSE:
            depth -= 1
            if depth == 0:
                return source[open_index + 1 : index], index + 1
    return None


def _read_base_group(source, index):
    """Recognise ``{...}`` standing in front of a ``^^`` or ``__``.

    Without this the base is the single character before the marker, which is
    right for a symbol but wrong for a word: "lim__{x→0}" would hang the
    limit under the "m" alone.
    """
    group = _read_group(source, index)
    if group is None:
        return None

    content, after = group
    if source[after : after + 2] not in (OVER_MARKER, UNDER_MARKER):
        return None
    if not content.strip():
        raise NotationError(
            "Empty group before '{}'.".format(source[after : after + 2])
        )
    return content, after


def _single_item(content):
    """Parse a base group, which has to come out as exactly one item."""
    items = parse(content)
    if len(items) != 1:
        raise NotationError(
            "The group before a doubled marker must be one run of text, "
            "not {!r}.".format(content)
        )
    return items[0]


def _read_fraction(source, index):
    """Recognise ``{a}/{b}`` at `index`, or return None if that is not it.

    A brace group followed by a slash is the point of no return. Up to there
    the braces may still be ordinary characters - ``{1,2}`` is text, and so
    is ``{a} b`` - but once a slash follows a group the only thing it can be
    is a fraction, so anything wrong with the denominator is an error.

    Committing here is what stops ``{a}/{b`` from quietly printing its own
    braces, which is the one place the notation used to render something the
    writer plainly did not mean.
    """
    first = _read_group(source, index)
    if first is None:
        return None

    numerator, after = first
    if source[after : after + 1] != FRACTION_SLASH:
        return None

    second = _read_group(source, after + 1)
    if second is None:
        if source[after + 1 : after + 2] != GROUP_OPEN:
            raise NotationError(
                "A fraction needs its denominator in braces, as in "
                "'{{a}}/{{b}}'. Nothing usable follows the '/' at position "
                "{}.".format(after)
            )
        raise NotationError(
            "Unclosed '{{' in the denominator of the fraction starting at "
            "position {}.".format(index)
        )

    denominator, end = second
    if not numerator.strip() or not denominator.strip():
        raise NotationError("A fraction needs both a numerator and a denominator.")
    return numerator, denominator, end


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


def rendered_characters(items):
    """Return every character these items will actually put on the page.

    Not the same as the source text: ``^``, ``_``, braces and a fraction's
    slash are notation, consumed by the parser, and never drawn. Anything
    asking "can the font draw this?" has to ask about the output.
    """
    text = []
    for item in items:
        if isinstance(item, Fraction):
            text.append(rendered_characters(item.numerator))
            text.append(rendered_characters(item.denominator))
        elif isinstance(item, Radical):
            text.append(RADICAL_SIGN)
            text.append(rendered_characters(item.radicand))
        elif isinstance(item, Stack):
            text.append(rendered_characters([item.base]))
            text.append(rendered_characters(item.over))
            text.append(rendered_characters(item.under))
        else:
            text.append(item.text)
    return "".join(text)


def describe(tokens):
    """Return a short human readable summary of tokens, handy for debugging.

    Example
    -------
    >>> describe(parse("x^2"))
    "'x'(normal) '2'(super)"
    """
    return " ".join("'{}'({})".format(token.text, token.level) for token in tokens)
