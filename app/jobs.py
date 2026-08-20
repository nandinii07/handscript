"""Font builds, tracked in memory.

A build takes about two seconds, so it needs somewhere to run that is not the
request thread, and nothing more than that. A thread pool with a small limit
covers it: no broker, no database, no worker fleet to operate. The registry is
deliberately in-process, which is also its main limitation - restart the
server and running jobs are gone.

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
from typing import Dict, List, Optional, Sequence

from app import errors, service

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


@dataclass
class Job:
    """One font build."""

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


class JobRegistry:
    """Creates, runs and remembers font builds."""

    def __init__(
        self,
        root: Path,
        max_workers: int = 3,
        timeout: float = 120.0,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="handwrite-build"
        )

    def create(self, family_name: str) -> Job:
        """Register a new job and make its directory.

        The id is a random token, not a counter and not a path: it is the only
        thing a client ever sees, and the directory is looked up from it
        rather than built out of it.
        """
        job_id = secrets.token_urlsafe(16)
        job = Job(
            job_id=job_id,
            family_name=family_name,
            directory=self.root / job_id,
        )
        job.directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def submit(self, job: Job, page_paths: Sequence[Path]) -> None:
        """Start the build on a worker thread."""
        self._pool.submit(self._run, job, [Path(p) for p in page_paths])

    def get(self, job_id: str) -> Optional[Job]:
        """Look a job up by id. Unknown ids simply do not exist."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            self._fail_if_overdue(job)
        return job

    def all_jobs(self) -> List[Job]:
        with self._lock:
            return list(self._jobs.values())

    def forget(self, job: Job) -> None:
        """Drop a job and delete everything it produced."""
        with self._lock:
            self._jobs.pop(job.job_id, None)
        shutil.rmtree(job.directory, ignore_errors=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)

    def _run(self, job: Job, page_paths: Sequence[Path]) -> None:
        with self._lock:
            job.status = PROCESSING
            job.stage = STAGE_BUILDING
            job.started_at = time.time()

        try:
            font_path = service.build_font(page_paths, job.directory, job.family_name)
        except BaseException as error:  # noqa: BLE001 - re-classified below
            if not errors.is_expected(error):
                logger.exception("Unexpected failure in job %s", job.job_id)
            self._finish_failed(job, error)
            return

        with self._lock:
            job.font_path = font_path
            job.status = COMPLETED
            job.stage = None
            job.finished_at = time.time()

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
        """
        with self._lock:
            job.status = FAILED
            job.stage = None
            job.error = message if message is not None else errors.message_for(error)
            job.error_type = type(error).__name__
            job.status_code = (
                status_code if status_code is not None else errors.status_for(error)
            )
            job.finished_at = time.time()

    def _fail_if_overdue(self, job: Job) -> None:
        """Give up on a build that has run far too long.

        A wedged potrace or FontForge would otherwise leave a job saying
        "building your font" for ever. The worker thread cannot be killed from
        here - the wait is inside a subprocess the backend owns - so this
        stops the job being reported as live; the thread releases its slot
        whenever it does finish.
        """
        if job.status != PROCESSING or job.started_at is None:
            return
        if time.time() - job.started_at <= self.timeout:
            return
        message = (
            "The font build took longer than {:.0f} seconds and was given up "
            "on. Please try again.".format(self.timeout)
        )
        self._finish_failed(
            job, TimeoutError(message), message=message, status_code=504
        )
