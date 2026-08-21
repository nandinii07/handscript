"""HandScript - turn a scanned handwriting sample into a real, installable font.

    from handscript import HandScript

    hs = HandScript()
    result = hs.create_font(
        input_dir="handwriting/",
        output_path="output/my_handwriting.ttf",
    )

This package (`handscript/`) is a small public API and CLI over the actual
pipeline, which lives unchanged in `handwrite/`:

* `handwrite.sheettopng`  - reads a scan, finds each character's box, crops it
* `handwrite.pngtosvg`    - traces each cropped character to a vector outline
* `handwrite.svgtottf`    - assembles the outlines into a `.ttf`
* `handwrite.characters`  - the box-position -> Unicode-character mapping
                             (also re-exported as `handscript.glyphs`)
* `handwrite.notation`,
  `handwrite.renderer`    - the formula/notation typesetting layer

None of that algorithm is reimplemented here - see README.md for what each
stage does and what it needs (Potrace and FontForge, both system binaries).

Nothing in this package requires a web browser, an HTTP server, or the
optional Flask UI in `app/`. It can be imported and used from any Python
process, or driven from the shell as `handscript build ...`.
"""

from handscript.config import HandScriptConfig
from handscript.exceptions import (
    FontBuildError,
    HandScriptError,
    InvalidInputError,
    MissingDependencyError,
    MissingGlyphsError,
    NotationSyntaxError,
    PageValidationError,
)
from handscript.pipeline import HandScript, HandScriptResult

__version__ = "0.1.0"

__all__ = [
    "HandScript",
    "HandScriptResult",
    "HandScriptConfig",
    "HandScriptError",
    "InvalidInputError",
    "PageValidationError",
    "MissingDependencyError",
    "FontBuildError",
    "NotationSyntaxError",
    "MissingGlyphsError",
    "__version__",
]
