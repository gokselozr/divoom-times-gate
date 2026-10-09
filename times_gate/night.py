"""Five pixel-native night scenes; all movement repeats within its cached data key."""
from __future__ import annotations

from functools import lru_cache
import math
import random
import time

from PIL import Image, ImageDraw

from .pixel import (AMBER, BARK, CLAY, CORAL, CREAM, EMBER, FLAME, FOG, FOREST,
                    GRASS, INK, LEMON, MIST, NAVY, PINE, PLUM, ROSE, RUST, SAND,
                    SLATE, STEEL, WOOD, outlined, timed)
from .render import DAYS, MONTHS, centered, text

TITLES = ("RAIN", "CAMPFIRE", "MOON", "COFFEE", "CAT NAP")
PANES = ((7, 7, 61, 57), (66, 7, 120, 57), (7, 62, 61, 105), (66, 62, 120, 105))


# --- Rain: outside rain, glass beads, then the wooden frame ---------------------

@lru_cache(maxsize=1)
def rain_backdrop():
    image = Image.new("RGB", (128, 128), NAVY)
    draw = ImageDraw.Draw(image)
    # Low rain clouds overlap in connected masses above the distant skyline.
    draw.polygon(((0, 24), (14, 24), (19, 21), (37, 21), (42, 25),
                  (56, 25), (63, 28), (34, 28), (28, 30), (0, 30)), fill=SLATE)
    draw.polygon(((77, 18), (89, 18), (94, 16), (111, 16), (116, 20),
                  (127, 20), (127, 24), (100, 24), (95, 22), (77, 22)), fill=SLATE)
    draw.polygon(((0, 28), (19, 28), (28, 26), (46, 27), (55, 30),
                  (0, 32)), fill=NAVY)
    draw.polygon(((0, 39), (22, 39), (30, 36), (49, 36), (57, 40),
                  (77, 40), (87, 44), (127, 44), (127, 106), (0, 106)), fill=SLATE)
    draw.polygon(((0, 45), (25, 45), (35, 43), (53, 43), (61, 46),
                  (100, 46), (109, 48), (127, 48), (127, 106), (0, 106)), fill=NAVY)
    # Each building has its own silhouette; haze never paints over the skyline.
    for x, top, w in ((4, 62, 12), (20, 52, 15), (38, 65, 12), (55, 47, 14),
                      (74, 58, 11), (90, 53, 16), (111, 66, 14)):
        draw.rectangle((x, top, x + w, 106), fill=SLATE)
        draw.line((x + 2, top - 1, x + w - 2, top - 1), fill=STEEL)
        for wy in range(top + 6, 103, 7):
            for wx in range(x + 3, x + w - 2, 5):
                if (wx + wy) % 3:
                    draw.line((wx, wy, wx + 1, wy), fill=STEEL)
    rng = random.Random(7)
    windows = []
    for i, (x, top, w) in enumerate(((-3, 80, 18), (19, 72, 17), (41, 85, 16),
                                     (63, 69, 16), (83, 83, 18), (106, 76, 22))):
        draw.rectangle((x, top, x + w, 106), fill=INK)
        draw.rectangle((x + w - 3, top + 2, x + w, 106), fill=NAVY)
        draw.line((x, top, x + w, top), fill=NAVY)
        if i in (1, 4):
            draw.rectangle((x + 5, top - 8, x + 11, top - 3), fill=INK)
            draw.polygon(((x + 4, top - 8), (x + 8, top - 11), (x + 12, top - 8)), fill=INK)
            draw.line((x + 6, top - 2, x + 6, top), fill=INK)
            draw.line((x + 10, top - 2, x + 10, top), fill=INK)
        if i == 3:
            draw.line((x + 8, top - 8, x + 8, top), fill=INK, width=2)
            draw.line((x + 4, top - 6, x + 12, top - 6), fill=INK)
        if i == 5:
            draw.rectangle((x + 3, top - 3, x + 12, top - 1), fill=NAVY)
        for wy in range(top + 5, 104, 7):
            for wx in range(max(8, x + 3), min(120, x + w - 3), 5):
                if rng.random() < 0.43:
                    color = rng.choice((SAND, CLAY, AMBER))
                    windows.append((wx, wy, color, rng.random() < 0.10))
                    draw.rectangle((wx, wy, wx + 1, wy + 1), fill=color)
    # Reflected room light stays quieter than the real droplets.
    draw.line((12, 12, 12, 35), fill=SLATE)
    draw.line((13, 12, 13, 24), fill=SLATE)
    draw.line((71, 12, 71, 30), fill=SLATE)
    return image, windows


