"""
arkham_art.py

Procedurally generates an original "Arkham-esque" cosmic-horror night-sky
illustration (gradient sky, starfield, pale glowing moon, gothic rooftop
silhouette, gnarled branch shapes, film-grain texture) for use as cover
art. This is original generated artwork, not a reproduction of any
official illustration -- built specifically so the multi-campaign
investigator-rules compilation cover doesn't have to borrow one specific
campaign's art for a book that isn't about any single campaign.
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _lerp(a, b, t):
    return a + (b - a) * t


def make_sky_gradient(w, h, top_color, bottom_color, seed):
    rng = np.random.default_rng(seed)
    yy = np.linspace(0, 1, h).reshape(h, 1)
    grad = np.zeros((h, w, 3), dtype=np.float32)
    for c in range(3):
        grad[:, :, c] = _lerp(top_color[c], bottom_color[c], yy[:, 0])[:, None]
    grad = np.repeat(grad, 1, axis=1)
    grad = np.broadcast_to(grad, (h, w, 3)).copy()

    # Subtle horizontal color drift so it doesn't read as a flat banded gradient.
    xx = np.linspace(-1, 1, w)
    drift = (0.03 * np.sin(xx * 2.3 + seed)).astype(np.float32)
    grad += drift[None, :, None] * 40

    return np.clip(grad, 0, 255).astype(np.uint8)


def add_vignette(arr, strength=0.55):
    h, w, _ = arr.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h / 2, w / 2
    dist = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    vignette = 1 - strength * np.clip(dist - 0.35, 0, None)
    vignette = np.clip(vignette, 0.25, 1.0)
    out = arr.astype(np.float32) * vignette[:, :, None]
    return np.clip(out, 0, 255).astype(np.uint8)


def add_stars(img, count, seed, region_top=0.0, region_bottom=0.62):
    rng = random.Random(seed)
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(count):
        x = rng.uniform(0, w)
        y = rng.uniform(h * region_top, h * region_bottom)
        r = rng.choice([0.6, 0.8, 1.0, 1.0, 1.3, 1.8])
        alpha = rng.randint(60, 230)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(235, 238, 245, alpha))
    return img


def add_moon(img, cx_frac, cy_frac, radius_frac, seed):
    w, h = img.size
    cx, cy = w * cx_frac, h * cy_frac
    r = w * radius_frac

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i, (rr, a) in enumerate([(r * 3.2, 18), (r * 2.2, 30), (r * 1.5, 55)]):
        gdraw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(210, 225, 235, a))
    glow = glow.filter(ImageFilter.GaussianBlur(r * 0.6))
    img.alpha_composite(glow) if img.mode == "RGBA" else img.paste(glow, (0, 0), glow)

    disc = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(disc)
    ddraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(232, 236, 232, 235))
    # a couple of soft craters for texture, not perfectly flat
    rng = random.Random(seed + 1)
    for _ in range(5):
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, r * 0.6)
        px, py = cx + math.cos(ang) * dist, cy + math.sin(ang) * dist
        pr = rng.uniform(r * 0.08, r * 0.2)
        ddraw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(210, 216, 214, 120))
    disc = disc.filter(ImageFilter.GaussianBlur(r * 0.03))
    img.paste(disc, (0, 0), disc)
    return img


def _jagged_skyline_points(w, h, base_y, seed, n_buildings=14):
    rng = random.Random(seed)
    pts = [(0, h)]
    x = 0
    while x < w:
        bw = rng.uniform(w * 0.03, w * 0.11)
        roof = rng.choice(["flat", "peak", "spire", "step"])
        top = base_y - rng.uniform(h * 0.01, h * 0.10)
        if roof == "spire":
            top -= rng.uniform(h * 0.08, h * 0.16)
        pts.append((x, base_y))
        if roof == "peak" or roof == "spire":
            pts.append((x + bw * 0.5, top))
            pts.append((x + bw, base_y))
        elif roof == "step":
            step_h = rng.uniform(h * 0.02, h * 0.05)
            pts.append((x, top + step_h))
            pts.append((x + bw * 0.4, top + step_h))
            pts.append((x + bw * 0.4, top))
            pts.append((x + bw * 0.7, top))
            pts.append((x + bw * 0.7, top + step_h))
            pts.append((x + bw, top + step_h))
        else:
            pts.append((x, top))
            pts.append((x + bw, top))
        x += bw
    pts.append((w, h))
    return pts


def add_skyline(img, base_y_frac, seed, color=(8, 10, 14, 255)):
    w, h = img.size
    base_y = h * base_y_frac
    pts = _jagged_skyline_points(w, h, base_y, seed)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.polygon(pts, fill=color)
    return img


def _branch(draw, x0, y0, angle, length, width, depth, rng, color):
    if depth <= 0 or length < 4:
        return
    x1 = x0 + math.cos(angle) * length
    y1 = y0 + math.sin(angle) * length
    draw.line([x0, y0, x1, y1], fill=color, width=max(1, int(width)))
    n_children = rng.choice([1, 2, 2])
    for _ in range(n_children):
        da = rng.uniform(-0.6, 0.6)
        _branch(draw, x1, y1, angle + da, length * rng.uniform(0.6, 0.78),
                width * 0.65, depth - 1, rng, color)


def add_gnarled_branches(img, seed, n=5, base_y_frac=0.62):
    w, h = img.size
    rng = random.Random(seed)
    draw = ImageDraw.Draw(img, "RGBA")
    base_y = h * base_y_frac
    for _ in range(n):
        x0 = rng.uniform(0, w)
        angle = -math.pi / 2 + rng.uniform(-0.5, 0.5)
        length = rng.uniform(h * 0.10, h * 0.22)
        width = rng.uniform(3, 6)
        color = (6, 8, 11, rng.randint(160, 220))
        _branch(draw, x0, base_y, angle, length, width, rng.randint(3, 4), rng, color)
    return img


def add_grain(arr, seed, amount=9):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, amount, arr.shape[:2])[:, :, None]
    out = arr.astype(np.float32) + noise
    return np.clip(out, 0, 255).astype(np.uint8)


def generate_arkham_background(w_px, h_px, seed=42):
    """Build a w_px x h_px original cosmic-horror night scene: gradient
    sky, stars, a pale moon, a jagged gothic skyline, and gnarled branch
    silhouettes, finished with film grain and a vignette."""
    top_color = (10, 14, 24)
    bottom_color = (28, 46, 48)
    sky = make_sky_gradient(w_px, h_px, top_color, bottom_color, seed)
    img = Image.fromarray(sky).convert("RGBA")

    img = add_moon(img, cx_frac=0.68, cy_frac=0.30, radius_frac=0.09, seed=seed)
    img = add_stars(img, count=int(w_px * h_px / 9000), seed=seed, region_bottom=0.58)
    img = add_skyline(img, base_y_frac=0.66, seed=seed + 7)
    img = add_gnarled_branches(img, seed=seed + 13, n=6, base_y_frac=0.665)

    arr = np.array(img.convert("RGB"))
    arr = add_vignette(arr, strength=0.5)
    arr = add_grain(arr, seed=seed + 99, amount=6)
    return Image.fromarray(arr).convert("RGB")


if __name__ == "__main__":
    im = generate_arkham_background(2250, 2250, seed=42)
    im.save("arkham_bg_preview.png")
    print("wrote arkham_bg_preview.png", im.size)
