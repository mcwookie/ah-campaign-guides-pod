#!/usr/bin/env python3
"""
make_investigator_rules_cover.py

One-time generator for the front/back wraparound cover of the combined
investigator-rules compilation book (Lulu Small Square, 7.5in x 7.5in,
Coil Bound). Unlike make_wraparound_cover.py, this doesn't take an
existing front-cover PDF -- there isn't one single "official" cover for
a book spanning multiple campaigns -- so it generates original Arkham-
esque background art (see arkham_art.py) instead, reuses the real
Arkham Horror: The Card Game logo lockup, and builds a matching back
cover in the same visual language as the campaign guide covers: mirror+
blur background, dark panel, title, an italicized Lovecraft quote with
attribution, description body text, and the fan-print disclaimer.

Requires: pypdf, pymupdf, pillow, numpy
    pip install pypdf pymupdf pillow numpy

Example:
    python make_investigator_rules_cover.py \\
        --logo ah_tcg_logo.png \\
        --output investigator_rules_cover.pdf
"""
import argparse
import sys
import textwrap

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from arkham_art import generate_arkham_background
from lulu_sizes import LULU_TRIM_SIZES_IN, DEFAULT_BLEED_IN, resolve_trim_size
from make_wraparound_cover import (
    DISCLAIMER_TEXT, FONT_CANDIDATES, build_back_background, dominant_color,
    draw_wrapped_text, load_font, relative_luminance, wrap_text_to_width,
)

DEFAULT_TITLE = "CHAPTER ONE"
DEFAULT_SUBTITLE = "INVESTIGATOR RULES"
DEFAULT_QUOTE = ("The most merciful thing in the world, I think, is the "
                  "inability of the human mind to correlate all its contents.")
DEFAULT_QUOTE_ATTRIBUTION = "\u2013 H. P. Lovecraft, \u201cThe Call of Cthulhu\u201d"
DEFAULT_DESCRIPTION = (
    "This volume collects the Investigator Expansion rules inserts for "
    "Arkham Horror: The Card Game's first chapter of campaigns, gathered "
    "together for quick reference at the table.\n\n"
    "Each entry reproduces its original rules clarifications, keyword "
    "reminders, and credits exactly as published, organized in release "
    "order for easy navigation."
)


