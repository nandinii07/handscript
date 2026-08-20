"""Font builds: run on a small thread pool, tracked in SQLite.

A build takes about two seconds, so it needs somewhere to run that is not the
request thread, and nothing more than that. A thread pool with a small limit
covers it: no broker, no worker fleet to operate.

Job metadata - status, stage, the finished font's path - lives in one SQLite
table (see app/store.py), so it survives a restart. The files a build
produces were always durable; only the facts about the job used to live in a
Python dict and be forgotten the moment the process stopped. Nothing about
the handwriting itself goes through the database: pages, traced outlines and
the finished .ttf all stay on disk exactly where they always did.

The concurrency cap matters because each build starts a FontForge subprocess
and spends most of its time in potrace, so a handful at once is plenty for
one machine.
"""

import logging
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from app import errors, service
from app.store import JobRecord, JobStore

logger = logging.getLogger(__name__)

QUEUED = "queued"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"

# Stages are coarse on purpose. The build runs through the backend's own
# converters(), which is one call and reports nothing in between; splitting it
# up here would mean reproducing the logic it wraps, and the whole thing takes
# about two seconds anyway.
STAGE_WAITING = "waiting to start"
STAGE_BUILDING = "building your font"

DEFAULT_CLEANUP_INTERVAL = 1800.0  # 30 minutes


@dataclass
class Job:
    """One font build, as the rest of the application sees it.

    A plain in-memory shape, kept identical to before persistence existed so
    that nothing outside this module and `app.store` has to know SQLite is
    involved. `_job_from_record` and `_record_from_job` are the only places
    that convert between the two.
    """

    job_id: str
    family_name: str
    directory: Path
    status: str = QUEUED
    stage: Optional[str] = STAGE_WAITING
    error: Optional[str] = None
    error_type: Optional[str] = None
    status_code: Optional[int] = None
    font_path: Optional[Path] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def is_finished(self) -> bool:
        return self.status in (COMPLETED, FAILED)


