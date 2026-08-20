"""The HTTP surface: upload pages, watch a build, preview, download.

Route handlers do request handling and nothing else. Anything to do with
handwriting goes through `app.service`, and anything to do with running a
build goes through `app.jobs`.
"""

import logging
from pathlib import Path
from typing import List, Tuple

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.datastructures import FileStorage

from app import errors, jobs, service
from app.errors import NotationError

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

# The three upload fields, in page order. Naming them explicitly means the
# order comes from the request shape rather than from filenames a client
# chose, which is what the backend's page validation is trusting.
PAGE_FIELDS = ("page_1", "page_2", "page_3")

MAX_PAGE_BYTES = 10 * 1024 * 1024


def _error(message: str, status: int, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def _collect_pages(directory: Path) -> Tuple[List[Path], object]:
    """Save the three uploaded pages, or return a response explaining why not.

    Filenames come from the field they arrived in, never from the client, so
    a name like "../../etc/passwd" cannot reach the filesystem.
    """
    missing = [field for field in PAGE_FIELDS if field not in request.files]
    if missing:
        return [], _error(
            "Three page images are required, named {}. Missing: {}.".format(
                ", ".join(PAGE_FIELDS), ", ".join(missing)
            ),
            400,
        )

    saved: List[Path] = []
    for number, field in enumerate(PAGE_FIELDS, start=1):
        upload: FileStorage = request.files[field]
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in service.IMAGE_SUFFIXES:
            return [], _error(
                "{} is not an image this can read ({}). Accepted types: {}.".format(
                    field, suffix or "no extension", ", ".join(service.IMAGE_SUFFIXES)
                ),
                400,
            )

        upload.stream.seek(0, 2)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size == 0:
            return [], _error("{} is empty.".format(field), 400)
        if size > MAX_PAGE_BYTES:
            return [], _error(
                "{} is {:.1f} MB, over the {:.0f} MB limit for one page.".format(
                    field, size / 1024 / 1024, MAX_PAGE_BYTES / 1024 / 1024
                ),
                400,
            )

        destination = directory / "upload_{}{}".format(number, suffix)
        upload.save(destination)
        saved.append(destination)

    return saved, None


def _job_payload(job: jobs.Job) -> dict:
    payload = {
        "job_id": job.job_id,
        "status": job.status,
        "stage": job.stage,
        "family_name": job.family_name,
        "error": job.error,
        "error_type": job.error_type,
        "download_url": None,
    }
    if job.status == jobs.COMPLETED:
        payload["download_url"] = "/api/jobs/{}/font.ttf".format(job.job_id)
    return payload


@api.post("/jobs")
def create_job():
    """Accept three page scans and start building a font."""
    registry: jobs.JobRegistry = current_app.extensions["job_registry"]
    family_name = request.form.get("family_name") or current_app.config["FONT_FAMILY"]
    if not family_name.replace(" ", "").isalnum():
        return _error("Font name may only contain letters, numbers and spaces.", 400)

    job = registry.create(family_name)
    uploads_dir = job.directory / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    pages, failure = _collect_pages(uploads_dir)
    if failure is not None:
        registry.forget(job)
        return failure

    registry.submit(job, pages)
    return jsonify(_job_payload(job)), 202


@api.get("/jobs/<job_id>")
def job_status(job_id: str):
    """Report how a build is going, and how it ended."""
    registry: jobs.JobRegistry = current_app.extensions["job_registry"]
    job = registry.get(job_id)
    if job is None:
        return _error("No such job.", 404)

    payload = _job_payload(job)
    status = job.status_code if job.status == jobs.FAILED else 200
    return jsonify(payload), status or 500


@api.get("/jobs/<job_id>/font.ttf")
def download_font(job_id: str):
    """Serve one job's finished font, and only that."""
    registry: jobs.JobRegistry = current_app.extensions["job_registry"]
    job = registry.get(job_id)
    if job is None:
        return _error("No such job.", 404)
    if job.status != jobs.COMPLETED or job.font_path is None:
        return _error(
            "This font is not ready yet (status: {}).".format(job.status), 409
        )
    if not job.font_path.exists():
        return _error("This font is no longer available.", 410)

    return send_file(
        job.font_path,
        mimetype="font/ttf",
        as_attachment=True,
        download_name="{}.ttf".format(job.family_name),
    )


@api.post("/preview")
def preview():
    """Render a line of notation in a finished font.

    Bad notation is not a server error: it is something the writer is in the
    middle of typing. It comes back with a 200 and the message beside it, the
    same way a missing glyph does.
    """
    registry: jobs.JobRegistry = current_app.extensions["job_registry"]
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    job_id = payload.get("job_id")

    if not isinstance(text, str):
        return _error("'text' must be a string.", 400)

    job = registry.get(job_id) if job_id else None
    if job_id and job is None:
        return _error("No such job.", 404)
    if job is not None and job.status != jobs.COMPLETED:
        return _error(
            "That font is not ready yet (status: {}).".format(job.status), 409
        )

    try:
        html = service.render_fragment(text, job.font_path if job else None)
    except NotationError as error:
        return jsonify({"html": None, "error": str(error), "missing": []}), 200

    missing = service.coverage(text, job.font_path) if job else []
    return jsonify({"html": html, "error": None, "missing": missing}), 200


@api.get("/template.pdf")
def template():
    """Serve the printable three page form, exactly as committed."""
    path: Path = current_app.config["TEMPLATE_PATH"]
    if not path.exists():
        logger.error("Template PDF missing at %s", path)
        return _error("The handwriting template is unavailable.", 503)
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="handwrite_template.pdf",
    )


@api.errorhandler(413)
def too_large(_error):
    return _error_response()


def _error_response():
    return (
        jsonify({"error": "The upload is too large."}),
        413,
    )


__all__ = ["api", "errors"]
