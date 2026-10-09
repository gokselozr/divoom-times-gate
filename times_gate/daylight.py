"""Daylight mode: sunny scenes beside the night ones, on the same ENDESGA 32 palette."""
from __future__ import annotations

from functools import lru_cache
import math
import random
import time

from PIL import Image, ImageDraw

from .pixel import (AMBER, BARK, CLAY, CORAL, CREAM, DEEP, FOREST, GRASS, ICE, INK, LEAF, LEMON, MIST, NAVY,
                    PEACH, PINE, PLUM, ROSE, SAND, SKY, SLATE, SNOW, STEEL, WOOD, BAYER, gradient, outlined, timed)
from .knight import knight_frames
from .render import DAYS, MONTHS, centered, right, text

TITLES = ("SUN", "MEADOW", "SEA", "LEMONADE", "KNIGHT")
# Used until the config names another place; the sun panel needs a latitude and longitude.
ISTANBUL = (41.01, 28.98)


# --- 1. The sun's real path ----------------------------------------------------------------

def solar_elevation(ts, lat, lon):
    """Sun elevation in degrees (NOAA's low-precision formulae, good to a fraction of a degree)."""
    d = ts / 86400 - 10957.5
    g = math.radians(357.529 + 0.98560028 * d)
    q = 280.459 + 0.98564736 * d
    ecliptic = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    tilt = math.radians(23.439 - 0.00000036 * d)
    ra = math.degrees(math.atan2(math.cos(tilt) * math.sin(ecliptic), math.cos(ecliptic)))
    dec = math.asin(math.sin(tilt) * math.sin(ecliptic))
    sidereal = (18.697374558 + 24.06570982441908 * d) % 24
    hour = math.radians(sidereal * 15 + lon - ra)
    phi = math.radians(lat)
    return math.degrees(math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour)))


@lru_cache(maxsize=4)
def sun_day(day_start, lat, lon):
    """Sunrise, sunset (unix seconds) and the highest elevation for the local day starting at day_start."""
    samples = [(day_start + m * 60, solar_elevation(day_start + m * 60, lat, lon)) for m in range(0, 1441, 2)]
    rise = next((t for (t, e), (_, prev) in zip(samples[1:], samples) if prev < -0.833 <= e), None)
    sets = next((t for (t, e), (_, prev) in zip(samples[1:], samples) if prev >= -0.833 > e), None)
    return rise, sets, max(e for _, e in samples)


def local_midnight(ts):
    local = time.localtime(ts)
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))


def sky_colors(elevation):
    if elevation < -6:
        return (INK, NAVY, SLATE)
    if elevation < 1:
        return (DEEP, PLUM, CORAL, AMBER)
    if elevation < 12:
        return (SKY, PEACH, AMBER)
    return (DEEP, SKY, MIST)


def hhmm(ts):
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"


def _sky(draw, bottom, colors):
    """Broad quiet colour planes with short, pixel-native transitions."""
    draw.rectangle((0, 0, 127, bottom), fill=colors[0])
    # Daytime needs room for the arc in blue, with haze confined to the horizon.
    edges = (.12, .83) if colors == (DEEP, SKY, MIST) else ((.18, .48, .81) if len(colors) == 4 else (.24, .79))
    for n, color in enumerate(colors[1:]):
        edge = round(bottom * edges[n])
        # Uneven atmospheric edges, with sparse clusters instead of Bayer stripes.
        for x in range(128):
            seam = edge + round(2 * math.sin(x / 29 + n) + math.sin(x / 11))
            draw.line((x, seam, x, bottom), fill=color)
            if (x * 13 + n * 7) % 19 < 4:
                draw.line((x, seam - 2, x + 1, seam - 2), fill=color)



