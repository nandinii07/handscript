"""Jobs surviving a restart, and cleanup respecting a TTL.

Before this pass, job metadata lived only in a Python dict: restarting the
process meant every job id it had ever issued became a 404, even for a font
that had finished building minutes earlier and whose .ttf was still sitting
on disk. These tests simulate a restart by discarding one `JobRegistry` and
building a fresh one against the same directory - which is exactly what
happens when the container is replaced and a volume keeps the directory.
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from app.jobs import COMPLETED, FAILED, PROCESSING, QUEUED, Job, JobRegistry
from app.store import JobRecord, JobStore
from app.tests.conftest import NEEDS_FONT_TOOLS, build_pages


class TestStore(unittest.TestCase):
    """The SQLite layer on its own, with no registry involved."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.store = JobStore(self.directory / "jobs.db")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _record(self, job_id="abc", status=QUEUED, created_at=None):
        now = time.time()
        return JobRecord(
            job_id=job_id,
            status=status,
            stage="waiting",
            family_name="Test",
            directory=str(self.directory / job_id),
            font_path=None,
            error=None,
            error_type=None,
            status_code=None,
            created_at=created_at if created_at is not None else now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )

    def test_a_saved_record_can_be_read_back(self):
        self.store.save(self._record())
        found = self.store.get("abc")
        self.assertEqual(found.status, QUEUED)
        self.assertEqual(found.family_name, "Test")

    def test_an_unknown_id_is_none(self):
        self.assertIsNone(self.store.get("nope"))

    def test_saving_twice_overwrites_rather_than_duplicating(self):
        self.store.save(self._record(status=QUEUED))
        self.store.save(self._record(status=COMPLETED))
        self.assertEqual(self.store.get("abc").status, COMPLETED)
        self.assertEqual(len(self.store.all()), 1)

    def test_a_new_store_reads_what_an_old_one_wrote(self):
        # The point of SQLite here: two independent Python objects pointed at
        # the same file see the same data, the way two process lifetimes do.
        self.store.save(self._record())
        reopened = JobStore(self.directory / "jobs.db")
        self.assertIsNotNone(reopened.get("abc"))

    def test_compare_and_update_applies_only_from_the_expected_state(self):
        self.store.save(self._record(status=QUEUED))

        applied = self.store.compare_and_update(
            "abc", (QUEUED,), {"status": PROCESSING}
        )
        self.assertTrue(applied)
        self.assertEqual(self.store.get("abc").status, PROCESSING)

        # A second writer expecting the job to still be processing, after a
        # first writer already moved it on, must not overwrite the result.
        self.store.compare_and_update("abc", (QUEUED,), {"status": FAILED})
        self.assertEqual(self.store.get("abc").status, PROCESSING)

    def test_expired_only_returns_finished_jobs_past_the_cutoff(self):
        old_cutoff = time.time() - 10
        self.store.save(
            self._record("finished-old", COMPLETED, created_at=old_cutoff - 100)
        )
        self.store.save(self._record("finished-new", COMPLETED, created_at=time.time()))
        self.store.save(
            self._record("still-queued", QUEUED, created_at=old_cutoff - 100)
        )
        self.store.save(
            self._record("still-processing", PROCESSING, created_at=old_cutoff - 100)
        )

        expired_ids = {record.job_id for record in self.store.expired(old_cutoff)}
        self.assertEqual(expired_ids, {"finished-old"})


