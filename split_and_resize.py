#!/usr/bin/env python3
"""
split_and_resize.py

Split an input PDF into:
  - a 1-page "cover" PDF (the first page), and
  - an "interior" PDF (every remaining page),
resizing both to a target Lulu.com trim size (Executive 7x10in by default).

Each page's content is scaled to fit (preserving aspect ratio, no cropping
or distortion) and centered on the new page size, so no content is lost.

Requires: pypdf  (pip install pypdf)

Examples:
    # Default: Lulu Executive size (7x10in)
    python split_and_resize.py my_guide.pdf \\
        --cover-out cover.pdf --interior-out interior.pdf

    # A different named Lulu trim size
    python split_and_resize.py my_guide.pdf --trim us_letter \\
        --cover-out cover.pdf --interior-out interior.pdf

    # A custom size in inches
    python split_and_resize.py my_guide.pdf --width 6 --height 9 \\
        --cover-out cover.pdf --interior-out interior.pdf
"""
import argparse
import sys

from pypdf import PdfReader, PdfWriter, Transformation

from lulu_sizes import LULU_TRIM_SIZES_IN, POINTS_PER_INCH, resolve_trim_size


def resize_pages(pages, target_w_pt, target_h_pt):
    """Return a PdfWriter with each input page scaled to fit and centered
    on a new target_w_pt x target_h_pt page."""
    writer = PdfWriter()
    for page in pages:
        src_w = float(page.mediabox.width)
        src_h = float(page.mediabox.height)
        scale = min(target_w_pt / src_w, target_h_pt / src_h)
        tx = (target_w_pt - src_w * scale) / 2
        ty = (target_h_pt - src_h * scale) / 2

        new_page = writer.add_blank_page(width=target_w_pt, height=target_h_pt)
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

    cover_writer = resize_pages([reader.pages[0]], target_w_pt, target_h_pt)
    with open(args.cover_out, "wb") as f:
        cover_writer.write(f)

    interior_writer = resize_pages(reader.pages[1:], target_w_pt, target_h_pt)
    with open(args.interior_out, "wb") as f:
        interior_writer.write(f)

    print(f"Trim size: {trim_w_in}in x {trim_h_in}in")
    print(f"Wrote {args.cover_out}  (1 page)")
    print(f"Wrote {args.interior_out}  ({len(reader.pages) - 1} pages)")


if __name__ == "__main__":
    main()
