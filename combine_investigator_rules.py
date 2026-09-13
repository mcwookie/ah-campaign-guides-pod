#!/usr/bin/env python3
"""
combine_investigator_rules.py

Scan a folder for investigator-rules-insert PDFs named with a two-digit
release-order prefix (e.g. "01-dwl-ahc65_dunwich_legacy_rules_insert.pdf",
"02-ptc-ahc67_rules_insert_v2.pdf"), and concatenate them -- in prefix
order -- into a single print-ready PDF.

By design this does NOT scale pages. These inserts are already sized to
Lulu's Small Square (7.5in x 7.5in) trim, so unlike the campaign guide
scripts, this one just validates that every page actually is that size
and errors out (rather than silently producing a malformed book) if any
page doesn't match.

One exception, handled automatically: some releases are exported as
press-ready proofs with visible crop marks and a slug area around the
actual page (often named with a "-web" suffix) -- the MediaBox is
larger than the real trim size, but the PDF also carries a separate
TrimBox recording where the real page boundary is. When that's
detected, the page is cropped to its TrimBox (crop marks and all
discarded) before the size check runs, so these files combine cleanly
without needing --allow-size-mismatch or losing any print quality.

Another exception, also handled automatically: Lulu rejects any PDF
with a non-embedded font, even a "standard" one like Times-Roman that
every PDF viewer nominally has built in -- some files use a fallback
system font for a handful of symbol glyphs (e.g. (r) and (c)) that
their main custom fonts don't include, and that fallback often isn't
embedded. When detected, just those specific glyphs are redacted and
redrawn using an embedded substitute font (matched to the surrounding
background color), leaving everything else in the file untouched.

Requires: pypdf, pymupdf, pillow, numpy
    pip install pypdf pymupdf pillow numpy

Example:
    python combine_investigator_rules.py ./rules_inserts \\
        --output combined_investigator_rules.pdf

    # If you ever get a file at a different page size and want it
    # scaled-to-fit instead of the script refusing to proceed:
    python combine_investigator_rules.py ./rules_inserts \\
        --output combined_investigator_rules.pdf --allow-size-mismatch

    # Point at a specific substitute font for the non-embedded-font fix,
    # if none of the usual system font paths are found automatically:
    python combine_investigator_rules.py ./rules_inserts \\
        --output combined_investigator_rules.pdf --replacement-font /path/to/font.ttf
"""
import argparse
import io
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation

from lulu_sizes import LULU_TRIM_SIZES_IN, POINTS_PER_INCH, resolve_trim_size

try:
    from split_and_resize import resize_pages
except ImportError:
    resize_pages = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

PREFIX_RE = re.compile(r"^(\d{2})-")
SIZE_EPS_PT = 1.0  # ~0.014in tolerance before treating pages as mismatched

REPLACEMENT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    "DejaVuSerif.ttf",
    "LiberationSerif-Regular.ttf",
]


def find_replacement_font(explicit_path=None):
    if explicit_path:
        if Path(explicit_path).is_file():
            return explicit_path
        sys.exit(f"--replacement-font path not found: {explicit_path}")
    for cand in REPLACEMENT_FONT_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return None


def scan_nonembedded_fonts(pdf_path):
    """Return {page_number: {font_names}} for any font PyMuPDF reports as
    having no embedded font program (ext == 'n/a')."""
    doc = fitz.open(pdf_path)
    found = {}
    for page in doc:
        bad = {basefont for xref, ext, ftype, basefont, name, enc, emb
               in page.get_fonts(full=True) if ext == "n/a"}
        if bad:
            found[page.number] = bad
    doc.close()
    return found