def _job_from_record(record: JobRecord) -> Job:
    return Job(
        job_id=record.job_id,
        family_name=record.family_name,
        directory=Path(record.directory),
        status=record.status,
        stage=record.stage,
        error=record.error,
        error_type=record.error_type,
        status_code=record.status_code,
        font_path=Path(record.font_path) if record.font_path else None,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _record_from_job(job: Job) -> JobRecord:
    return JobRecord(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        family_name=job.family_name,
        directory=str(job.directory),
        font_path=str(job.font_path) if job.font_path else None,
        error=job.error,
        error_type=job.error_type,
        status_code=job.status_code,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=time.time(),
    )


class JobRegistry:
    """Creates, runs and remembers font builds."""

    def __init__(
        self,
        root: Path,
        max_workers: int = 3,
        timeout: float = 120.0,
        ttl_hours: float = 24.0,
        cleanup_interval: Optional[float] = DEFAULT_CLEANUP_INTERVAL,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.ttl_seconds = max(ttl_hours, 0) * 3600
        self.store = JobStore(self.root / "jobs.db")
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="handwrite-build"
        )

        self._recover_orphaned_jobs()

        self._stop_cleanup = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        if cleanup_interval and cleanup_interval > 0:
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                args=(cleanup_interval,),
                name="handwrite-cleanup",
                daemon=True,
            )
            self._cleanup_thread.start()

    # ---- lifecycle ----------------------------------------------------

    def create(self, family_name: str) -> Job:
        """Register a new job and make its directory.

        The id is a random token, not a counter and not a path: it is the
        only thing a client ever sees, and the directory is looked up from it
        rather than built out of it.
        """
        job_id = secrets.token_urlsafe(16)
        job = Job(job_id=job_id, family_name=family_name, directory=self.root / job_id)
        job.directory.mkdir(parents=True, exist_ok=True)
        self.store.save(_record_from_job(job))
        logger.info("job created id=%s", job_id)
        return job

    def submit(self, job: Job, page_paths: Sequence[Path]) -> None:
        """Start the build on a worker thread."""
        self._pool.submit(self._run, job, [Path(p) for p in page_paths])

    def get(self, job_id: str) -> Optional[Job]:
        """Look a job up by id. Unknown ids simply do not exist.

        Reads always go to the store, which is what makes a job reachable
        after a restart: nothing about it lives only in this process.
        """
        record = self.store.get(job_id)
        if record is None:
            return None
        job = _job_from_record(record)

        if job.status == PROCESSING and job.started_at is not None:
            if time.time() - job.started_at > self.timeout:
                self._fail_if_overdue(job)
                record = self.store.get(job_id)
                if record is not None:
                    job = _job_from_record(record)
        return job

    def all_jobs(self) -> List[Job]:
        return [_job_from_record(record) for record in self.store.all()]

    def forget(self, job: Job) -> None:
        """Drop a job and delete everything it produced."""
        self.store.delete(job.job_id)
        shutil.rmtree(job.directory, ignore_errors=True)

    def shutdown(self) -> None:
        self._stop_cleanup.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=1.0)
        self._pool.shutdown(wait=False)

    # ---- building -------------------------------------------------------

    def _run(self, job: Job, page_paths: Sequence[Path]) -> None:
        job.status = PROCESSING
        job.stage = STAGE_BUILDING
        job.started_at = time.time()
        self.store.compare_and_update(
            job.job_id,
            (QUEUED,),
            {
                "status": PROCESSING,
                "stage": STAGE_BUILDING,
                "started_at": job.started_at,
            },
        )
        logger.info("build started id=%s", job.job_id)

        try:
            font_path = service.build_font(page_paths, job.directory, job.family_name)
        except BaseException as error:  # noqa: BLE001 - re-classified below
            if not errors.is_expected(error):
                logger.exception("unexpected failure id=%s", job.job_id)
            self._finish_failed(job, error)
            return

        finished_at = time.time()
        applied = self.store.compare_and_update(
            job.job_id,
            (PROCESSING,),
            {
                "status": COMPLETED,
                "stage": None,
                "font_path": str(font_path),
                "finished_at": finished_at,
            },
        )
        if applied:
            job.font_path = font_path
            job.status = COMPLETED
            job.stage = None
            job.finished_at = finished_at
        logger.info("build completed id=%s", job.job_id)

    def _finish_failed(
        self,
        job: Job,
        error: BaseException,
        message: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        """Record a failure.

        `message` and `status_code` are for failures the registry raises
        itself, such as giving up on an overdue build: those already say
        something useful and should not be put through the backend error map,
        which would treat them as unrecognised and replace the wording.

        The write only applies if the job was still active. That is what
        stops two writers - a build finishing normally and the overdue check
        firing at nearly the same moment - from one silently overwriting the
        other's result.
        """
        error_message = message if message is not None else errors.message_for(error)
        error_type = type(error).__name__
        code = status_code if status_code is not None else errors.status_for(error)
        finished_at = time.time()

        applied = self.store.compare_and_update(
            job.job_id,
            (QUEUED, PROCESSING),
            {
                "status": FAILED,
                "stage": None,
                "error": error_message,
                "error_type": error_type,
                "status_code": code,
                "finished_at": finished_at,
            },
        )
        if applied:
            job.status = FAILED
            job.stage = None
            job.error = error_message
            job.error_type = error_type
            job.status_code = code
            job.finished_at = finished_at
        logger.info("build failed id=%s type=%s", job.job_id, error_type)

    def _fail_if_overdue(self, job: Job) -> None:
        """Give up on a build that has run far too long.

        A wedged potrace or FontForge would otherwise leave a job saying
        "building your font" for ever. The worker thread cannot be killed
        from here - the wait is inside a subprocess the backend owns - so
        this stops the job being reported as live; the thread releases its
        slot whenever it does finish.
        """
        message = (
            "The font build took longer than {:.0f} seconds and was given up "
            "on. Please try again.".format(self.timeout)
        )
        self._finish_failed(
            job, TimeoutError(message), message=message, status_code=504
        )

    # ---- startup recovery and cleanup ------------------------------------

    def _recover_orphaned_jobs(self) -> None:
        """Mark jobs left mid-build by a previous process as failed.

        A build runs on a thread inside this process. If the process
        restarted, any job still saved as queued or processing belongs to a
        thread that no longer exists and will never finish on its own -
        without this it would sit "building your font" forever.
        """
        message = (
            "The server restarted while this font was building. Please "
            "upload your pages again."
        )
        for record in self.store.all():
            if record.status not in (QUEUED, PROCESSING):
                continue
            was = record.status
            record.status = FAILED
            record.stage = None
            record.error = message
            record.error_type = "ServerRestarted"
            record.status_code = 503
            record.finished_at = time.time()
            self.store.save(record)
            logger.warning("recovered orphaned job id=%s (was %s)", record.job_id, was)

    def cleanup_expired(self) -> int:
        """Delete finished jobs older than the configured TTL.

        Only ``completed`` or ``failed`` jobs are ever candidates - the store
        enforces that - so a build that is merely slow is never touched.
        Returns how many jobs were removed, mostly so tests can check.
        """
        if self.ttl_seconds <= 0:
            return 0
        cutoff = time.time() - self.ttl_seconds
        removed = 0
        for record in self.store.expired(cutoff):
            shutil.rmtree(record.directory, ignore_errors=True)
            self.store.delete(record.job_id)
            removed += 1
        if removed:
            logger.info("cleanup removed %d expired job(s)", removed)
        return removed

    def _cleanup_loop(self, interval: float) -> None:
        while not self._stop_cleanup.wait(interval):
            try:
                self.cleanup_expired()
            except Exception:  # noqa: BLE001 - a cleanup bug must not end the loop
                logger.exception("cleanup failed")
