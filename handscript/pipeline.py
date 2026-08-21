"""The public HandScript API: scans in, a font out.

This module is deliberately thin. The real work - box detection and page
validation, tracing to vector outlines, assembling a TTF - is all done by the
``handwrite`` package underneath, exactly as it already worked; nothing about
that algorithm is reimplemented or changed here. What this module adds is:

* a single object (`HandScript`) with a small, memorable method surface,
  instead of importing three pipeline modules and knowing their call order,
* one exception hierarchy (see ``handscript.exceptions``) instead of the
  pipeline's own stage-specific exception types,
* an `output_path` that names the finished ``.ttf`` file directly, rather
  than a directory the pipeline writes an implicitly-named file into.

Nothing in this module touches a network socket, a browser, or a running
server - it can be imported and used from any Python process, with no web
framework involved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Union

from handwrite.cli import converters as _converters
from handwrite.notation import NotationError as _NotationError
from handwrite.pngtosvg import PotraceFailed as _PotraceFailed
from handwrite.pngtosvg import PotraceNotFound as _PotraceNotFound
from handwrite.renderer import FontNotFound as _FontNotFound
from handwrite.renderer import MissingGlyphs as _MissingGlyphs
from handwrite.renderer import check_coverage as _check_coverage
from handwrite.renderer import render_to_file as _render_to_file
from handwrite.renderer import tokens_to_html as _tokens_to_html
from handwrite.notation import parse as _parse
from handwrite.sheettopng import PageValidationError as _PageValidationError
from handwrite.sheettopng import SheetDetectionError as _SheetDetectionError
from handwrite.svgtottf import FontForgeFailed as _FontForgeFailed
from handwrite.svgtottf import FontForgeNotFound as _FontForgeNotFound

from handscript.config import HandScriptConfig
from handscript.exceptions import (
    FontBuildError,
    InvalidInputError,
    MissingDependencyError,
    MissingGlyphsError,
    NotationSyntaxError,
    PageValidationError,
)

PathLike = Union[str, os.PathLike]


@dataclass
class HandScriptResult:
    """What a successful :meth:`HandScript.create_font` call produced."""

    font_path: Path
    family_name: str
    style: Optional[str]
    input_source: Path
    intermediates_dir: Optional[Path]

    def __fspath__(self) -> str:
        # So `open(result)` / `str(result)`-adjacent uses of the result work
        # the way most people reach for the font file first.
        return str(self.font_path)


class HandScript:
    """Turn scanned handwriting into a font, and typeset notation in it.

    Examples
    --------
    >>> from handscript import HandScript
    >>> hs = HandScript()
    >>> result = hs.create_font(
    ...     input_dir="handwriting/",
    ...     output_path="output/my_handwriting.ttf",
    ... )
    >>> result.font_path
    PosixPath('output/my_handwriting.ttf')
    """

    def __init__(self, config: Optional[HandScriptConfig] = None) -> None:
        self.config = config or HandScriptConfig()

    # ---- font building --------------------------------------------------

    def create_font(
        self,
        input_dir: Optional[PathLike] = None,
        input_path: Optional[PathLike] = None,
        output_path: Optional[PathLike] = None,
        family_name: Optional[str] = None,
        style: Optional[str] = None,
        keep_intermediates: Optional[PathLike] = None,
    ) -> HandScriptResult:
        """Build a font from scanned handwriting.

        Parameters
        ----------
        input_dir
            Directory containing one scanned page image per form page (the
            191-character extended form). Pages are matched to form pages by
            sorted filename - name them e.g. ``page_1.jpg``, ``page_2.jpg``,
            ``page_3.jpg``. Pass exactly one of `input_dir` / `input_path`.
        input_path
            A single scanned page image (the original 80-character form).
            Pass exactly one of `input_dir` / `input_path`.
        output_path
            Where to write the finished font, e.g.
            ``"output/my_handwriting.ttf"``. Its filename (without
            ``.ttf``) is also the default font family name.
        family_name
            Font family name. Defaults to `HandScriptConfig.family_name`,
            then to the stem of `output_path`.
        style
            Font style/subfamily, e.g. ``"Regular"``. Defaults to
            `HandScriptConfig.style`, then to the pipeline's own default.
        keep_intermediates
            Directory to keep the per-character PNGs and traced SVGs in,
            instead of a temporary directory that is deleted once the build
            finishes. Useful for inspecting what the pipeline extracted.

        Returns
        -------
        HandScriptResult

        Raises
        ------
        handscript.exceptions.InvalidInputError
            The input path/directory is missing, empty, or the wrong number
            of pages/an unreadable image type was given.
        handscript.exceptions.PageValidationError
            A scanned page is upside down, rotated, or out of order.
        handscript.exceptions.MissingDependencyError
            Potrace or FontForge is not installed / not on PATH.
        handscript.exceptions.FontBuildError
            Potrace or FontForge ran but failed.
        """
        if (input_dir is None) == (input_path is None):
            raise InvalidInputError(
                "Pass exactly one of input_dir (a directory of scanned page "
                "images) or input_path (a single scanned page image)."
            )
        if output_path is None:
            raise InvalidInputError(
                "output_path is required, e.g. output_path='output/my_handwriting.ttf'."
            )

        source = str(input_dir if input_dir is not None else input_path)
        if not os.path.exists(source):
            raise InvalidInputError("No such file or directory: {!r}".format(source))

        output_path = Path(output_path)
        output_dir = output_path.parent if str(output_path.parent) else Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)

        # The filename also names the font family unless one is given
        # explicitly - the same default the pipeline itself already uses
        # (see handwrite/svgtottf.py: family falls back to filename).
        filename = output_path.stem
        resolved_family = family_name or self.config.family_name or filename
        resolved_style = style or self.config.style
        resolved_keep = keep_intermediates or self.config.keep_intermediates

        metadata = {
            "filename": filename,
            "family": resolved_family,
            "style": resolved_style,
        }

        try:
            _converters(
                source,
                str(output_dir),
                directory=str(resolved_keep) if resolved_keep else None,
                config=self.config.pipeline_config_path,
                metadata=metadata,
            )
        except _PageValidationError as error:
            raise PageValidationError(str(error)) from error
        except _SheetDetectionError as error:
            raise PageValidationError(str(error)) from error
        except _PotraceNotFound as error:
            raise MissingDependencyError(str(error)) from error
        except _FontForgeNotFound as error:
            raise MissingDependencyError(str(error)) from error
        except _PotraceFailed as error:
            raise FontBuildError(str(error)) from error
        except _FontForgeFailed as error:
            raise FontBuildError(str(error)) from error
        except (FileNotFoundError, IsADirectoryError, ValueError) as error:
            raise InvalidInputError(str(error)) from error

        produced = output_dir / "{}.ttf".format(filename)
        if not produced.exists():
            # Should not happen if the pipeline reported success - checked
            # explicitly rather than assumed, so a caller never gets back a
            # HandScriptResult pointing at a file that isn't actually there.
            raise FontBuildError(
                "The build finished without error, but no font was found at "
                "{}.".format(produced)
            )

        return HandScriptResult(
            font_path=produced,
            family_name=resolved_family,
            style=resolved_style,
            input_source=Path(source),
            intermediates_dir=Path(resolved_keep) if resolved_keep else None,
        )

    # ---- typesetting notation in the finished font -----------------------

    def render(
        self,
        formulas: Union[str, Sequence[str]],
        font_path: PathLike,
        output_path: PathLike,
        font_size: Optional[int] = None,
        strict: Optional[bool] = None,
        title: str = "HandScript",
    ) -> Path:
        """Render one or more notation strings to a self-contained HTML page.

        `formulas` uses the syntax documented in the README: ``^``/``_`` for
        single-character super/subscripts, ``{}`` to group more than one
        character, ``{a}/{b}`` for fractions, ``√{...}`` for radicals, and
        ``^^``/``__`` doubled markers for stacked notation (limits, accents).

        Open the returned file in a browser; use the browser's Print dialog
        to get a PDF.
        """
        resolved_size = (
            font_size if font_size is not None else self.config.notation_font_size
        )
        resolved_strict = strict if strict is not None else self.config.strict_notation
        try:
            written = _render_to_file(
                formulas,
                str(font_path),
                str(output_path),
                font_size=resolved_size,
                title=title,
                strict=resolved_strict,
            )
        except _FontNotFound as error:
            raise InvalidInputError(str(error)) from error
        except _NotationError as error:
            raise NotationSyntaxError(str(error)) from error
        except _MissingGlyphs as error:
            raise MissingGlyphsError(str(error)) from error
        return Path(written)

    def render_fragment(self, text: str) -> str:
        """Render one notation string as an HTML fragment (no page/CSS).

        For embedding into a page that already applies the font via its own
        ``@font-face`` - e.g. an interactive preview that re-renders on every
        keystroke without re-sending the whole font each time.
        """
        try:
            return _tokens_to_html(_parse(text))
        except _NotationError as error:
            raise NotationSyntaxError(str(error)) from error

    def check_coverage(self, text: Union[str, Sequence[str]], font_path: PathLike) -> List[str]:
        """Return the characters in `text` the font has no glyph for.

        An empty list means every character in `text` can be drawn in this
        font. Non-empty means those characters will silently fall back to
        some other font wherever this one is used - collect them on the form,
        or leave them out.
        """
        try:
            return _check_coverage(text, str(font_path))
        except _FontNotFound as error:
            raise InvalidInputError(str(error)) from error
