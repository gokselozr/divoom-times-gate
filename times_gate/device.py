"""Times Gate HTTP transport; the device downloads each panel from a local frame server."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from PIL import Image
from .runtime import DATA_ROOT

LOG = DATA_ROOT / "device.log"
# Pushing JPEGs with Draw/SendHttpGif made the device drop off Wi-Fi after a few hundred uploads;
# with Device/PlayGif the request is tiny and the device fetches a lossless GIF at its own pace.
FRAME_PORT = 8477
FETCH_TIMEOUT = 10
PANEL_PAUSE = 0.5
# A rebooting device needs its cloud handshake before the local API is stable again.
RETRY_AFTER = 60


class DeviceError(Exception):
    pass


def log(message: str):
    try:
        LOG.parent.mkdir(parents=True,exist_ok=True)
        with LOG.open("a",encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def validate_address(address: str) -> str:
    address = address.strip()
    try:
        ipaddress.IPv4Address(address)
    except ValueError as exc:
        raise ValueError("Enter a valid IPv4 address.") from exc
    return address


SHIFT = bytes(min(i+1,255) for i in range(256))


def palette_frames(frames: list) -> list:
    # One palette for every frame, so no frame gets a local palette that reuses entry 0.
    sheet = Image.new("RGB",(128,128*len(frames)))
    for row,frame in enumerate(frames):
        sheet.paste(frame.convert("RGB"),(0,row*128))
    # Panels use few colours, so a 255-colour palette keeps every pixel exact.
    quantized = sheet.quantize(colors=255)
    # The firmware draws palette entry 0 as see-through, so every pixel moves up one entry.
    shifted = Image.frombytes("P",sheet.size,quantized.tobytes().translate(SHIFT))
    shifted.putpalette([0,0,0]+quantized.getpalette()[:255*3])
    return [shifted.crop((0,row*128,128,(row+1)*128)) for row in range(len(frames))]


def gif_bytes(frames: list, speed: int) -> bytes:
    images = palette_frames(frames)
    buf = io.BytesIO()
    # optimize=False keeps the palette order, and with it the unused entry 0.
    if len(images) > 1:
        # A scene may set its own pace per frame; otherwise the transport speed applies.
        durations = [frame.info.get("duration",speed) for frame in frames]
        images[0].save(buf,"GIF",save_all=True,append_images=images[1:],duration=durations,loop=0,optimize=False)
    else:
        images[0].save(buf,"GIF",optimize=False)
    return buf.getvalue()


class FrameServer:
    """Serves the current GIF of every screen to the device, and only to the device."""

    def __init__(self, device_ip: str, port: int):
        self.device_ip = device_ip
        self.files: dict[str,bytes] = {}
        self.current: dict[int,str] = {}
        self.fetches: dict[str,int] = {}
        self.fetched = threading.Condition()
        try:
            self.server = ThreadingHTTPServer(("0.0.0.0",port),self.handler())
        except OSError:
            self.server = ThreadingHTTPServer(("0.0.0.0",0),self.handler())
        self.server.daemon_threads = True
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:
            # The interface that routes to the device is the one it can reach us on.
            probe.connect((device_ip,9))
            self.host = probe.getsockname()[0]
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True,name="frame-server")
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def publish(self, index: int, data: bytes) -> str:
        # A new link per picture; the device keeps showing the old one for an unchanged link.
        path = f"/lcd{index+1}-{hashlib.sha256(data).hexdigest()[:16]}.gif"
        with self.fetched:
            self.files[path] = data
            self.current[index] = path
            # Keep every screen's current picture; the device fetches it again after a reboot.
            for old in [p for p in self.files if p not in self.current.values()][:-5]:
                del self.files[old]
        return f"http://{self.host}:{self.port}{path}"

    def wait_fetch(self, url: str, timeout: float) -> bool:
        path = urllib.parse.urlsplit(url).path
        with self.fetched:
            return self.fetched.wait_for(lambda: self.fetches.get(path),timeout)

    def handler(self):
        frames = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with frames.fetched:
                    data = frames.files.get(self.path)
                if self.client_address[0] != frames.device_ip or data is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type","image/gif")
                self.send_header("Content-Length",str(len(data)))
                self.send_header("Cache-Control","no-store")
                self.end_headers()
                self.wfile.write(data)
                with frames.fetched:
                    frames.fetches[self.path] = frames.fetches.get(self.path,0)+1
                    frames.fetched.notify_all()

            def log_message(self, *args):
                pass

        return Handler

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TimesGate:
    def __init__(self, ip: str, token: int, endpoint: str = "auto", timeout: float = 5,
                 frame_port: int = FRAME_PORT):
        self.ip = validate_address(ip)
        self.token = int(token)
        self.endpoint = endpoint
        self.timeout = timeout
        self.frame_port = frame_port
        self.frames = None
        self.url = None
        self.sent: dict[int,str] = {}
        self.connected_at = None
        self.uploads = 0
        self.failed_at = None
        self.offline_since = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, command: dict, url: str | None = None) -> dict:
        payload = {**command,"LocalToken":self.token}
        request = urllib.request.Request(url or self.url, data=json.dumps(payload).encode(),
                                         headers={"Content-Type":"application/json"})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                result = json.load(response)
        except Exception as exc:
            raise DeviceError(f"Device connection failed: {type(exc).__name__}") from exc
        if not isinstance(result,dict):
            raise DeviceError("The device returned an invalid response.")
        code = result.get("error_code",result.get("ReturnCode"))
        if code not in (0,"0"):
            message = str(result.get("ReturnMessage",code))
            message = message.replace(str(self.token),"[token]")
            raise DeviceError(f"The device rejected the command: {message}")
        return result

    def connect(self):
        if self.frames is None:
            self.frames = FrameServer(self.ip,self.frame_port)
            log(f"frame server http://{self.frames.host}:{self.frames.port}")
        urls = {"9000":f"http://{self.ip}:9000/divoom_api", "80":f"http://{self.ip}/post"}
        candidates = [urls[self.endpoint]] if self.endpoint in urls else [urls["9000"],urls["80"]]
        for url in candidates:
            try:
                self.post({"Command":"Channel/GetAllConf"},url)
                self.url = url
                self.sent.clear()
                self.connected_at = time.monotonic()
                self.uploads = 0
                offline = (f" after {self.connected_at-self.offline_since:.0f}s offline"
                           if self.offline_since is not None else "")
                log(f"connected {url}{offline}")
                self.failed_at = self.offline_since = None
                return
            except DeviceError as exc:
                self.url = None
                log(f"connect failed {url}: {exc} ({exc.__cause__!r})")
        self.mark_offline()
        raise DeviceError(f"Could not connect to {self.ip}. Check the IP, LocalToken and Wi-Fi.")

    def send(self, panels: list, force=False, speed: int = 1000) -> int:
        """Send five panels; each is an image or a list of animation frames."""
        if len(panels) != 5:
            raise ValueError("Times Gate needs exactly five panels.")
        panels = [frames if isinstance(frames,list) else [frames] for frames in panels]
        if any(not frames or len(frames) > 60 or any(f.size != (128,128) for f in frames) for frames in panels):
            raise ValueError("Panels must be 1-60 frames of 128x128.")
        if not self.url:
            wait = RETRY_AFTER-(time.monotonic()-self.failed_at) if self.failed_at is not None else 0
            if wait > 0 and not force:
                raise DeviceError(f"Device not responding; retrying in {wait:.0f} s.")
            self.connect()
        count = 0
        for index,frames in enumerate(panels):
            digest = hashlib.sha256(b"".join(f.tobytes() for f in frames)).hexdigest()
            if not force and self.sent.get(index) == digest:
                continue
            mask = [0]*5
            mask[index] = 1
            data = gif_bytes(frames,speed)
            url = self.frames.publish(index,data)
            started = time.monotonic()
            try:
                self.post({"Command":"Device/PlayGif","LcdArray":mask,"FileName":[url]})
            except DeviceError as exc:
                self.fail(exc,f"lcd={index+1} bytes={len(data)} ms={(time.monotonic()-started)*1000:.0f}")
                raise
            command_ms = (time.monotonic()-started)*1000
            if not self.frames.wait_fetch(url,FETCH_TIMEOUT):
                # Not cached as sent, so the next cycle offers this panel again.
                log(f"not fetched lcd={index+1} within {FETCH_TIMEOUT}s")
                continue
            self.sent[index] = digest
            self.uploads += 1
            count += 1
            log(f"upload lcd={index+1} frames={len(frames)} bytes={len(data)} ms={command_ms:.0f} "
                f"fetched_ms={(time.monotonic()-started)*1000:.0f}")
            time.sleep(PANEL_PAUSE)
        return count

    def fail(self, exc: DeviceError, detail: str = ""):
        uptime = time.monotonic()-self.connected_at if self.connected_at is not None else 0
        detail = f" {detail}" if detail else ""
        log(f"failed uploads={self.uploads} uptime={uptime:.0f}s{detail}: {exc} ({exc.__cause__!r})")
        self.url = None
        self.sent.clear()
        self.mark_offline()

    def mark_offline(self):
        self.failed_at = time.monotonic()
        if self.offline_since is None:
            self.offline_since = self.failed_at

    def close(self):
        if self.frames is not None:
            self.frames.close()
            self.frames = None
