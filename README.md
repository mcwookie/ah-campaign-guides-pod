# Lulu Cover Tools

Two standalone scripts for prepping a print-on-demand book for Lulu.com:

- **`split_and_resize.py`** — splits a source PDF into a 1-page front-cover
  PDF and a remaining-pages interior PDF, resizing both to a Lulu trim size.
- **`make_wraparound_cover.py`** — builds a full front+back wraparound cover
  PDF, auto-stylizing a back cover to match your front cover's art and
  color palette, with a title, description text, optional logo, and a
  fan-print disclaimer.

## Install

```bash
pip install pypdf pillow pymupdf requests beautifulsoup4 numpy
```

## Script 1: split_and_resize.py

```bash
python split_and_resize.py my_guide.pdf \
    --cover-out cover.pdf --interior-out interior.pdf
```

Defaults to Lulu's **Executive (7x10in)** trim size. Every page is scaled to
fit (aspect-preserved, nothing cropped or stretched) and centered on the new
page — no content is lost.

Other options:

```bash
# A different named Lulu trim size
python split_and_resize.py my_guide.pdf --trim us_letter ...

# A custom size in inches
python split_and_resize.py my_guide.pdf --width 6 --height 9 ...
```

Run `python split_and_resize.py --help` for the full option list, or see
`lulu_sizes.py` for every supported named trim size.

## Script 2: make_wraparound_cover.py

```bash
python make_wraparound_cover.py cover.pdf \
    --description-file my_description.txt \
    --campaign-name "The Dunwich Legacy" \
    --logo ah_tcg_logo.png \
    --output wraparound_cover.pdf
```

This is the file you upload to Lulu as your cover. It takes page 1 of
`cover.pdf` (typically the output of script 1) as the front panel, and
builds a matching back panel using:

- a mirrored, blurred, darkened crop of that same front-cover art as the
  background (so the two panels share one visual identity automatically),
- the front cover's own dominant color as an accent/border color,
- your supplied logo image (optional) at the top,
- the campaign name as a title,
- your description text, and
- a fixed disclaimer at the bottom: *"This is a fan-made document for
  personal use only and is not an official Fantasy Flight Games product."*

Output is sized correctly for a **Coil Bound** (or Saddle Stitch) cover:
2x the trim width with **no spine gap** (Lulu doesn't require spine-width
math for those bindings), plus the required 0.125in bleed on every outer
edge, added by extending the artwork itself outward — not blank padding.

### Getting the description text

Two ways to supply it:

1. **`--description-file some_text.txt`** (recommended). Just paste the
   product copy you want into a text file. This repo includes
   `dunwich_legacy_description.txt` as a working example.
2. **`--url "https://..."`**. The script will try to scrape the paragraph
   text between the page's `<h1>` title and a "news"/"related products"
   style heading. This is a generic heuristic, not a purpose-built parser
   for any specific site — **it will not work on every site**, and it does
   not work on fantasyflightgames.com specifically, which returns an
   HTTP 403 to non-browser requests. When scraping fails you'll get a
   clear error telling you to use `--description-file` instead — that's
   expected, not a bug to chase.

### Trim size / bleed options

Same `--trim`, `--width`, `--height` flags as script 1, plus:

- `--bleed` — bleed per edge in inches (default 0.125, matching Lulu)
- `--dpi` — render resolution (default 300)

## Files in this folder

| File | Purpose |
|---|---|
| `lulu_sizes.py` | Shared trim-size table used by both scripts |
| `split_and_resize.py` | Script 1 |
| `make_wraparound_cover.py` | Script 2 |
| `dunwich_legacy_description.txt` | Example description text (The Dunwich Legacy) |
| `ah_tcg_logo.png` | Example logo asset you can pass to `--logo` |

## Notes / things worth knowing

- **Fonts**: the script tries a short list of common serif font names
  (DejaVu Serif, Liberation Serif, FreeSerif, Georgia) and falls back to a
  plain bitmap font if none are found on your system. If your output text
  looks like a basic pixel font, install one of those (e.g.
  `apt install fonts-dejavu` on Debian/Ubuntu) or point the script at your
  own via the `FONT_CANDIDATES` dict at the top of the file.
- **Auto-shrinking text**: the description font size shrinks automatically
  to fit above the disclaimer. If your description text is very long, it
  will get small — trimming the text is better than relying on the
  smallest size.
- **Proof before bulk ordering**: font substitution, color accents, and
  the auto-generated background will vary by input art. Always order a
  single proof copy before printing multiples.
