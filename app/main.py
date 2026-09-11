"""Application factory.

Browser -> production web server (gunicorn) -> this Flask app -> handwrite.
Nothing more sits between them: no queue, no cache, no second service. See
app/config.py for what varies between a laptop and a deployed instance, and
app/store.py for why a restart no longer forgets a job.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify

from app.api import api
from app.config import TEMPLATE_PATH, load_settings
from app.jobs import JobRegistry
from app.web import web


def _configure_logging(application: Flask) -> None:
    """One line per event, to stdout - what a container runtime expects.

    Nothing here logs a request body, an uploaded image or font bytes: the
    messages this application writes are job ids, statuses and exception
    class names, never handwriting.
    """
    level = os.environ.get("HANDWRITE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    application.logger.setLevel(level)


def create_app(job_root: Optional[Path] = None, **config) -> Flask:
    """Build the Flask application.

    `job_root` and `**config` remain accepted directly (rather than only
    through the environment) because the test suite builds many short-lived
    applications against their own temporary directories; production simply
    lets the environment supply everything instead.
    """
    settings = load_settings()
    _configure_logging_once = not logging.getLogger().handlers
    application = Flask(__name__)
    if _configure_logging_once:
        _configure_logging(application)

    application.config.update(
        MAX_CONTENT_LENGTH=settings.max_content_length,
        MAX_PAGE_BYTES=settings.max_page_bytes,
        TEMPLATE_PATH=TEMPLATE_PATH,
        FONT_FAMILY=settings.font_family,
        JOB_ROOT=Path(job_root) if job_root else settings.job_root,
        MAX_CONCURRENT_BUILDS=settings.max_workers,
        BUILD_TIMEOUT=settings.build_timeout,
        JOB_TTL_HOURS=settings.job_ttl_hours,
        CORS_ORIGINS=settings.cors_origins,
    )
    application.config.update(config)

    registry = JobRegistry(
        root=application.config["JOB_ROOT"],
        max_workers=application.config["MAX_CONCURRENT_BUILDS"],
        timeout=application.config["BUILD_TIMEOUT"],
        ttl_hours=application.config["JOB_TTL_HOURS"],
        # The test suite passes its own short-lived registries and does not
        # want a background thread outliving the test; production keeps the
        # default interval from JobRegistry.
        cleanup_interval=config.get("CLEANUP_INTERVAL", 1800.0),
    )
    application.extensions["job_registry"] = registry

    application.register_blueprint(api)
    application.register_blueprint(web)

    @application.after_request
    def _allow_cross_origin(response):
        """Let a frontend served from a different origin call this API.

        No dependency added (no flask-cors) for something this small. Applied
        to every response, including Flask's own automatic reply to an
        OPTIONS preflight - browsers send one before a POST whose
        Content-Type is application/json (/api/preview), since that content
        type is not CORS-"simple". A plain <form> or FormData POST
        (/api/jobs) never triggers a preflight, so this is the only piece
        needed for either request shape.
        """
        origin = application.config["CORS_ORIGINS"]
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @application.errorhandler(413)
    def _too_large(_error):
        return jsonify({"error": "The upload is too large."}), 413

    @application.errorhandler(500)
    def _internal_error(error):
        # A route that reaches this has already let an exception escape;
        # logging it here is a backstop, not the primary path (jobs.py logs
        # build failures as they happen). Never hand the exception itself,
        # or its traceback, back to the browser.
        application.logger.exception("unhandled exception: %s", error)
        return jsonify({"error": "Something went wrong. Please try again."}), 500

    @application.get("/health")
    @application.get("/healthz")
    def _health():
        """Liveness and a basic capability check - no paths, no internals."""
        binaries_ok = shutil.which("potrace") is not None and (
            shutil.which("fontforge") is not None
        )
        return jsonify({"status": "ok", "build_tools_available": binaries_ok}), 200

    return application


# Used by `flask run` for local development and as the target gunicorn loads
# in production (see wsgi.py / the Dockerfile's CMD).
app = create_app()
