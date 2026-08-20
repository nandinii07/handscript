"""Shared fixtures: a real application, and real filled-in form pages.

The pages are drawn by the backend's own test helper rather than mocked, so
these tests exercise the same validation, extraction, tracing and font build
a real upload would.
"""

import io
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.main import create_app
from handwrite.characters import PAGES

from tests.test_sheettopng import render_synthetic_page

NEEDS_FONT_TOOLS = unittest.skipIf(
    shutil.which("potrace") is None or shutil.which("fontforge") is None,
    "potrace and/or fontforge not installed",
)


def build_pages(directory: Path):
    """Return three filled-in form pages, in page order."""
    pages = []
    for index, page in enumerate(PAGES):
        source = render_synthetic_page(page, index)
        target = Path(directory) / "page_{}.png".format(index + 1)
        shutil.copyfile(source, target)
        pages.append(target)
    return pages


def rotate(path: Path, degrees: int, directory: Path) -> Path:
    target = Path(directory) / "rotated_{}.png".format(degrees)
    Image.open(path).rotate(degrees, expand=True).save(target)
    return target


def upload_files(pages, fields=("page_1", "page_2", "page_3")):
    """Turn page paths into a multipart payload."""
    payload = {}
    for field, path in zip(fields, pages):
        payload[field] = (io.BytesIO(Path(path).read_bytes()), Path(path).name)
    return payload


class AppTestCase(unittest.TestCase):
    """A test case with a live application and its own job directory."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = Path(tempfile.mkdtemp())
        cls.pages = build_pages(cls.fixtures)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fixtures, ignore_errors=True)

    def setUp(self):
        self.job_root = Path(tempfile.mkdtemp())
        # No background cleanup thread in tests: it would outlive nothing
        # useful in a test this short, and tests that care about cleanup call
        # registry.cleanup_expired() directly for a deterministic result.
        self.app = create_app(
            job_root=self.job_root, TESTING=True, CLEANUP_INTERVAL=None
        )
        self.registry = self.app.extensions["job_registry"]
        self.client = self.app.test_client()

    def tearDown(self):
        self.registry.shutdown()
        shutil.rmtree(self.job_root, ignore_errors=True)

    def wait_for(self, job_id, timeout=180.0):
        """Poll a job until it finishes, the way a browser would."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.client.get("/api/jobs/{}".format(job_id))
            payload = response.get_json()
            if payload["status"] in ("completed", "failed"):
                return response, payload
            time.sleep(0.05)
        self.fail("job {} did not finish within {}s".format(job_id, timeout))
