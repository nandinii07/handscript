from PIL import Image, ImageChops
import os
import shutil
import subprocess


class PotraceNotFound(Exception):
    pass


class PotraceFailed(Exception):
    """Raised when potrace is installed but fails to trace an image."""


class PNGtoSVG:
    """Converter class to convert character PNGs to BMPs and SVGs."""

    def convert(self, directory):
        """Call converters on each .png in the provider directory.

        Walk through the custom directory containing all .png files
        from sheettopng and convert them to png -> bmp -> svg.
        """
        path = os.walk(directory)
        for root, dirs, files in path:
            for f in files:
                if f.endswith(".png"):
                    self.pngToBmp(root + "/" + f)
                    # self.trim(root + "/" + f[0:-4] + ".bmp")
                    self.bmpToSvg(root + "/" + f[0:-4] + ".bmp")

    def bmpToSvg(self, path):
        """Convert .bmp image to .svg using potrace.

        Converts the passed .bmp file to .svg using the potrace
        (http://potrace.sourceforge.net/). Each .bmp is passed as
        a parameter to potrace which is called as a subprocess.

        Parameters
        ----------
        path : str
            Path to the bmp file to be converted.

        Raises
        ------
        PotraceNotFound
            Raised if potrace not found in path by shutil.which()
        PotraceFailed
            Raised if potrace runs but exits with an error.
        """
        if shutil.which("potrace") is None:
            raise PotraceNotFound(
                "Potrace is either not installed or not in path. Install it "
                "from http://potrace.sourceforge.net/ (macOS: `brew install "
                "potrace`, Debian/Ubuntu: `apt install potrace`)."
            )

        output_path = path[0:-4] + ".svg"
        result = subprocess.run(
            ["potrace", path, "-b", "svg", "-o", output_path],
            capture_output=True,
            text=True,
        )
        # potrace failing used to go unnoticed until FontForge later
        # complained about a missing .svg, or - worse - produced a font with
        # a blank glyph.
        if result.returncode != 0:
            raise PotraceFailed(
                "potrace failed on {} (exit code {}): {}".format(
                    path, result.returncode, result.stderr.strip() or "no output"
                )
            )

    def pngToBmp(self, path):
        """Convert a .png character image to a thresholded .bmp.

        Every pixel is forced to either black or white, since potrace traces
        a two-colour bitmap. The image is scaled to a fixed 100x100 so all
        glyphs arrive in FontForge at a consistent size - which is why the
        form draws identically shaped boxes on every page.

        Parameters
        ----------
        path : str
            Path to the png file to be converted.
        """
        img = Image.open(path).convert("RGBA").resize((100, 100))

        # Threshold image to convert each pixel to either black or white
        threshold = 200
        data = []
        for pix in list(img.getdata()):
            if pix[0] >= threshold and pix[1] >= threshold and pix[3] >= threshold:
                data.append((255, 255, 255, 0))
            else:
                data.append((0, 0, 0, 1))
        img.putdata(data)
        img.save(path[0:-4] + ".bmp")

    def trim(self, im_path):
        im = Image.open(im_path)
        bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
        diff = ImageChops.difference(im, bg)
        bbox = list(diff.getbbox())
        bbox[0] -= 1
        bbox[1] -= 1
        bbox[2] += 1
        bbox[3] += 1
        cropped_im = im.crop(bbox)
        cropped_im.save(im_path)
