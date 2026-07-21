#!/usr/bin/env python3
"""
make_wraparound_cover.py

Build a print-ready wraparound (back + front) cover PDF for Lulu.com from:
  - an input PDF whose first page is your front-cover art, and
  - back-cover copy, either scraped from a product page URL or supplied
    directly as a text file.

The back cover is auto-stylized to match the front: it reuses a mirrored,
blurred, darkened crop of the same front-cover art as its background and
samples the front cover's dominant color for its accent/border color, so
the two panels feel like one design without needing second piece of art.

Output is sized to the target Lulu trim size x2 width (no spine, correct
for Coil Bound / Saddle Stitch, which need no spine-width calculation),
plus the required 0.125in bleed on every outer edge.

Requires: pymupdf, Pillow, requests, beautifulsoup4, numpy
    pip install pymupdf pillow requests beautifulsoup4 numpy

Examples:
    # Scrape description text live from a product page
    python make_wraparound_cover.py front_cover.pdf \\
        --url "https://www.fantasyflightgames.com/en/products/.../" \\
        --campaign-name "The Dunwich Legacy" \\
        --logo ah_tcg_logo.png \\
        --output wraparound_cover.pdf

    # Use your own back-cover text instead of scraping (recommended --
    # web scraping is a best-effort heuristic and can break if a site's
    # layout changes)
    python make_wraparound_cover.py front_cover.pdf \\
        --description-file dunwich_legacy_description.txt \\
        --campaign-name "The Dunwich Legacy" \\
        --logo ah_tcg_logo.png \\
        --output wraparound_cover.pdf
"""
import argparse
import sys
import textwrap

import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from lulu_sizes import LULU_TRIM_SIZES_IN, DEFAULT_BLEED_IN, resolve_trim_size

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("This script needs PyMuPDF. Install it with: pip install pymupdf")


DISCLAIMER_TEXT = ("This is a fan-made document for personal use only and is not "
                    "an official Fantasy Flight Games product.")

STOP_HEADING_MARKERS = (
    "recent news", "related news", "news", "you may also like",
    "related products", "reviews", "designers", "customers who bought",
)

FONT_CANDIDATES = {
    "regular": ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "FreeSerif.ttf", "Georgia.ttf"],
    "bold": ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "FreeSerifBold.ttf", "Georgia Bold.ttf"],
    "italic": ["DejaVuSerif-Italic.ttf", "LiberationSerif-Italic.ttf", "FreeSerifItalic.ttf", "Georgia Italic.ttf"],
}


# --------------------------------------------------------------------------
# Description text: scrape from a URL, or load from a file
# --------------------------------------------------------------------------

