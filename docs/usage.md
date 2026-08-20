# Getting Started with Handwrite!

## Creating your Handwritten Sample

There are two forms to choose from:

- **`handwrite_sample.pdf`** - the original single page, 80 characters
  (A-Z, a-z, 0-9 and common punctuation).
- **`handwrite_sample_extended.pdf`** - three pages, 191 characters. Page 1 is
  the same as above; page 2 adds Greek letters, math operators, arrows and
  braces (`α β γ δ ε θ λ μ π ρ σ φ ω Δ Ω × ÷ ≠ ≤ ≥ ± ∓ ≈ ∝ ∞ √ → ← ↔ { } | °`);
  page 3 completes the Greek alphabet in both cases and adds calculus,
  set, logic and geometry symbols along with the punctuation a word processor
  inserts for you (`∫ ∑ ∏ ∂ ∇ ħ ′ · ≡ ⇒ ⇌ ∴ ∈ ⊂ ∪ ∩ ∅ ∀ ∃ ∠ ⊥ ∥ ∮ ⊕ ⊗ ≪ ≫
  < > * ^ _ ~ # $ @ \ – — ‘ ’ “ ” …`). Use this one if you want to write
  scientific notation.

You can also regenerate the extended form yourself, which is useful if you
want to change the character set:

```console
python -m handwrite.formgen my_form.pdf
```

Then:

1. Take a printout of the form.

2. Fill the form using the image below as a reference. Write each character
   inside its box - the small character printed under each box tells you what
   to write there. Do not write in boxes marked with a cross.

3. Scan the filled form using a scanner, or Adobe Scan in your phone.

4. Save the image(s) in your system. For the extended form, save one image
   per page and name them so they sort in page order, e.g. `page_1.jpg`,
   `page_2.jpg`, in a directory of their own.

Your form should look like this:

<p align="center">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/handwrite_filled_form.jpg" width=50%>
        </img>
</p>

## Creating your font

1.  Make sure you have installed `handwrite`, `potrace` & `fontforge`.

2.  In a terminal type `handwrite [PATH TO IMAGE] [OUTPUT DIRECTORY]`.
    (You can also type `handwrite -h`, to see all the arguments you can use).

    For the extended three-page form, pass the **directory** holding your page
    scans instead of a single image:

        handwrite path/to/scans/ path/to/output/

    The pages are matched to the form by sorted filename, so `page_1.jpg`
    comes before `page_2.jpg`. The directory must hold exactly one image per
    form page.

3.  (Optional) Config file containing custom options for your font can also be passed using
    the `--config [CONFIG FILE]` argument.

        ???+ note - If you expicitly pass the metadata (filename, family or style) as CLI arguments, they are given a preference over the default config file data.

             - If no config file is provided for an input then the [default config file](https://github.com/yashlamba/handwrite/blob/main/handwrite/default.json) is used.

4.  Your font will be created as `OUTPUT DIRECTORY/OUTPUT FONT NAME.ttf`. Install the font in your system.

5.  Select your font in your word processor and get to work!
    Here's the end result!

<p align="center">
        <img src="https://raw.githubusercontent.com/builtree/assets/handwrite/handwrite_sentence.png">
        </img>
</p>

## Writing scientific notation

Installing the font is enough for ordinary typing. For superscripts and
subscripts there is a second command, `handwrite-render`, which lays out a
formula and writes a self-contained HTML page using your font:

```console
handwrite-render --font MyFont.ttf "E = mc^2" "H_2O" "SO_4^{2-}"
```

That writes `notation.html`. Open it in a browser; to get a PDF, use the
browser's own Print dialog. Other options:

- `--output FILE` - where to write the page (default `notation.html`).
- `--input FILE` - read formulas from a text file, one per line.
- `--font-size N` - size of normal text in pixels (default 48).

Running it with no formulas renders a built-in demo set.

### Notation syntax

The syntax is a small subset of LaTeX's, and nothing more:

| You type      | You get                                    |
| ------------- | ------------------------------------------ |
| `x^2`         | `2` raised, at reduced size                 |
| `H_2O`        | `2` lowered, at reduced size                |
| `x_1^2`       | subscript and superscript on the same base  |
| `x^{10}`      | braces raise the whole group, both digits   |
| `A_{ij}`      | braces lower the whole group                |
| `SO_4^{2-}`   | both, with a grouped superscript            |

Rules worth knowing:

- Without braces, `^` and `_` apply to exactly **one** character, so `x^10`
  raises only the `1`.
- `{` and `}` are ordinary characters unless they come straight after a `^`
  or `_`, so `f{x}` is plain text and prints as written.
- Everything else - Greek letters, operators, arrows - is ordinary text and
  is printed as it is, in your handwriting.
- One level only: `x^{a^2}` is rejected rather than silently misprinted.
  There are no fractions, roots, matrices or integrals.

Anything malformed (`x^`, `x^{12`, `x^{}`) stops with a message naming the
position of the problem, instead of producing a wrong-looking formula.

There are no separate superscript or subscript glyphs anywhere: a raised `2`
is your ordinary handwritten `2`, scaled down and shifted up. That is why the
form never asks you to write one.

## Configuring

TO DO
