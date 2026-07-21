"""
lulu_sizes.py

Shared trim-size table for Lulu.com print products, used by both
split_and_resize.py and make_wraparound_cover.py.

All sizes are (width_inches, height_inches) for a single page/panel in
portrait orientation.
"""

POINTS_PER_INCH = 72

# Lulu's published trim sizes (inches). Source: Lulu Book Creation Guide.
LULU_TRIM_SIZES_IN = {
    "pocketbook": (4.25, 6.875),
    "novella": (5.0, 8.0),
    "digest": (5.5, 8.5),
    "a5": (5.83, 8.27),
    "royal": (6.14, 9.21),
    "us_trade": (6.0, 9.0),
    "comic_book": (6.63, 10.25),
    "executive": (7.0, 10.0),
    "crown_quarto": (7.44, 9.68),
    "small_square": (7.5, 7.5),
    "square": (8.5, 8.5),
    "a4": (8.27, 11.69),
    "us_letter": (8.5, 11.0),
    "small_landscape": (9.0, 7.0),
}

# Lulu requires 0.125in of bleed on every outer edge of a full-bleed cover.
# Coil Bound and Saddle Stitch books need no spine-width calculation
# (only Paperback/Hardcover perfect-bound spines do), so a coil-bound
# wraparound cover is simply: back panel + front panel, no spine gap.
DEFAULT_BLEED_IN = 0.125


def resolve_trim_size(trim_name=None, width_in=None, height_in=None):
    """Return (width_in, height_in) for a trim name or explicit dimensions."""
    if width_in and height_in:
        return width_in, height_in
    if not trim_name:
        raise ValueError("Provide either a trim name or both width_in and height_in.")
    key = trim_name.lower().replace(" ", "_").replace("-", "_")
    if key not in LULU_TRIM_SIZES_IN:
        valid = ", ".join(sorted(LULU_TRIM_SIZES_IN))
        raise ValueError(f"Unknown trim size '{trim_name}'. Choose from: {valid}")
    return LULU_TRIM_SIZES_IN[key]
