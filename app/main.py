"""Application factory."""

import logging
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify

from app.api import api
from app.jobs import JobRegistry
from app.web import web

# The committed three page form, served as-is. The backend's form generator is
# not run here: the PDF in the repository is the one that was printed, filled
# in and validated.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPOSITORY_ROOT / "handwrite_sample_extended.pdf"

# One page of handwriting is a photo, so the ceiling is generous; the per-page
# limit in the routes is what actually governs.
MAX_CONTENT_LENGTH = 40 * 1024 * 1024


def create_app(job_root: Optional[Path] = None, **config) -> Flask:
    """Build the Flask application."""
    logging.basicConfig(level=logging.INFO)

    application = Flask(__name__)
    application.config.update(
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        TEMPLATE_PATH=TEMPLATE_PATH,
        FONT_FAMILY="MyHandwriting",
        JOB_ROOT=Path(job_root) if job_root else Path("/tmp/handwrite-jobs"),
        MAX_CONCURRENT_BUILDS=3,
        BUILD_TIMEOUT=120.0,
    )
    application.config.update(config)

    registry = JobRegistry(
        root=application.config["JOB_ROOT"],
        max_workers=application.config["MAX_CONCURRENT_BUILDS"],
        timeout=application.config["BUILD_TIMEOUT"],
    )
    application.extensions["job_registry"] = registry

    application.register_blueprint(api)
    application.register_blueprint(web)

    @application.errorhandler(413)
    def _too_large(_error):
        return jsonify({"error": "The upload is too large."}), 413

    @application.get("/healthz")
    def _health():
        return jsonify({"status": "ok"}), 200

    return application


app = create_app()
