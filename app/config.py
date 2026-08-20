"""Everything that changes between a laptop and a production box.

Read once, from environment variables, with defaults that work unchanged for
local development. Nothing here is a secret - there is no API key or
credential anywhere in this application - but the *paths* and *limits* still
belong outside the code, because where jobs live and how long they last is a
deployment decision, not a code change.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# The committed three page form, served as-is. The backend's form generator is
# not run in production: the PDF in the repository is the one that was
# printed, filled in and validated.
TEMPLATE_PATH = REPOSITORY_ROOT / "handwrite_sample_extended.pdf"


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    job_root: Path
    job_ttl_hours: float
    max_upload_mb: float
    build_timeout: float
    max_workers: int
    font_family: str

    @property
    def max_content_length(self) -> int:
        # A little above three pages at the per-page limit, so the request
        # itself is not rejected before the per-file check can give a clearer
        # reason. Comfortably short of anything that could exhaust memory.
        return int(self.max_upload_mb * 1024 * 1024 * 3.5)

    @property
    def max_page_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


def load_settings() -> Settings:
    """Read configuration from the environment, with sane local defaults."""
    return Settings(
        job_root=Path(os.environ.get("HANDWRITE_JOB_ROOT", "/tmp/handwrite-jobs")),
        job_ttl_hours=_float_env("HANDWRITE_JOB_TTL_HOURS", 24.0),
        max_upload_mb=_float_env("HANDWRITE_MAX_UPLOAD_MB", 10.0),
        build_timeout=_float_env("HANDWRITE_BUILD_TIMEOUT", 120.0),
        max_workers=_int_env("HANDWRITE_MAX_WORKERS", 3),
        font_family=os.environ.get("HANDWRITE_FONT_FAMILY", "MyHandwriting"),
    )
