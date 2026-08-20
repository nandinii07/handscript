"""Find out which characters a generated font actually contains.

The renderer embeds the user's font and then names it first in the CSS font
stack, so a character the font happens to lack is quietly drawn by whatever
the browser falls back to. On a page that is otherwise entirely handwriting
that is obvious once you see it and invisible until you do, which is the
worst way for it to fail.

Only the `cmap` table is read, and only the format 4 subtable that FontForge
writes for these fonts - enough to answer "is this character in there?"
without taking on a font library as a dependency.
"""

import struct


def mapped_codepoints(data):
    """Return the set of codepoints the font data contains a glyph for.

    Parameters
    ----------
    data : bytes
        The contents of a .ttf file.

    Returns
    -------
    set of int
        Empty if the font cannot be read, so a caller treats an unreadable
        font as "cannot tell" rather than "everything is missing".
    """
    try:
        return _mapped_codepoints(data)
    except (struct.error, KeyError, IndexError, ValueError):
        return set()


def missing_characters(text, data):
    """Return the characters of `text` the font has no glyph for.

    Whitespace is ignored: a space is handled by the font's own space glyph,
    and line breaks never reach the font at all.
    """
    mapped = mapped_codepoints(data)
    if not mapped:
        return []

    missing = []
    for character in text:
        if character.isspace() or ord(character) in mapped:
            continue
        if character not in missing:
            missing.append(character)
    return missing


def _mapped_codepoints(data):
    tables = {}
    for index in range(struct.unpack(">H", data[4:6])[0]):
        entry = 12 + 16 * index
        tag = data[entry : entry + 4].decode("latin1")
        tables[tag] = struct.unpack(">II", data[entry + 8 : entry + 16])[0]

    offset = tables["cmap"]
    codepoints = set()
    for index in range(struct.unpack(">H", data[offset + 2 : offset + 4])[0]):
        _platform, _encoding, subtable_offset = struct.unpack(
            ">HHI", data[offset + 4 + 8 * index : offset + 12 + 8 * index]
        )
        subtable = offset + subtable_offset
        if struct.unpack(">H", data[subtable : subtable + 2])[0] != 4:
            continue

        segments_x2 = struct.unpack(">H", data[subtable + 6 : subtable + 8])[0]
        segments = segments_x2 // 2
        ends = struct.unpack(
            ">%dH" % segments, data[subtable + 14 : subtable + 14 + segments_x2]
        )
        starts = struct.unpack(
            ">%dH" % segments,
            data[subtable + 16 + segments_x2 : subtable + 16 + 2 * segments_x2],
        )
        for start, end in zip(starts, ends):
            if end == 0xFFFF:
                continue
            codepoints.update(range(start, end + 1))
    return codepoints
