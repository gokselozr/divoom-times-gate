"""Game mode: detect what is being played and draw an arcade-style dashboard around it."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import io
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

from . import pixel as _palette
from .pixel import (AMBER, BARK, CLAY, CORAL, CREAM, DEEP, EMBER, FOG, GRASS, INK, LEAF, LEMON, MIST, NAVY, RUST,
                    SKY, SLATE, STEEL, WOOD, timed)
from .render import GLYPHS as _glyphs
from .render import ascii_text, centered, right, text

LEAF = "#63c74d"
SKY = "#0099db"
TITLES = ("CARTRIDGE", "SESSION", "HEALTH", "RIG", "ARCADE")
# Paths that only ever hold games, whether or not they run fullscreen.
GAME_FOLDERS = ("steamapps\\common", "epic games", "riot games", "ubisoft game launcher\\games",
                "xboxgames", "gog galaxy\\games", "ea games", "battle.net\\games")
NOT_GAMES = {"explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
             "vlc.exe", "mpc-hc64.exe", "mpc-be64.exe", "potplayermini64.exe", "applicationframehost.exe",
             "searchhost.exe", "shellexperiencehost.exe", "lockapp.exe", "teams.exe", "ms-teams.exe",
             "zoom.exe", "powerpnt.exe", "timesgate.exe", "code.exe", "windowsterminal.exe", "steam.exe",
             "steamwebhelper.exe", "epicgameslauncher.exe", "discord.exe", "spotify.exe",
             # Fullscreen video, chat and office apps are the usual false positives.
             "vivaldi.exe", "arc.exe", "yandex.exe", "mpv.exe", "potplayer.exe", "potplayer64.exe",
             "potplayermini.exe", "kmplayer.exe", "kmplayer64x.exe", "smplayer.exe", "wmplayer.exe",
             "video.ui.exe", "microsoft.media.player.exe", "netflix.exe", "disneyplus.exe", "primevideo.exe",
             "plex.exe", "stremio.exe", "obs64.exe", "whatsapp.exe", "telegram.exe", "slack.exe", "notion.exe",
             "winword.exe", "excel.exe", "acrobat.exe", "acrord32.exe", "photos.exe", "microsoft.photos.exe",
             "snippingtool.exe", "screenclippinghost.exe", "mstsc.exe", "vmconnect.exe"}


@dataclass
class GameSnapshot:
    name: str = ""
    source: str = ""
    started_at: float = 0.0
    icon: bytes = b""
    cover: bytes = b""
    cpu: float | None = None
    ram: float | None = None
    # Steam's own playtime for this game before the current session, in minutes.
    played_minutes: int = 0


def png(image):
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


# --- Windows probes ------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import winreg

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + \
                   [(name, ctypes.c_ulonglong) for name in ("total", "avail", "pagetotal", "pageavail",
                                                             "virtualtotal", "virtualavail", "extended")]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", ctypes.c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(RECT))
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetIconInfo.argtypes = (wintypes.HICON, ctypes.POINTER(ICONINFO))
    user32.DestroyIcon.argtypes = (wintypes.HICON,)
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD))
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetSystemTimes.argtypes = (ctypes.POINTER(wintypes.FILETIME),) * 3
    kernel32.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(MEMORYSTATUSEX),)
    shell32.ExtractIconExW.argtypes = (wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.HICON),
                                       ctypes.POINTER(wintypes.HICON), wintypes.UINT)
    gdi32.GetObjectW.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p)
    gdi32.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.c_void_p, wintypes.UINT)
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)

    QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    STILL_ACTIVE = 259

    def filetime(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    def process_info(pid):
        """Executable path and start time (unix seconds) of a process, or None once it exited."""
        handle = kernel32.OpenProcess(QUERY, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != STILL_ACTIVE:
                return None
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            kernel32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
            started = (filetime(times[0]) - 116444736000000000) / 1e7
            return buf.value, started
        finally:
            kernel32.CloseHandle(handle)

    def foreground():
        """(pid, title, fullscreen) of the foreground window."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        rect, info = RECT(), MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
        m = info.rcMonitor
        full = rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
        return pid.value, title.value, full

    def exe_icon(path):
        """The executable's large icon as PNG bytes."""
        large = wintypes.HICON()
        if shell32.ExtractIconExW(path, 0, ctypes.byref(large), None, 1) < 1 or not large:
            return b""
        info = ICONINFO()
        try:
            if not user32.GetIconInfo(large, ctypes.byref(info)) or not info.hbmColor:
                return b""
            bitmap = BITMAP()
            gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bitmap))
            w, h = bitmap.bmWidth, bitmap.bmHeight
            header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                                      biPlanes=1, biBitCount=32)
            buf = ctypes.create_string_buffer(w * h * 4)
            dc = user32.GetDC(None)
            gdi32.GetDIBits(dc, info.hbmColor, 0, h, buf, ctypes.byref(header), 0)
            user32.ReleaseDC(None, dc)
            image = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)
            if not image.getchannel("A").getbbox():
                # Old icons carry no alpha; treat them as fully opaque.
                image.putalpha(255)
            return png(image)
        finally:
            for handle in (info.hbmColor, info.hbmMask):
                if handle:
                    gdi32.DeleteObject(handle)
            user32.DestroyIcon(large)

    def system_times():
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        return filetime(idle), filetime(kernel) + filetime(user)

    def memory_load():
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return float(status.dwMemoryLoad)

    def steam_folder():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                return Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            return None

    def steam_running():
        """(app id, name, steam folder) of the game Steam reports as running."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                app = int(winreg.QueryValueEx(key, "RunningAppID")[0] or 0)
                folder = Path(winreg.QueryValueEx(key, "SteamPath")[0])
            if not app:
                return None
            name = ""
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Valve\Steam\Apps\{app}") as key:
                    name = winreg.QueryValueEx(key, "Name")[0]
            except OSError:
                pass
            return app, name or f"STEAM {app}", folder
        except (OSError, ValueError):
            return None
else:
    def process_info(pid):
        return None

    def foreground():
        return None

    def exe_icon(path):
        return b""

    def system_times():
        return 0, 0

    def memory_load():
        return None

    def steam_running():
        return None

    def steam_folder():
        return None


def parse_vdf(source):
    """Steam's text KeyValues format: quoted keys, quoted values or nested braces."""
    import re
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', source)
    position = 0

    def block():
        nonlocal position
        result = {}
        while position < len(tokens):
            word, brace = tokens[position]
            position += 1
            if brace == "}":
                return result
            if position < len(tokens) and tokens[position][1] == "{":
                position += 1
                result[word.lower()] = block()
            elif position < len(tokens):
                result[word.lower()] = tokens[position][0].replace("\\\\", "\\")
                position += 1
        return result

    return block()


