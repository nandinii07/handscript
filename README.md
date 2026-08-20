<p align="center">
    <a href="https://github.com/builtree/handwrite">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/logo_white_background.svg" width=40%>
        </img>
    </a>
</p>

[![Tests](https://github.com/yashlamba/handwrite/workflows/Tests/badge.svg)](https://github.com/yashlamba/handwrite/actions)
[![PyPI version](https://img.shields.io/pypi/v/handwrite.svg)](https://pypi.org/project/handwrite)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

# Handwrite - Type in your Handwriting!

Ever had those long-winded assignments, that the teacher always wants handwritten?
Is your written work messy, cos you think faster than you can write?
Now, you can finish them with the ease of typing in your own font!

<p align="center">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/handwrite.gif">
        </img>
</p>

Handwrite makes typing written assignments efficient, convenient and authentic.

Handwrite generates a custom font based on your handwriting sample, which can easily be used in text editors and word processors like Microsoft Word & Libre Office Word!

Handwrite is also helpful for those with dysgraphia.

You can get started with Handwrite [here](https://yashlamba.github.io/handwrite/).

## What you get

1. **A font from your handwriting.** Print a form, fill in one character per
   box, scan it, and `handwrite` turns it into a `.ttf` you can install and
   use in any word processor.

2. **Scientific notation in that handwriting.** `handwrite-render` types
   formulas like `E = mc^2`, `H_2O` and `SO_4^{2-}` in your font, with real
   superscripts and subscripts.

There are two forms. The original `handwrite_sample.pdf` collects 80
characters on one page. The newer `handwrite_sample_extended.pdf` collects
191 across three pages, adding Greek in both cases, math operators, arrows
(`α β γ δ ε θ λ μ π ρ σ φ ω Δ Ω × ÷ ≠ ≤ ≥ ± ∓ ≈ ∝ ∞ √ → ← ↔ { } | °`) - use
that one if you want to write notation.

## Quick start

```console
pip install handwrite            # also needs potrace and fontforge installed

# Build a font from a single-page form:
handwrite scan.jpg fonts/

# ...or from the three-page extended form (one image per page in a directory):
handwrite scans/ fonts/

# Type notation in it:
handwrite-render --font fonts/MyFont.ttf "E = mc^2" "H_2O" "SO_4^{2-}"
```

The second command writes a self-contained HTML page; print it to PDF from
your browser. Supported notation is `^` and `_`, with `{}` to group more than
one character - see the
[usage guide](https://yashlamba.github.io/handwrite/usage/) for the full
syntax.

## Web application

A small Flask app (`app/`) sits in front of the library above, so filling in
the form is the only part left to do by hand: upload three scans, watch it
build, then type in the result.

```
Browser -> gunicorn (production) or `flask run` (local) -> Flask (app/) -> handwrite/
```

`app/service.py` is the only application module that imports `handwrite` -
everything else is HTTP handling, job tracking and templates that know
nothing about fonts. Job metadata (status, stage, the finished font's path)
lives in a small SQLite database under the job root; the files a build
produces - pages, traced outlines, the `.ttf` - stay on disk exactly where
they always did. That split is what lets a job survive the process
restarting: the facts about it are durable, not just the files.

### Local setup

Requires Python 3.9+ and, for anything that actually builds a font,
**Potrace** and **FontForge** on `PATH`:

```console
brew install potrace fontforge        # macOS
apt install potrace fontforge         # Debian/Ubuntu

pip install -e .
pip install -r app/requirements.txt
python -m flask --app app.main run --debug
```

Open `http://127.0.0.1:5000`. Everything defaults sensibly for local use;
see `.env.example` for what can be tuned.

### Running with Docker

The image bundles Potrace, FontForge and the fonts `formgen.py` needs, so
nothing has to be installed on the host:

```console
docker build -t handwrite .
docker run -p 8000:8000 -v handwrite-jobs:/data/handwrite-jobs handwrite
```

The volume is what makes a job outlive the *container*, not only the
process inside it - without it, recreating the container (as opposed to
restarting it) starts with an empty job store. `GET /health` reports `{"status":
"ok", "build_tools_available": true}` once it is up.

### API overview

| | |
|---|---|
| `POST /api/jobs` | Upload `page_1`/`page_2`/`page_3`, start a build |
| `GET /api/jobs/{id}` | Status, stage, error, download link once ready |
| `GET /api/jobs/{id}/font.ttf` | The finished font |
| `POST /api/preview` | Render one line of notation (`{"text": "...", "job_id": "..."}`) |
| `GET /api/template.pdf` | The printable three-page form |
| `GET /health` | Liveness, plus whether Potrace/FontForge were found |

Page order comes from which field a file was uploaded in, never from its
filename - pages 1 and 3 have the same number of boxes, so filename sorting
would be exactly the mistake the backend's own page validation exists to
catch.

### Production deployment

One gunicorn worker process with several threads, not several worker
processes. This is deliberate: job builds already run on their own bounded
thread pool inside the app (`app/jobs.py`), so one process gets full
concurrency for both requests and builds, and it avoids several processes
racing each other's crash-recovery logic on startup. Scaling beyond one
container means moving the SQLite file to shared storage or a real database
first - a real change, not a flag.

Configuration is environment variables only - there are no secrets to set,
since nothing here calls a third-party service:

| Variable | Default | |
|---|---|---|
| `HANDWRITE_JOB_ROOT` | `/tmp/handwrite-jobs` | Where jobs and their SQLite database live |
| `HANDWRITE_JOB_TTL_HOURS` | `24` | How long a finished job is kept before cleanup removes it |
| `HANDWRITE_MAX_UPLOAD_MB` | `10` | Largest single page image accepted |
| `HANDWRITE_BUILD_TIMEOUT` | `120` | Seconds before a stuck build is given up on |
| `HANDWRITE_MAX_WORKERS` | `3` | Concurrent font builds |
| `HANDWRITE_FONT_FAMILY` | `MyHandwriting` | Default name when a request does not give one |
| `HANDWRITE_LOG_LEVEL` | `INFO` | Standard Python logging level |

See `.env.example` for the full list with explanations.

### Limitations

- **Job storage is one SQLite file.** It survives a restart of the same
  container/volume; it is not shared across multiple containers or hosts.
- **A build interrupted by a restart is not resumed** - it is marked failed
  with a clear reason, and the user re-uploads. Builds take about two
  seconds, so this is deliberately simple rather than durable-queue-simple.
- **No authentication.** Anyone who can reach the API can start a build;
  a job's id is an unguessable random token, which is the only thing
  standing between a stranger and someone else's font.
- Cleanup runs on a timer inside the process; it does not run between
  container restarts if the process never stays up long enough to fire.

## Sample

You just need to fill up a form:

<p align="center">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/handwrite_filled_form.jpg" width=50%>
        </img>
</p>

Here's the end result!

<p align="center">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/handwrite_sentence.png">
        </img>
</p>

## Credits and Reference

1. [Potrace](http://potrace.sourceforge.net/) algorithm and package has been immensely helpful.

2. [Fontforge](https://fontforge.org/en-US/) for packaging and adjusting font parameters.

3. [Sacha Chua's](https://github.com/sachac) [project](https://github.com/sachac/sachac-hand/) proved to be a great reference for fontforge python.

4. All credit for svgtottf converter goes to this [project](https://github.com/pteromys/svgs2ttf) by [pteromys](https://github.com/pteromys). We made a quite a lot of modifications of our own, but the base script idea was derived from here.
