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
   box, scan it, and HandScript turns it into a `.ttf` you can install and
   use in any word processor.

2. **Scientific notation in that handwriting.** Type formulas like
   `E = mc^2`, `H_2O` and `SO_4^{2-}` in your font, with real superscripts
   and subscripts.

There are two forms. The original `handwrite_sample.pdf` collects 80
characters on one page. The newer `handwrite_sample_extended.pdf` collects
191 across three pages, adding Greek in both cases, math operators, arrows
(`α β γ δ ε θ λ μ π ρ σ φ ω Δ Ω × ÷ ≠ ≤ ≥ ± ∓ ≈ ∝ ∞ √ → ← ↔ { } | °`) - use
that one if you want to write notation. Run `handscript glyphs` to print
exactly what each page expects.

The core product is the **`handscript` Python package** below - it works
entirely on your own machine from Python or the command line, with no server,
browser, or network involved. The optional [web application](#web-application)
further down wraps the same package in a point-and-click UI; it is a
convenience, not a requirement.

## HandScript - the Python package

### Installation

```console
pip install -e .              # from a clone, for development
pip install handscript        # once published to PyPI
```

Either way you also need **Potrace** and **FontForge** on `PATH` - see
[Native dependencies](#native-dependencies) below; nothing in `pip install`
can put these there for you, since they are not Python packages.

### Input format

Two ways to build a font, matching the two printed forms:

- **`input_dir`** - a directory containing one scanned page image per form
  page (`.png`/`.jpg`/`.jpeg`/`.bmp`/`.tif`/`.tiff`), for the 191-character
  extended form. Name them so sorting puts them in order, e.g. `page_1.jpg`,
  `page_2.jpg`, `page_3.jpg` - pages are matched by sorted filename, not by
  guessing content, because two of the three pages share an identical box
  grid and a swapped scan would otherwise build a font with the wrong
  character in every box, silently.
- **`input_path`** - a single scanned image, for the original 80-character
  form.

Each scan should be reasonably straight and right-side up; HandScript checks
this itself (see [Limitations](#limitations)) and raises
`PageValidationError` rather than silently building a wrong font from a
rotated or out-of-order scan.

### Python API

```python
from handscript import HandScript

hs = HandScript()

result = hs.create_font(
    input_dir="handwriting/",
    output_path="output/my_handwriting.ttf",
)

print(result.font_path)     # output/my_handwriting.ttf
print(result.family_name)   # "my_handwriting" (from the filename, by default)

# Check whether the font can draw some text before you rely on it:
missing = hs.check_coverage("E = mc^2", result.font_path)

# Typeset notation in the font you just built:
hs.render(["E = mc^2", "H_2O", "SO_4^{2-}"], result.font_path, "formulas.html")
```

See `examples/basic_usage.py` for a complete, runnable script, and
`handscript/pipeline.py` for the full docstrings of every method.

Defaults (family name, style, font size, strict mode, ...) can be set once
instead of on every call:

```python
from handscript import HandScript, HandScriptConfig

hs = HandScript(HandScriptConfig(family_name="My Handwriting", strict_notation=True))
```

### CLI

```console
handscript build ./handwriting --output ./my_handwriting.ttf
handscript render ./my_handwriting.ttf "E = mc^2" "H_2O"
handscript coverage ./my_handwriting.ttf "SO_4^{2-}"
handscript glyphs
handscript --help
```

Supported notation is `^` and `_` for single-character scripts, `{}` to
group more than one character, `{a}/{b}` for fractions, `√{...}` for
radicals, and `^^`/`__` (doubled markers) for stacked notation such as
limits - see the [usage guide](https://yashlamba.github.io/handwrite/usage/)
for the full syntax reference.

The original `handwrite` / `handwrite-render` commands are still installed
and unchanged, for anything already scripted against them.

### Output format

A standard TrueType `.ttf`, installable and usable anywhere a font can be -
word processors, design tools, browsers via `@font-face`. `handscript render`
produces a self-contained HTML file (the font is embedded as base64); print
it to PDF from a browser to get a document.

### Configuration

`HandScriptConfig` (passed to `HandScript(...)`) covers family name, style,
an alternate pipeline configuration file, where to keep intermediate files,
and notation rendering options - see `handscript/config.py` for the full,
documented list. Nothing here is an environment variable or a secret; it is
all plain constructor/method arguments, since a library has no deployment
environment to read one from.

### Native dependencies

The actual image-to-font work is done by two system binaries, not Python
packages - `pip install` cannot install either of them:

| Binary | Used for | Install |
|---|---|---|
| [Potrace](http://potrace.sourceforge.net/) | Tracing each cropped character bitmap to a vector outline | `brew install potrace` (macOS), `apt install potrace` (Debian/Ubuntu) |
| [FontForge](https://fontforge.org/) | Assembling the traced outlines into a `.ttf` | `brew install fontforge` (macOS), `apt install fontforge` (Debian/Ubuntu) |

If either is missing, `HandScript.create_font` raises
`MissingDependencyError` naming which one - it never builds a partial or
placeholder font instead. `handwrite/svgtottf.py` and `handwrite/pngtosvg.py`
are the two modules that call out to them, if you want to see exactly how.
`opencv-python` and `Pillow` (the box-detection and image-I/O dependencies)
*are* ordinary Python packages, and are installed automatically as part of
`pip install`.

### Platforms

Tested on macOS and Linux, which is also where Potrace and FontForge are
straightforward to install. Nothing in the pipeline is platform-specific by
design, but Windows support depends entirely on getting both binaries onto
`PATH` there - see `docs/contributing.md` for notes on that.

### Using HandScript from another Python project

`handscript` is an ordinary importable package with no side effects at
import time and no global state - construct a `HandScript()` (or several,
with different `HandScriptConfig`s) anywhere in your own code:

```python
from handscript import HandScript, InvalidInputError, PageValidationError

hs = HandScript()
try:
    result = hs.create_font(input_dir=scans_dir, output_path=out_path)
except PageValidationError as error:
    ...  # a scan was upside down, rotated, or out of order
except InvalidInputError as error:
    ...  # a bad path, wrong page count, or unsupported image type
```

See `handscript/exceptions.py` for the full hierarchy - every exception the
package raises inherits from `HandScriptError`.

### Limitations

- **No OCR.** Character identity comes from box *position* on the form, not
  from reading the ink - so the form itself, not a freehand page, is the
  required input shape.
- **Requires two native binaries** (Potrace, FontForge) that `pip` cannot
  install - see [Native dependencies](#native-dependencies).
- **A build takes a couple of seconds** and runs synchronously in the calling
  process/thread - `create_font` is a blocking call by design, not a
  background job; wrap it yourself (a thread, a task queue) if you need it
  otherwise.
- **Only TrueType (`.ttf`) output** - not OpenType (`.otf`) - matching what
  the underlying FontForge assembly step produces.

## Web application

An optional Flask app (`app/`) sits in front of the package above, so filling
in the form is the only part left to do by hand: upload three scans, watch it
build, then type in the result. It is not required to use HandScript - the
package above works standalone from Python or the CLI, with no server, no
browser, and no HTTP involved anywhere in its own code path.

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