def active_steam_user(folder):
    """The logged-in account's userdata folder, falling back to the most recently used one."""
    if sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
                user = int(winreg.QueryValueEx(key, "ActiveUser")[0] or 0)
            if user and (folder / "userdata" / str(user)).is_dir():
                return folder / "userdata" / str(user)
        except (OSError, ValueError):
            pass
    users = [path for path in (folder / "userdata").glob("*") if path.name.isdigit()]
    return max(users, key=lambda path: path.stat().st_mtime, default=None)


def steam_playtime(folder, app):
    """Minutes Steam has recorded for an app in localconfig.vdf; read once per session."""
    user = active_steam_user(folder)
    if user is None:
        return 0
    try:
        config = parse_vdf((user / "config" / "localconfig.vdf").read_text(encoding="utf-8", errors="replace"))
        apps = config["userlocalconfigstore"]["software"]["valve"]["steam"]["apps"]
        return int(apps.get(str(app), {}).get("playtime", 0))
    except (OSError, KeyError, TypeError, ValueError):
        return 0


def steam_installs(folder):
    """Install folder name (lower case) -> (app id, name) across every Steam library."""
    libraries = [folder]
    try:
        data = parse_vdf((folder / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
        libraries += [Path(entry["path"]) for entry in data.get("libraryfolders", {}).values()
                      if isinstance(entry, dict) and "path" in entry]
    except OSError:
        pass
    installs = {}
    for library in dict.fromkeys(libraries):
        for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
            try:
                state = parse_vdf(manifest.read_text(encoding="utf-8", errors="replace"))["appstate"]
                installs[state["installdir"].lower()] = (int(state["appid"]), state.get("name", ""))
            except (OSError, KeyError, ValueError):
                continue
    return installs


def xbox_details(path):
    """Name, icon and square logo from an Xbox / Game Pass game's MicrosoftGame.config."""
    from xml.etree import ElementTree
    folder = Path(path).parent
    for candidate in (folder, *list(folder.parents)[:2]):
        config = candidate / "MicrosoftGame.config"
        if not config.is_file():
            continue
        try:
            root = ElementTree.parse(config).getroot()
        except (OSError, ElementTree.ParseError):
            return None
        visuals = next((e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "ShellVisuals"), None)
        if visuals is None:
            return None

        def art(key):
            try:
                with Image.open(candidate / visuals.get(key, "")) as image:
                    return png(image.convert("RGBA"))
            except (OSError, ValueError):
                return b""
        return (visuals.get("DefaultDisplayName", ""), art("Square44x44Logo") or art("StoreLogo"),
                art("Square150x150Logo"))
    return None


def steam_art(folder, app):
    """Steam's cached 32x32 community icon and portrait cover for an app, as PNG bytes."""
    cache = folder / "appcache" / "librarycache"
    icon = cover = b""
    candidates = list((cache / str(app)).glob("*.jpg")) + [cache / f"{app}_icon.jpg"]
    for path in candidates:
        try:
            with Image.open(path) as image:
                if image.size == (32, 32):
                    icon = png(image.convert("RGBA"))
                    break
        except OSError:
            continue
    for path in (cache / str(app) / "library_600x900.jpg", cache / f"{app}_library_600x900.jpg"):
        try:
            with Image.open(path) as image:
                cover = png(image.convert("RGB"))
                break
        except OSError:
            continue
    return icon, cover


class GameReader:
    def __init__(self):
        self.cpu_last = None
        self.seen = {}
        self.window_game = None
        self.installs = None

    def system(self):
        idle, total = system_times()
        cpu = None
        if self.cpu_last and total > self.cpu_last[1]:
            cpu = max(0.0, min(100.0, 100 * (1 - (idle - self.cpu_last[0]) / (total - self.cpu_last[1]))))
        self.cpu_last = (idle, total)
        return cpu, memory_load()

    def poll(self):
        snapshot = GameSnapshot()
        snapshot.cpu, snapshot.ram = self.system()
        steam = steam_running()
        if steam:
            app, name, folder = steam
            key = f"steam:{app}"
            if key not in self.seen:
                self.seen = {key: (time.time(), *steam_art(folder, app), steam_playtime(folder, app))}
            started, snapshot.icon, snapshot.cover, snapshot.played_minutes = self.seen[key]
            snapshot.name, snapshot.source, snapshot.started_at = name, "steam", started
            return snapshot
        game = self.window()
        if game:
            (snapshot.name, snapshot.source, snapshot.started_at, snapshot.icon,
             snapshot.cover, snapshot.played_minutes) = game
        return snapshot

    def window(self):
        if self.window_game:
            pid, *game = self.window_game
            # A game keeps its session while alt-tabbed, until its process exits.
            if process_info(pid):
                return tuple(game)
            self.window_game = None
        front = foreground()
        if not front:
            return None
        pid, title, full = front
        info = process_info(pid)
        if not info:
            return None
        path, started = info
        lower = path.lower()
        exe = lower.rsplit("\\", 1)[-1]
        if exe in NOT_GAMES or not (full or any(folder in lower for folder in GAME_FOLDERS)):
            return None
        self.window_game = (pid, *self.describe(path, title, started))
        return self.window_game[1:]

    def describe(self, path, title, started):
        """Prefer launcher data over the window: Steam history and art, or Xbox logos."""
        lower = path.lower()
        folder = steam_folder()
        if folder and "steamapps\\common\\" in lower:
            if self.installs is None:
                self.installs = steam_installs(folder)
            installdir = lower.split("steamapps\\common\\", 1)[1].split("\\", 1)[0]
            if installdir in self.installs:
                app, name = self.installs[installdir]
                icon, cover = steam_art(folder, app)
                return (name or title, "steam", started, icon or exe_icon(path), cover,
                        steam_playtime(folder, app))
        xbox = xbox_details(path)
        if xbox:
            name, icon, cover = xbox
            return (name or title, "xbox", started, icon or exe_icon(path), cover, 0)
        return (title.strip() or Path(path).stem, "window", started, exe_icon(path), b"", 0)


# --- Panels --------------------------------------------------------------------------------


def frame_box(draw, accent):
    """Stepped metal rim: broad corner clusters, a quiet accent, no neon outline."""
    draw.polygon(((5, 1), (122, 1), (126, 5), (126, 122), (122, 126),
                  (5, 126), (1, 122), (1, 5)), fill=NAVY)
    draw.line((5, 2, 122, 2), fill=STEEL, width=2)
    draw.line((2, 5, 2, 121), fill=SLATE, width=2)
    draw.line((125, 6, 125, 121), fill=BARK, width=2)
    draw.line((6, 125, 121, 125), fill=BARK, width=2)
    # The interior stays dark, with four steel corner fasteners.
    draw.rectangle((5, 5, 122, 122), fill=INK)
    for x, y in ((5, 5), (120, 5), (5, 120), (120, 120)):
        draw.rectangle((x, y, x + 2, y + 2), fill=STEEL)
    draw.rectangle((9, 3, 30, 4), fill=accent)
    draw.rectangle((33, 3, 39, 4), fill=SLATE)


def _face(accent):
    image = Image.new("RGB", (128, 128), INK)
    frame_box(ImageDraw.Draw(image), accent)
    return image


_ART_COLORS = tuple(value for key, value in vars(_palette).items()
                    if key.isupper() and isinstance(value, str) and value.startswith("#"))


def _art_palette(colors):
    palette = Image.new("P", (1, 1))
    rgb = [tuple(bytes.fromhex(color[1:])) if isinstance(color, str) else color for color in colors]
    rgb += [rgb[-1]] * (256 - len(rgb))
    palette.putpalette([channel for color in rgb for channel in color])
    return palette


@lru_cache(maxsize=8)
def pixel_art(data: bytes, size: tuple[int, int], colors: int = 16):
    """Fit real art, retaining its aspect and alpha, into ENDESGA colour clusters."""
    w, h = size
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGBA")
        scale = min(w / image.width, h / image.height)
        fitted = (max(1, min(w, round(image.width * scale))),
                  max(1, min(h, round(image.height * scale))))
        image = image.resize(fitted, Image.Resampling.BOX)
        # Composite after shrinking to avoid an original-size temporary image.
        background = Image.new("RGBA", fitted, INK)
        image = Image.alpha_composite(background, image).convert("RGB")
        image = image.quantize(palette=_art_palette(_ART_COLORS), dither=Image.Dither.NONE)
        # Limit colours using only members of ENDESGA, never photo-derived averages.
        count = max(2, min(len(_ART_COLORS), int(colors)))
        popular = sorted(image.getcolors(), reverse=True)
        if len(popular) > count:
            source_palette = image.getpalette()
            selected = [tuple(source_palette[index * 3:index * 3 + 3]) for _, index in popular[:count]]
            image = image.convert("RGB").quantize(palette=_art_palette(selected), dither=Image.Dither.NONE)
        result = Image.new("RGB", size, INK)
        result.paste(image.convert("RGB"), ((w - fitted[0]) // 2, (h - fitted[1]) // 2))
        return result
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return placeholder_art("?", size)


def _label(value):
    return "".join(char if char in _glyphs else " " for char in ascii_text(value))


def initials(name):
    words = [word for word in _label(name).split() if word[:1].isalnum()]
    return "".join(word[0] for word in words[:2]) or "?"


def placeholder_art(name, size):
    """A physical label with quiet diagonal hatch and legible initials."""
    w, h = size
    image = Image.new("RGB", size, NAVY)
    draw = ImageDraw.Draw(image)
    # Hatch only at the edges; don't run busy stripes through the initials.
    for x in range(-h, w, 10):
        draw.line((x, h - 1, x + h, 0), fill=SLATE, width=2)
    letters = initials(name)
    scale = min(3, max(1, min((w - 4) // (6 * len(letters)), (h - 4) // 7)))
    span = len(letters) * 6 * scale - scale
    x, y = (w - span) // 2, (h - 7 * scale) // 2
    draw.rectangle((x - 2, y - 3, x + span + 1, y + 7 * scale + 2), fill=NAVY)
    text(draw, letters, x, y, LEMON, scale)
    return image


def wrap(name, limit, lines):
    """Bound every line, including long first words; mark omitted title text."""
    words = _label(name).split()
    out = []
    while words and len(out) < lines:
        line = words.pop(0)
        if len(line) > limit:
            words.insert(0, line[limit:])
            line = line[:limit]
        while words and len(line) + 1 + len(words[0]) <= limit:
            line += " " + words.pop(0)
        out.append(line)
    if words and out:
        out[-1] = out[-1][:max(0, limit - 2)].rstrip() + ".."
    return out


def cartridge_panel(game: GameSnapshot):
    base = _face(AMBER)
    draw = ImageDraw.Draw(base)
    # Low brass cradle grounds the silhouette; loaded labels never animate.
    draw.polygon(((12, 87), (19, 80), (109, 80), (116, 87), (116, 103),
                  (12, 103)), fill=BARK)
    draw.rectangle((15, 94, 112, 102), fill=WOOD)
    draw.line((16, 94, 111, 94), fill=CLAY, width=2)
    if game.name:
        # Chamfered upper corners, grip ridges, left light and a deep right side.
        draw.polygon(((23, 10), (101, 10), (108, 17), (108, 102), (19, 102),
                      (19, 16)), fill=SLATE)
        draw.polygon(((24, 12), (100, 12), (104, 16), (104, 100), (22, 100),
                      (22, 16)), fill=STEEL)
        draw.line((24, 12, 99, 12), fill=MIST, width=2)
        draw.line((22, 17, 22, 97), fill=FOG, width=2)
        draw.rectangle((55, 10, 73, 16), fill=INK)
        draw.line((55, 17, 73, 17), fill=SLATE, width=2)
        draw.line((29, 16, 50, 16), fill=SLATE, width=2)
        draw.line((78, 16, 98, 16), fill=SLATE, width=2)
        for y in range(25, 96, 8):
            draw.rectangle((23, y, 25, y + 3), fill=SLATE)
            draw.rectangle((102, y, 104, y + 3), fill=NAVY)
        draw.rectangle((27, 20, 100, 100), fill=INK)
        draw.line((28, 19, 99, 19), fill=SLATE)
        draw.line((29, 28, 29, 91), fill=BARK)
        draw.line((98, 28, 98, 91), fill=BARK)
        if game.cover:
            # A portrait fits in a 2px logical grid; Xbox's square fits as a square.
            art = pixel_art(game.cover, (36, 40), 20).resize((72, 80), Image.Resampling.NEAREST)
        elif game.icon:
            art = pixel_art(game.icon, (32, 32), 20).resize((64, 64), Image.Resampling.NEAREST)
        else:
            art = placeholder_art(game.name, (72, 80))
        base.paste(art, ((128 - art.width) // 2, 21 + (80 - art.height) // 2))
        # Two footer lines preserve useful words of the actual title.
        for i, line in enumerate(wrap(game.name, 18, 2) or [initials(game.name)]):
            centered(draw, line, 105 + i * 10, CREAM)
        return timed([base], 1000)

    # No game: an empty recessed slot, rather than a fake cartridge.
    draw.polygon(((20, 31), (105, 31), (113, 39), (113, 86), (14, 86),
                  (14, 39)), fill=SLATE)
    draw.polygon(((22, 33), (104, 33), (109, 39), (109, 81), (18, 81),
                  (18, 39)), fill=STEEL)
    draw.line((23, 34, 103, 34), fill=FOG, width=2)
    draw.rectangle((25, 42, 102, 72), fill=BARK)
    draw.rectangle((27, 44, 100, 67), fill=INK)
    draw.line((29, 69, 98, 69), fill=WOOD, width=2)
    for x in range(35, 95, 8):
        draw.rectangle((x, 70, x + 3, 72), fill=CLAY)
    draw.rectangle((30, 78, 46, 79), fill=SLATE)
    draw.rectangle((81, 78, 97, 79), fill=SLATE)
    centered(draw, "INSERT", 103, LEMON)
    centered(draw, "NO GAME", 114, FOG)
    frames = []
    for shift in (0, 0, 1, 1, 0, 0, -1, -1):
        image = base.copy()
        d = ImageDraw.Draw(image)
        y = 16 + shift
        d.rectangle((61, y, 66, y + 6), fill=AMBER)
        d.polygon(((57, y + 5), (70, y + 5), (66, y + 9), (61, y + 9)), fill=AMBER)
        d.rectangle((61, y, 64, y + 2), fill=LEMON)
        frames.append(image)
    return timed(frames, 300)


def gamepad(draw, x, y):
    """Compact pad with a stepped silhouette, two grips and shaded controls."""
    outline = ((x + 7, y), (x + 45, y), (x + 50, y + 5), (x + 55, y + 25),
               (x + 52, y + 33), (x + 44, y + 33), (x + 36, y + 24),
               (x + 16, y + 24), (x + 8, y + 33), (x, y + 33),
               (x - 3, y + 26), (x + 2, y + 6))
    draw.polygon(outline, fill=BARK)
    draw.polygon(tuple((px, py - 2) for px, py in outline), fill=STEEL)
    draw.polygon(((x + 8, y), (x + 44, y), (x + 48, y + 5), (x + 51, y + 19),
                  (x + 44, y + 27), (x + 35, y + 20), (x + 17, y + 20),
                  (x + 6, y + 27), (x + 1, y + 21), (x + 4, y + 6)), fill=FOG)
    draw.line((x + 9, y, x + 43, y), fill=MIST, width=2)
    draw.rectangle((x + 7, y + 8, x + 21, y + 12), fill=SLATE)
    draw.rectangle((x + 12, y + 3, x + 16, y + 17), fill=SLATE)
    draw.rectangle((x + 9, y + 8, x + 19, y + 10), fill=INK)
    draw.rectangle((x + 12, y + 5, x + 14, y + 15), fill=INK)
    draw.rectangle((x + 35, y + 5, x + 41, y + 11), fill=RUST)
    draw.rectangle((x + 35, y + 5, x + 39, y + 9), fill=EMBER)
    draw.rectangle((x + 43, y + 12, x + 49, y + 18), fill=WOOD)
    draw.rectangle((x + 43, y + 12, x + 47, y + 16), fill=AMBER)
    draw.rectangle((x + 24, y + 12, x + 30, y + 14), fill=SLATE)
    draw.line((x + 6, y + 23, x + 10, y + 20), fill=MIST, width=2)


def _minutes(game, now):
    return max(0, int((now - game.started_at) // 60)) if game.name and game.started_at > 0 else 0


def _big_text(draw, value, y, color, maximum=108):
    if len(value) * 6 - 1 > maximum:
        value = "OVERFLOW"
    scale = max(1, min(3, maximum // max(1, len(value) * 6 - 1)))
    centered(draw, value, y, color, scale)


def session_panel(game: GameSnapshot, now: float):
    base = _face(SKY)
    draw = ImageDraw.Draw(base)
    if not game.name:
        text(draw, "PLAYER 1", 10, 10, FOG)
        # Coiled lead, table shadow and grouped light give the pad a setting.
        draw.line(((65, 20), (65, 26), (73, 26), (73, 32), (65, 32), (65, 40)), fill=SLATE, width=3)
        draw.rectangle((34, 75, 92, 78), fill=NAVY)
        draw.rectangle((42, 79, 83, 80), fill=BARK)
        centered(draw, "PRESS START", 91, CREAM)
        centered(draw, "READY", 107, SKY)
        frames = []
        for shift in (0, 0, 1, 1, 0, 0, -1, -1):
            image = base.copy()
            gamepad(ImageDraw.Draw(image), 38, 42 + shift)
            frames.append(image)
        return timed(frames, 350)

    text(draw, "NOW PLAYING", 10, 10, FOG)
    draw.rectangle((8, 23, 39, 54), fill=SLATE)
    art = pixel_art(game.icon, (28, 28), 20) if game.icon else placeholder_art(game.name, (28, 28))
    base.paste(art, (10, 25))
    for i, line in enumerate(wrap(game.name, 12, 3) or [initials(game.name)]):
        text(draw, line, 44, 24 + i * 10, CREAM)
    draw.line((10, 59, 117, 59), fill=SLATE)
    minutes = _minutes(game, now)
    hours, rest = divmod(minutes, 60)
    timer = f"{hours}:{rest:02}" if game.started_at > 0 else "--:--"
    _big_text(draw, timer, 66, CREAM)
    # Zero is also the detector's unavailable-history sentinel. Keep it unknown.
    known = game.source.lower() == "steam" and game.played_minutes > 0
    if known:
        level, progress = divmod(game.played_minutes + minutes, 60)
        caption = f"LVL {level}"
        xp_label = f"TOTAL XP {progress}/60"
        scale = 1
        if len(caption) * 6 - 1 <= 108:
            text(draw, caption, 10, 95, LEAF, scale)
            history_label = f"{level}H PLAYED"
            if len(caption) * 6 + len(history_label) * 6 <= 102:
                right(draw, history_label, 118, 95, FOG)
            else:
                # Still state the truthful total when two labels no longer fit.
                xp_label = history_label
        else:
            centered(draw, "LVL TOO LARGE", 95, FOG)
            xp_label = "HISTORY TOO LARGE"
    else:
        progress = rest
        text(draw, "LVL --", 10, 95, FOG)
        right(draw, "UNKNOWN", 118, 95, STEEL)
        xp_label = f"SESSION XP {progress}/60"
    for i in range(18):
        x = 10 + i * 6
        draw.rectangle((x, 107, x + 3, 113), fill=LEAF if i < progress * 18 // 60 else NAVY)
    centered(draw, xp_label, 116, FOG)
    return timed([base], 1000)


HEART = ("01110001110", "11111011111", "11111111111", "11111111111", "11111111111",
         "01111111110", "00111111100", "00011111000", "00001110000", "00000100000")


def heart(image, x, y, fill, beat=False):
    """Two-pixel heart clusters, shaded feet and visible empty containers."""
    draw = ImageDraw.Draw(image)
    for row, bits in enumerate(HEART):
        for col, bit in enumerate(bits):
            if bit != "1":
                continue
            full = fill >= 1 or (fill >= 0.5 and col <= 5)
            edge = (row == 0 or col == 0 or col == 10 or row == len(HEART) - 1
                    or (row > 0 and HEART[row - 1][col] == "0")
                    or (row + 1 < len(HEART) and HEART[row + 1][col] == "0"))
            color = (CORAL if row < 2 else RUST if row >= 6 else EMBER) if full else (STEEL if edge else NAVY)
            draw.rectangle((x + col * 2, y + row * 2, x + col * 2 + 1, y + row * 2 + 1), fill=color)
    if fill > 0:
        draw.rectangle((x + 4, y + 2, x + 7, y + 3), fill=CREAM if beat else CORAL)
        draw.rectangle((x + 2, y + 4, x + 3, y + 7), fill=CORAL)


def _recovery(draw, y, shift=0):
    """A small glass of water on a brass coaster, with a closed 1px glint."""
    draw.rectangle((92, y + 25, 120, y + 27), fill=BARK)
    draw.rectangle((90, y + 23, 118, y + 25), fill=WOOD)
    draw.line((92, y + 23, 116, y + 23), fill=CLAY, width=2)
    draw.polygon(((94, y), (115, y), (113, y + 22), (97, y + 22)), fill=STEEL)
    draw.polygon(((97, y + 3), (112, y + 3), (110, y + 20), (99, y + 20)), fill=NAVY)
    draw.polygon(((98, y + 10), (111, y + 10), (110, y + 20), (99, y + 20)), fill=DEEP)
    draw.line((99, y + 11, 110, y + 11), fill=SKY, width=2)
    draw.line((96, y + 2, 113, y + 2), fill=MIST, width=2)
    draw.rectangle((97, y + 5 + shift, 98, y + 14 + shift), fill=FOG)
    draw.rectangle((101, y + 18, 108, y + 19), fill=SKY)


def health_panel(game: GameSnapshot, now: float):
    minutes = _minutes(game, now)
    # Eight half-hearts over one hour; no invented recovery while still playing.
    unknown_start = bool(game.name) and game.started_at <= 0
    halves = 0 if unknown_start else max(0, 8 - int(minutes / 7.5)) if game.name else 8
    frames = []
    for phase, shift in enumerate((0, 0, 1, 1, 0, 0, -1, -1)):
        image = _face(EMBER)
        draw = ImageDraw.Draw(image)
        text(draw, "HEALTH", 10, 10, FOG)
        # A visible shelf under four containers unifies their outlines.
        draw.rectangle((10, 52, 117, 54), fill=BARK)
        for i in range(4):
            fill = min(1, max(0, (halves - i * 2) / 2))
            heart(image, 11 + i * 27, 30, fill, phase in (2, 3) and i == (halves - 1) // 2)
        draw = ImageDraw.Draw(image)
        if not game.name:
            centered(draw, "FULL HP", 67, LEAF, 2)
            centered(draw, "READY TO PLAY", 95, CREAM)
            centered(draw, "REST EVERY HOUR", 110, FOG)
        elif unknown_start:
            centered(draw, "SESSION --", 70, CREAM)
            centered(draw, "START UNKNOWN", 91, FOG)
            centered(draw, "REST EVERY HOUR", 110, FOG)
        elif minutes < 60:
            centered(draw, "BREAK IN", 66, FOG)
            centered(draw, f"{60 - minutes}M", 81, CREAM, 3)
            centered(draw, "REST EVERY HOUR", 111, FOG)
        else:
            text(draw, "TAKE A", 12, 63, LEMON, 2)
            text(draw, "BREAK", 18, 81, CREAM, 2)
            _recovery(draw, 66, shift)
            centered(draw, "STRETCH + WATER", 110, CREAM)
        frames.append(image)
    return timed(frames, 350)


def _load(value):
    if value is None or not math.isfinite(value):
        return None
    return max(0, min(100, round(value)))


def meter(draw, label, value, y):
    value = _load(value)
    text(draw, label, 12, y, MIST)
    right(draw, "--" if value is None else f"{value}%", 116, y - 3, CREAM, 2)
    draw.rectangle((10, y + 14, 117, y + 33), fill=BARK)
    draw.line((11, y + 14, 116, y + 14), fill=SLATE)
    # Fractional last segment preserves 1% loads without inventing a whole bar.
    pixels = 0 if value is None else round(value * 84 / 100)
    for i in range(14):
        color = GRASS if i < 8 else AMBER if i < 11 else EMBER
        highlight = LEAF if i < 8 else LEMON if i < 11 else CORAL
        x = 12 + i * 15 // 2
        draw.rectangle((x, y + 17, x + 5, y + 30), fill=NAVY)
        amount = max(0, min(6, pixels - i * 6))
        if amount:
            draw.rectangle((x, y + 18, x + amount - 1, y + 30), fill=color)
            draw.rectangle((x, y + 17, x + amount - 1, y + 19), fill=highlight)


def rig_panel(game: GameSnapshot):
    image = _face(LEAF)
    draw = ImageDraw.Draw(image)
    text(draw, "RIG STATUS", 10, 10, FOG)
    # Quiet ventilation slits: actual load remains completely static.
    for x in range(12, 116, 8):
        draw.rectangle((x, 22, x + 4, 23), fill=SLATE)
    meter(draw, "CPU", game.cpu, 34)
    meter(draw, "RAM", game.ram, 79)
    return timed([image], 1000)


# Front-face dwell, symmetrical narrowing and return: one calm 4.8s revolution.
COIN_WIDTHS = (8, 8, 8, 7, 6, 4, 2, 1, 2, 4, 6, 7,
               8, 8, 8, 7, 6, 4, 2, 1, 2, 4, 6, 7)


def spinning_icon(draw, image, icon, frame, cx, cy):
    """The real icon on a brass token, retaining its mirrored back face."""
    art = pixel_art(icon, (28, 28), 20)
    step = frame % len(COIN_WIDTHS)
    # Change face only at an edge-on pose, not at the fully visible half turn.
    if 8 <= step < 20:
        art = art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    width = max(2, round(28 * COIN_WIDTHS[step] / 8))
    left = cx - width // 2
    draw.rectangle((left - 2, cy - 16, left + width + 1, cy + 15), fill=WOOD)
    draw.line((left - 2, cy - 16, left + width, cy - 16), fill=AMBER, width=2)
    if width <= 4:
        draw.rectangle((left, cy - 14, left + width - 1, cy + 13), fill=AMBER)
        draw.line((left, cy - 12, left, cy + 10), fill=CREAM, width=2)
    else:
        image.paste(art.resize((width, 28), Image.Resampling.NEAREST), (left, cy - 14))
        draw.line((left - 2, cy - 13, left - 2, cy + 10), fill=CLAY)


@lru_cache(maxsize=2)
def arcade_frames(minute_key: int, score: int, playing: bool, icon: bytes = b""):
    now = minute_key * 60
    base = _face(AMBER)
    draw = ImageDraw.Draw(base)
    # Arcade dressing: the score is 100 per session minute, the credit is decoration.
    text(draw, "1UP", 10, 10, EMBER)
    score_label = f"{max(0, score):06}"
    if len(score_label) <= 18:
        right(draw, score_label, 117, 21, CREAM)
    else:
        right(draw, "SCORE OVERFLOW", 117, 21, CREAM)
    # Cabinet screen recess and lower coin mechanism.
    draw.rectangle((10, 33, 117, 97), fill=SLATE)
    draw.rectangle((12, 35, 115, 95), fill=NAVY)
    draw.rectangle((14, 37, 113, 93), fill=INK)
    draw.line((13, 95, 114, 95), fill=STEEL, width=2)
    draw.rectangle((10, 101, 117, 117), fill=BARK)
    draw.rectangle((13, 104, 30, 113), fill=STEEL)
    draw.rectangle((17, 107, 26, 109), fill=INK)
    text(draw, "CREDIT 01" if playing else "INSERT COIN", 36, 106, LEMON)
    # Clustered stationary stars breathe by one palette step, avoiding drift seams.
    stars = ((23, 44), (99, 46), (34, 57), (89, 62), (106, 57), (23, 66))
    frames = []
    count = len(COIN_WIDTHS)
    for frame in range(count):
        image = base.copy()
        d = ImageDraw.Draw(image)
        for i, (x, y) in enumerate(stars):
            bright = (frame + i * 3) % count in (5, 6, 7, 8)
            d.rectangle((x, y, x + 1, y + 1), fill=STEEL if bright else SLATE)
            if i in (0, 1):
                d.rectangle((x - 1, y + 2, x + 2, y + 3), fill=SLATE)
        cx, cy = 64, 52
        if icon:
            spinning_icon(d, image, icon, frame, cx, cy)
        else:
            half = COIN_WIDTHS[frame] * 2
            if half <= 2:
                d.rectangle((cx - 1, cy - 15, cx + 1, cy + 14), fill=CLAY)
                d.line((cx - 1, cy - 12, cx - 1, cy + 10), fill=AMBER, width=2)
            else:
                d.ellipse((cx - half, cy - 16, cx + half, cy + 15), fill=WOOD)
                d.ellipse((cx - half, cy - 16, cx + half - 2, cy + 12), fill=AMBER)
                if half >= 6:
                    d.ellipse((cx - half + 3, cy - 13, cx + half - 5, cy + 9), outline=CLAY, width=2)
                if half >= 12:
                    d.rectangle((cx - 2, cy - 8, cx + 1, cy + 5), fill=LEMON)
                    d.rectangle((cx - 4, cy - 8, cx + 1, cy - 6), fill=LEMON)
                d.rectangle((cx - half // 2, cy - 11, cx - half // 2 + 1, cy - 7), fill=CREAM)
        centered(d, time.strftime("%H:%M", time.localtime(now)), 73, CREAM, 3)
        frames.append(image)
    return timed(frames, 200)


def render_game(game: GameSnapshot, now: float | None = None) -> list[list[Image.Image]]:
    now = time.time() if now is None else now
    minutes = _minutes(game, now)
    return [cartridge_panel(game), session_panel(game, now), health_panel(game, now), rig_panel(game),
            arcade_frames(int(now // 60), minutes * 100, bool(game.name), game.icon if game.name else b"")]
