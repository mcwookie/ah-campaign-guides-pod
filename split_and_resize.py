#!/usr/bin/env python3
"""
split_and_resize.py

Split an input PDF into:
  - a 1-page "cover" PDF (the first page), and
  - an "interior" PDF (every remaining page),
resizing both to a target Lulu.com trim size (Executive 7x10in by default).

Each page's content is scaled to fit (preserving aspect ratio, no cropping
or distortion) and centered on the new page size -- so no content is lost --
and stays fully vector (crisp text, small file size).

When the source page's aspect ratio doesn't match the target trim size,
scale-to-fit leaves blank margins on two opposite edges (e.g. white bars
above and below every page when fitting an 8.5x11 letter page into a
7x10 Executive trim). By default this script fills those margins with a
mirrored reflection of the page's own edge content, blurred into a soft
ambient color bleed, rasterized only in that thin margin strip, so the
page reads as a natural full-bleed design instead of floating on white.
Use --margin-fill mirror for a crisper (unblurred) reflection,
--margin-fill edge to flat-extend the edge pixel instead, or
--margin-fill white for the old blank-margin behavior.

Requires: pypdf, pymupdf, pillow, numpy
    pip install pypdf pymupdf pillow numpy

Examples:
    # Default: Lulu Executive size (7x10in), blurred margin fill
    python split_and_resize.py my_guide.pdf \\
        --cover-out cover.pdf --interior-out interior.pdf

    # A different named Lulu trim size
    python split_and_resize.py my_guide.pdf --trim us_letter \\
        --cover-out cover.pdf --interior-out interior.pdf

    # A custom size in inches
    python split_and_resize.py my_guide.pdf --width 6 --height 9 \\
        --cover-out cover.pdf --interior-out interior.pdf

    # Keep the old plain-white-margin behavior
    python split_and_resize.py my_guide.pdf --margin-fill white \\
        --cover-out cover.pdf --interior-out interior.pdf
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter
from pypdf import PdfReader, PdfWriter, Transformation

from lulu_sizes import LULU_TRIM_SIZES_IN, POINTS_PER_INCH, resolve_trim_size

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


MARGIN_EPS_PT = 0.5  # ignore sub-pixel gaps; not worth filling

# CLI --margin-fill choice -> (source, blur). source is None for 'white'
# (no fill at all), otherwise 'mirror' or 'edge'; blur is a bool.
MARGIN_FILL_MODES = {
    "blur": ("mirror", True),
    "mirror": ("mirror", False),
    "edge-blur": ("edge", True),
    "edge": ("edge", False),
    "white": (None, False),
}


def embed_all_fonts(pdf_path):
    """Force-embed every font in pdf_path via Ghostscript, in place.

    This script copies page content streams straight from the source PDF
    (merge_transformed_page), so any non-embedded standard font the source
    uses (FFG's web PDFs have shown Times-Roman/Times-Bold left unembedded
    on a handful of pages -- credits, disclaimers) carries straight through
    and gets rejected by Lulu's "unable to embed fonts" check. Re-distilling
    with Ghostscript's -dEmbedAllFonts substitutes and embeds those fonts;
    image downsampling is disabled so page raster content isn't degraded.
    """
    gs = shutil.which("gs")
    if gs is None:
        print(f"Warning: ghostscript ('gs') not found on PATH -- skipping font-embed "
              f"check on {pdf_path}. Verify with 'pdffonts {pdf_path}' before uploading "
              f"to Lulu; install ghostscript to enable this automatically.")
        return

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [gs, "-o", tmp_path, "-sDEVICE=pdfwrite",
             "-dCompatibilityLevel=1.6", "-dPDFSETTINGS=/prepress",
             "-dEmbedAllFonts=true", "-dSubsetFonts=true",
             "-dDownsampleColorImages=false", "-dDownsampleGrayImages=false",
             "-dDownsampleMonoImages=false", "-dAutoRotatePages=/None",
             pdf_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Warning: ghostscript font-embed pass failed for {pdf_path}, "
                  f"leaving it unmodified:\n{result.stderr}")
            return
        shutil.copyfile(tmp_path, pdf_path)
    finally:
        os.unlink(tmp_path)


def image_page(img, w_pt, h_pt, jpeg_quality=88):
    """Wrap a PIL image as a 1-page PDF (via PyMuPDF) sized exactly
    w_pt x h_pt, returned as a pypdf Page ready to merge. Saved as JPEG
    (these are decorative fill strips, not text) so file size stays sane --
    the naive PNG path here otherwise embeds each band essentially
    uncompressed and can bloat a 25-page interior PDF by 40+ MB."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality)
    buf.seek(0)
    doc = fitz.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(fitz.Rect(0, 0, w_pt, h_pt), stream=buf.read())
    pdf_bytes = doc.tobytes()
    doc.close()
    return PdfReader(io.BytesIO(pdf_bytes)).pages[0]


