"""Shared pixel-art toolkit: the ENDESGA 32 palette and the drawing helpers every scene uses."""
from __future__ import annotations

from PIL import ImageFilter

INK = "#181425"
NAVY = "#262b44"
SLATE = "#3a4466"
STEEL = "#5a6988"
FOG = "#8b9bb4"
MIST = "#c0cbdc"
SNOW = "#ffffff"
LEMON = "#fee761"
AMBER = "#feae34"
FLAME = "#f77622"
EMBER = "#e43b44"
RUST = "#a22633"
WOOD = "#733e39"
BARK = "#3e2731"
CLAY = "#b86f50"
SAND = "#e4a672"
CREAM = "#ead4aa"
PINE = "#193c3e"
FOREST = "#265c42"
PLUM = "#68386c"
ROSE = "#b55088"
CORAL = "#f6757a"
SKY = "#0099db"
DEEP = "#124e89"
ICE = "#2ce8f5"
LEAF = "#63c74d"
GRASS = "#3e8948"
PEACH = "#e8b796"


def timed(frames, ms):
    for frame in frames:
        frame.info["duration"] = ms
    return frames


def dither(draw, box, a, b, density=0.5):
    """Fill a box with an ordered 2x2 dither of a over b."""
    pattern = ((0, 2), (3, 1))
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            draw.point((x, y), a if pattern[y % 2][x % 2] < density * 4 else b)


BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def gradient(draw, top, bottom, colors, x0=0, x1=127):
    """Vertical gradient: flat colour bands joined by a 4x4 Bayer-dithered seam."""
    steps = len(colors) - 1
    for y in range(top, bottom + 1):
        t = (y - top) / max(1, bottom - top) * steps
        i = min(steps - 1, int(t))
        # Only the middle of each band is dithered, so colours stay calm.
        f = min(1.0, max(0.0, (t - i - 0.3) / 0.4))
        for x in range(x0, x1 + 1):
            draw.point((x, y), colors[i + 1] if f * 16 > BAYER[y % 4][x % 4] else colors[i])


def outlined(image, sprite, color):
    """Paste a transparent sprite with a one-pixel outline, the way pixel artists ink a shape."""
    alpha = sprite.getchannel("A").point(lambda a: 255 if a else 0)
    ring = alpha.filter(ImageFilter.MaxFilter(3))
    image.paste(color, (0, 0), ring)
    image.paste(sprite, (0, 0), alpha)


def stars(draw, rng, count, area, colors=(FOG, MIST)):
    x0, y0, x1, y1 = area
    points = [(rng.randint(x0, x1), rng.randint(y0, y1), rng.choice(colors)) for _ in range(count)]
    for x, y, color in points:
        draw.point((x, y), color)
    return points
