# Lulu Cover Tools

Four standalone scripts for prepping print-on-demand books for Lulu.com:

- **`split_and_resize.py`** — splits a source PDF into a 1-page front-cover
  PDF and a remaining-pages interior PDF, resizing both to a Lulu trim size.
- **`make_wraparound_cover.py`** — builds a full front+back wraparound cover
  PDF, auto-stylizing a back cover to match your front cover's art and
  color palette, with a title, description text, optional logo, and a
  fan-print disclaimer.
- **`combine_investigator_rules.py`** — concatenates a folder of
  investigator-rules-insert PDFs, in release order, into one print-ready
  PDF at their native Small Square trim (no resizing), automatically
  fixing press-proof crop marks and non-embedded fonts along the way.
- **`make_investigator_rules_cover.py`** (+ `arkham_art.py`) — a one-time
  wraparound cover generator for the combined investigator-rules book,
  using procedurally generated original background art.

I also want to shout out clayton-grey's reformatted Arkham Horror: The Card Game [standalone scenario rules](https://github.com/clayton-grey/arkham_campaign_guides).  These are already formatted for printing (I use [lulu.com](https://lulu.com) and 7.5"x7.5" is the `small square` book size).  They include two scenarios (`Curse of the Rougarou` and `Carnevale of Horrors`) that haven't been digitized before. All I did was combine them into one pdf and generate a wraparound cover.

## Install

```bash
pip install pypdf pillow pymupdf requests beautifulsoup4 numpy
```

`split_and_resize.py` also shells out to **Ghostscript** (`gs`) to force-embed
fonts in its outputs (see below); install it with `apt install ghostscript`
on Debian/Ubuntu.

## Script 1: split_and_resize.py

```bash
python split_and_resize.py my_guide.pdf \
    --cover-out cover.pdf --interior-out interior.pdf
```

Defaults to Lulu's **Executive (7x10in)** trim size. Every page is scaled to
fit (aspect-preserved, nothing cropped or stretched) and centered on the new
page — no content is lost.

**Margin fill**: when the source page's aspect ratio doesn't match the
target trim, scale-to-fit leaves blank bars on two opposite edges (e.g.
white bars above and below every page when fitting 8.5x11 letter pages
into a 7x10 Executive trim). By default the script fills those bars with
a **mirrored reflection of the page's own edge content, blurred into a
soft ambient color bleed** — rasterized only in that thin margin strip,
so the page reads as a natural full-bleed design instead of floating on
white, without looking like an obvious flipped duplicate of the edge.
The actual page content (text, vector art) is untouched and stays full
vector quality; only the filler strip is raster.

```bash
# Default: blurred mirror margin fill
python split_and_resize.py my_guide.pdf ...

# Crisper mirrored reflection, no blur (can look "flipped")
python split_and_resize.py my_guide.pdf --margin-fill mirror ...

# Flat color extension from an averaged edge sliver, smoothed
python split_and_resize.py my_guide.pdf --margin-fill edge-blur ...

# Flat color extension, unsmoothed (can look streaky)
python split_and_resize.py my_guide.pdf --margin-fill edge ...

# Old behavior: leave the margins blank/white
python split_and_resize.py my_guide.pdf --margin-fill white ...
```

The five `--margin-fill` modes break down along two independent axes --
what pixels the fill is built from, and whether it's blurred afterward:

| Mode | Source | Blurred | Looks like |
|---|---|---|---|
| `blur` (default) | mirrored reflection | yes | soft ambient color bleed |
| `mirror` | mirrored reflection | no | crisp, recognizably-flipped duplicate |
| `edge-blur` | averaged edge sliver | yes | smooth flat gradient |
| `edge` | averaged edge sliver | no | flat but can look streaky |
| `white` | none | -- | blank bar (old behavior) |

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

## Script 3: combine_investigator_rules.py

```bash
python combine_investigator_rules.py ./rules_inserts \
    --output combined_investigator_rules.pdf
```

Scans a folder for investigator-rules-insert PDFs named with a two-digit
release-order prefix (e.g. `01-dwl-ahc65_dunwich_legacy_rules_insert.pdf`,
`02-ptc-ahc67_rules_insert_v2.pdf`) and concatenates them, in prefix
order, into one PDF -- pages untouched. Unlike the other two scripts,
this one does **not** resize anything: these inserts already come at
Lulu's Small Square (7.5in x 7.5in) trim, and the whole point is to
print them at that size, not convert them to Executive.

What it checks for you, rather than silently doing the wrong thing:

- **Duplicate prefixes** (two files both starting `03-...`) stop the
  script with an error naming both files, rather than guessing an order.
- **Files with no two-digit prefix** are skipped with a note (so a
  `combined.pdf` from a previous run sitting in the same folder doesn't
  get swept up into a new one).
- **Press-proof exports with crop marks** (some releases -- often named
  with a `-web` suffix -- are exported as full press-ready sheets with
  visible crop marks and slug area around the actual page, larger than
  the real trim size) are detected automatically via the PDF's embedded
  TrimBox and cropped down to it before anything else happens, so the
  crop marks don't end up baked into your printed book. You'll see a
  note when this kicks in; no flag needed.
