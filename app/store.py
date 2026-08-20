"""Where job metadata lives between requests, and across a restart.

A build produces two things: files on disk (the pages, the traced outlines,
the finished .ttf) and a handful of facts about the job (its status, which
stage it is in, what went wrong if anything). The files were always durable -
they are just a directory. The facts were not: they lived in a Python dict,
so restarting the process forgot every job that had ever run.

SQLite fixes that without adding a service to operate. One file, one table,
one row per job. Nothing here stores the handwriting itself - the images and
the font stay exactly where they always did, under the job's own directory -
so this file only ever holds metadata small enough to not think about.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    stage       TEXT,
    family_name TEXT NOT NULL,
    directory   TEXT NOT NULL,
    font_path   TEXT,
    error       TEXT,
    error_type  TEXT,
    status_code INTEGER,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL,
    updated_at  REAL NOT NULL
);
"""


@dataclass
class JobRecord:
    """One row of the jobs table, as plain data.

    Paths are stored as strings, since SQLite has no path type and this is
    the boundary where that stops mattering - `JobRegistry` converts back to
    `Path` on the way out.
    """

    job_id: str
    status: str
    stage: Optional[str]
    family_name: str
    directory: str
    font_path: Optional[str]
    error: Optional[str]
    error_type: Optional[str]
    status_code: Optional[int]
    created_at: float
    started_at: Optional[float]
    finished_at: Optional[float]
    updated_at: float


_COLUMNS = [field.name for field in fields(JobRecord)]


class JobStore:
    """A small SQLite-backed table of job metadata.

    SQLite connections are not shared between threads, and this registry is
    used from a request thread and from build worker threads at once, so a
    connection is opened per operation rather than held open. That costs
    nothing worth measuring at this scale and avoids the whole question of
    cross-thread connection safety.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.execute(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        try:
            with self._lock:
                yield connection
                connection.commit()
        finally:
            connection.close()

    def save(self, record: JobRecord) -> None:
        """Insert a job, or overwrite it if the id already exists."""
        record.updated_at = time.time()
        values = asdict(record)
        placeholders = ", ".join(":" + name for name in _COLUMNS)
        columns = ", ".join(_COLUMNS)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO jobs ({}) VALUES ({})".format(
                    columns, placeholders
                ),
                values,
            )

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def all(self) -> List[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs").fetchall()
        return [_row_to_record(row) for row in rows]

    def compare_and_update(
        self, job_id: str, expected_statuses: tuple, updates: dict
    ) -> bool:
        """Apply `updates` only if the job's current status is one expected.

        Returns whether the update was applied. This is the guard that stops
        two writers - a build finishing normally and the timeout check firing
        at nearly the same moment - from one silently overwriting the other's
        result: whichever gets here first wins, and the second is a no-op.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] not in expected_statuses:
                return False

            values = dict(updates)
            values["updated_at"] = time.time()
            assignments = ", ".join("{} = :{}".format(name, name) for name in values)
            values["job_id"] = job_id
            connection.execute(
                "UPDATE jobs SET {} WHERE job_id = :job_id".format(assignments),
                values,
            )
            return True

    def delete(self, job_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def expired(self, cutoff: float) -> List[JobRecord]:
        """Finished jobs old enough to clean up.

        Only ``completed`` or ``failed`` jobs are ever returned: a job still
        ``queued`` or ``processing`` is active by definition, and cleanup
        must never touch one, however old ``created_at`` says it is.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status IN ('completed', 'failed') "
                "AND created_at < ?",
                (cutoff,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]


def _row_to_record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(**{name: row[name] for name in _COLUMNS})