def embed_missing_fonts(pdf_path, replacement_font):
    """Redact and redraw, using an embedded substitute font, any text
    that uses a font with no embedded font program. Returns (fixed_bytes,
    total_glyphs_fixed). Background color for each redaction patch is
    sampled from nearby pixels so the patch blends in."""
    doc = fitz.open(pdf_path)
    total_fixed = 0

    for page in doc:
        bad_fonts = {basefont for xref, ext, ftype, basefont, name, enc, emb
                     in page.get_fonts(full=True) if ext == "n/a"}
        if not bad_fonts:
            continue

        d = page.get_text("dict")
        zoom = 4
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = np.array(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))

        targets = []
        for block in d["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["font"] in bad_fonts:
                        targets.append(span)

        for span in targets:
            x0, y0, x1, y1 = span["bbox"]
            sample_x = min(int((x1 + 8) * zoom), img.shape[1] - 4)
            sample_y = min(max(int((y0 + (y1 - y0) / 2) * zoom), 0), img.shape[0] - 4)
            patch = img[max(0, sample_y - 4):sample_y + 4, max(0, sample_x - 4):sample_x + 4].reshape(-1, 3)
            bg = tuple(float(c) / 255 for c in np.median(patch, axis=0))
            pad = 0.5
            rect = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            page.add_redact_annot(rect, fill=bg)

        page.apply_redactions()

        for span in targets:
            x0, y0, x1, y1 = span["bbox"]
            color_int = span["color"]
            color = ((color_int >> 16 & 255) / 255, (color_int >> 8 & 255) / 255, (color_int & 255) / 255)
            origin = fitz.Point(x0, y1 - span["size"] * 0.12)
            page.insert_text(origin, span["text"], fontsize=span["size"], fontfile=replacement_font,
                              fontname="EmbedFix", color=color, render_mode=0)

        total_fixed += len(targets)

    fixed_bytes = doc.write(garbage=4, deflate=True)
    doc.close()
    return fixed_bytes, total_fixed


def normalize_page(page):
    """Some print-ready exports (press proofs with crop marks / slug area,
    often named with a '-web' suffix) have a MediaBox larger than the
    actual intended page: the real boundary is recorded separately as
    the page's TrimBox. If this page has a TrimBox that's meaningfully
    smaller than its MediaBox, crop to it (re-based to origin) so the
    crop marks and surrounding slug area don't end up baked into the
    printed page. Pages without a distinct TrimBox are returned as-is."""
    try:
        trimbox = page.trimbox
    except Exception:
        return page, False

    mb = page.mediabox
    same = (
        abs(float(trimbox.left) - float(mb.left)) < 0.01
        and abs(float(trimbox.bottom) - float(mb.bottom)) < 0.01
        and abs(float(trimbox.width) - float(mb.width)) < 0.01
        and abs(float(trimbox.height) - float(mb.height)) < 0.01
    )
    if same:
        return page, False

    w = float(trimbox.width)
    h = float(trimbox.height)
    writer = PdfWriter()
    new_page = writer.add_blank_page(width=w, height=h)
    transform = Transformation().translate(-float(trimbox.left), -float(trimbox.bottom))
    new_page.merge_transformed_page(page, transform)
    return new_page, True


def find_ordered_files(directory, pattern):
    directory = Path(directory)
    if not directory.is_dir():
        sys.exit(f"Not a directory: {directory}")

    candidates = sorted(directory.glob(pattern))
    numbered = []
    unmatched = []
    for path in candidates:
        m = PREFIX_RE.match(path.name)
        if m:
            numbered.append((int(m.group(1)), path))
        else:
            unmatched.append(path)

    if unmatched:
        names = ", ".join(p.name for p in unmatched)
        print(f"Note: skipping {len(unmatched)} file(s) with no two-digit "
              f"release-order prefix (expected e.g. '01-...'): {names}")

    if not numbered:
        sys.exit(f"No files matching '{pattern}' with a two-digit prefix "
                  f"found in {directory}.")

    seen = {}
    dupes = []
    for num, path in numbered:
        if num in seen:
            dupes.append((num, seen[num].name, path.name))
        else:
            seen[num] = path
    if dupes:
        lines = "\n".join(f"  {num:02d}: {a}  vs  {b}" for num, a, b in dupes)
        sys.exit(
            "Error: duplicate release-order prefixes found -- refusing to "
            f"guess an order:\n{lines}\n"
            "Rename one of each pair so every prefix is unique, then re-run."
        )

    numbered.sort(key=lambda t: t[0])
    return numbered


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("directory", help="Folder to scan for rules-insert PDFs")
    parser.add_argument("--pattern", default="*.pdf",
                         help="Glob pattern for matching files within the directory (default: *.pdf)")
    parser.add_argument("--output", default="combined_investigator_rules.pdf",
                         help="Output PDF path (default: combined_investigator_rules.pdf)")
    parser.add_argument("--trim", default="small_square",
                         help="Expected Lulu trim size name, used only to validate page sizes "
                              f"(default: small_square). Choices: {', '.join(sorted(LULU_TRIM_SIZES_IN))}")
    parser.add_argument("--width", type=float, default=None,
                         help="Custom expected trim width in inches (overrides --trim)")
    parser.add_argument("--height", type=float, default=None,
                         help="Custom expected trim height in inches (overrides --trim)")
    parser.add_argument("--allow-size-mismatch", action="store_true",
                         help="If a file's pages don't match the expected trim size, scale-to-fit "
                              "and center them (same approach as split_and_resize.py) instead of "
                              "erroring out. Off by default -- a size mismatch usually means the "
                              "wrong file snuck in, and silently rescaling it can hide that.")
    parser.add_argument("--no-embed-fix", action="store_true",
                         help="Don't automatically fix non-embedded fonts (Lulu rejects any PDF "
                              "containing one). Off by default -- the fix only touches the "
                              "specific glyphs using a non-embedded font, redrawing them with an "
                              "embedded substitute.")
    parser.add_argument("--replacement-font", default=None,
                         help="Path to a .ttf/.otf font file to use when re-embedding glyphs that "
                              "used a non-embedded font. Auto-detected from common system font "
                              "paths (DejaVu Serif, Liberation Serif) if not given.")
    args = parser.parse_args()

    try:
        expected_w_in, expected_h_in = resolve_trim_size(args.trim, args.width, args.height)
    except ValueError as e:
        sys.exit(str(e))
    expected_w_pt = expected_w_in * POINTS_PER_INCH
    expected_h_pt = expected_h_in * POINTS_PER_INCH

    ordered_files = find_ordered_files(args.directory, args.pattern)

    if args.allow_size_mismatch and resize_pages is None:
        sys.exit("--allow-size-mismatch needs split_and_resize.py in the same folder as this script.")

    do_embed_fix = not args.no_embed_fix
    replacement_font = None
    if do_embed_fix:
        if fitz is None:
            print("Warning: pymupdf is not installed, so non-embedded fonts can't be auto-fixed "
                  "(pip install pymupdf). Files with this issue will be left as-is and may be "
                  "rejected by Lulu.")
            do_embed_fix = False
        else:
            replacement_font = find_replacement_font(args.replacement_font)
            if replacement_font is None:
                print("Warning: no substitute font found for the non-embedded-font fix (looked for "
                      "DejaVu Serif / Liberation Serif in common system paths). Pass "
                      "--replacement-font /path/to/font.ttf to enable it. Files with this issue "
                      "will be left as-is and may be rejected by Lulu.")
                do_embed_fix = False

    writer = PdfWriter()
    summary_rows = []
    page_cursor = 1

    for num, path in ordered_files:
        if do_embed_fix and scan_nonembedded_fonts(str(path)):
            fixed_bytes, n_glyphs_fixed = embed_missing_fonts(str(path), replacement_font)
            print(f"Note: {path.name} had {n_glyphs_fixed} character(s) using a non-embedded font "
                  f"(Lulu rejects these); re-embedded automatically using a substitute font.")
            reader = PdfReader(io.BytesIO(fixed_bytes))
        else:
            reader = PdfReader(str(path))
        n_pages = len(reader.pages)

        pages = []
        n_cropped = 0
        for page in reader.pages:
            norm_page, was_cropped = normalize_page(page)
            pages.append(norm_page)
            n_cropped += was_cropped

        if n_cropped:
            print(f"Note: {path.name} has {n_cropped} page(s) with crop marks/slug area "
                  f"outside an embedded TrimBox (likely a press-proof export); "
                  f"cropped to the TrimBox automatically.")

        mismatched = []
        for i, page in enumerate(pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            if abs(w - expected_w_pt) > SIZE_EPS_PT or abs(h - expected_h_pt) > SIZE_EPS_PT:
                mismatched.append((i, w / POINTS_PER_INCH, h / POINTS_PER_INCH))

        if mismatched:
            details = "; ".join(f"page {i+1}: {w:.3f}in x {h:.3f}in" for i, w, h in mismatched)
            if not args.allow_size_mismatch:
                sys.exit(
                    f"Error: {path.name} has page(s) that don't match the expected "
                    f"{expected_w_in}in x {expected_h_in}in trim size ({details}).\n"
                    "Re-run with --allow-size-mismatch to scale-to-fit these pages instead, "
                    "or confirm this is the right file."
                )
            print(f"Warning: {path.name} has mismatched page size(s) ({details}); scaling to fit.")
            fixed_writer = resize_pages(
                pages, expected_w_pt, expected_h_pt,
                fitz_doc=None, fill_source=None, fill_blur=False,
            )
            pages_to_add = fixed_writer.pages
        else:
            pages_to_add = pages

        for page in pages_to_add:
            writer.add_page(page)

        summary_rows.append((num, path.name, n_pages, page_cursor, page_cursor + n_pages - 1))
        page_cursor += n_pages

    with open(args.output, "wb") as f:
        writer.write(f)

    print(f"\nTrim size: {expected_w_in}in x {expected_h_in}in")
    print(f"Wrote {args.output}  ({page_cursor - 1} pages total)\n")
    print(f"{'#':>3}  {'file':<55}  {'pages':>5}  {'final pages':>12}")
    for num, name, n_pages, start, end in summary_rows:
        page_range = f"{start}" if start == end else f"{start}-{end}"
        print(f"{num:>3}  {name:<55}  {n_pages:>5}  {page_range:>12}")


if __name__ == "__main__":
    main()