def rain_frames():
    backdrop, windows = rain_backdrop()
    rng = random.Random(11)
    near = [(rng.randint(9, 119), rng.randrange(48)) for _ in range(11)]
    far = [(rng.randint(9, 119), rng.randrange(24)) for _ in range(7)]
    beads = ((21, 31, 0), (49, 77, 5), (83, 24, 11), (105, 61, 17), (31, 94, 7))
    frames = []
    for frame in range(24):
        image = backdrop.copy()
        draw = ImageDraw.Draw(image)
        for i, (wx, wy, color, flicker) in enumerate(windows):
            if flicker:
                level = (frame + i * 5) % 24
                draw.rectangle((wx, wy, wx + 1, wy + 1), fill=WOOD if 8 <= level < 12 else color)
        # 24 * velocity equals exactly one period; no discontinuity at the seam.
        for x, y in far:
            for row in range(-1, 6):
                yy = (y + frame) % 24 + row * 24
                draw.line((x, yy, x - 1, yy + 2), fill=SLATE)
        for x, y in near:
            for row in range(-1, 4):
                yy = (y + frame * 2) % 48 + row * 48
                draw.line((x, yy, x - 1, yy + 4), fill=STEEL)
                draw.line((x, yy + 1, x, yy + 2), fill=FOG)
        for x, y, offset in beads:
            dy = round(math.sin(2 * math.pi * (frame + offset) / 24))
            draw.line((x, y - 4 + dy, x, y - 1 + dy), fill=SLATE)
            draw.rectangle((x - 1, y + dy, x + 1, y + 3 + dy), fill=STEEL)
            draw.line((x, y + dy, x, y + 1 + dy), fill=MIST)
            draw.point((x, y + 3 + dy), FOG)
        draw.rectangle((0, 0, 127, 127), outline=BARK, width=7)
        draw.rectangle((6, 6, 121, 106), outline=WOOD)
        draw.line((7, 7, 120, 7), fill=CLAY)
        draw.line((7, 8, 7, 105), fill=WOOD)
        draw.rectangle((62, 6, 65, 106), fill=BARK)
        draw.line((62, 7, 62, 105), fill=CLAY)
        draw.line((63, 7, 63, 105), fill=WOOD)
        draw.rectangle((6, 58, 121, 61), fill=BARK)
        draw.line((7, 58, 120, 58), fill=WOOD)
        draw.line((7, 61, 120, 61), fill=WOOD)
        draw.rectangle((0, 107, 127, 116), fill=WOOD)
        draw.line((0, 107, 127, 107), fill=CLAY)
        draw.rectangle((0, 117, 127, 127), fill=BARK)
        draw.line((0, 117, 127, 117), fill=WOOD)
        for x0, y0, x1 in ((13, 111, 34), (41, 114, 61), (72, 110, 86), (7, 123, 20)):
            draw.line((x0, y0, x1, y0), fill=BARK if y0 < 117 else WOOD)
        draw.ellipse((93, 114, 114, 118), fill=BARK)
        draw.polygon(((96, 111), (111, 111), (109, 122), (98, 122)), fill=CLAY)
        draw.polygon(((106, 112), (111, 112), (109, 122), (106, 122)), fill=WOOD)
        draw.line((96, 111, 111, 111), fill=SAND)
        for poly in (((103, 111), (96, 107), (95, 103), (100, 103), (104, 109)),
                     ((103, 109), (100, 101), (102, 97), (105, 101), (105, 109)),
                     ((105, 111), (106, 104), (111, 102), (112, 106), (108, 110))):
            draw.polygon(poly, fill=FOREST)
            draw.line((poly[1][0], poly[1][1], poly[2][0], poly[2][1]), fill=GRASS)
        draw.line((103, 100, 103, 106), fill=GRASS)
        frames.append(image)
    return timed(frames, 140)