def scrape_description(url, timeout=15):
    """Best-effort extraction of the main product-description paragraphs
    from a product page: everything after the <h1> title and before a
    heading that looks like a news/related-products section.

    This is a heuristic over generic HTML structure, not a dedicated
    parser for any specific site, so a page redesign can break it.
    Prefer --description-file for reliable, repeatable output.
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Could not fetch {url} ({e}). Some sites block automated requests "
            "outright (this happens with fantasyflightgames.com, for example). "
            "Copy the product description text into a .txt file and use "
            "--description-file instead."
        ) from e
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    elements = (soup.body or soup).find_all(["h1", "h2", "h3", "p"])

    collecting = False
    paragraphs = []
    for el in elements:
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        low = text.lower()

        if el.name == "h1":
            collecting = True
            continue
        if not collecting:
            continue
        if el.name in ("h2", "h3"):
            if any(marker in low for marker in STOP_HEADING_MARKERS):
                break
            continue  # a sub-heading inside the description; keep going
        if el.name == "p":
            if any(marker in low for marker in STOP_HEADING_MARKERS):
                break
            if len(text) < 20:
                continue  # skip short breadcrumb / label lines
            paragraphs.append(text)

    if not paragraphs:
        raise RuntimeError(
            "Could not automatically find description text on that page. "
            "The site's layout may not match this script's heuristic -- "
            "use --description-file with your own text instead."
        )
    return "\n\n".join(paragraphs)


def load_description(args):
    if args.description_file:
        with open(args.description_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    if args.url:
        return scrape_description(args.url)
    sys.exit("Provide either --url or --description-file for the back-cover text.")


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------

def rasterize_first_page(pdf_path, target_w_px, target_h_px):
    """Render page 1 of a PDF to an RGB image at (at least) the requested
    pixel size, then scale-to-fit + center on a canvas of exactly that
    size (same "no cropping, no distortion" behavior as script 1)."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    rect = page.rect
    zoom = max(target_w_px / rect.width, target_h_px / rect.height) * 1.05
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()

    scale = min(target_w_px / img.width, target_h_px / img.height)
    new_size = (round(img.width * scale), round(img.height * scale))
    img = img.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (target_w_px, target_h_px), (255, 255, 255))
    x = (target_w_px - img.width) // 2
    y = (target_h_px - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def dominant_color(img, sample_size=64):
    small = img.resize((sample_size, sample_size))
    arr = np.array(small).reshape(-1, 3)
    return tuple(int(c) for c in arr.mean(axis=0))


def relative_luminance(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def build_back_background(front_img, target_w_px, target_h_px):
    """Mirror + blur + darken a copy of the front cover art to use as a
    stylistically-matched (but visually distinct) back-cover background."""
    mirrored = ImageOps.mirror(front_img)

    src_w, src_h = mirrored.size
    target_aspect = target_w_px / target_h_px
    src_aspect = src_w / src_h
    if src_aspect > target_aspect:
        new_w = int(src_h * target_aspect)
        x0 = (src_w - new_w) // 2
        mirrored = mirrored.crop((x0, 0, x0 + new_w, src_h))
    else:
        new_h = int(src_w / target_aspect)
        y0 = (src_h - new_h) // 2
        mirrored = mirrored.crop((0, y0, src_w, y0 + new_h))

    mirrored = mirrored.resize((target_w_px, target_h_px), Image.LANCZOS)
    blurred = mirrored.filter(ImageFilter.GaussianBlur(radius=max(4, target_w_px * 0.012)))
    overlay = Image.new("RGB", blurred.size, (0, 0, 0))
    return Image.blend(blurred, overlay, alpha=0.55)


def load_font(style, size):
    for name in FONT_CANDIDATES[style]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_wrapped_text(draw, text, font, x, y, max_chars, fill, line_spacing=10,
                       align="left", center_x=None):
    wrapper = textwrap.TextWrapper(width=max_chars)
    lines = []
    for para in text.split("\n"):
        lines.extend(wrapper.wrap(para) if para.strip() else [""])
        lines.append("")  # blank line between paragraphs
    if lines and lines[-1] == "":
        lines.pop()

    for line in lines:
        if not line:
            bbox = draw.textbbox((0, 0), "Ag", font=font)
            y += (bbox[3] - bbox[1]) // 2
            continue
        bbox = draw.textbbox((0, 0), line, font=font)
        lh = bbox[3] - bbox[1]
        if align == "center" and center_x is not None:
            lw = bbox[2] - bbox[0]
            draw.text((center_x - lw / 2, y), line, font=font, fill=fill)
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += lh + line_spacing
    return y


# --------------------------------------------------------------------------
# Main build
# --------------------------------------------------------------------------

def build_cover(args):
    trim_w_in, trim_h_in = resolve_trim_size(args.trim, args.width, args.height)
    dpi = args.dpi
    panel_w_px = round(trim_w_in * dpi)
    panel_h_px = round(trim_h_in * dpi)

    description = load_description(args)

    print("Rendering front cover...")
    front_img = rasterize_first_page(args.front_cover_pdf, panel_w_px, panel_h_px)

    accent = dominant_color(front_img)
    # Push the accent toward a usable mid-tone so text/borders stay legible
    # regardless of how light or dark the source art is.
    luminance = relative_luminance(accent)
    if luminance < 90:
        accent = tuple(min(255, int(c * 1.8) + 40) for c in accent)
    text_color = (245, 243, 236)
    accent = tuple(max(60, min(220, c)) for c in accent)

    print("Building back cover background...")
    back_bg = build_back_background(front_img, panel_w_px, panel_h_px)
    canvas = back_bg.convert("RGBA")

    # Panel: semi-transparent dark card with an accent border
    pad = int(panel_w_px * 0.07)
    panel_box = (pad, int(panel_h_px * 0.10), panel_w_px - pad, int(panel_h_px * 0.94))
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rounded_rectangle(panel_box, radius=int(panel_w_px * 0.03),
                             fill=(15, 15, 18, 190),
                             outline=accent + (255,), width=max(2, int(panel_w_px * 0.006)))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    text_left = panel_box[0] + int(panel_w_px * 0.05)
    text_right = panel_box[2] - int(panel_w_px * 0.05)
    text_width = text_right - text_left
    center_x = (panel_box[0] + panel_box[2]) // 2
    cursor_y = panel_box[1] + int(panel_h_px * 0.04)

    # Logo (optional)
    if args.logo:
        logo = Image.open(args.logo).convert("RGBA")
        target_logo_w = int(text_width * 0.85)
        target_logo_h = int(logo.height * target_logo_w / logo.width)
        logo = logo.resize((target_logo_w, target_logo_h), Image.LANCZOS)
        canvas.paste(logo, (center_x - target_logo_w // 2, cursor_y), logo)
        draw = ImageDraw.Draw(canvas)
        cursor_y += target_logo_h + int(panel_h_px * 0.035)

    # Campaign name
    title_font = load_font("bold", int(panel_w_px * 0.075))
    cursor_y = draw_wrapped_text(
        draw, args.campaign_name.upper(), title_font, text_left, cursor_y,
        max_chars=18, fill=accent, align="center", center_x=center_x, line_spacing=6,
    )
    cursor_y += int(panel_h_px * 0.03)

    # Description body -- auto-shrink the font until it fits above the
    # disclaimer, rather than letting long product copy run off the panel.
    disc_font = load_font("italic", int(panel_w_px * 0.02))
    disc_max_chars = max(30, int(text_width / (disc_font.size * 0.52)))
    wrapped = textwrap.wrap(DISCLAIMER_TEXT, width=disc_max_chars)
    disc_h_total = 0
    line_heights = []
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=disc_font)
        lh = (bbox[3] - bbox[1]) + 6
        line_heights.append(lh)
        disc_h_total += lh
    disc_top = panel_box[3] - int(panel_h_px * 0.035) - disc_h_total

    # Auto-shrink the body font so the description fits between cursor_y
    # and the disclaimer, instead of overflowing the panel.
    available_h = disc_top - int(panel_h_px * 0.02) - cursor_y
    body_size = int(panel_w_px * 0.028)
    min_body_size = int(panel_w_px * 0.015)
    while body_size >= min_body_size:
        body_font = load_font("regular", body_size)
        max_chars = max(30, int(text_width / (body_size * 0.52)))
        wrapper = textwrap.TextWrapper(width=max_chars)
        measured_lines = []
        for para in description.split("\n"):
            measured_lines.extend(wrapper.wrap(para) if para.strip() else [""])
        line_h = draw.textbbox((0, 0), "Ag", font=body_font)[3] + 8
        total_h = sum(line_h if l else line_h // 2 for l in measured_lines)
        if total_h <= available_h or body_size == min_body_size:
            break
        body_size -= 2

    cursor_y = draw_wrapped_text(
        draw, description, body_font, text_left, cursor_y,
        max_chars=max_chars, fill=text_color, align="left", line_spacing=8,
    )
    if body_size == min_body_size and total_h > available_h:
        print("Warning: description text is still long at the minimum font size "
              "and may run close to the disclaimer; consider trimming the text.")

    disc_y = disc_top
    for line, lh in zip(wrapped, line_heights):
        bbox = draw.textbbox((0, 0), line, font=disc_font)
        lw = bbox[2] - bbox[0]
        draw.text((center_x - lw / 2, disc_y), line, font=disc_font, fill=(190, 188, 182))
        disc_y += lh

    back_img = canvas.convert("RGB")

    # Assemble spread: back (left) + front (right)
    print("Assembling wraparound spread...")
    spread = Image.new("RGB", (panel_w_px * 2, panel_h_px))
    spread.paste(back_img, (0, 0))
    spread.paste(front_img, (panel_w_px, 0))

    # Add bleed by extending edge pixels outward (no spine gap: correct
    # for Coil Bound / Saddle Stitch per Lulu's spec).
    bleed_px = round(args.bleed * dpi)
    arr = np.array(spread)
    padded = np.pad(arr, ((bleed_px, bleed_px), (bleed_px, bleed_px), (0, 0)), mode="edge")
    final_img = Image.fromarray(padded)

    final_w_in = trim_w_in * 2 + args.bleed * 2
    final_h_in = trim_h_in + args.bleed * 2
    exact_w_px = round(final_w_in * dpi)
    exact_h_px = round(final_h_in * dpi)
    if final_img.size != (exact_w_px, exact_h_px):
        final_img = final_img.resize((exact_w_px, exact_h_px), Image.LANCZOS)

    final_img.save(args.output, "PDF", resolution=float(dpi))
    print(f"Wrote {args.output}  ({final_w_in:.3f}in x {final_h_in:.3f}in, "
          f"trim {trim_w_in}x{trim_h_in}in x2 + {args.bleed}in bleed)")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("front_cover_pdf", help="PDF whose first page is your front-cover art")
    parser.add_argument("--url", default=None,
                         help="Product page URL to scrape back-cover description text from")
    parser.add_argument("--description-file", default=None,
                         help="Path to a text file with the back-cover description "
                              "(overrides --url; recommended for reliability)")
    parser.add_argument("--campaign-name", required=True, help="Campaign/expansion name for the back cover title")
    parser.add_argument("--logo", default=None, help="Path to a logo image (PNG with transparency) for the top of the back cover")
    parser.add_argument("--output", default="wraparound_cover.pdf", help="Output PDF path")
    parser.add_argument("--trim", default="executive",
                         help=f"Lulu trim size name (default: executive). Choices: {', '.join(sorted(LULU_TRIM_SIZES_IN))}")
    parser.add_argument("--width", type=float, default=None, help="Custom trim width in inches (overrides --trim)")
    parser.add_argument("--height", type=float, default=None, help="Custom trim height in inches (overrides --trim)")
    parser.add_argument("--bleed", type=float, default=DEFAULT_BLEED_IN, help=f"Bleed in inches per edge (default: {DEFAULT_BLEED_IN})")
    parser.add_argument("--dpi", type=int, default=300, help="Render resolution (default: 300)")
    args = parser.parse_args()

    try:
        build_cover(args)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