def rasterize_page(fitz_page, zoom):
    mat = fitz.Matrix(zoom, zoom)
    pix = fitz_page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def make_fill_strip(full_img, edge, band_px, source, blur, blur_frac=0.45, blur_source_mult=4):
    """Build one fill strip (a PIL image) for one edge of the page raster.

    edge is one of 'top', 'bottom', 'left', 'right' -- which edge of
    full_img this strip extends beyond. band_px is how many pixels deep
    the strip needs to be. source is 'mirror' (reflect the edge content)
    or 'edge' (flat-extend an averaged sliver of the edge). blur softens
    either source into a smoother color bleed instead of a crisp,
    recognizable copy of the edge. Returns an image whose row/column
    nearest the true page edge sits at the seam-adjacent side of the
    returned strip, ready to butt directly against the vector content.
    """
    axis = "v" if edge in ("top", "bottom") else "h"

    if source == "edge":
        # Average a thin sliver near the true edge (rather than stretching
        # a single raw pixel row/column) so stray detail right at the edge
        # -- a line of small text, a hard rule -- doesn't get smeared into
        # a streaky stripe when stretched.
        sliver_px = min(12, full_img.height if axis == "v" else full_img.width)
        if edge == "top":
            region = full_img.crop((0, 0, full_img.width, sliver_px))
        elif edge == "bottom":
            region = full_img.crop((0, full_img.height - sliver_px, full_img.width, full_img.height))
        elif edge == "left":
            region = full_img.crop((0, 0, sliver_px, full_img.height))
        else:
            region = full_img.crop((full_img.width - sliver_px, 0, full_img.width, full_img.height))

        arr = np.array(region).astype(np.float32)
        if axis == "v":
            base = Image.fromarray(arr.mean(axis=0, keepdims=True).astype(np.uint8))  # 1 x w
        else:
            base = Image.fromarray(arr.mean(axis=1, keepdims=True).astype(np.uint8))  # h x 1

        if blur:
            # Smooth transitions along the strip's long axis (e.g. left-to-
            # right color shifts), not just the averaging above.
            radius = max(4, band_px * 0.2)
            pad = int(radius * 2) + 1
            if axis == "v":
                padded = Image.fromarray(np.pad(np.array(base), ((0, 0), (pad, pad), (0, 0)), mode="edge"))
                padded = padded.filter(ImageFilter.GaussianBlur(radius))
                base = padded.crop((pad, 0, pad + base.width, base.height))
            else:
                padded = Image.fromarray(np.pad(np.array(base), ((pad, pad), (0, 0), (0, 0)), mode="edge"))
                padded = padded.filter(ImageFilter.GaussianBlur(radius))
                base = padded.crop((0, pad, base.width, pad + base.height))

        if axis == "v":
            return base.resize((full_img.width, band_px))
        else:
            return base.resize((band_px, full_img.height))

    # source == "mirror": reflect the edge content; blur softens it from a
    # crisp, recognizably-flipped duplicate into an ambient color bleed.
    sample_px = band_px * blur_source_mult if blur else band_px
    if edge == "top":
        sample_px = min(sample_px, full_img.height)
        src = full_img.crop((0, 0, full_img.width, sample_px))
        mirrored = src.transpose(Image.FLIP_TOP_BOTTOM)  # true edge row -> last row
    elif edge == "bottom":
        sample_px = min(sample_px, full_img.height)
        src = full_img.crop((0, full_img.height - sample_px, full_img.width, full_img.height))
        mirrored = src.transpose(Image.FLIP_TOP_BOTTOM)  # true edge row -> first row
    elif edge == "left":
        sample_px = min(sample_px, full_img.width)
        src = full_img.crop((0, 0, sample_px, full_img.height))
        mirrored = src.transpose(Image.FLIP_LEFT_RIGHT)  # true edge col -> last col
    else:
        sample_px = min(sample_px, full_img.width)
        src = full_img.crop((full_img.width - sample_px, 0, full_img.width, full_img.height))
        mirrored = src.transpose(Image.FLIP_LEFT_RIGHT)  # true edge col -> first col

    if blur:
        radius = max(10, band_px * blur_frac)
        mirrored = mirrored.filter(ImageFilter.GaussianBlur(radius))

    # Take the band_px slice nearest the true edge (which sits at the
    # seam-adjacent side after the flip above).
    if edge == "top":
        strip = mirrored.crop((0, max(0, mirrored.height - band_px), mirrored.width, mirrored.height))
    elif edge == "bottom":
        strip = mirrored.crop((0, 0, mirrored.width, min(band_px, mirrored.height)))
    elif edge == "left":
        strip = mirrored.crop((max(0, mirrored.width - band_px), 0, mirrored.width, mirrored.height))
    else:
        strip = mirrored.crop((0, 0, min(band_px, mirrored.width), mirrored.height))

    return strip


