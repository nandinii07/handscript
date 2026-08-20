"""The integration boundary, enforced rather than agreed.

`app.service` is meant to be the only module that touches the backend. That
is easy to say and easy to erode - one convenient import from a route handler
and the boundary is gone - so it is checked here by reading the source.
"""

import ast
import unittest
from pathlib import Path

from app import errors, jobs
from app.tests.conftest import NEEDS_FONT_TOOLS, AppTestCase, upload_files
from handwrite.sheettopng import PageValidationError

APP_ROOT = Path(__file__).resolve().parents[1]

# errors.py maps backend exception classes to HTTP statuses, so it has to name
# them. It calls nothing and builds nothing.
EXEMPT = {"service.py", "errors.py"}


def modules_importing_handwrite():
    """Every application module that imports the backend."""
    offenders = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "tests" in path.parts or path.name in EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "handwrite" or name.startswith("handwrite.") for name in names
            ):
                offenders.append(path.relative_to(APP_ROOT).as_posix())
                break
    return offenders


class TestIntegrationBoundary(unittest.TestCase):
    def test_only_service_and_the_error_map_import_the_backend(self):
        self.assertEqual(
            modules_importing_handwrite(),
            [],
            "these modules should go through app.service instead",
        )

    def test_service_really_does_import_the_backend(self):
        # Guards against the check above passing because nothing uses the
        # backend at all any more.
        source = (APP_ROOT / "service.py").read_text(encoding="utf-8")
        self.assertIn("from handwrite import", source)

    def test_nothing_shells_out_to_the_command_line_tools(self):
        # The backend is a library here. Driving `handwrite` or
        # `handwrite-render` as commands would mean parsing stderr to find out
        # what went wrong, instead of catching a typed exception.
        for path in sorted(APP_ROOT.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.add(node.module or "")
            with self.subTest(module=path.name):
                self.assertNotIn("subprocess", imported)
                self.assertNotIn("os.system", imported)


class TestErrorMapping(unittest.TestCase):
    """Each backend failure has to keep its own status and its own words."""

    def test_expected_backend_errors_map_to_their_status(self):
        from handwrite import (
            FontForgeFailed,
            FontForgeNotFound,
            PotraceFailed,
            PotraceNotFound,
            SheetDetectionError,
        )

        expected = {
            PageValidationError("page 1"): 422,
            SheetDetectionError("no boxes"): 422,
            FileNotFoundError("missing"): 400,
            ValueError("bad"): 400,
            IsADirectoryError("dir"): 400,
            PotraceNotFound("no potrace"): 503,
            FontForgeNotFound("no fontforge"): 503,
            PotraceFailed("trace blew up"): 500,
            FontForgeFailed("build blew up"): 500,
        }
        for error, status in expected.items():
            with self.subTest(error=type(error).__name__):
                self.assertEqual(errors.status_for(error), status)

    def test_an_unexpected_error_is_a_generic_500(self):
        error = RuntimeError("something nobody planned for")
        self.assertEqual(errors.status_for(error), 500)
        self.assertFalse(errors.is_expected(error))
        self.assertNotIn("nobody planned", errors.message_for(error))

    def test_expected_errors_keep_the_backend_wording(self):
        # The backend's message names the page and says what to do, which is
        # the whole value of it.
        error = PageValidationError(
            "Page 1 of 3 ('page_1.png') does not look like page 1"
        )
        self.assertIn("does not look like page 1", errors.message_for(error))

    def test_user_fixable_statuses_are_the_four_hundreds(self):
        self.assertEqual(set(errors.USER_FIXABLE), {400, 422})


@NEEDS_FONT_TOOLS
class TestPageValidationIsNeverBypassed(AppTestCase):
    """The application must not find a way around the backend's own guard.

    This is the failure the backend was hardened against: pages in the wrong
    order still have the right number of boxes, so without validation the
    build succeeds and produces a font with every character under the wrong
    codepoint.
    """

    def test_a_swapped_upload_fails_and_produces_no_font(self):
        first, second, third = self.pages
        response = self.client.post(
            "/api/jobs",
            data=upload_files([third, second, first]),
            content_type="multipart/form-data",
        )
        job_id = response.get_json()["job_id"]
        status, payload = self.wait_for(job_id)

        self.assertEqual(payload["status"], jobs.FAILED)
        self.assertEqual(payload["error_type"], "PageValidationError")
        self.assertEqual(status.status_code, 422)

        job = self.registry.get(job_id)
        self.assertEqual(list((job.directory / "font").glob("*.ttf")), [])

    def test_the_guard_runs_before_any_character_is_extracted(self):
        first, second, third = self.pages
        response = self.client.post(
            "/api/jobs",
            data=upload_files([third, second, first]),
            content_type="multipart/form-data",
        )
        job_id = response.get_json()["job_id"]
        self.wait_for(job_id)

        work = self.registry.get(job_id).directory / "work"
        self.assertEqual(
            list(work.iterdir()) if work.exists() else [],
            [],
            "characters were extracted despite validation failing",
        )


class TestJobRegistry(AppTestCase):
    def test_job_ids_are_random_and_reveal_no_paths(self):
        first = self.registry.create("A")
        second = self.registry.create("B")
        self.assertNotEqual(first.job_id, second.job_id)
        for job in (first, second):
            self.assertNotIn("/", job.job_id)
            self.assertNotIn("..", job.job_id)
            self.assertGreaterEqual(len(job.job_id), 16)

    def test_a_new_job_starts_queued(self):
        job = self.registry.create("A")
        self.assertEqual(job.status, jobs.QUEUED)
        self.assertEqual(job.stage, jobs.STAGE_WAITING)
        self.assertIsNone(job.font_path)

    def test_forgetting_a_job_removes_it_and_its_files(self):
        job = self.registry.create("A")
        directory = job.directory
        self.assertTrue(directory.exists())

        self.registry.forget(job)
        self.assertIsNone(self.registry.get(job.job_id))
        self.assertFalse(directory.exists())

    def test_an_overdue_build_is_given_up_on(self):
        import time

        job = self.registry.create("A")
        job.status = jobs.PROCESSING
        job.started_at = time.time() - 10_000

        self.assertEqual(self.registry.get(job.job_id).status, jobs.FAILED)
        self.assertIn("longer than", job.error)


if __name__ == "__main__":
    unittest.main()


class TestMessagesRevealNoServerPaths(unittest.TestCase):
    """A user should never see where the server keeps its files."""

    def test_an_absolute_path_is_reduced_to_a_filename(self):
        error = PageValidationError(
            "Page 1 of 3 ('/tmp/handwrite-jobs/abc123/pages/page_1.png') does "
            "not look like page 1: it ends with 2 unwritten box(es)."
        )
        message = errors.message_for(error)

        self.assertNotIn("/tmp/", message)
        self.assertNotIn("handwrite-jobs", message)
        self.assertIn("'page_1.png'", message)
        self.assertIn("does not look like page 1", message)

    def test_a_windows_path_is_reduced_too(self):
        error = PageValidationError(
            "Page 2 of 3 ('C:\\\\jobs\\\\x\\\\page_2.png') is rotated."
        )
        self.assertNotIn("jobs", errors.message_for(error))
        self.assertIn("page_2.png", errors.message_for(error))

    def test_messages_without_paths_are_untouched(self):
        error = PageValidationError("Page 3 of 3 looks upside down.")
        self.assertEqual(errors.message_for(error), "Page 3 of 3 looks upside down.")
