"""128x128 pixel-native retro panels, with no external font downloads."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import time
import unicodedata
from PIL import Image, ImageDraw
from .codex import Snapshot, Quota

# Five-column bitmap glyphs. Every stroke lands on a physical pixel.
GLYPHS = {
    "A":"01110/10001/10001/11111/10001/10001/10001", "B":"11110/10001/10001/11110/10001/10001/11110",
    "C":"01111/10000/10000/10000/10000/10000/01111", "D":"11110/10001/10001/10001/10001/10001/11110",
    "E":"11111/10000/10000/11110/10000/10000/11111", "F":"11111/10000/10000/11110/10000/10000/10000",
    "G":"01111/10000/10000/10111/10001/10001/01111", "H":"10001/10001/10001/11111/10001/10001/10001",
    "I":"11111/00100/00100/00100/00100/00100/11111", "J":"00111/00010/00010/00010/10010/10010/01100",
    "K":"10001/10010/10100/11000/10100/10010/10001", "L":"10000/10000/10000/10000/10000/10000/11111",
    "M":"10001/11011/10101/10101/10001/10001/10001", "N":"10001/11001/10101/10011/10001/10001/10001",
    "O":"01110/10001/10001/10001/10001/10001/01110", "P":"11110/10001/10001/11110/10000/10000/10000",
    "Q":"01110/10001/10001/10001/10101/10010/01101", "R":"11110/10001/10001/11110/10100/10010/10001",
    "S":"01111/10000/10000/01110/00001/00001/11110", "T":"11111/00100/00100/00100/00100/00100/00100",
    "U":"10001/10001/10001/10001/10001/10001/01110", "V":"10001/10001/10001/10001/10001/01010/00100",
    "W":"10001/10001/10001/10101/10101/10101/01010", "X":"10001/10001/01010/00100/01010/10001/10001",
    "Y":"10001/10001/01010/00100/00100/00100/00100", "Z":"11111/00001/00010/00100/01000/10000/11111",
    "0":"01110/10001/10011/10101/11001/10001/01110", "1":"00100/01100/00100/00100/00100/00100/01110",
    "2":"01110/10001/00001/00010/00100/01000/11111", "3":"11110/00001/00001/01110/00001/00001/11110",
    "4":"00010/00110/01010/10010/11111/00010/00010", "5":"11111/10000/10000/11110/00001/00001/11110",
    "6":"01110/10000/10000/11110/10001/10001/01110", "7":"11111/00001/00010/00100/01000/01000/01000",
    "8":"01110/10001/10001/01110/10001/10001/01110", "9":"01110/10001/10001/01111/00001/00001/01110",
    "%":"11001/11010/00010/00100/01000/01011/10011", ".":"00000/00000/00000/00000/00000/00110/00110",
    "-":"00000/00000/00000/11111/00000/00000/00000", ":":"00000/00100/00100/00000/00100/00100/00000",
    "/":"00001/00010/00010/00100/01000/01000/10000", "_":"00000/00000/00000/00000/00000/00000/11111",
    "+":"00000/00100/00100/11111/00100/00100/00000", ">":"10000/01000/00100/00010/00100/01000/10000",
    "?":"01110/10001/00001/00010/00100/00000/00100", " ":"00000/00000/00000/00000/00000/00000/00000",
}
# 11x11 agent marks, drawn on the same pixel grid as the font.
ICONS = {
    "claude": ("00000100000","01000100010","00100100100","00010101000","00001110000","11111111111",
               "00001110000","00010101000","00100100100","01000100010","00000100000"),
    "codex": ("11111111111","10000000001","10100000001","10010000001","10001000001","10010000001",
              "10100111001","10000000001","10000000001","10000000001","11111111111"),
}
# Busy agents animate their icon over this many frames of FRAME_MS each.
ICON_FRAMES = 8
BG = "#090f12"
MUTED = "#667e7f"
WHITE = "#dfebcf"
GREEN = "#a9e46d"
AMBER = "#ffbf69"
CYAN = "#7ed6cd"
RED = "#ff7f69"
LINE = "#253a3c"
FRAME_MS = 140
AGENTS = {"claude": ("CLAUDE", AMBER), "codex": ("CODEX", CYAN)}
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


@dataclass
class Board:
    claude: Snapshot = field(default_factory=lambda: Snapshot(provider="claude"))
    codex: Snapshot = field(default_factory=Snapshot)


def ascii_text(value: str) -> str:
    value = value.replace("ı", "i").replace("İ", "I")
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().upper()


def width(value: str, scale: int = 1) -> int:
    return max(0, len(ascii_text(value)) * 6 * scale - scale)


def bitmap(draw, rows, x, y, color, scale=1):
    for row, bits in enumerate(rows):
        for col, bit in enumerate(bits):
            if bit == "1":
                draw.rectangle((x+col*scale, y+row*scale, x+(col+1)*scale-1, y+(row+1)*scale-1), fill=color)


def text(draw: ImageDraw.ImageDraw, value: str, x: int, y: int, color=WHITE, scale=1):
    for char in ascii_text(value):
        bitmap(draw, GLYPHS.get(char, GLYPHS["?"]).split("/"), x, y, color, scale)
        x += 6 * scale


def centered(draw, value, y, color=WHITE, scale=1):
    text(draw, value, (128-width(value, scale))//2, y, color, scale)


def right(draw, value, x, y, color=WHITE, scale=1):
    text(draw, value, x-width(value, scale), y, color, scale)


def fit(value: str, maximum: int = 18) -> str:
    value = ascii_text(value)
    return value if len(value) <= maximum else value[:maximum-2] + ".."


def model_parts(value: str, provider: str) -> list[str]:
    model = ascii_text(value).replace("GPT-","GPT ")
    if provider == "claude":
        model = re.sub(r"^CLAUDE-([A-Z]+)-(?=\d)", r"\1 ", model)
        model = re.sub(r"-(\d{8})$", "", model).replace("[1M]", "")
        return [model.replace("-", "."), "CLAUDE CODE"]
    return model.split("-")


def panel(title, accent, footer="", status=""):
    image = Image.new("RGB", (128,128), BG)
    draw = ImageDraw.Draw(image)
    for y in range(24, 115, 4):
        draw.line((4,y,123,y), fill="#0b1417")
    draw.rectangle((2,2,125,125), outline=LINE)
    draw.rectangle((7,7,120,21), fill=accent)
    text(draw, title, 11, 11, BG)
    if status:
        right(draw, status, 117, 11, BG)
    draw.line((8,114,119,114), fill=LINE)
    text(draw, fit(footer, 16), 9, 119, MUTED)
    text(draw, "//", 108, 119, accent)
    return image, draw


def bar(draw, percent, y, color, height=7):
    filled = round(max(0,min(100,percent or 0))*18/100)
    for i in range(18):
        draw.rectangle((10+i*6,y,13+i*6,y+height-1),fill=color if i < filled else "#223438")


def level(percent):
    return RED if percent is not None and percent <= 10 else AMBER if percent is not None and percent <= 30 else GREEN


def shown(percent):
    return f"{round(percent)}%" if percent is not None else "--"


def reset_label(quota: Quota, now: float):
    if not quota.resets_at:
        return "RESET --"
    minutes = math.ceil(max(0,quota.resets_at-now)/60)
    days, rest = divmod(minutes,1440)
    hours, mins = divmod(rest,60)
    return f"RESET {days}D {hours}H" if days else f"RESET {hours}H {mins:02}M"


def quota_left(quota: Quota, now: float):
    return quota.remaining if quota.available(now) else None


def quota_note(quota: Quota, now: float):
    return reset_label(quota,now) if quota.available(now) else "AWAITING UPDATE" if quota.resets_at else "NO LIMIT DATA"


def clock(now: float, seconds=False):
    return time.strftime("%H:%M:%S" if seconds else "%H:%M", time.localtime(now))


def agent_state(snapshot: Snapshot, now: float):
    return "BUSY" if snapshot.state == "working" else "READY"


def agent_panel(snapshot: Snapshot, provider: str, now: float) -> Image.Image:
    name, accent = AGENTS[provider]
    active = bool(snapshot.session_id)
    image, draw = panel(name, accent, snapshot.repo if active else "NO SESSION", agent_state(snapshot, now))
    parts = model_parts(snapshot.model, provider)
    model = (parts[0] if provider == "claude" else " ".join(parts)) if active else "--"
    if width(model, 2) <= 108:
        centered(draw, model, 27, WHITE, 2)
    else:
        centered(draw, fit(model), 31, WHITE)
    effort = "--" if snapshot.effort == "UNKNOWN" else snapshot.effort
    text(draw, "EFFORT", 10, 46, MUTED)
    right(draw, fit(effort, 10), 118, 46, accent)
    draw.line((10,57,117,57), fill=LINE)
    context = snapshot.context_left
    color = MUTED if context is not None and now-snapshot.context_observed_at > 900 else level(context)
    text(draw, "CONTEXT", 10, 62, MUTED)
    right(draw, shown(context), 118, 62, color)
    bar(draw, context, 72, color, 5)
    left = quota_left(snapshot.five_hour, now)
    text(draw, "5H LIMIT", 10, 83, MUTED)
    right(draw, shown(left), 118, 83, level(left))
    bar(draw, left, 93, level(left), 5)
    centered(draw, quota_note(snapshot.five_hour, now), 103, MUTED)
    return image


def claude_icon(frame: int) -> list[str]:
    """The Claude spark shrinks and grows, like Claude Code's own spinner, while it works."""
    straight = (5,4,3,2,2,3,4,5)[frame]
    diagonal = (4,3,2,1,1,2,3,4)[frame]
    rows = [["0"]*11 for _ in range(11)]
    rows[5][5] = "1"
    for step in range(1,straight+1):
        for dy,dx in ((0,1),(0,-1),(1,0),(-1,0)):
            rows[5+dy*step][5+dx*step] = "1"
    for step in range(1,diagonal+1):
        for dy,dx in ((1,1),(1,-1),(-1,1),(-1,-1)):
            rows[5+dy*step][5+dx*step] = "1"
    return ["".join(row) for row in rows]