class TestJobRegistrySurvivesRestart(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_job_created_before_a_restart_is_visible_after_it(self):
        first = JobRegistry(root=self.root, cleanup_interval=None)
        job = first.create("Persisted")
        first.shutdown()

        second = JobRegistry(root=self.root, cleanup_interval=None)
        try:
            found = second.get(job.job_id)
            self.assertIsNotNone(found)
            self.assertEqual(found.family_name, "Persisted")
        finally:
            second.shutdown()

    def test_a_completed_jobs_font_path_survives_a_restart(self):
        first = JobRegistry(root=self.root, cleanup_interval=None)
        job = first.create("Persisted")
        fake_font = job.directory / "font" / "Persisted.ttf"
        fake_font.parent.mkdir(parents=True)
        fake_font.write_bytes(b"\x00\x01\x00\x00fake")
        first.store.compare_and_update(
            job.job_id,
            (QUEUED,),
            {"status": COMPLETED, "font_path": str(fake_font)},
        )
        first.shutdown()

        second = JobRegistry(root=self.root, cleanup_interval=None)
        try:
            found = second.get(job.job_id)
            self.assertEqual(found.status, COMPLETED)
            self.assertEqual(found.font_path, fake_font)
            self.assertTrue(found.font_path.exists())
        finally:
            second.shutdown()

    def test_a_job_still_building_when_the_process_stops_is_recovered_as_failed(self):
        """The build thread does not survive a restart; the job must say so.

        Without this a job interrupted mid-build would be stuck reporting
        "building your font" forever - the thread that would have finished it
        is simply gone.
        """
        first = JobRegistry(root=self.root, cleanup_interval=None)
        job = first.create("Interrupted")
        first.store.compare_and_update(
            job.job_id, (QUEUED,), {"status": PROCESSING, "started_at": time.time()}
        )
        first.shutdown()

        second = JobRegistry(root=self.root, cleanup_interval=None)
        try:
            found = second.get(job.job_id)
            self.assertEqual(found.status, FAILED)
            self.assertEqual(found.error_type, "ServerRestarted")
            self.assertIn("restarted", found.error)
        finally:
            second.shutdown()

    def test_a_queued_job_that_never_started_is_also_recovered(self):
        first = JobRegistry(root=self.root, cleanup_interval=None)
        job = first.create("NeverStarted")  # left QUEUED, submit() never called
        first.shutdown()

        second = JobRegistry(root=self.root, cleanup_interval=None)
        try:
            self.assertEqual(second.get(job.job_id).status, FAILED)
        finally:
            second.shutdown()

    def test_an_already_finished_job_is_left_alone_by_recovery(self):
        first = JobRegistry(root=self.root, cleanup_interval=None)
        job = first.create("Done")
        first.store.compare_and_update(job.job_id, (QUEUED,), {"status": COMPLETED})
        first.shutdown()

        second = JobRegistry(root=self.root, cleanup_interval=None)
        try:
            self.assertEqual(second.get(job.job_id).status, COMPLETED)
        finally:
            second.shutdown()


class TestCleanupRespectsTTL(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.registry = JobRegistry(root=self.root, ttl_hours=1, cleanup_interval=None)

    def tearDown(self):
        self.registry.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def _age(self, job: Job, seconds: float, status: str):
        self.registry.store.compare_and_update(
            job.job_id,
            (QUEUED, PROCESSING, COMPLETED, FAILED),
            {"status": status, "created_at": time.time() - seconds},
        )

    def test_an_old_finished_job_is_removed(self):
        job = self.registry.create("Old")
        self._age(job, seconds=2 * 3600, status=COMPLETED)  # 1h TTL, 2h old

        removed = self.registry.cleanup_expired()

        self.assertEqual(removed, 1)
        self.assertIsNone(self.registry.get(job.job_id))
        self.assertFalse(job.directory.exists())

    def test_a_recent_finished_job_is_kept(self):
        job = self.registry.create("Recent")
        self._age(job, seconds=60, status=COMPLETED)  # well under the 1h TTL

        self.registry.cleanup_expired()

        self.assertIsNotNone(self.registry.get(job.job_id))
        self.assertTrue(job.directory.exists())

    def test_an_old_but_still_active_job_is_never_removed(self):
        job = self.registry.create("StillGoing")
        self._age(job, seconds=2 * 3600, status=PROCESSING)

        removed = self.registry.cleanup_expired()

        self.assertEqual(removed, 0)
        found = self.registry.get(job.job_id)
        self.assertIsNotNone(found)
        self.assertTrue(job.directory.exists())

    def test_cleanup_deletes_the_jobs_files_not_only_its_row(self):
        job = self.registry.create("WithFiles")
        marker = job.directory / "pages" / "page_1.png"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"fake")
        self._age(job, seconds=2 * 3600, status=FAILED)

        self.registry.cleanup_expired()

        self.assertFalse(marker.exists())
        self.assertFalse(job.directory.exists())

    def test_ttl_of_zero_disables_cleanup(self):
        registry = JobRegistry(root=self.root, ttl_hours=0, cleanup_interval=None)
        try:
            job = registry.create("NeverExpires")
            registry.store.compare_and_update(
                job.job_id,
                (QUEUED,),
                {"status": COMPLETED, "created_at": time.time() - 1_000_000},
            )
            self.assertEqual(registry.cleanup_expired(), 0)
            self.assertIsNotNone(registry.get(job.job_id))
        finally:
            registry.shutdown()


@NEEDS_FONT_TOOLS
class TestStudioReachableAfterRestart(unittest.TestCase):
    """The scenario the frontend audit named directly: does /studio survive?"""

    def test_a_completed_build_can_be_downloaded_from_a_new_process(self):
        from app.main import create_app

        root = Path(tempfile.mkdtemp())
        fixtures = Path(tempfile.mkdtemp())
        try:
            pages = build_pages(fixtures)

            first_app = create_app(job_root=root, TESTING=True, CLEANUP_INTERVAL=None)
            client = first_app.test_client()
            with open(pages[0], "rb") as p1, open(pages[1], "rb") as p2, open(
                pages[2], "rb"
            ) as p3:
                response = client.post(
                    "/api/jobs",
                    data={"page_1": p1, "page_2": p2, "page_3": p3},
                    content_type="multipart/form-data",
                )
            job_id = response.get_json()["job_id"]

            deadline = time.time() + 60
            while time.time() < deadline:
                status = client.get("/api/jobs/{}".format(job_id)).get_json()
                if status["status"] in ("completed", "failed"):
                    break
                time.sleep(0.05)
            self.assertEqual(status["status"], "completed")
            first_app.extensions["job_registry"].shutdown()

            # A brand new process, same directory - simulating a restart.
            second_app = create_app(job_root=root, TESTING=True, CLEANUP_INTERVAL=None)
            second_client = second_app.test_client()
            try:
                studio = second_client.get("/studio/{}".format(job_id))
                self.assertEqual(studio.status_code, 200)

                download = second_client.get("/api/jobs/{}/font.ttf".format(job_id))
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download.data[:4], b"\x00\x01\x00\x00")
            finally:
                second_app.extensions["job_registry"].shutdown()
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(fixtures, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