# --- Campfire: irregular pines and forked, independently moving flames ---------

def pine(draw, x, base, height, color, lit):
    """A stepped evergreen with irregular branches and a fire-facing edge."""
    tip = base - height
    side = 1 if lit > 0 else -1
    draw.rectangle((x - 1, tip + 9, x + 1, base + 3), fill=BARK)
    for i, (level, half) in enumerate(((0.31, 5), (0.54, 9), (0.77, 13), (1.0, 16))):
        bottom = tip + round(height * level)
        spread = max(3, round(half * height / 58))
        top = tip if i == 0 else bottom - round(height * 0.32)
        draw.polygon(((x, top), (x + spread - 2, bottom - 5), (x + spread, bottom - 4),
                      (x + spread - 2, bottom - 1), (x + spread + 1, bottom),
                      (x - spread, bottom), (x - spread + 3, bottom - 4),
                      (x - spread + 1, bottom - 4)), fill=color)
        if color == PINE:
            draw.line((x + side * (spread - 3), bottom - 5, x + side * spread, bottom - 2), fill=FOREST)
            if i > 1:
                draw.line((x, bottom - 5, x + side * (spread - 5), bottom - 2), fill=FOREST)


@lru_cache(maxsize=1)
def campfire_backdrop():
    image = Image.new("RGB", (128, 128), NAVY)
    draw = ImageDraw.Draw(image)
    for x, y in ((8, 13), (31, 8), (57, 22), (88, 12), (118, 28), (98, 38), (39, 33)):
        draw.line((x, y, x + 1, y), fill=STEEL)
    draw.line((77, 8, 77, 10), fill=FOG)
    draw.line((76, 9, 78, 9), fill=STEEL)
    draw.polygon(((0, 87), (19, 81), (32, 86), (45, 83), (60, 88),
                  (82, 82), (98, 87), (117, 80), (127, 85), (127, 100), (0, 100)), fill=PINE)
    for x, base, h in ((34, 91, 33), (89, 92, 37), (68, 87, 22), (122, 91, 35)):
        pine(draw, x, base, h, NAVY, 1)
    for x, base, h, lit in ((9, 104, 67, 1), (25, 98, 48, 1), (116, 103, 72, -1), (103, 96, 43, -1)):
        pine(draw, x, base, h, PINE, lit)
    draw.polygon(((0, 102), (26, 99), (45, 102), (83, 99), (108, 102),
                  (127, 100), (127, 127), (0, 127)), fill=INK)
    draw.polygon(((21, 105), (37, 99), (77, 97), (99, 102), (110, 109),
                  (99, 117), (76, 121), (43, 119), (24, 114), (16, 109)), fill=NAVY)
    draw.polygon(((35, 105), (48, 100), (79, 101), (94, 106), (99, 110),
                  (84, 117), (54, 116), (37, 113), (29, 109)), fill=SLATE)
    draw.polygon(((44, 105), (57, 101), (81, 104), (89, 111), (76, 115),
                  (52, 114), (39, 110)), fill=WOOD)
    draw.ellipse((43, 101, 87, 111), fill=BARK)
    for x, y, width, color in ((22, 107, 8, INK), (96, 111, 13, NAVY), (31, 116, 18, INK),
                              (79, 119, 17, INK), (32, 104, 6, SLATE), (87, 106, 8, NAVY)):
        draw.line((x, y, x + width, y), fill=color)
    for x, y, w in ((38, 107, 9), (50, 112, 9), (64, 113, 10), (79, 111, 9), (89, 106, 7)):
        draw.polygon(((x - w // 2, y), (x - 2, y - 3), (x + 3, y - 3),
                      (x + w // 2, y), (x + 3, y + 3), (x - 3, y + 3)), fill=STEEL, outline=NAVY)
        draw.line((x - 2, y - 2, x + 2, y - 2), fill=CLAY)
        draw.line((x - 2, y + 2, x + 2, y + 2), fill=SLATE)
    # A foreground stone and low branch provide scale and ground depth.
    draw.polygon(((6, 123), (10, 120), (16, 120), (20, 124), (18, 127),
                  (7, 127)), fill=NAVY)
    draw.line((10, 121, 15, 121), fill=SLATE)
    draw.line((99, 125, 110, 121, 122, 121), fill=BARK, width=2)
    draw.line((108, 122, 113, 118), fill=BARK, width=2)
    return image


FLAME_LAYERS = ((RUST, 15, 44, 1.5), (EMBER, 13, 41, 1.5),
                (FLAME, 10, 33, 1.2), (AMBER, 7, 24, 1.0), (LEMON, 4, 14, 0.8))


def flame(draw, cx, base, frame, frames):
    phase = 2 * math.pi * frame / frames
    # Individually drawn lobes, not scaled copies of one triangular outline.
    shapes = (
        ((-15, 0), (-16, 9), (-11, 17), (-10, 29), (-5, 23), (-3, 33), (4, 44),
         (6, 35), (5, 26), (10, 20), (12, 28), (14, 18), (12, 10), (15, 4), (12, 0)),
        ((-12, 0), (-13, 10), (-8, 18), (-8, 26), (-4, 21), (1, 30), (4, 40),
         (5, 28), (3, 20), (8, 15), (11, 24), (11, 13), (13, 7), (10, 0)),
        ((-9, 0), (-10, 8), (-6, 18), (-3, 14), (2, 25), (3, 33), (6, 25),
         (4, 16), (8, 11), (10, 4), (7, 0)),
        ((-6, 0), (-7, 7), (-3, 15), (0, 24), (3, 18), (3, 11), (6, 7), (7, 0)),
        ((-3, 0), (-4, 5), (-1, 10), (0, 14), (2, 9), (4, 4), (3, 0)),
    )
    for n, ((color, half, height, sway), shape) in enumerate(zip(FLAME_LAYERS, shapes)):
        vertices = []
        for x, rise in shape:
            t = rise / height
            dx = round(sway * math.sin(phase + n * 0.7 + t) * t)
            dy = round(math.sin(phase * 2 + n * 1.1) * t)
            vertices.append((cx + x + dx, base - rise - dy))
        draw.polygon(vertices, fill=color)
    draw.line((cx - 5, base - 7, cx - 3, base - 13), fill=CREAM)


def campfire_frames():
    backdrop = campfire_backdrop()
    frames = []
    for frame in range(24):
        image = backdrop.copy()
        draw = ImageDraw.Draw(image)
        # Draw embers first: their birth is occluded by the flame, never a pop.
        for i, (sx, offset) in enumerate(((64, 0), (69, 8), (66, 16))):
            step = (frame + offset) % 24
            if 3 <= step <= 21:
                y = 78 - step
                x = sx + round(math.sin(2 * math.pi * step / 24 + i))
                color = FLAME if step < 12 else CLAY if step < 17 else WOOD
                draw.line((x, y, x, y + 1), fill=color)
        flame(draw, 64, 102, frame, 24)
        # The warm side of the stone ring follows the same slow flame cycle.
        reflection = CLAY if 5 <= frame <= 15 else WOOD
        for x, y, end in ((46, 110, 50), (61, 111, 66), (76, 109, 81)):
            draw.line((x, y, end, y), fill=reflection)
        draw.line((55, 115, 63, 115), fill=reflection)
        draw.polygon(((40, 104), (43, 98), (86, 94), (89, 100)), fill=BARK, outline=INK)
        draw.polygon(((42, 96), (45, 94), (87, 103), (85, 109)), fill=WOOD, outline=INK)
        draw.line((47, 96, 81, 103), fill=CLAY)
        draw.line((49, 101, 80, 97), fill=WOOD)
        draw.line((53, 100, 64, 98), fill=EMBER)
        draw.line((66, 102, 76, 104), fill=FLAME)
        for x, y in ((40, 101), (83, 105)):
            draw.ellipse((x - 3, y - 3, x + 4, y + 3), fill=CLAY, outline=BARK)
            draw.line((x - 1, y - 1, x + 2, y - 1), fill=SAND)
            draw.line((x, y, x + 1, y + 1), fill=WOOD)
        frames.append(image)
    return timed(frames, 150)


# --- Moon: original astronomical semantics, per-pixel terminator ----------------

SYNODIC = 29.530588853
NEW_MOON = 947182440  # 2000-01-06 18:14 UTC


def moon_phase(now):
    """Phase angle in radians: 0 new, pi full."""
    age = ((now - NEW_MOON) / 86400) % SYNODIC
    return 2 * math.pi * age / SYNODIC


def phase_name(angle):
    names = ("NEW MOON", "WAXING CRESCENT", "FIRST QUARTER", "WAXING GIBBOUS",
             "FULL MOON", "WANING GIBBOUS", "LAST QUARTER", "WANING CRESCENT")
    return names[round(angle / (2 * math.pi) * 8) % 8]


CRATERS = ((-0.35, -0.3, 0.22), (0.25, -0.4, 0.14), (0.1, 0.15, 0.28),
           (-0.4, 0.35, 0.12), (0.45, 0.3, 0.1))


@lru_cache(maxsize=4)
def moon_frames_for(hour_key):
    angle = moon_phase(hour_key * 3600)
    image = Image.new("RGB", (128, 128), NAVY)
    draw = ImageDraw.Draw(image)
    draw.polygon(((0, 65), (27, 65), (39, 68), (77, 68), (91, 64),
                  (127, 64), (127, 91), (0, 91)), fill=SLATE)
    points = ((12, 12), (28, 26), (103, 10), (116, 39), (18, 58), (108, 58),
              (44, 7), (89, 22), (7, 40), (119, 17), (37, 61), (91, 55))
    for x, y in points:
        draw.line((x, y, x + 1, y), fill=STEEL)
    cx, cy, r = 64, 42, 29
    # Draw albedo separately so no crater or bright rim crosses the terminator.
    surface = Image.new("RGB", (128, 128), FOG)
    sd = ImageDraw.Draw(surface)
    sd.polygon(((49, 25), (60, 18), (72, 18), (85, 30), (87, 42),
                (79, 36), (75, 28), (64, 25), (57, 29)), fill=MIST)
    # A connected dark sea with broken borders gives the surface a recognizable
    # geography. Small crater cuts sit in it, rather than five floating spots.
    sd.polygon(((43, 32), (47, 28), (51, 28), (51, 33), (58, 34), (60, 37),
                (65, 35), (69, 37), (72, 42), (71, 48), (75, 53), (70, 57),
                (62, 54), (59, 49), (54, 47), (53, 40), (47, 40)), fill=STEEL)
    for polygon in (
        ((47, 30), (51, 27), (57, 28), (60, 32), (58, 37), (54, 39), (47, 37), (45, 33)),
        ((60, 43), (65, 39), (70, 42), (73, 45), (73, 51), (69, 55), (62, 53), (58, 48)),
        ((72, 27), (77, 26), (80, 30), (78, 33), (73, 32)),
    ):
        sd.polygon(polygon, fill=STEEL)
    sd.line((48, 29, 54, 27, 59, 30), fill=SLATE)
    sd.line((60, 45, 63, 41, 68, 41), fill=SLATE)
    sd.line((61, 51, 65, 54, 69, 54), fill=MIST)
    sd.line((48, 51, 51, 50, 53, 52), fill=STEEL, width=2)
    sd.line((77, 51, 80, 50, 82, 53), fill=STEEL, width=2)
    sd.line((78, 54, 81, 54), fill=MIST)
    sd.line((55, 59, 58, 58, 60, 60), fill=MIST)
    waxing = angle < math.pi
    pixels = surface.load()
    for y in range(-r, r + 1):
        half = math.sqrt(max(0, r * r - y * y))
        edge = half * math.cos(angle)
        for x in range(-r, r + 1):
            d2 = x * x + y * y
            if d2 > r * r:
                continue
            depth = x - edge if waxing else -edge - x
            if depth <= 0:
                color = INK  # Unlit limb must not invent a bright full ring.
            else:
                color = pixels[cx + x, cy + y]
                if d2 > (r - 1) ** 2:
                    color = STEEL
                elif depth < 1.5:
                    color = STEEL if (x + y) % 2 else FOG
            draw.point((cx + x, cy + y), color)
    draw.polygon(((0, 86), (14, 81), (27, 81), (40, 86), (56, 81), (72, 78),
                  (85, 82), (102, 80), (116, 85), (127, 82), (127, 127), (0, 127)), fill=NAVY)
    draw.polygon(((0, 93), (22, 89), (43, 92), (65, 88), (85, 91), (104, 89),
                  (127, 93), (127, 127), (0, 127)), fill=INK)
    draw.rectangle((96, 80, 111, 89), fill=BARK)
    draw.rectangle((106, 81, 111, 89), fill=WOOD)
    draw.polygon(((93, 81), (102, 74), (114, 81)), fill=INK)
    draw.line((94, 81, 102, 75, 113, 81), fill=NAVY)
    draw.rectangle((108, 73, 109, 78), fill=BARK)
    draw.rectangle((98, 83, 100, 85), fill=SAND)
    draw.rectangle((106, 83, 108, 85), fill=AMBER)
    draw.line((96, 89, 112, 89), fill=WOOD)
    lit = round((1 - math.cos(angle)) / 2 * 100)
    centered(draw, phase_name(angle), 99, CREAM)
    centered(draw, f"{lit}% LIT", 113, MIST)
    frames = []
    for frame in range(16):
        copy = image.copy()
        d = ImageDraw.Draw(copy)
        for i, (x, y) in enumerate(((12, 12), (116, 39), (28, 26))):
            level = (frame + i * 5) % 16
            color = FOG if 4 <= level <= 10 else STEEL
            d.line((x, y, x + 1, y), fill=color)
        frames.append(copy)
    return timed(frames, 260)


# --- Coffee: honest clock, glazed mug and slow connected steam -----------------

@lru_cache(maxsize=1)
def mug_sprite():
    sprite = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    draw.ellipse((36, 102, 102, 113), fill=CLAY)
    draw.ellipse((39, 102, 99, 109), fill=SAND)
    draw.line((46, 110, 88, 110), fill=WOOD)
    draw.ellipse((85, 76, 107, 97), fill=SAND)
    draw.ellipse((90, 80, 102, 93), fill=NAVY)
    draw.arc((88, 77, 106, 96), 260, 90, fill=CREAM, width=2)
    draw.polygon(((43, 72), (90, 72), (90, 98), (87, 103), (81, 106),
                  (52, 106), (46, 103), (43, 97)), fill=SAND)
    draw.polygon(((47, 74), (78, 74), (78, 102), (74, 104), (53, 103),
                  (48, 100)), fill=CREAM)
    # Turned ceramic planes, with a smaller cream face and a warm lower glaze.
    draw.polygon(((75, 77), (80, 76), (80, 101), (75, 104), (71, 103),
                  (73, 97), (73, 84)), fill=SAND)
    draw.polygon(((49, 96), (71, 99), (75, 99), (75, 103), (53, 103),
                  (49, 100)), fill=SAND)
    draw.polygon(((86, 74), (90, 73), (90, 99), (86, 103), (83, 103), (86, 98)), fill=CLAY)
    draw.line((53, 106, 81, 106), fill=CLAY)
    draw.ellipse((43, 66, 90, 77), fill=CREAM)
    draw.ellipse((46, 68, 87, 74), fill=WOOD)
    draw.ellipse((49, 69, 85, 73), fill=BARK)
    draw.line((52, 69, 64, 69), fill=CLAY)
    draw.line((48, 79, 48, 95), fill=MIST)
    draw.line((49, 79, 49, 86), fill=CREAM)
    draw.line((54, 77, 73, 77), fill=SAND)
    return sprite


@lru_cache(maxsize=2)
def coffee_frames_for(minute_key):
    now = minute_key * 60
    base = Image.new("RGB", (128, 128), NAVY)
    draw = ImageDraw.Draw(base)
    draw.rectangle((0, 0, 127, 43), fill=INK)
    draw.polygon(((0, 46), (18, 46), (35, 107), (0, 107)), fill=SLATE)
    draw.line((12, 47, 29, 106), fill=NAVY)
    draw.rectangle((0, 108, 127, 127), fill=WOOD)
    draw.line((0, 108, 127, 108), fill=CLAY)
    draw.line((0, 110, 127, 110), fill=BARK)
    draw.line((0, 121, 127, 121), fill=BARK)
    for x, y, end in ((5, 116, 21), (16, 118, 33), (107, 114, 121), (91, 125, 114)):
        draw.line((x, y, end, y), fill=BARK)
    draw.ellipse((33, 107, 109, 116), fill=BARK)
    outlined(base, mug_sprite(), BARK)
    local = time.localtime(now)
    centered(draw, time.strftime("%H:%M", local), 7, CREAM, 3)
    centered(draw, f"{DAYS[local.tm_wday]} {local.tm_mday:02} {MONTHS[local.tm_mon - 1]}", 34, MIST)
    frames = []
    for frame in range(16):
        image = base.copy()
        d = ImageDraw.Draw(image)
        for i, x in enumerate((57, 69, 79)):
            previous = None
            for step in range(18):
                y = 64 - step
                drift = math.sin(2 * math.pi * frame / 16 + i * 1.7)
                xx = x + round(1.4 * math.sin(step / 3 + i) + drift)
                color = FOG if step < 8 else STEEL
                if previous:
                    d.line((*previous, xx, y), fill=color, width=2 if step < 5 else 1)
                previous = (xx, y)
        frames.append(image)
    return timed(frames, 220)


# --- Cat: low torso, tucked paws, connected tail, one-pixel breathing -----------

def cat_sprite(breath):
    """A naturally proportioned grey tabby, resting its head on tucked paws."""
    sprite = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    draw.polygon(((43, 91), (48, 85), (58, 81 - breath), (76, 80 - breath),
                  (89, 83 - breath), (98, 88), (103, 94), (100, 101),
                  (91, 106), (56, 105), (45, 100)), fill=FOG)
    draw.polygon(((47, 97), (63, 96), (76, 99), (98, 95), (100, 101),
                  (91, 106), (56, 105), (45, 100)), fill=STEEL)
    draw.line((56, 83 - breath, 64, 81 - breath, 75, 81 - breath), fill=MIST)
    draw.line((78, 82 - breath, 87, 84 - breath), fill=MIST)
    for polygon in (((61, 82 - breath), (64, 82 - breath), (62, 87), (60, 89)),
                    ((71, 81 - breath), (74, 81 - breath), (73, 86), (70, 90)),
                    ((81, 82 - breath), (84, 83 - breath), (83, 88), (81, 90)),
                    ((91, 86), (94, 88), (93, 92), (91, 93))):
        draw.polygon(polygon, fill=SLATE)
    draw.polygon(((53, 89), (57, 89), (60, 93), (60, 98),
                  (56, 98), (58, 94)), fill=STEEL)
    draw.polygon(((97, 95), (103, 96), (104, 102), (100, 108), (90, 111),
                  (73, 112), (56, 109), (51, 106), (55, 102), (61, 104),
                  (77, 107), (92, 105), (98, 101)), fill=STEEL)
    draw.line((57, 104, 74, 109, 90, 108, 99, 105, 101, 101), fill=FOG, width=2)
    draw.line((55, 105, 61, 107), fill=SLATE, width=3)
    draw.line((87, 106, 88, 110), fill=SLATE, width=2)
    draw.line((96, 103, 98, 106), fill=SLATE, width=2)
    draw.ellipse((27, 84, 57, 104), fill=FOG)
    draw.polygon(((29, 90), (29, 80), (32, 78), (36, 83), (40, 87)), fill=FOG)
    draw.polygon(((44, 87), (50, 80), (53, 81), (54, 92)), fill=FOG)
    draw.polygon(((31, 85), (31, 81), (35, 86)), fill=CLAY)
    draw.polygon(((48, 86), (51, 83), (52, 89)), fill=CLAY)
    draw.line((40, 85, 40, 89), fill=SLATE, width=2)
    draw.line((44, 85, 44, 89), fill=SLATE)
    # Small cheek and nose bridge, rather than a large round white muzzle.
    draw.polygon(((29, 96), (34, 95), (39, 96), (43, 100),
                  (41, 103), (33, 103), (29, 101)), fill=MIST)
    draw.line((31, 92, 34, 94, 38, 92), fill=BARK)
    draw.line((44, 93, 47, 94, 50, 92), fill=BARK)
    draw.rectangle((38, 98, 39, 99), fill=CORAL)
    draw.line((24, 96, 29, 97), fill=FOG)
    draw.line((23, 100, 29, 100), fill=FOG)
    draw.ellipse((37, 102, 57, 108), fill=MIST)
    draw.line((45, 105, 45, 107), fill=FOG)
    draw.line((49, 105, 49, 107), fill=FOG)
    draw.line((36, 101, 40, 101), fill=FOG)
    draw.line((39, 100, 40, 101), fill=BARK)
    return sprite


@lru_cache(maxsize=1)
def cat_frames():
    base = Image.new("RGB", (128, 128), NAVY)
    draw = ImageDraw.Draw(base)
    # A narrow curtain gives the wall a setting without a huge geometric wedge.
    draw.polygon(((112, 0), (127, 0), (127, 91), (122, 88), (117, 91),
                  (113, 87), (110, 88)), fill=SLATE)
    draw.polygon(((119, 0), (123, 0), (122, 88), (118, 88)), fill=NAVY)
    draw.line((112, 7, 111, 76), fill=STEEL)
    draw.line((0, 111, 21, 111), fill=WOOD)
    # Quiet floorboard joints keep the cushion grounded without pink flooring.
    draw.line((0, 124, 18, 124), fill=WOOD)
    draw.line((115, 123, 127, 123), fill=WOOD)
    draw.line((114, 111, 127, 111), fill=WOOD)
    draw.rectangle((0, 113, 127, 127), fill=BARK)
    draw.line((0, 113, 127, 113), fill=WOOD)
    draw.ellipse((16, 96, 113, 123), fill=PLUM, outline=BARK)
    draw.ellipse((20, 95, 109, 116), fill=PLUM)
    draw.arc((20, 95, 109, 116), 182, 355, fill=ROSE, width=2)
    draw.ellipse((26, 97, 103, 113), fill=WOOD)
    draw.arc((20, 96, 109, 118), 5, 175, fill=CLAY)
    for x, y in ((29, 112), (38, 116), (52, 119), (73, 120), (90, 117), (102, 111)):
        draw.line((x, y, x + 2, y), fill=SAND)
    frames = []
    for frame in range(16):
        image = base.copy()
        breath = 1 if 4 <= frame <= 10 else 0
        outlined(image, cat_sprite(breath), BARK)
        d = ImageDraw.Draw(image)
        for i, (x, y, scale) in enumerate(((38, 63, 1), (52, 46, 2))):
            step = (frame + i * 5) % 16
            bob = round(math.sin(2 * math.pi * step / 16))
            color = FOG if 3 <= step <= 10 else STEEL
            text(d, "Z", x, y + bob, color, scale)
        frames.append(image)
    return timed(frames, 320)


def render_night(now: float | None = None) -> list[list[Image.Image]]:
    now = time.time() if now is None else now
    return [rain_frames_cached(), campfire_frames_cached(), moon_frames_for(int(now // 3600)),
            coffee_frames_for(int(now // 60)), cat_frames()]


rain_frames_cached = lru_cache(maxsize=1)(rain_frames)
campfire_frames_cached = lru_cache(maxsize=1)(campfire_frames)