def codex_icon(frame: int) -> list[str]:
    """The Codex prompt blinks its cursor and types a line of output while it works."""
    rows = [list(row) for row in ICONS["codex"]]
    if frame >= ICON_FRAMES//2:
        rows[6][5:8] = "000"
    rows[8][2:2+frame] = "1"*frame
    return ["".join(row) for row in rows]


ICON_ANIMATIONS = {"claude": claude_icon, "codex": codex_icon}


def agents_panel(board: Board, now: float) -> list[Image.Image]:
    states={key:agent_state(getattr(board,key),now) for key in ("claude","codex")}
    count=ICON_FRAMES if "BUSY" in states.values() else 1
    frames=[]
    for frame in range(count):
        image,draw=panel("AGENTS",GREEN,"LOCAL STATUS")
        for index,(key,state) in enumerate(states.items()):
            name,accent=AGENTS[key]
            top=27+index*44
            draw.rectangle((8,top,119,top+38),outline=LINE)
            icon=ICON_ANIMATIONS[key](frame) if state=="BUSY" else ICONS[key]
            bitmap(draw,icon,13,top+8,accent,2)
            text(draw,name,43,top+7,accent)
            right(draw,state,114,top+23,AMBER if state=="BUSY" else GREEN)
        frames.append(image)
    return frames


