"""Options for a :class:`~handscript.pipeline.HandScript` build.

Everything here has a working default - a caller building their first font
does not need to look inside this module at all. It exists so those defaults
are named and documented in one place, rather than scattered across keyword
arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HandScriptConfig:
    """Default options for a :class:`~handscript.pipeline.HandScript` instance.

    Anything set here is used whenever the same option is not given directly
    to a method call - a method argument always wins over a config default.

    Parameters
    ----------
    family_name
        Default font family name, used when ``create_font`` is not given one
        explicitly. If neither is set, the family name is taken from the
        output filename (``my_handwriting.ttf`` -> family ``my_handwriting``).
    style
        Default font style/subfamily name (e.g. ``"Regular"``, ``"Bold"``).
        Passed straight through to the pipeline's own default when unset.
    pipeline_config_path
        Path to an alternate ``default.json``-shaped pipeline configuration
        (glyph list, bearings, kerning). Almost nobody needs this - it exists
        because the pipeline itself accepts it, and hiding it would make
        HandScript less capable than the engine underneath it.
    keep_intermediates
        Directory to write intermediate files (per-character PNGs, traced
        SVGs) to, instead of a temporary directory that is deleted afterwards.
        Useful for inspecting or debugging a build.
    strict_notation
        If true, :meth:`~handscript.pipeline.HandScript.render` raises
        :class:`~handscript.exceptions.MissingGlyphsError` instead of warning
        when the font has no glyph for a character being rendered.
    notation_font_size
        Base font size, in pixels, used when rendering notation to HTML.
    """

    family_name: Optional[str] = None
    style: Optional[str] = None
    pipeline_config_path: Optional[str] = None
    keep_intermediates: Optional[str] = None
    strict_notation: bool = False
    notation_font_size: int = 48
