import os
import shutil
import tempfile
import unittest
from unittest import mock

from handwrite.pngtosvg import PNGtoSVG, PotraceNotFound, PotraceFailed

NEEDS_POTRACE = unittest.skipIf(
    shutil.which("potrace") is None, "potrace not installed"
)


class TestPNGtoSVG(unittest.TestCase):
    def setUp(self):
        self.directory = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_data" + os.sep + "pngtosvg",
        )
        self.converter = PNGtoSVG()

    @NEEDS_POTRACE
    def test_bmpToSvg(self):
        self.converter.bmpToSvg(self.directory + os.sep + "45.bmp")
        self.assertTrue(os.path.exists(self.directory + os.sep + "45.svg"))
        os.remove(self.directory + os.sep + "45.svg")

    @NEEDS_POTRACE
    def test_convert(self):
        self.converter.convert(self.directory)
        path = os.walk(self.directory)
        for root, dirs, files in path:
            for f in files:
                if f[-4:] == ".png":
                    self.assertTrue(os.path.exists(root + os.sep + f[0:-4] + ".bmp"))
                    self.assertTrue(os.path.exists(root + os.sep + f[0:-4] + ".svg"))
                    os.remove(root + os.sep + f[0:-4] + ".bmp")
                    os.remove(root + os.sep + f[0:-4] + ".svg")

    @NEEDS_POTRACE
    def test_potrace_failing_is_reported(self):
        # potrace is installed but cannot trace this: the failure has to
        # surface here rather than later as a missing .svg, or as a font with
        # a silently blank glyph.
        directory = tempfile.mkdtemp()
        try:
            broken = os.path.join(directory, "broken.bmp")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write("this is not a bitmap")

            with self.assertRaises(PotraceFailed) as caught:
                self.converter.bmpToSvg(broken)

            message = str(caught.exception)
            self.assertIn("potrace failed", message)
            self.assertIn("broken.bmp", message)
            # potrace leaves a partial .svg behind on failure, which is
            # exactly why the non-zero exit has to be raised: going by "did a
            # file appear?" would treat the failure as a success and hand
            # FontForge an empty glyph.
        finally:
            shutil.rmtree(directory)

    def test_missing_potrace_is_reported_clearly(self):
        with mock.patch.dict(os.environ, {"PATH": ""}):
            with self.assertRaises(PotraceNotFound) as caught:
                self.converter.bmpToSvg(self.directory + os.sep + "45.bmp")
        message = str(caught.exception)
        self.assertIn("not installed", message)
        # The message has to say how to fix it, not just what went wrong.
        self.assertIn("potrace", message)


if __name__ == "__main__":
    unittest.main()