- **Non-embedded fonts** -- Lulu rejects any interior PDF containing
  one, even a "standard" font like Times-Roman that every viewer
  nominally has built in. Some files use a fallback system font for a
  handful of symbol glyphs their main custom fonts don't include (the
  ® and © in a copyright line, say), and that fallback often isn't
  embedded. When detected, just those specific characters are redacted
  and redrawn with an embedded substitute font (DejaVu Serif or
  Liberation Serif, auto-detected from common system paths, or point
  at your own with `--replacement-font`), sampling the surrounding
  background color so the patch blends in. Nothing else in the file is
  touched. Disable with `--no-embed-fix` if you'd rather handle it
  yourself.
- **Genuine page-size mismatches** (after the TrimBox check above --
  i.e. an actual different trim size, not just a proof export) stop the
  script with an error by default. A file at the wrong size usually
  means the wrong file got dropped in the folder, not something to
  paper over automatically. Pass `--allow-size-mismatch` if you do want
  it scaled-to-fit and centered (reusing the same logic as script 1)
  instead of refusing to proceed.

It also prints a summary table mapping each source file to its final
page range in the combined PDF, handy for cross-referencing later:

```
  #  file                                                     pages   final pages
  1  01-dwl-ahc65_dunwich_legacy_rules_insert.pdf                 2           1-2
  2  02-ptc-ahc67_rules_insert_v2.pdf                              2           3-4
```

Other options: `--pattern` to change the glob used to find files
(default `*.pdf`), `--trim`/`--width`/`--height` if you're ever
validating against a size other than Small Square.

## Script 4: make_investigator_rules_cover.py (+ arkham_art.py)

```bash
python make_investigator_rules_cover.py \
    --logo ah_tcg_logo.png \
    --output investigator_rules_cover.pdf
```

A one-time cover generator for the combined investigator-rules book.
Unlike script 2, it doesn't take an existing front-cover PDF to build
from -- there's no single "official" cover for a book spanning multiple
campaigns -- so `arkham_art.py` procedurally generates original cosmic-
horror background art instead (gradient night sky, starfield, a pale
glowing moon, a jagged gothic rooftop silhouette, gnarled branch
shapes, film grain, vignette). This is original generated artwork, not
a reproduction of any official illustration. The real AH:TCG logo
lockup is still reused on both panels for authenticity.

Back cover follows the same visual language as the campaign guide
covers (mirror+blur background, dark panel, title, description, fan
disclaimer), plus an italicized quote + attribution block, since a
Lovecraft quote was part of the brief for this one.

Defaults to Lulu's **Small Square (7.5in x 7.5in)** trim -- matching
script 3's output -- with the same coil-bound-appropriate no-spine,
0.125in-bleed sizing as script 2.

Everything is overridable:

```bash
python make_investigator_rules_cover.py \
    --title "CHAPTER ONE" \
    --subtitle "INVESTIGATOR RULES" \
    --quote "Your quote here" \
    --quote-attribution "– Author, Work" \
    --description-file my_description.txt \
    --logo ah_tcg_logo.png \
    --seed 7 \
    --output investigator_rules_cover.pdf
```

`--seed` controls the generated background art -- same seed always
produces the same art, change it to get a different composition without
touching any code.

## Files in this folder

| File | Purpose |
|---|---|
| `lulu_sizes.py` | Shared trim-size table used by all scripts |
| `split_and_resize.py` | Script 1 |
| `make_wraparound_cover.py` | Script 2 |
| `combine_investigator_rules.py` | Script 3 |
| `make_investigator_rules_cover.py` | Script 4 |
| `arkham_art.py` | Procedural background art generator used by script 4 |
| `dunwich_legacy_description.txt` | Example description text (The Dunwich Legacy) |
| `ah_tcg_logo.png` | Example logo asset you can pass to `--logo` |

## Notes / things worth knowing

- **Font embedding (Lulu upload)**: `split_and_resize.py` copies each source
  page's content stream through unchanged, so any font the source PDF left
  un-embedded comes through un-embedded too. FFG's official campaign guide
  PDFs have shipped pages that use standard Times-Roman/Times-Bold without
  embedding them (seen in the Dream-Eaters A guide, on the Design Notes and
  Credits pages) — Lulu's printer rejects uploads with any non-embedded font.
  To catch this automatically, `split_and_resize.py` now runs both outputs
  through Ghostscript (`-dEmbedAllFonts=true`) after writing them, which
  substitutes and embeds any missing standard fonts without touching image
  quality. This is on by default; pass `--no-font-embed-fix` to skip it, or
  if `gs` isn't installed the script prints a warning and skips it
  automatically — in that case, run `pdffonts your_interior.pdf` yourself
  before uploading and check every row says `yes` in the `emb` column.
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
- **File size**: margin fill (blur/mirror/edge) adds two small JPEG
  strips per page (compressed, not raw), which grows a typical interior
  PDF by roughly 5-20% depending on mode. Use `--margin-fill white` if
  you'd rather keep the file as small as possible and don't mind the
  plain white bars.
- **Proof before bulk ordering**: font substitution, color accents, and
  the auto-generated background will vary by input art. Always order a
  single proof copy before printing multiples.