def draw_title_band(canvas, title, subtitle, accent, panel_w_px, panel_h_px):
    draw = ImageDraw.Draw(canvas, "RGBA")
    center_x = panel_w_px // 2
    band_bottom = int(panel_h_px * 0.94)

    title_font = load_font("bold", int(panel_w_px * 0.11))
    subtitle_font = load_font("regular", int(panel_w_px * 0.042))

    subtitle_lines = wrap_text_to_width(draw, subtitle, subtitle_font, int(panel_w_px * 0.85))
    sub_h = sum(draw.textbbox((0, 0), l, font=subtitle_font)[3] + 6 for l in subtitle_lines)

    title_lines = wrap_text_to_width(draw, title, title_font, int(panel_w_px * 0.85))
    title_h = sum(draw.textbbox((0, 0), l, font=title_font)[3] + 4 for l in title_lines)

    rule_gap = int(panel_h_px * 0.018)
    y = band_bottom - sub_h - rule_gap - title_h

    def draw_centered_shadowed(lines, font, y, fill):
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            shadow_off = max(2, font.size // 22)
            draw.text((center_x - lw / 2 + shadow_off, y + shadow_off), line, font=font, fill=(0, 0, 0, 170))
            draw.text((center_x - lw / 2, y), line, font=font, fill=fill)
            y += lh + 4
        return y

    y = draw_centered_shadowed(title_lines, title_font, y, (245, 244, 238, 255))
    y += rule_gap
    rule_w = int(panel_w_px * 0.22)
    draw.line([(center_x - rule_w // 2, y), (center_x + rule_w // 2, y)], fill=accent + (230,), width=3)
    y += rule_gap
    draw_centered_shadowed(subtitle_lines, subtitle_font, y, tuple(accent) + (255,))


def build_front(panel_w_px, panel_h_px, title, subtitle, logo_path, seed):
    front = generate_arkham_background(panel_w_px, panel_h_px, seed=seed).convert("RGBA")

    accent = dominant_color(front.convert("RGB"))
    luminance = relative_luminance(accent)
    if luminance < 90:
        accent = tuple(min(255, int(c * 1.9) + 50) for c in accent)
    accent = tuple(max(70, min(225, c)) for c in accent)

    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        target_w = int(panel_w_px * 0.72)
        target_h = int(logo.height * target_w / logo.width)
        logo = logo.resize((target_w, target_h), Image.LANCZOS)
        front.paste(logo, ((panel_w_px - target_w) // 2, int(panel_h_px * 0.05)), logo)

    draw_title_band(front, title, subtitle, accent, panel_w_px, panel_h_px)
    return front.convert("RGB"), accent


def build_back(front_img, panel_w_px, panel_h_px, title, subtitle, quote, quote_attribution,
                description, logo_path, accent):
    back_bg = build_back_background(front_img, panel_w_px, panel_h_px)
    canvas = back_bg.convert("RGBA")

    pad = int(panel_w_px * 0.07)
    panel_box = (pad, int(panel_h_px * 0.08), panel_w_px - pad, int(panel_h_px * 0.94))
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
    cursor_y = panel_box[1] + int(panel_h_px * 0.035)

    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        target_logo_w = int(text_width * 0.8)
        target_logo_h = int(logo.height * target_logo_w / logo.width)
        logo = logo.resize((target_logo_w, target_logo_h), Image.LANCZOS)
        canvas.paste(logo, (center_x - target_logo_w // 2, cursor_y), logo)
        draw = ImageDraw.Draw(canvas)
        cursor_y += target_logo_h + int(panel_h_px * 0.03)

    title_text = f"{title} \u2014 {subtitle}" if subtitle else title
    title_size = int(panel_w_px * 0.052)
    min_title_size = int(panel_w_px * 0.03)
    while title_size >= min_title_size:
        title_font = load_font("bold", title_size)
        title_lines = wrap_text_to_width(draw, title_text.upper(), title_font, text_width)
        widest = max(draw.textlength(l, font=title_font) for l in title_lines)
        if widest <= text_width or title_size == min_title_size:
            break
        title_size -= 3
    cursor_y = draw_wrapped_text(draw, title_text.upper(), title_font, text_left, cursor_y,
                                  text_width, fill=accent, align="center", center_x=center_x, line_spacing=5)
    cursor_y += int(panel_h_px * 0.025)

    quote_font = load_font("italic", int(panel_w_px * 0.028))
    attrib_font = load_font("italic", int(panel_w_px * 0.023))
    cursor_y = draw_wrapped_text(draw, f'\u201c{quote}\u201d', quote_font, text_left, cursor_y,
                                  text_width, fill=(225, 222, 212), align="center",
                                  center_x=center_x, line_spacing=8)
    cursor_y += 6
    cursor_y = draw_wrapped_text(draw, quote_attribution, attrib_font, text_left, cursor_y,
                                  text_width, fill=(190, 188, 180), align="center",
                                  center_x=center_x, line_spacing=6)
    cursor_y += int(panel_h_px * 0.035)

    disc_font = load_font("italic", int(panel_w_px * 0.02))
    disc_lines = wrap_text_to_width(draw, DISCLAIMER_TEXT, disc_font, text_width)
    disc_h_total = sum(draw.textbbox((0, 0), l, font=disc_font)[3] + 6 for l in disc_lines)
    disc_top = panel_box[3] - int(panel_h_px * 0.035) - disc_h_total

    available_h = disc_top - int(panel_h_px * 0.02) - cursor_y
    body_size = int(panel_w_px * 0.026)
    min_body_size = int(panel_w_px * 0.014)
    while body_size >= min_body_size:
        body_font = load_font("regular", body_size)
        measured_lines = wrap_text_to_width(draw, description, body_font, text_width)
        line_h = draw.textbbox((0, 0), "Ag", font=body_font)[3] + 8
        total_h = sum(line_h if l else line_h // 2 for l in measured_lines)
        if total_h <= available_h or body_size == min_body_size:
            break
        body_size -= 2
    cursor_y = draw_wrapped_text(draw, description, body_font, text_left, cursor_y,
                                  text_width, fill=(230, 228, 222), align="left", line_spacing=8)
    if body_size == min_body_size and total_h > available_h:
        print("Warning: description text is long at the minimum font size and may run close to the disclaimer.")

    disc_y = disc_top
    for line in disc_lines:
        bbox = draw.textbbox((0, 0), line, font=disc_font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        draw.text((center_x - lw / 2, disc_y), line, font=disc_font, fill=(190, 188, 182))
        disc_y += lh + 6

    return canvas.convert("RGB")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--subtitle", default=DEFAULT_SUBTITLE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--quote-attribution", default=DEFAULT_QUOTE_ATTRIBUTION)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION,
                         help="Back-cover description text. Use \\n\\n between paragraphs.")
    parser.add_argument("--description-file", default=None,
                         help="Path to a text file with the back-cover description (overrides --description)")
    parser.add_argument("--logo", default=None, help="Path to the AH:TCG logo image (PNG with transparency)")
    parser.add_argument("--output", default="investigator_rules_cover.pdf")
    parser.add_argument("--trim", default="small_square",
                         help=f"Lulu trim size name (default: small_square). Choices: {', '.join(sorted(LULU_TRIM_SIZES_IN))}")
    parser.add_argument("--width", type=float, default=None)
    parser.add_argument("--height", type=float, default=None)
    parser.add_argument("--bleed", type=float, default=DEFAULT_BLEED_IN)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42, help="Random seed for the generated background art")
    args = parser.parse_args()

    try:
        trim_w_in, trim_h_in = resolve_trim_size(args.trim, args.width, args.height)
    except ValueError as e:
        sys.exit(str(e))

    description = args.description
    if args.description_file:
        with open(args.description_file, "r", encoding="utf-8") as f:
            description = f.read().strip()

    dpi = args.dpi
    panel_w_px = round(trim_w_in * dpi)
    panel_h_px = round(trim_h_in * dpi)

    print("Generating front cover art...")
    front_img, accent = build_front(panel_w_px, panel_h_px, args.title, args.subtitle, args.logo, args.seed)

    print("Building back cover...")
    back_img = build_back(front_img, panel_w_px, panel_h_px, args.title, args.subtitle,
                           args.quote, args.quote_attribution, description, args.logo, accent)

    print("Assembling wraparound spread...")
    spread = Image.new("RGB", (panel_w_px * 2, panel_h_px))
    spread.paste(back_img, (0, 0))
    spread.paste(front_img, (panel_w_px, 0))

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


if __name__ == "__main__":
    main()
