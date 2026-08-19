"""Single source of truth for every character the handwriting form collects.

Both the form generator (``formgen.py``) and the sheet processor
(``sheettopng.py``) import their character lists from this module. That way
the order characters are drawn on the printed form and the order the code
expects them to appear in can never drift apart - there is exactly one place
that defines "box number N on page P is character X".

The project does NOT use OCR to figure out which character is in a box.
Instead, every box's position (its row/column on a given page) deterministically
maps to one Unicode character. This file is that mapping.
"""

import itertools

# ---------------------------------------------------------------------------
# Existing character set - EXACTLY the same 80 characters, in the exact same
# order, as the original project (see the old ALL_CHARS in sheettopng.py).
# This is Page 1 of the form and must not be reordered or edited without
# also regenerating Page 1 and re-collecting samples for everyone.
# ---------------------------------------------------------------------------
EXISTING_CHARS = list(
    itertools.chain(
        range(65, 91),  # A-Z
        range(97, 123),  # a-z
        range(48, 58),  # 0-9
        [ord(c) for c in ".,;:!?\"'-+=/%&()[]"],  # punctuation / brackets
    )
)

# ---------------------------------------------------------------------------
# New character set added in Phase 1 to support scientific/mathematical
# notation. Grouped only for readability - the groups are concatenated in
# this fixed order to build Page 2 of the form.
# ---------------------------------------------------------------------------
GREEK_LOWERCASE = [ord(c) for c in "αβγδεθλμπρσφω"]
GREEK_UPPERCASE = [ord(c) for c in "ΔΩ"]
MATH_OPERATORS = [ord(c) for c in "×÷≠≤≥±∓≈∝∞√"]
ARROWS = [ord(c) for c in "→←↔"]
NOTATION = [ord(c) for c in "{}|°"]

NEW_CHARS = GREEK_LOWERCASE + GREEK_UPPERCASE + MATH_OPERATORS + ARROWS + NOTATION

# Full character set, in the exact order the two form pages present them.
# (Kept for convenience/backwards compatibility - most code should use
# EXISTING_CHARS / NEW_CHARS / PAGES directly instead.)
ALL_CHARS = EXISTING_CHARS + NEW_CHARS

# ---------------------------------------------------------------------------
# Page layout: defines how the character set is split across printable form
# pages, and the grid (columns x rows) used to lay out and later detect the
# boxes on each page.
#
# `cols * rows` may be larger than `len(chars)`. Any leftover boxes are
# drawn on the form but left blank/unlabeled, and are simply ignored when
# the scanned sheet is processed (see SHEETtoPNG.save_images).
# ---------------------------------------------------------------------------
PAGE_1 = {"cols": 8, "rows": 10, "chars": EXISTING_CHARS}  # unchanged layout
PAGE_2 = {"cols": 8, "rows": 5, "chars": NEW_CHARS}  # new: 33 chars, 40 boxes

PAGES = [PAGE_1, PAGE_2]