def _cloud(d, x, y, w):
    """A stepped cloud with a warm underside and a small lit crown."""
    d.polygon(((x, y), (x+2, y-2), (x+6, y-2), (x+6, y-5),
               (x+9, y-5), (x+9, y-7), (x+13, y-7), (x+13, y-9),
               (x+18, y-9), (x+18, y-7), (x+22, y-7), (x+22, y-4),
               (x+w-5, y-4), (x+w-5, y-2), (x+w-2, y-2),
               (x+w-2, y), (x+w, y), (x+w, y+2), (x+w-3, y+2),
               (x+w-3, y+4), (x+3, y+4), (x+3, y+2), (x, y+2)), fill=CREAM)
    d.line((x+5, y+4, x+w-5, y+4), fill=MIST)
    d.line((x+10, y-6, x+13, y-6, x+13, y-8, x+17, y-8), fill=SNOW)
    d.polygon(((x+5, y), (x+9, y), (x+9, y+2), (x+16, y+2),
               (x+16, y+3), (x+5, y+3)), fill=MIST)


def _pine(d, x, y, h, color):
    d.polygon(((x, y-h), (x-3, y-h+8), (x-1, y-h+8), (x-6, y-5),
               (x-3, y-5), (x-8, y), (x+8, y), (x+3, y-5),
               (x+6, y-5), (x+1, y-h+8), (x+3, y-h+8)), fill=color)
    d.rectangle((x-1, y-2, x+1, y+3), fill=color)


@lru_cache(maxsize=2)
def sun_frames_for(ten_minute_key, lat, lon):
    now = ten_minute_key * 600
    rise, sets, peak = sun_day(local_midnight(now), lat, lon)
    elevation = solar_elevation(now, lat, lon)
    base = Image.new("RGB", (128, 128), INK)
    draw = ImageDraw.Draw(base)
    _sky(draw, 88, sky_colors(elevation))
    horizon, top = 78, 18
    # Both the guide and marker use today's actual elevation, not a sine arc.
    if rise is not None and sets is not None:
        for x in range(12, 117, 5):
            sample = rise + (sets-rise) * (x-12) / 104
            lift = max(0.0, solar_elevation(sample, lat, lon)) / max(1.0, peak)
            y = round(horizon - (horizon-top) * lift)
            arc_color = CREAM if elevation >= 12 and y < 72 else STEEL
            draw.rectangle((x, y, x+1, y+1), fill=arc_color)
    # Sparse low cloud clusters break up the warm dusk planes without stripes.
    if -6 <= elevation < 12:
        draw.polygon(((3, 60), (13, 59), (22, 60), (34, 60), (42, 62),
                      (27, 63), (15, 62), (3, 62)), fill=PEACH if elevation >= 1 else CORAL)
        draw.polygon(((79, 69), (89, 67), (98, 68), (107, 67), (118, 69),
                      (105, 71), (92, 70), (79, 71)), fill=AMBER)
    # Small warm clouds leave the actual marker's arc open.
    if elevation > 12:
        draw.polygon(((0, 48), (6, 45), (14, 45), (18, 48), (28, 48),
                      (33, 51), (0, 51)), fill=CREAM)
        draw.line((0, 52, 29, 52), fill=MIST)
    elif elevation < -6:
        for x, y in ((17, 13), (91, 10), (110, 30), (24, 37)):
            draw.line((x, y, x+1, y), fill=STEEL)
    position = None
    if rise is not None and sets is not None and rise <= now < sets:
        t = (now - rise) / (sets - rise)
        lift = max(0.0, elevation) / max(1.0, peak)
        position = (12 + 104 * t, horizon - (horizon - top) * lift)
    # With no rise/set interval, don't invent a position along a nonexistent arc.
    daylight = ((sets is not None and (rise is None or rise <= now) and now < sets)
                or (sets is None and rise is not None and now >= rise))
    if daylight and sets is not None:
        left = max(0, int(sets - now))
        label = f"SET IN {left // 3600}H {left % 3600 // 60:02}M"
    elif daylight:
        label = "SUN UP"
    elif rise is None and sets is None:
        label = "SUN UP" if elevation > -0.833 else "SUN DOWN"
    else:
        upcoming = rise if rise is not None and rise > now else sun_day(local_midnight(now + 86400), lat, lon)[0]
        label = f"RISE {hhmm(upcoming)}"
    frames = []
    for frame in range(4):
        image = base.copy()
        d = ImageDraw.Draw(image)
        if position:
            sx, sy = round(position[0]), round(position[1])
            # Fixed rays: a single warm highlight breathes without moving real data.
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                d.line((sx+dx*10, sy+dy*10, sx+dx*12, sy+dy*12), fill=AMBER)
            d.ellipse((sx - 7, sy - 7, sx + 7, sy + 7), fill=LEMON, outline=AMBER)
            d.line((sx-3, sy-4, sx, sy-4), fill=CREAM if frame in (0, 3) else SNOW)
        # Hills in front of the horizon, nearer ones darker.
        for x in range(128):
            far = 86 + round(3 * math.sin(x / 15 + 1) + 2 * math.sin(x / 7))
            d.line((x, far, x, 127), fill=GRASS if elevation > 1 else FOREST)
            near = 94 + round(2 * math.sin(x / 19 + 4))
            d.line((x, near, x, 127), fill=FOREST if elevation > 1 else PINE)
        for x, y, h in ((3, 95, 17), (124, 94, 23)):
            _pine(d, x, y, h, FOREST if elevation > 1 else PINE)
        d.line((10, 110, 117, 110), fill=GRASS if elevation > 1 else FOREST)
        centered(d, label, 100, CREAM)
        text(d, "UP", 5, 117, LEMON)
        text(d, hhmm(rise), 20, 117, CREAM)
        text(d, "DN", 68, 117, AMBER)
        right(d, hhmm(sets), 123, 117, CREAM)
        frames.append(image)
    return timed(frames, 500)


