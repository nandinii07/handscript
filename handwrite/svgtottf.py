import sys
import os
import json
import uuid


class FontForgeNotFound(Exception):
    """Raised when the FontForge executable cannot be found."""


class FontForgeFailed(Exception):
    """Raised when FontForge runs but does not produce a font."""


class SVGtoTTF:
    def convert(self, directory, outdir, config, metadata=None):
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

        result = subprocess.run(
            [executable]
            + arguments
            + [
                os.path.abspath(__file__),
                config,
                directory,
                outdir,
                json.dumps(metadata),
            ],
            capture_output=True,
            text=True,
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

        self.config["sfnt_names"]["UniqueID"] = family + " " + str(uuid.uuid4())

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

    def convert_main(self, config_file, directory, outdir, metadata):
        # Only importable inside FontForge's own Python, which is why this
        # module re-runs itself under `fontforge -script` (see convert()).
        import fontforge

        with open(config_file) as f:
            self.config = json.load(f)
        self.metadata = json.loads(metadata) or {}

        self.font = fontforge.font()
        self.unicode_mapping = {}
        self.set_properties()
        self.add_glyphs(directory)

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
    if len(sys.argv) != 5:
        raise ValueError("Incorrect call to SVGtoTTF")
    SVGtoTTF().convert_main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
