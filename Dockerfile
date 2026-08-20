# Handwrite - production image.
#
# Browser -> gunicorn -> Flask (app/) -> handwrite backend, all in one
# container. The backend needs two system binaries that pip cannot install -
# potrace (bitmap tracing) and fontforge (font assembly) - so this cannot be
# a plain python-slim image with `pip install`; both are installed from apt
# below, and the application never assumes they exist without checking
# (handwrite.svgtottf raises FontForgeNotFound / PotraceNotFound if either is
# missing, and GET /health reports whether they were found).
#
# One gunicorn worker process, several threads. This is deliberate, not a
# resource cut: job metadata lives in SQLite (app/store.py) and font builds
# already run on a small in-process thread pool (app/jobs.py) - so a single
# process gets fair concurrency for both without a second process racing the
# same recovery-on-startup logic against jobs a sibling process owns. See
# README.md "Production deployment" for how to scale beyond one container.

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Handwrite"
LABEL org.opencontainers.image.description="Turn handwriting into a font."

# potrace, fontforge     - the backend's own external tools
# fonts-dejavu-core       - covers Greek/math, needed only if the printable
#                           form is ever regenerated (formgen.py); harmless to
#                           have even if it never is
# libgl1, libglib2.0-0    - opencv-python (used by the box-detection stage)
# curl                    - the container HEALTHCHECK below
RUN apt-get update && apt-get install -y --no-install-recommends \
        potrace \
        fontforge \
        fonts-dejavu-core \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/handwrite

# Dependencies first, so editing application code does not invalidate the
# apt/pip layers on a rebuild.
COPY setup.py MANIFEST.in README.md ./
COPY handwrite ./handwrite
RUN pip install --no-cache-dir .

COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

COPY app ./app
COPY handwrite_sample_extended.pdf ./handwrite_sample_extended.pdf

# A non-root runtime user, owning only what it needs to write to: the job
# store. Everything else in the image is read-only to it.
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin handwrite \
    && mkdir -p /data/handwrite-jobs \
    && chown -R handwrite:handwrite /data/handwrite-jobs /srv/handwrite

ENV HANDWRITE_JOB_ROOT=/data/handwrite-jobs \
    HANDWRITE_JOB_TTL_HOURS=24 \
    HANDWRITE_MAX_UPLOAD_MB=10 \
    HANDWRITE_BUILD_TIMEOUT=120 \
    HANDWRITE_MAX_WORKERS=3 \
    HANDWRITE_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

# Where completed fonts and job metadata live. Mount a volume here (or point
# HANDWRITE_JOB_ROOT elsewhere) for jobs to survive the *container* being
# recreated, not only restarted - see README.md.
VOLUME ["/data/handwrite-jobs"]

USER handwrite

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["gunicorn", \
     "--workers", "1", \
     "--threads", "8", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "180", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
