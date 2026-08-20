"""The pages a person actually visits.

Server-rendered templates and a little vanilla JavaScript. There is no build
step and no framework: the whole application is five screens, and the browser
does three things - upload files, poll a job, and ask for a formula preview.

These routes render HTML only. Everything else goes through the JSON API in
`app.api`, which the browser calls directly, so the frontend is a client of
that API exactly like any other consumer would be.
"""

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_file

web = Blueprint("web", __name__)

# A font this pipeline produced, shown on the landing page so a first-time
# visitor can see what the result looks like before committing to filling in
# three pages. It is the sample the renderer tests use.
DEMO_FONT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "test_data"
    / "renderer"
    / "sample.ttf"
)


@web.get("/")
def landing():
    return render_template("landing.html")


@web.get("/template")
def template_page():
    return render_template("template.html")


@web.get("/upload")
def upload_page():
    return render_template("upload.html")


@web.get("/build/<job_id>")
def build_page(job_id: str):
    """Watch a job. The page polls the API; it holds no state of its own."""
    registry = current_app.extensions["job_registry"]
    if registry.get(job_id) is None:
        abort(404)
    return render_template("build.html", job_id=job_id)


@web.get("/studio/<job_id>")
def studio_page(job_id: str):
    """Type in the finished font. Only reachable once a job has completed."""
    registry = current_app.extensions["job_registry"]
    job = registry.get(job_id)
    if job is None:
        abort(404)
    if job.status != "completed":
        return render_template("not_ready.html", job_id=job_id, status=job.status), 409
    return render_template("studio.html", job_id=job_id, family_name=job.family_name)


@web.get("/demo-font.ttf")
def demo_font():
    """The landing page specimen."""
    if not DEMO_FONT.exists():
        abort(404)
    return send_file(DEMO_FONT, mimetype="font/ttf")
