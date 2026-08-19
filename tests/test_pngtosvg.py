import os
import shutil
import unittest
from unittest import mock

from handwrite.pngtosvg import PNGtoSVG, PotraceNotFound

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