# --- 2. Meadow -----------------------------------------------------------------------------

FLOWERS = ((CORAL, SNOW), (LEMON, AMBER), (SNOW, LEMON), (ROSE, CORAL))


@lru_cache(maxsize=1)
def meadow_backdrop():
    image = Image.new("RGB", (128, 128), SKY)
    draw = ImageDraw.Draw(image)
    _cloud(draw, 72, 23, 35)
    _cloud(draw, 19, 37, 27)
    draw.polygon(((0, 63), (18, 59), (36, 62), (57, 56), (81, 60),
                  (105, 55), (127, 58), (127, 127), (0, 127)), fill=FOREST)
    draw.polygon(((0, 72), (18, 68), (38, 70), (58, 63), (80, 64),
                  (103, 60), (127, 64), (127, 127), (0, 127)), fill=GRASS)
    draw.polygon(((0, 81), (23, 77), (47, 72), (65, 74), (94, 69),
                  (127, 73), (127, 127), (0, 127)), fill=LEAF)
    # A quiet sweep through the middle, framed by darker flower banks.
    draw.polygon(((0, 93), (22, 90), (39, 94), (49, 101), (52, 112), (60, 127), (0, 127)), fill=GRASS)
    draw.polygon(((128, 87), (113, 89), (101, 98), (95, 109), (82, 119), (73, 127), (128, 127)), fill=GRASS)
    draw.polygon(((0, 112), (18, 109), (30, 115), (38, 128), (0, 128)), fill=FOREST)
    draw.polygon(((110, 117), (119, 111), (127, 113), (127, 127), (101, 127)), fill=FOREST)
    # A little overhead foliage echoes the knight without cloning his tree.
    draw.polygon(((0, 7), (11, 5), (26, 0), (33, 0), (20, 6), (6, 10), (0, 14)), fill=BARK)
    for x, y, w in ((0, 0, 17), (15, 1, 13), (30, 0, 9), (4, 10, 9)):
        draw.polygon(((x-5, y), (x, y-4), (x+w, y-3), (x+w+2, y+2),
                      (x+w-2, y+5), (x+2, y+6)), fill=FOREST)
        draw.line((x+1, y, x+w-2, y), fill=GRASS, width=2)
    rng = random.Random(8)
    for _ in range(85):
        x, y = rng.randint(1, 126), rng.randint(76, 126)
        if 44 < x < 82 and y > 98:
            continue
        color = GRASS if y < 94 else FOREST
        draw.line((x, y, x+1, y-3), fill=color)
        draw.line((x+2, y, x+3, y-2), fill=color)
    for x, y in ((9, 79), (28, 75), (65, 80), (95, 74), (111, 83), (123, 77)):
        draw.line((x, y, x+2, y), fill=CREAM)
    return image


