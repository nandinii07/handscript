import sys
import os
import json
import hashlib

# FontForge stamps the current time into the font's `head` and `FFTM` tables,
# so two builds of the same handwriting are never byte-identical. It honours
# SOURCE_DATE_EPOCH, the reproducible-builds convention, so a fixed default is
# supplied here. An epoch already set in the environment is left alone, which
# is what that convention asks for.
DEFAULT_SOURCE_DATE_EPOCH = "1609459200"  # 2021-01-01T00:00:00Z


class FontForgeNotFound(Exception):
    """Raised when the FontForge executable cannot be found."""


class FontForgeFailed(Exception):
    """Raised when FontForge runs but does not produce a font."""


def _median(values):
    """Middle value of a list. Written out because FontForge runs this file
    under its own interpreter, so the fewer imports it needs, the better."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def scale_plan(measurements, limit=2.0):
    """Work out each page's correction from measured ink summaries.

    Separated from FontForge deliberately: this is the whole decision, and
    keeping it as plain arithmetic means it can be tested directly instead of
    only through a built font.

    Parameters
    ----------
    measurements : list
        One ``(median ink height, median ink bottom)`` per page, in page
        order, or None for a page nothing could be measured on.
    limit : float
        Largest correction allowed in either direction.

    Returns
    -------
    list of tuple
        ``(page index, factor, from_bottom, to_bottom)`` for each page that
        needs correcting. The first page is the reference and never appears,
        which is what leaves the Latin letters untouched.
    """
    if len(measurements) < 2 or measurements[0] is None:
        return []

    reference_height, reference_bottom = measurements[0]
    plan = []
    for index, measured in enumerate(measurements[1:], start=1):
        if measured is None:
            continue
        height, bottom = measured
        if height <= 0:
            continue

        factor = reference_height / height
        if not 1.0 / limit <= factor <= limit:
            # Beyond this the measurement is not describing handwriting -
            # a mostly blank page, say - and "correcting" it would distort
            # the font rather than tidy it.
            continue
        plan.append((index, factor, bottom, reference_bottom))
    return plan


def source_digest(directory, glyphs):
    """Return a short digest of the traced outlines a font is built from.

    This is what the font's UniqueID is derived from. The ID has two jobs that
    pull in opposite directions: it has to be the *same* for two builds of the
    same handwriting, or no two builds can ever be compared, and *different*
    for different handwriting, or two people's fonts collide in the operating
    system's font cache. A random uuid satisfied only the second.

    Hashing the outlines satisfies both, because the outlines are precisely
    what makes one person's font different from another's.

    Parameters
    ----------
    directory : str
        Path to the directory of traced SVGs.
    glyphs : list of int
        Codepoints the font is being built from.
    """
    digest = hashlib.sha256()
    for codepoint in sorted(glyphs):
        path = os.path.join(directory, str(codepoint), "{}.svg".format(codepoint))
        if not os.path.isfile(path):
            # add_glyphs reports a missing outline with a far better message.
            continue
        digest.update(str(codepoint).encode("utf-8"))
        with open(path, "rb") as outline:
            digest.update(outline.read())
    return digest.hexdigest()[:16]


class SVGtoTTF:
    def convert(self, directory, outdir, config, metadata=None, groups=None):
        """Convert a directory with SVG images to TrueType Font.

        Calls a subprocess to the run this script with Fontforge Python
        environment.

        Parameters
        ----------
        directory : str
            Path to directory with SVGs to be converted.
        outdir : str
            Path to output directory.
        config : str
            Path to config file.
        metadata : dict
            Dictionary containing the metadata (filename, family or style)
        groups : list of list of int, optional
            Codepoints per form page, in page order. Given these, glyph sizes
            are normalised across pages (see normalize_glyph_scale). Left out,
            the glyphs are built exactly as traced.

        Raises
        ------
        FontForgeNotFound
            If the FontForge executable is not on PATH.
        FontForgeFailed
            If FontForge exits with an error.
        """
        import shutil
        import subprocess
        import platform

        # Windows ships a bundled Python (ffpython); elsewhere fontforge runs
        # the script itself.
        if platform.system() == "Windows":
            executable, arguments = "ffpython", []
        else:
            executable, arguments = "fontforge", ["-script"]

        if shutil.which(executable) is None:
            raise FontForgeNotFound(
                "{} is either not installed or not in path. Install FontForge "
                "from https://fontforge.org (macOS: `brew install fontforge`, "
                "Debian/Ubuntu: `apt install fontforge`).".format(executable)
            )

        # Pass the whole environment through (PATH and friends still matter),
        # with a fixed build timestamp added unless the caller set one.
        environment = dict(os.environ)
        environment.setdefault("SOURCE_DATE_EPOCH", DEFAULT_SOURCE_DATE_EPOCH)

        result = subprocess.run(
            [executable]
            + arguments
            + [
                os.path.abspath(__file__),
                config,
                directory,
                outdir,
                json.dumps(metadata),
                json.dumps(groups or []),
            ],
            capture_output=True,
            text=True,
            env=environment,
        )
        # Without this check a failed run just left the output directory
        # empty and the command still looked like it had worked.
        if result.returncode != 0:
            raise FontForgeFailed(
                "FontForge failed to build the font (exit code {}):\n{}".format(
                    result.returncode,
                    (result.stderr or result.stdout).strip() or "no output",
                )
            )

    def set_properties(self):
        """Set metadata of the font from config."""
        props = self.config["props"]
        lang = props.get("lang", "English (US)")
        fontname = self.metadata.get("filename", None) or props.get(
            "filename", "Example"
        )
        family = self.metadata.get("family", None) or fontname
        style = self.metadata.get("style", None) or props.get("style", "Regular")

        self.font.familyname = fontname
        self.font.fontname = fontname + "-" + style
        self.font.fullname = fontname + " " + style
        self.font.encoding = props.get("encoding", "UnicodeFull")

        for k, v in props.items():
            if hasattr(self.font, k):
                if isinstance(v, list):
                    v = tuple(v)
                setattr(self.font, k, v)

        if self.config.get("sfnt_names", None):
            self.config["sfnt_names"]["Family"] = family
            self.config["sfnt_names"]["Fullname"] = family + " " + style
            self.config["sfnt_names"]["PostScriptName"] = family + "-" + style
            self.config["sfnt_names"]["SubFamily"] = style

        self.config["sfnt_names"]["UniqueID"] = family + " " + self.source_digest

        for k, v in self.config.get("sfnt_names", {}).items():
            self.font.appendSFNTName(str(lang), str(k), str(v))

    def add_glyphs(self, directory):
        """Read and add SVG images as glyphs to the font.

        Walks through the provided directory and uses each ord(character).svg file
        as glyph for the character. Then using the provided config, set the font
        parameters and export TTF file to outdir.

        Parameters
        ----------
        directory : str
            Path to directory with SVGs to be converted.
        """
        space = self.font.createMappedChar(ord(" "))
        space.width = 500

        for k in self.config["glyphs"]:
            # Create character glyph
            g = self.font.createMappedChar(k)
            self.unicode_mapping.setdefault(k, g.glyphname)
            # Get outlines
            src = "{}/{}.svg".format(k, k)
            src = directory + os.sep + src
            if not os.path.isfile(src):
                # Usually means the config asks for more characters than the
                # scanned form provided - e.g. the full two-page glyph list
                # used with a single page-1 scan.
                raise FileNotFoundError(
                    "No traced outline for '{}' (U+{:04X}): {} is missing. The "
                    "config lists a character the scanned sheet(s) did not "
                    "provide.".format(chr(k), k, src)
                )
            g.importOutlines(src, ("removeoverlap", "correctdir"))
            g.removeOverlap()

    def _ink_summary(self, group):
        """Return (median ink height, median ink bottom) for a page's glyphs.

        Medians rather than extremes: a page holds everything from a full
        stop to an integral sign, and one unusually tall or short character
        must not decide the scale for the rest.
        """
        heights, bottoms = [], []
        for codepoint in group:
            name = self.unicode_mapping.get(codepoint)
            if name is None:
                continue
            xmin, ymin, xmax, ymax = self.font[name].boundingBox()
            if ymax <= ymin:
                continue  # empty glyph, nothing to measure
            heights.append(ymax - ymin)
            bottoms.append(ymin)

        if not heights:
            return None
        return _median(heights), _median(bottoms)

    def normalize_glyph_scale(self, groups, limit=2.0):
        """Bring every page's glyphs to the size and footing of the first page.

        How big a character comes out depends on how much of its box the
        writer filled, and that varies from page to page - one filled 41% of
        the box, another 30%. The pipeline scales each box to a fixed bitmap,
        so that difference survives all the way into the font and the Greek
        and mathematical characters end up visibly smaller than the Latin
        ones, sitting higher above the baseline as well.

        Each page after the first is corrected by ONE similarity transform,
        shared by every glyph on that page: a uniform scale (so shapes and
        aspect ratios are untouched) plus a vertical shift onto the reference
        page's footing. Because the whole page moves together, the sizes of
        characters *relative to each other* - a full stop against a capital -
        are exactly as written. Only the page as a whole changes.

        The first group is the reference and is never transformed, which is
        what keeps the Latin letters and digits pixel-for-pixel as they were.

        Parameters
        ----------
        groups : list of list of int
            Codepoints per form page, in page order.
        limit : float
            Refuse to scale by more than this factor either way. A correction
            beyond it means the measurement is not describing handwriting -
            a mostly blank page, say - and forcing it would distort the font
            rather than tidy it.
        """
        import psMat

        groups = [group for group in groups if group]
        if len(groups) < 2:
            return

        measurements = [self._ink_summary(group) for group in groups]
        for index, factor, from_bottom, to_bottom in scale_plan(measurements, limit):
            # Move the page's own footing to the origin, scale about it, then
            # set it down on the reference page's footing. A single uniform
            # scale, so shapes and aspect ratios come through untouched.
            matrix = psMat.compose(
                psMat.translate(0, -from_bottom),
                psMat.compose(psMat.scale(factor), psMat.translate(0, to_bottom)),
            )
            for codepoint in groups[index]:
                name = self.unicode_mapping.get(codepoint)
                if name is not None:
                    self.font[name].transform(matrix)

    def set_bearings(self, bearings):
        """Add left and right bearing from config.

        Every glyph in the font gets a bearing. Characters named in the table
        get their hand-tuned values; everything else - notably the Greek
        letters, math operators and arrows, which have no tuned entries -
        falls back to "Default".

        Iterating over the font rather than over the table is what makes that
        fallback happen. It also means a table entry for a character that is
        not in this font (for instance the tuned Latin table being used with
        a partial glyph set) is simply ignored instead of raising.

        Parameters
        ----------
        bearings : dict
            Map from character: [left bearing, right bearing]
        """
        default = bearings.get("Default", [60, 60])

        for codepoint, glyph_name in self.unicode_mapping.items():
            left, right = bearings.get(chr(codepoint), [None, None])
            glyph = self.font[glyph_name]
            glyph.left_side_bearing = default[0] if left is None else left
            glyph.right_side_bearing = default[1] if right is None else right

    def set_kerning(self, table):
        """Set kerning values in the font.

        Note on "seperation" (sic - the key name is kept as it is so existing
        config files keep working): it is the optical gap FontForge aims to
        leave between two glyphs when autokerning. At 0 it packs them until
        they visually touch, which turned pairs like "ij", "il" and "in" into
        single blobs in every font this pipeline produced.

        Parameters
        ----------
        table : dict
            Config dictionary with kerning values/autokern bool.
        """
        rows = table["rows"]
        rows = [list(i) if i != None else None for i in rows]
        cols = table["cols"]
        cols = [list(i) if i != None else None for i in cols]

        self.font.addLookup("kern", "gpos_pair", 0, [["kern", [["latn", ["dflt"]]]]])

        if table.get("autokern", True):
            self.font.addKerningClass(
                "kern", "kern-1", table.get("seperation", 0), rows, cols, True
            )
        else:
            kerning_table = table.get("table", False)
            if not kerning_table:
                raise ValueError("Kerning offsets not found in the config file.")
            flatten_list = lambda y: (
                [x for a in y for x in flatten_list(a)] if type(y) is list else [y]
            )
            offsets = [0 if x is None else x for x in flatten_list(kerning_table)]
            self.font.addKerningClass("kern", "kern-1", rows, cols, offsets)

    def generate_font_file(self, filename, outdir, config_file):
        """Output TTF file.

        Additionally checks for multiple outputs and duplicates.

        Parameters
        ----------
        filename : str
            Output filename.
        outdir : str
            Path to output directory.
        config_file : str
            Path to config file.
        """
        if filename is None:
            raise NameError("filename not found in config file.")

        # FontForge will not create the directory itself: generating into one
        # that does not exist fails with a bare "Font generation failed",
        # which says nothing about the actual problem.
        os.makedirs(outdir, exist_ok=True)

        outfile = str(
            outdir
            + os.sep
            + (filename + ".ttf" if not filename.endswith(".ttf") else filename)
        )

        while os.path.exists(outfile):
            outfile = os.path.splitext(outfile)[0] + " (1).ttf"

        sys.stderr.write("\nGenerating %s...\n" % outfile)
        self.font.generate(outfile)

    def convert_main(self, config_file, directory, outdir, metadata, groups="[]"):
        # Only importable inside FontForge's own Python, which is why this
        # module re-runs itself under `fontforge -script` (see convert()).
        import fontforge

        with open(config_file) as f:
            self.config = json.load(f)
        self.metadata = json.loads(metadata) or {}

        self.font = fontforge.font()
        self.unicode_mapping = {}
        # Derived before the glyphs are imported because set_properties needs
        # it for the UniqueID.
        self.source_digest = source_digest(directory, self.config["glyphs"])
        self.set_properties()
        self.add_glyphs(directory)

        # Even out the size difference between form pages before any spacing
        # is worked out, since the bearings and kerning below depend on how
        # big the glyphs actually are.
        self.normalize_glyph_scale(json.loads(groups))

        # bearing table
        self.set_bearings(self.config["typography_parameters"].get("bearing_table", {}))

        # kerning table
        self.set_kerning(self.config["typography_parameters"].get("kerning_table", {}))

        # Generate font and save as a .ttf file
        filename = self.metadata.get("filename", None) or self.config["props"].get(
            "filename", None
        )
        self.generate_font_file(str(filename), outdir, config_file)


if __name__ == "__main__":
    # The page grouping is optional, so both the four and five argument forms
    # are accepted.
    if len(sys.argv) not in (5, 6):
        raise ValueError("Incorrect call to SVGtoTTF")
    SVGtoTTF().convert_main(*sys.argv[1:])