def fit_size(img, w, h):
    """Pad (edge-replicate) or crop img to exactly w x h."""
    if img.size == (w, h):
        return img
    arr = np.array(img)
    ch, cw = arr.shape[0], arr.shape[1]
    if ch < h:
        arr = np.pad(arr, ((h - ch, 0), (0, 0), (0, 0)), mode="edge")
    elif ch > h:
        arr = arr[:h]
    if cw < w:
        arr = np.pad(arr, ((0, 0), (w - cw, 0), (0, 0)), mode="edge")
    elif cw > w:
        arr = arr[:, :w]
    return Image.fromarray(arr)


def build_margin_bands(fitz_page, src_w_pt, src_h_pt, scale, target_w_pt, target_h_pt,
                        gap_w_pt, gap_h_pt, dpi, source, blur):
    """Return a list of (pypdf_page, translate_x_pt, translate_y_pt) for
    the fill bands needed on whichever axis has a gap. Only ever one axis
    has a meaningful gap for a given page (the other is the width- or
    height-binding axis with ~0 gap)."""
    bands = []
    zoom = scale * dpi / 72.0  # matches the final on-page pixel density

    if gap_h_pt > MARGIN_EPS_PT:
        full_img = rasterize_page(fitz_page, zoom)
        margin_pt = gap_h_pt / 2
        band_h_px = max(1, round(margin_pt / 72.0 * dpi))
        band_w_px = full_img.width

        top_band = fit_size(make_fill_strip(full_img, "top", band_h_px, source, blur), band_w_px, band_h_px)
        bottom_band = fit_size(make_fill_strip(full_img, "bottom", band_h_px, source, blur), band_w_px, band_h_px)

        top_page = image_page(top_band, target_w_pt, margin_pt)
        bottom_page = image_page(bottom_band, target_w_pt, margin_pt)
        bands.append((bottom_page, 0, 0))
        bands.append((top_page, 0, target_h_pt - margin_pt))

    elif gap_w_pt > MARGIN_EPS_PT:
        full_img = rasterize_page(fitz_page, zoom)
        margin_pt = gap_w_pt / 2
        band_w_px = max(1, round(margin_pt / 72.0 * dpi))
        band_h_px = full_img.height

        left_band = fit_size(make_fill_strip(full_img, "left", band_w_px, source, blur), band_w_px, band_h_px)
        right_band = fit_size(make_fill_strip(full_img, "right", band_w_px, source, blur), band_w_px, band_h_px)

        left_page = image_page(left_band, margin_pt, target_h_pt)
        right_page = image_page(right_band, margin_pt, target_h_pt)
        bands.append((left_page, 0, 0))
        bands.append((right_page, target_w_pt - margin_pt, 0))

    return bands


