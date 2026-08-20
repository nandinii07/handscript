"""Minimal TrueType reader, so tests can check what a built font really says.

FontForge is only importable inside its own Python, so the only way to assert
anything about a generated .ttf from the test suite is to read the file. This
covers just the two tables the tests need: `cmap` (which character maps to
which glyph) and `hmtx` (advance width and left side bearing per glyph).

Deliberately small - it is not a font library, and it only understands the
cmap format 4 subtable that FontForge writes for these fonts.
"""

import struct


def _table_directory(data):
    tables = {}
    for index in range(struct.unpack(">H", data[4:6])[0]):
        entry = 12 + 16 * index
        tag = data[entry : entry + 4].decode("latin1")
        tables[tag] = struct.unpack(">II", data[entry + 8 : entry + 16])
    return tables


def _character_map(data, offset):
    """Return {codepoint: glyph id} from the format 4 subtable."""
    mapping = {}
    for index in range(struct.unpack(">H", data[offset + 2 : offset + 4])[0]):
        _, _, subtable_offset = struct.unpack(
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
        deltas = struct.unpack(
            ">%dh" % segments,
            data[subtable + 16 + 2 * segments_x2 : subtable + 16 + 3 * segments_x2],
        )
        range_offsets_at = subtable + 16 + 3 * segments_x2
        range_offsets = struct.unpack(
            ">%dH" % segments, data[range_offsets_at : range_offsets_at + segments_x2]
        )

        for segment, (start, end) in enumerate(zip(starts, ends)):
            if end == 0xFFFF:
                continue
            for codepoint in range(start, end + 1):
                if range_offsets[segment] == 0:
                    glyph = (codepoint + deltas[segment]) & 0xFFFF
                else:
                    at = (
                        range_offsets_at
                        + segment * 2
                        + range_offsets[segment]
                        + (codepoint - start) * 2
                    )
                    glyph = struct.unpack(">H", data[at : at + 2])[0]
                    if glyph:
                        glyph = (glyph + deltas[segment]) & 0xFFFF
                if glyph:
                    mapping[codepoint] = glyph
    return mapping


def name_records(path):
    """Return {name id: text} from the font's `name` table.

    Name id 3 is the UniqueID, which is the one determinism depends on.
    """
    with open(path, "rb") as font_file:
        data = font_file.read()
    offset = _table_directory(data)["name"][0]

    count, strings_at = struct.unpack(">HH", data[offset + 2 : offset + 6])
    strings = offset + strings_at

    records = {}
    for index in range(count):
        record = offset + 6 + 12 * index
        platform, _, _, name_id, length, at = struct.unpack(
            ">HHHHHH", data[record : record + 12]
        )
        raw = data[strings + at : strings + at + length]
        # Platform 3 (Windows) stores UTF-16BE; platform 1 (Mac) single bytes.
        text = raw.decode("utf-16-be" if platform == 3 else "latin1", "replace")
        records.setdefault(name_id, text)
    return records


def mapped_codepoints(path):
    """Return the set of codepoints the font has a glyph for."""
    with open(path, "rb") as font_file:
        data = font_file.read()
    tables = _table_directory(data)
    return set(_character_map(data, tables["cmap"][0]))


def metrics(path, characters):
    """Return {character: (advance_width, left_side_bearing)} in font units.

    Characters the font does not contain are simply absent from the result.
    """
    with open(path, "rb") as font_file:
        data = font_file.read()
    tables = _table_directory(data)
    mapping = _character_map(data, tables["cmap"][0])
    hmtx = tables["hmtx"][0]

    result = {}
    for character in characters:
        glyph = mapping.get(ord(character))
        if glyph is None:
            continue
        result[character] = struct.unpack(
            ">Hh", data[hmtx + 4 * glyph : hmtx + 4 * glyph + 4]
        )
    return result
