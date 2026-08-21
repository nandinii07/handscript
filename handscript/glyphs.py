"""Which characters HandScript expects, and where.

The actual mapping - "box number N on page P is character X" - lives in
``handwrite/characters.py``, unchanged; this module re-exports it under the
public package so a caller never has to import ``handwrite`` directly to
answer "what should I write on the form?" or "how many pages do I need?".

HandScript does not use OCR to read a filled-in box. Every box's position
deterministically maps to one Unicode character, defined once in
``handwrite/characters.py`` - see that module for the full mapping and why it
is append-only.
"""

from __future__ import annotations

from typing import List

from handwrite.characters import (
    ALL_CHARS,
    EXISTING_CHARS,
    EXTENDED_CHARS,
    NEW_CHARS,
    PAGE_1,
    PAGE_2,
    PAGE_3,
    PAGES,
)

__all__ = [
    "ALL_CHARS",
    "EXISTING_CHARS",
    "NEW_CHARS",
    "EXTENDED_CHARS",
    "PAGE_1",
    "PAGE_2",
    "PAGE_3",
    "PAGES",
    "page_count",
    "characters",
    "expected_characters",
]


def page_count() -> int:
    """How many scanned page images a full-character-set build needs."""
    return len(PAGES)


def characters(codepoints: List[int]) -> str:
    """Turn a list of Unicode codepoints (as used above) into a string."""
    return "".join(chr(codepoint) for codepoint in codepoints)


def expected_characters(page_index: int) -> str:
    """The characters expected on form page ``page_index`` (0-based), as text.

    Matches what ``handscript build`` and the printable form put in each box,
    in reading order - useful for checking a scan against what should be in
    it before running a full build.
    """
    return characters(PAGES[page_index]["chars"])