def butterfly(draw, x, y, open_, colors):
    wing, edge = colors
    if open_:
        span = 4 if open_ == .5 else 6
        for side in (-1, 1):
            draw.polygon(((x+side, y), (x+side*(span-2), y-4), (x+side*span, y-3),
                          (x+side*span, y), (x+side*2, y+1)), fill=edge)
            draw.line((x+side*(span-3), y-2, x+side*(span-2), y-2), fill=wing, width=2)
            draw.polygon(((x+side, y), (x+side*(span-2), y+1), (x+side*(span-2), y+3),
                          (x+side*2, y+4)), fill=wing)
    else:
        draw.polygon(((x, y+2), (x-2, y-3), (x-1, y-5), (x+2, y-4), (x+2, y)), fill=edge)
        draw.line((x, y-3, x+1, y-1), fill=wing)
    draw.line((x, y - 2, x, y + 3), fill=BARK)
    draw.point((x - 1, y - 3), BARK)
    draw.point((x + 1, y - 3), BARK)


@lru_cache(maxsize=1)
def meadow_frames():
    backdrop = meadow_backdrop()
    # Composed groups, with negative space through their centre.
    flowers = ((13, 94, 0, .2), (25, 98, 2, .8), (103, 95, 1, 1.5),
               (114, 101, 0, 1.9), (38, 101, 1, .9), (91, 104, 2, 1.4),
               (7, 112, 3, .1), (19, 115, 2, .4), (31, 119, 0, .7),
               (42, 121, 2, 1.1), (84, 118, 1, 1.3), (100, 122, 0, 1.8),
               (115, 122, 2, 2.0), (124, 114, 3, 2.2))
    frames = []
    for frame in range(16):
        image = backdrop.copy()
        draw = ImageDraw.Draw(image)
        phase = 2 * math.pi * frame / 16
        for x, y, kind, offset in sorted(flowers, key=lambda f: f[1]):
            # Nearer flowers (lower on screen) are taller and bigger.
            near = (y - 84) / 42
            height = 13 + round(near * 12)
            lean = round((1 if near < .45 else 2) * math.sin(phase + offset))
            draw.line(((x, y), (x-1, y-height//2), (x+lean, y-height)), fill=PINE, width=2 if near > .5 else 1)
            draw.polygon(((x, y-6), (x-5, y-11), (x-6, y-8), (x-3, y-6)), fill=FOREST)
            draw.line((x-5, y-10, x-2, y-7), fill=LEAF)
            draw.polygon(((x, y-10), (x+5, y-15), (x+5, y-11), (x+2, y-9)), fill=FOREST)
            petal, heart = FLOWERS[kind]
            fx, fy = x + lean, y - height
            size = 4 if near > .5 else 3
            if kind == 3:
                # Foxglove bells make an upright silhouette among the daisies.
                draw.line((fx, fy+5, fx-1, fy-9), fill=PINE)
                for dx, dy in ((-2, 2), (2, -2), (-2, -6)):
                    draw.rectangle((fx+dx-1, fy+dy-2, fx+dx+1, fy+dy+1), fill=ROSE)
                    draw.line((fx+dx-1, fy+dy-2, fx+dx, fy+dy-2), fill=CORAL)
                draw.line((fx-1, fy-10, fx, fy-10), fill=CORAL)
                continue
            draw.polygon(((fx-1, fy-size), (fx+1, fy-size), (fx+2, fy-2),
                          (fx+size, fy-1), (fx+size, fy+1), (fx+2, fy+2),
                          (fx+1, fy+size), (fx-1, fy+size), (fx-2, fy+2),
                          (fx-size, fy+1), (fx-size, fy-1), (fx-2, fy-2)), fill=petal)
            draw.line((fx-1, fy+size, fx+1, fy+size), fill=MIST if kind == 2 else heart)
            draw.rectangle((fx-1, fy-1, fx+1, fy+1), fill=heart)
            if kind == 2:
                draw.line((fx-1, fy-3, fx, fy-3), fill=SNOW)
                draw.line((fx+1, fy+5, fx+5, fy+10), fill=PINE)
                draw.rectangle((fx+4, fy+8, fx+6, fy+10), fill=CREAM)
                draw.line((fx+4, fy+10, fx+5, fy+10), fill=AMBER)
        # Suspended butterflies move 1–2 pixels at a time; wing poses hold.
        for n, (cx, cy, colors) in enumerate(((52, 58, (CORAL, ROSE)), (94, 44, (LEMON, AMBER)))):
            t = phase * (1 if n == 0 else -1) + n
            x = cx + round(3 * math.sin(t))
            y = cy + round(1.5 * math.sin(t))
            poses = (True, True, True, .5, .5, False, False, False,
                     False, .5, .5, True, True, True, True, True)
            butterfly(draw, x, y, poses[(frame+n*6) % 16], colors)
        frames.append(image)
    return timed(frames, 220)


# --- 3. Sea --------------------------------------------------------------------------------

# Colour-cycling ramp: each water pixel keeps its index and the colours march through it.
WATER = (DEEP, DEEP, DEEP, DEEP, SKY, SKY, SKY, SKY, ICE, SKY, SKY, SKY, SKY, DEEP, DEEP, DEEP)


@lru_cache(maxsize=1)
def sea_frames():
    base = Image.new("RGB", (128, 128), SKY)
    draw = ImageDraw.Draw(base)
    _cloud(draw, 3, 22, 34)
    _cloud(draw, 94, 14, 32)
    draw.rectangle((0, 58, 127, 63), fill=MIST)
    draw.line((0, 57, 127, 57), fill=CREAM)
    # A distant headland with a lighthouse.
    draw.polygon(((83, 62), (98, 55), (117, 52), (127, 54), (127, 66), (90, 66)), fill=STEEL)
    draw.polygon(((91, 60), (103, 53), (120, 51), (127, 53), (127, 57), (102, 58)), fill=FOREST)
    draw.line((102, 53, 119, 51, 127, 53), fill=GRASS, width=2)
    draw.polygon(((105, 37), (111, 37), (113, 55), (103, 55)), fill=CREAM, outline=SLATE)
    draw.polygon(((109, 39), (111, 39), (112, 54), (109, 54)), fill=MIST)
    draw.rectangle((105, 43, 111, 45), fill=CORAL)
    draw.rectangle((104, 50, 112, 52), fill=CORAL)
    draw.rectangle((106, 35, 110, 38), fill=LEMON, outline=SLATE)
    draw.polygon(((103, 34), (108, 31), (113, 34)), fill=BARK)
    draw.line((103, 39, 113, 39), fill=SLATE)
    # Persistent water planes; only their small crests colour-cycle.
    draw.rectangle((0, 64, 127, 127), fill=DEEP)
    for y, shift in ((65, 0), (69, 8), (73, -5)):
        for x in range(-10+shift, 128, 24):
            draw.line((x, y, x+14, y), fill=SKY)
    for pts in (
        ((0, 80), (19, 78), (43, 80), (65, 78), (89, 81), (127, 78), (127, 81), (85, 85), (43, 83), (0, 84)),
        ((0, 95), (22, 91), (49, 95), (77, 92), (106, 95), (127, 93), (127, 97), (94, 100), (61, 98), (28, 101), (0, 99)),
        ((0, 113), (27, 108), (56, 111), (83, 107), (111, 110), (127, 109), (127, 115), (101, 117), (70, 115), (41, 118), (0, 117)),
        ((0, 127), (24, 122), (49, 124), (76, 120), (107, 124), (127, 122), (127, 127)),
    ):
        draw.polygon(pts, fill=SKY)
    crests = ((4, 80, 17, 0), (53, 79, 21, 4), (96, 81, 21, 8),
              (15, 94, 20, 3), (71, 94, 27, 9), (106, 96, 15, 12),
              (4, 112, 29, 6), (55, 111, 20, 12), (96, 111, 27, 1),
              (19, 124, 26, 10), (79, 123, 29, 2))
    frames = []
    for frame in range(16):
        image = base.copy()
        d = ImageDraw.Draw(image)
        for x, y, length, offset in crests:
            for k in range(0, length, 4):
                color = WATER[(offset+k//4-frame) % len(WATER)]
                d.line((x+k, y, x+min(k+3, length-1), y), fill=color)
        phase = math.tau * frame / 16
        bob = round(math.sin(phase))
        # Sailboat: hull, mast, two sails and a short reflection.
        bx, by = 43, 93 + bob
        d.line((bx-16, by+5, bx+18, by+5), fill=SKY, width=2)
        d.polygon(((bx-15, by), (bx+16, by), (bx+10, by+6), (bx-10, by+6)), fill=WOOD, outline=BARK)
        d.line((bx-13, by+1, bx+13, by+1), fill=SAND)
        d.line((bx-9, by+4, bx+9, by+4), fill=CLAY)
        d.line((bx, by-30, bx, by), fill=BARK, width=2)
        d.polygon(((bx+2, by-29), (bx+2, by-3), (bx+19, by-3)), fill=CREAM, outline=SLATE)
        d.polygon(((bx+3, by-26), (bx+3, by-5), (bx+6, by-5)), fill=SNOW)
        d.line((bx+6, by-17, bx+11, by-8), fill=MIST)
        d.polygon(((bx-2, by-24), (bx-2, by-3), (bx-13, by-3)), fill=CREAM, outline=STEEL)
        d.line((bx-3, by-18, bx-3, by-5), fill=SNOW)
        d.polygon(((bx+1, by-30), (bx+9, by-29), (bx+1, by-27)), fill=CORAL)
        for ry in range(by + 6, by + 10, 2):
            d.line((bx-7+bob, ry, bx+6+bob, ry), fill=DEEP)
        # A gull glides in a slow loop.
        gx = 73 + round(3 * math.cos(phase))
        gy = 29 + round(math.sin(phase))
        wing = 1 if 4 <= frame < 12 else 0
        d.line(((gx-5, gy-wing), (gx-2, gy), (gx, gy+2), (gx+2, gy), (gx+5, gy-wing)), fill=CREAM)
        d.line((gx-1, gy+2, gx+1, gy+2), fill=BARK)
        frames.append(image)
    return timed(frames, 240)


# --- 4. Lemonade and the clock -------------------------------------------------------------

@lru_cache(maxsize=1)
def glass_sprite():
    sprite = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    # A tall tumbler, slightly narrower at the base.
    draw.polygon(((45, 58), (82, 58), (78, 103), (50, 103)), fill=MIST)
    draw.polygon(((48, 63), (79, 63), (76, 100), (52, 100)), fill=LEMON)
    draw.polygon(((73, 63), (79, 63), (76, 100), (71, 100)), fill=AMBER)
    draw.line((48, 63, 78, 63), fill=CREAM, width=2)
    # Straw sits behind the ice and enters the drink rather than floating on its rim.
    draw.line((56, 46, 60, 78), fill=CREAM, width=3)
    for y in range(48, 76, 6):
        x = 56 + (y-46)//8
        draw.line((x-1, y, x+1, y+1), fill=CORAL, width=2)
    for x, y in ((51, 67), (63, 71), (55, 82)):
        draw.polygon(((x, y+1), (x+7, y), (x+9, y+7), (x+2, y+9)), fill=CREAM)
        draw.polygon(((x+1, y+2), (x+6, y+1), (x+7, y+6), (x+2, y+7)), fill=MIST)
        draw.line((x+1, y+2, x+5, y+1), fill=SNOW)
        draw.line((x+3, y+6, x+6, y+5), fill=CREAM)
        draw.line((x+1, y+3, x+1, y+5), fill=ICE)
    draw.line((47, 64, 51, 98), fill=CREAM, width=2)
    draw.line((47, 68, 48, 77), fill=SNOW)
    draw.line((81, 64, 78, 99), fill=CREAM)
    draw.polygon(((50, 101), (78, 101), (77, 104), (51, 104)), fill=STEEL)
    draw.line((52, 102, 76, 102), fill=MIST)
    draw.ellipse((45, 55, 82, 61), fill=MIST, outline=CLAY)
    draw.ellipse((48, 56, 79, 59), fill=CREAM)
    draw.line((50, 59, 77, 59), fill=LEMON)
    draw.line((48, 56, 66, 56), fill=SNOW)
    # Lemon wheel on the rim and a striped straw.
    draw.ellipse((74, 48, 93, 67), fill=AMBER)
    draw.ellipse((76, 50, 91, 65), fill=CREAM)
    draw.ellipse((78, 52, 89, 63), fill=LEMON)
    for dx, dy in ((0, -6), (5, -3), (5, 3), (0, 6), (-5, 3), (-5, -3)):
        draw.line((84, 58, 84+dx, 58+dy), fill=CREAM)
    draw.rectangle((83, 57, 84, 58), fill=CREAM)
    draw.line((78, 50, 83, 49), fill=LEMON)
    return sprite


@lru_cache(maxsize=2)
def lemonade_frames_for(minute_key):
    now = minute_key * 60
    base = Image.new("RGB", (128, 128), PEACH)
    draw = ImageDraw.Draw(base)
    draw.rectangle((0, 0, 127, 43), fill=PEACH)
    # Side-wall shadow and a short reflected edge keep the room from glaring.
    draw.polygon(((0, 45), (9, 45), (29, 107), (0, 107)), fill=SAND)
    draw.line((10, 47, 28, 104), fill=CLAY)
    draw.line((35, 48, 92, 48), fill=CREAM)
    draw.line((38, 50, 66, 50), fill=SAND)
    draw.line((12, 44, 115, 44), fill=SAND)
    # Warm reflected window light: white is reserved for glass and ice highlights.
    draw.polygon(((104, 48), (116, 48), (97, 107), (85, 107)), fill=PEACH)
    draw.polygon(((106, 48), (112, 48), (93, 107), (87, 107)), fill=SAND)
    draw.polygon(((119, 48), (125, 48), (106, 107), (100, 107)), fill=PEACH)
    draw.rectangle((0, 108, 127, 127), fill=CLAY)
    draw.line((0, 108, 127, 108), fill=SAND, width=2)
    draw.line((0, 120, 127, 120), fill=WOOD)
    draw.line((23, 121, 23, 127), fill=WOOD)
    draw.line((96, 111, 113, 111), fill=SAND)
    draw.line((5, 116, 28, 116), fill=SAND)
    draw.ellipse((41, 104, 88, 112), fill=WOOD)
    draw.ellipse((44, 103, 85, 109), fill=SAND, outline=CLAY)
    # A small pot of mint balances the citrus on the right.
    draw.ellipse((13, 104, 36, 109), fill=WOOD)
    draw.polygon(((15, 95), (34, 95), (31, 105), (18, 105)), fill=CLAY, outline=WOOD)
    draw.line((16, 96, 32, 96), fill=SAND, width=2)
    for x, y, side in ((24, 94, -1), (25, 85, 1), (23, 81, -1)):
        draw.line((24, 97, x, y-6), fill=FOREST)
        draw.polygon(((x, y), (x+side*7, y-2), (x+side*9, y-6), (x+side*4, y-6)), fill=FOREST)
        draw.line((x+side*2, y-2, x+side*6, y-4), fill=GRASS, width=2)
    outlined(base, glass_sprite(), CLAY)
    local = time.localtime(now)
    centered(draw, time.strftime("%H:%M", local), 8, BARK, 3)
    centered(draw, f"{DAYS[local.tm_wday]} {local.tm_mday:02} {MONTHS[local.tm_mon - 1]}", 34, BARK)
    bubbles = ((55, 1), (68, 13), (73, 24), (61, 19))
    liquid = (tuple(bytes.fromhex(LEMON[1:])), tuple(bytes.fromhex(AMBER[1:])))
    frames = []
    for frame in range(16):
        image = base.copy()
        d = ImageDraw.Draw(image)
        for x, y in bubbles:
            by = 100 - (y + frame * 2) % 32
            # Full 32px cycle; entry and exit fade within the liquid. Ice occludes bubbles.
            if 70 <= by <= 98 and all(image.getpixel((px, py)) in liquid
                                      for px in (x, x+1) for py in (by, by+1)):
                d.rectangle((x, by, x+1, by+1), fill=AMBER if by > 95 or by < 73 else CREAM)
        frames.append(image)
    return timed(frames, 240)


def render_daylight(now: float | None = None, location=ISTANBUL) -> list[list[Image.Image]]:
    now = time.time() if now is None else now
    lat, lon = location
    return [sun_frames_for(int(now // 600), lat, lon), meadow_frames(), sea_frames(),
            lemonade_frames_for(int(now // 60)), knight_frames()]