def resize_pages(pages, target_w_pt, target_h_pt, fitz_doc=None, page_offset=0,
                  fill_source="mirror", fill_blur=True, dpi=300):
    """Return a PdfWriter with each input page scaled to fit and centered
    on a new target_w_pt x target_h_pt page. If fill_source is 'mirror' or
    'edge' and fitz_doc is provided, blank scale-to-fit margins are filled
    with mirrored/extended edge content (optionally blurred) instead of
    being left blank. Pass fill_source=None to leave margins white."""
    writer = PdfWriter()
    for i, page in enumerate(pages):
        src_w = float(page.mediabox.width)
        src_h = float(page.mediabox.height)
        scale = min(target_w_pt / src_w, target_h_pt / src_h)
        scaled_w = src_w * scale
        scaled_h = src_h * scale
        gap_w_pt = target_w_pt - scaled_w
        gap_h_pt = target_h_pt - scaled_h
        tx = gap_w_pt / 2
        ty = gap_h_pt / 2

        new_page = writer.add_blank_page(width=target_w_pt, height=target_h_pt)

        if fill_source is not None and fitz_doc is not None and (gap_w_pt > MARGIN_EPS_PT or gap_h_pt > MARGIN_EPS_PT):
            fitz_page = fitz_doc[page_offset + i]
            bands = build_margin_bands(
                fitz_page, src_w, src_h, scale, target_w_pt, target_h_pt,
                gap_w_pt, gap_h_pt, dpi, fill_source, fill_blur,
            )
            for band_page, band_tx, band_ty in bands:
                band_transform = Transformation().translate(band_tx, band_ty)
                new_page.merge_transformed_page(band_page, band_transform)

        transform = Transformation().scale(scale).translate(tx, ty)
        new_page.merge_transformed_page(page, transform)
    return writer


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input_pdf", help="Path to the source PDF")
    parser.add_argument("--cover-out", default="cover.pdf",
                         help="Output path for the 1-page front-cover PDF (default: cover.pdf)")
    parser.add_argument("--interior-out", default="interior.pdf",
                         help="Output path for the interior PDF (default: interior.pdf)")
    parser.add_argument("--trim", default="executive",
                         help="Lulu trim size name (default: executive). "
                              f"Choices: {', '.join(sorted(LULU_TRIM_SIZES_IN))}")
    parser.add_argument("--width", type=float, default=None,
                         help="Custom trim width in inches (overrides --trim)")
    parser.add_argument("--height", type=float, default=None,
                         help="Custom trim height in inches (overrides --trim)")
    parser.add_argument("--margin-fill", choices=list(MARGIN_FILL_MODES), default="blur",
                         help="How to fill the scale-to-fit margins when the source page's "
                              "aspect ratio doesn't match the target trim: 'blur' mirrors the "
                              "page's own edge content and softens it into an ambient color "
                              "bleed (default); 'mirror' does the same without blurring "
                              "(crisper, but can look like an obvious flipped duplicate); "
                              "'edge' flat-extends an averaged sliver of the edge (no blur); "
                              "'edge-blur' does the same as 'edge' but softened; 'white' "
                              "leaves the margins blank (old behavior).")
    parser.add_argument("--dpi", type=int, default=300,
                         help="Raster resolution for the mirrored/edge margin fill (default: 300). "
                              "Does not affect the vector page content, which stays full quality.")
    parser.add_argument("--no-font-embed-fix", action="store_true",
                         help="Skip the Ghostscript pass that force-embeds any non-embedded "
                              "fonts copied from the source PDF (e.g. FFG source PDFs have "
                              "shipped pages using un-embedded Times-Roman/Times-Bold, which "
                              "Lulu's printer rejects). On by default; requires ghostscript.")
    args = parser.parse_args()

    try:
        trim_w_in, trim_h_in = resolve_trim_size(args.trim, args.width, args.height)
    except ValueError as e:
        sys.exit(str(e))

    target_w_pt = trim_w_in * POINTS_PER_INCH
    target_h_pt = trim_h_in * POINTS_PER_INCH

    reader = PdfReader(args.input_pdf)
    if len(reader.pages) < 2:
        sys.exit("Input PDF needs at least 2 pages (1 cover page + 1+ interior pages).")

    fill_source, fill_blur = MARGIN_FILL_MODES[args.margin_fill]
    if fill_source is not None and fitz is None:
        print("Warning: pymupdf is not installed, so margins will be left white. "
              "Install it with 'pip install pymupdf' to enable margin fill.")
        fill_source = None

    fitz_doc = fitz.open(args.input_pdf) if fill_source is not None else None

    cover_writer = resize_pages([reader.pages[0]], target_w_pt, target_h_pt,
                                 fitz_doc=fitz_doc, page_offset=0,
                                 fill_source=fill_source, fill_blur=fill_blur, dpi=args.dpi)
    with open(args.cover_out, "wb") as f:
        cover_writer.write(f)

    interior_writer = resize_pages(reader.pages[1:], target_w_pt, target_h_pt,
                                    fitz_doc=fitz_doc, page_offset=1,
                                    fill_source=fill_source, fill_blur=fill_blur, dpi=args.dpi)
    with open(args.interior_out, "wb") as f:
        interior_writer.write(f)

    if fitz_doc is not None:
        fitz_doc.close()

    if not args.no_font_embed_fix:
        embed_all_fonts(args.cover_out)
        embed_all_fonts(args.interior_out)

    print(f"Trim size: {trim_w_in}in x {trim_h_in}in  (margin fill: {args.margin_fill})")
    print(f"Wrote {args.cover_out}  (1 page)")
    print(f"Wrote {args.interior_out}  ({len(reader.pages) - 1} pages)")


if __name__ == "__main__":
    main()
