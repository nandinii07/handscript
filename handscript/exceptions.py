"""HandScript's own error types.

The pipeline underneath (``handwrite/``) already raises specific, well-named
exceptions - ``PageValidationError``, ``PotraceNotFound``, ``FontForgeFailed``
and so on. Those names are about the *pipeline's internal stages*
(sheet-to-PNG, PNG-to-SVG, SVG-to-TTF); a caller using the public
``HandScript`` API should not need to know that vocabulary or import from
three different pipeline modules to catch errors sensibly.

Every exception here wraps exactly one underlying pipeline exception, keeps
its message, and chains it as ``__cause__`` (via ``raise ... from error``) so
nothing about the original failure is lost - ``str(error.__cause__)`` and
``type(error).__cause__`` are always the real thing that went wrong.
"""

from __future__ import annotations

from typing import Optional


class HandScriptError(Exception):
    """Base class for every error HandScript raises."""


class InvalidInputError(HandScriptError):
    """The input given to :meth:`HandScript.create_font` doesn't make sense.

    Covers a missing path, an empty directory, the wrong number of page
    images, or an image file type the pipeline cannot read - problems that
    are wrong before any image processing starts.
    """


class PageValidationError(HandScriptError):
    """A scanned page doesn't match what was expected of it.

    Raised when a page is upside down, rotated, or pages have been given out
    of order (page 1 and page 3 of the extended form have the same box grid,
    so a swapped scan would otherwise build a font with every character
    filed under the wrong codepoint, silently).
    """


class MissingDependencyError(HandScriptError):
    """A required external program (Potrace or FontForge) was not found.

    These are system binaries, not Python packages - see the "Native
    dependencies" section of the README for how to install them.
    """


class FontBuildError(HandScriptError):
    """Potrace or FontForge ran but failed to produce a usable result."""


class NotationSyntaxError(HandScriptError):
    """Text passed to :meth:`HandScript.render` isn't valid notation syntax."""


class MissingGlyphsError(HandScriptError):
    """The font has no glyph for a character being rendered, in strict mode."""


def _wrap(error: BaseException, exc_type: type, message: Optional[str] = None) -> HandScriptError:
    """Build one of the exceptions above, chained to the original `error`."""
    return exc_type(message if message is not None else str(error))