def week_panel(board: Board, now: float) -> Image.Image:
    image, draw = panel("WEEKLY", GREEN, "WEEK LIMIT LEFT")
    local = time.localtime(now)
    centered(draw, clock(now), 27, WHITE, 3)
    centered(draw, f"{DAYS[local.tm_wday]} {local.tm_mday:02} {MONTHS[local.tm_mon-1]}", 52, MUTED)
    draw.line((10,64,117,64), fill=LINE)
    for i, key in enumerate(("claude", "codex")):
        name, accent = AGENTS[key]
        left = quota_left(getattr(board, key).weekly, now)
        y = 69 + i*20
        text(draw, name, 10, y, accent)
        right(draw, shown(left), 118, y, level(left))
        bar(draw, left, y+10, level(left), 5)
    return image


# The fourth WORK screen rotates through scenes, picked by whether the sun is up where you are.
SCENE_MINUTES = 20


def scene_panel(now: float, location) -> list[Image.Image]:
    # Imported here: the scene modules use this module's font helpers.
    from . import daylight, night
    lat, lon = location
    try:
        rise, sets, _ = daylight.sun_day(daylight.local_midnight(now), lat, lon)
    except (OverflowError, OSError, ValueError):
        # Windows mktime rejects dates before 1970 local time; the elevation alone still answers.
        rise = sets = None
    sun_up = rise <= now < sets if rise and sets else daylight.solar_elevation(now, lat, lon) > 0
    # Scenes with their own clock are left out: the WEEKLY screen already shows the time.
    if sun_up:
        pool = (daylight.knight_frames, daylight.meadow_frames, daylight.sea_frames)
    else:
        pool = (night.campfire_frames_cached, night.rain_frames_cached,
                lambda: night.moon_frames_for(int(now // 3600)), night.cat_frames)
    return pool[int(now // (SCENE_MINUTES * 60)) % len(pool)]()


def render(board: Board, now: float | None = None, location=(41.01, 28.98)) -> list[list[Image.Image]]:
    """Five panels as frame lists: agents, Claude, Codex, a scene for the time of day, weekly limits."""
    now = time.time() if now is None else now
    return [agents_panel(board, now), [agent_panel(board.claude, "claude", now)],
            [agent_panel(board.codex, "codex", now)], scene_panel(now, location), [week_panel(board, now)]]


def overview(panels: list[list[Image.Image]], scale=4) -> Image.Image:
    result = Image.new("RGB",(5*128+4*12+24,160),"#071013")
    for i,frames in enumerate(panels):
        result.paste(frames[0],(12+i*140,16))
    return result.resize((result.width*scale,result.height*scale),Image.Resampling.NEAREST)
