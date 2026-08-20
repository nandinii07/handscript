import os
import sys
import json
import shutil
import argparse
import tempfile

from handwrite.sheettopng import SHEETtoPNG, SheetDetectionError
from handwrite.pngtosvg import PNGtoSVG, PotraceNotFound, PotraceFailed
from handwrite.svgtottf import SVGtoTTF, FontForgeNotFound, FontForgeFailed
from handwrite.characters import EXISTING_CHARS, PAGES

# Things that are the user's problem rather than a bug: a bad path, a scan
# that could not be read, a missing external tool. These are reported as a
# one-line message instead of a traceback.
USER_ERRORS = (
    FileNotFoundError,
    IsADirectoryError,
    ValueError,
    SheetDetectionError,
    PotraceNotFound,
    PotraceFailed,
    FontForgeNotFound,
    FontForgeFailed,
)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def _legacy_single_page_config(default_config_path):
    """Build a throwaway copy of a config, limited to the original 80 characters.

    handwrite/default.json's glyph list covers the full two-page extended
    form. If someone runs `handwrite` on a single (page-1-only) sheet
    without explicitly passing --config, we can't build glyphs for
    characters we never scanned - so fall back to a copy of that config
    with the glyph list trimmed down to just EXISTING_CHARS. This keeps the
    original single-page workflow working exactly as it always did.
    """
    with open(default_config_path) as f:
        cfg = json.load(f)
    cfg["glyphs"] = [c for c in cfg["glyphs"] if c in EXISTING_CHARS]

    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    return path


def run(sheets, output_directory, characters_dir, config, metadata):
    """Run the full SHEET -> PNG -> SVG -> TTF pipeline.

    `sheets` is either a single path (one-page form, e.g. just the original
    80-character page) or a list of paths, one per form page, in page order
    (see handwrite.characters.PAGES).
    """
    if isinstance(sheets, list):
        SHEETtoPNG().convert_pages(sheets, characters_dir, config)
        # How much of a box the writer filled varies from page to page, so
        # the font stage is told which characters came from which page and
        # evens the sizes out.
        groups = [page["chars"] for page in PAGES]
    else:
        SHEETtoPNG().convert(sheets, characters_dir, config)
        groups = None  # a single page has nothing to be consistent with

    PNGtoSVG().convert(directory=characters_dir)
    SVGtoTTF().convert(characters_dir, output_directory, config, metadata, groups)


def converters(sheet, output_directory, directory=None, config=None, metadata=None):
    if not directory:
        directory = tempfile.mkdtemp()
        isTempdir = True
    else:
        isTempdir = False

    config_explicitly_given = config is not None
    if config is None:
        config = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "default.json"
        )
    if os.path.isdir(config):
        raise IsADirectoryError("Config parameter should not be a directory.")

    temp_config = None
    try:
        if os.path.isdir(sheet):
            # A directory of scanned page images = the multi-page extended
            # form. Pages are matched to handwrite.characters.PAGES by
            # sorted filename, so name page scans e.g. "page_1.jpg",
            # "page_2.jpg" to make the order unambiguous.
            sheets = sorted(
                os.path.join(sheet, f)
                for f in os.listdir(sheet)
                if f.lower().endswith(IMAGE_EXTENSIONS)
            )
            if not sheets:
                raise FileNotFoundError(
                    "No page image files found in directory: {}".format(sheet)
                )
            run(sheets, output_directory, directory, config, metadata)
        else:
            if not config_explicitly_given:
                config = temp_config = _legacy_single_page_config(config)
            run(sheet, output_directory, directory, config, metadata)
    finally:
        if temp_config:
            os.remove(temp_config)
        if isTempdir:
            shutil.rmtree(directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", help="Path to sample sheet")
    parser.add_argument("output_directory", help="Directory Path to save font output")
    parser.add_argument(
        "--directory",
        help="Generate additional files to this path (Temp by default)",
        default=None,
    )
    parser.add_argument("--config", help="Use custom configuration file", default=None)
    parser.add_argument("--filename", help="Font File name", default=None)
    parser.add_argument("--family", help="Font Family name", default=None)
    parser.add_argument("--style", help="Font Style name", default=None)

    args = parser.parse_args()
    metadata = {"filename": args.filename, "family": args.family, "style": args.style}
    try:
        converters(
            args.input_path,
            args.output_directory,
            args.directory,
            args.config,
            metadata,
        )
    except USER_ERRORS as error:
        sys.exit("Error: {}".format(error))
