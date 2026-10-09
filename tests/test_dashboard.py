import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

from PIL import Image
from times_gate.codex import Session, CodexReader, Snapshot, Quota, parse_limits
from times_gate.device import TimesGate, DeviceError, FrameServer, RETRY_AFTER, gif_bytes, palette_frames
from times_gate.render import Board, render, overview


def event(kind,payload,at="2026-10-07T18:00:00Z"):
    return {"type":kind,"payload":payload,"timestamp":at}


class TelemetryTests(unittest.TestCase):
    def test_current_context_does_not_use_cumulative_or_double_count_cache(self):
        s = Session(Path("unused"))
        s.apply(event("event_msg",{"type":"token_count","info":{
            "total_token_usage":{"total_tokens":9000000},
            "last_token_usage":{"total_tokens":50000,"cached_input_tokens":40000},
            "model_context_window":200000}}))
        self.assertEqual(s.snapshot.context_percent,25)
        s.apply(event("token_usage_record",{"usage":{"total_tokens":60000}}))
        self.assertEqual(s.snapshot.context_percent,30)

    def test_missing_and_reset_limits_are_not_reported_as_full(self):
        short,long = parse_limits(None,100)
        self.assertIsNone(short.remaining)
        limits = {"primary":{"used_percent":20,"window_minutes":10080,"resets_at":200},
                  "secondary":{"used_percent":75,"window_minutes":300,"resets_at":150}}
        short,long = parse_limits(limits,100)
        self.assertEqual(short.remaining,25)
        self.assertEqual(long.remaining,80)
        self.assertFalse(short.available(150))
        self.assertTrue(long.available(150))
        self.assertTrue(long.stale(1100))
        self.assertIsNone(parse_limits({"limit_id":"spark",**limits},100)[0].remaining)

    def test_partial_line_is_retried_and_subagent_is_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            folder = home/"sessions"
            folder.mkdir()
            root = folder/"root.jsonl"
            meta = event("session_meta",{"id":"root","cwd":"C:\\workspaces\\actual-repo","source":"cli"})
            turn = event("turn_context",{"model":"gpt-test","effort":"high"})
            encoded = json.dumps(turn).encode()+b"\n"
            root.write_bytes(json.dumps(meta).encode()+b"\n"+encoded[:20])
            session = Session(root)
            session.read()
            self.assertEqual(session.snapshot.model,"UNKNOWN")
            with root.open("ab") as stream:
                stream.write(encoded[20:])
            session.read()
            self.assertEqual(session.snapshot.model,"gpt-test")
            guardian = folder/"guardian.jsonl"
            guardian.write_text(json.dumps(event("session_meta",{
                "id":"guard","cwd":"C:\\workspaces\\actual-repo",
                "source":{"subagent":{"other":"guardian"}},"parent_thread_id":"root"}))+"\n"+
                json.dumps(event("turn_context",{"model":"codex-auto-review","effort":"low"}))+"\n")
            snap = CodexReader(home).poll()
            self.assertEqual(snap.session_id,"root")
            self.assertEqual(snap.model,"gpt-test")
            self.assertEqual(snap.repo,"actual-repo")
            self.assertEqual(CodexReader(home,repo="other-repo").poll().repo,"NO SESSION")

    def test_task_events_track_working_done_and_aborted(self):
        s = Session(Path("unused"))
        s.apply(event("event_msg",{"type":"task_started"},"2026-10-07T18:00:00Z"))
        self.assertEqual(s.snapshot.state,"working")
        s.apply(event("event_msg",{"type":"task_complete"},"2026-10-07T18:05:00Z"))
        self.assertEqual(s.snapshot.state,"done")
        self.assertGreater(s.snapshot.finished_at,0)
        s.apply(event("event_msg",{"type":"task_started"}))
        s.apply(event("event_msg",{"type":"turn_aborted"}))
        self.assertEqual(s.snapshot.state,"")

    def test_rotated_log_does_not_keep_old_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"session.jsonl"
            old=event("event_msg",{"type":"token_count","rate_limits":{
                "primary":{"used_percent":20,"window_minutes":300}}})
            path.write_text(json.dumps(old)+"\n")
            session=Session(path)
            session.read()
            self.assertIsNotNone(session.rate_limits)
            path.write_text('{}\n')
            session.read()
            self.assertIsNone(session.rate_limits)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        # Keep tests fast and out of the real device log.
        self.log,_=[self.patch(target) for target in ("times_gate.device.log","times_gate.device.time.sleep")]

    def patch(self,target):
        patcher=mock.patch(target)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def device(self,fetch=lambda command: True):
        """A device on loopback that downloads each PlayGif link like the real one."""
        device = TimesGate("127.0.0.1",123,"9000",frame_port=0)
        self.addCleanup(device.close)
        self.commands, self.gifs = [], []
        def post(payload,url=None):
            self.commands.append(payload)
            if payload["Command"] == "Device/PlayGif" and fetch(payload):
                self.gifs.append(urllib.request.urlopen(payload["FileName"][0]).read())
            return {"ReturnCode":0}
        device.post = post
        return device

    def test_play_gif_targets_one_screen_with_lossless_gif_and_caches_fetched_panels(self):
        device = self.device()
        panels = render(Board(),now=100)
        self.assertEqual(device.send(panels),5)
        self.assertEqual(device.send(panels),0)
        plays = [c for c in self.commands if c["Command"] == "Device/PlayGif"]
        for i,(command,gif) in enumerate(zip(plays,self.gifs)):
            self.assertEqual(command["LcdArray"],[int(n==i) for n in range(5)])
            decoded = Image.open(io.BytesIO(gif))
            self.assertEqual((decoded.format,decoded.size),("GIF",(128,128)))
            self.assertEqual(decoded.convert("RGB").tobytes(),panels[i][0].convert("RGB").tobytes())
        self.assertEqual(len({c["FileName"][0] for c in plays}),5)
        panels[2][0].putpixel((0,0),(255,255,255))
        self.assertEqual(device.send(panels),1)
        self.assertEqual(self.commands[-1]["LcdArray"],[0,0,1,0,0])

    def test_gif_never_uses_palette_entry_the_firmware_draws_see_through(self):
        for frames in render(Board(),now=100):
            gif = Image.open(io.BytesIO(gif_bytes(frames,1000)))
            self.assertNotIn(0,[index for _,index in gif.getcolors()])
            self.assertEqual(gif.convert("RGB").tobytes(),frames[0].convert("RGB").tobytes())

    def test_animation_frames_share_one_palette_without_entry_zero(self):
        busy = Board(claude=Snapshot(provider="claude",session_id="a",state="working"),
                     codex=Snapshot(session_id="b",state="working"))
        frames = render(busy,now=100)[0]
        images = palette_frames(frames)
        self.assertEqual(len({bytes(image.getpalette()) for image in images}),1)
        for image,frame in zip(images,frames):
            self.assertNotIn(0,[index for _,index in image.getcolors()])
            self.assertEqual(image.convert("RGB").tobytes(),frame.convert("RGB").tobytes())

    def test_unfetched_panel_is_offered_again(self):
        skipped = []
        def fetch(command):
            if command["LcdArray"] == [0,1,0,0,0] and not skipped:
                skipped.append(command)
                return False
            return True
        device = self.device(fetch)
        with mock.patch("times_gate.device.FETCH_TIMEOUT",0.1):
            panels = render(Board(),now=100)
            self.assertEqual(device.send(panels),4)
            self.assertEqual(device.send(panels),1)
        self.assertEqual(self.commands[-1]["LcdArray"],[0,1,0,0,0])

    def test_frame_server_answers_only_the_device(self):
        server = FrameServer("127.0.0.2",0)
        self.addCleanup(server.close)
        url = server.publish(0,b"GIF89a")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url.replace(server.host,"127.0.0.1"))
        self.assertEqual(error.exception.code,404)

    def test_failed_send_clears_device_state_for_reconnect(self):
        device = self.device()
        device.url = "http://127.0.0.1:9000/divoom_api"
        device.frames = FrameServer("127.0.0.1",0)
        def fail(payload):
            raise DeviceError("offline")
        device.post = fail
        with self.assertRaises(DeviceError):
            device.send(render(Board(),now=100))
        self.assertIsNone(device.url)
        self.assertFalse(device.sent)

    def test_both_response_formats_and_device_rejection(self):
        class Response:
            def __init__(self,body): self.body=io.BytesIO(json.dumps(body).encode())
            def __enter__(self): return self.body
            def __exit__(self,*args): pass
        class Opener:
            body={"ReturnCode":0}
            def open(self,req,timeout):
                self.request=req
                return Response(self.body)
        device=TimesGate("192.168.1.120",123)
        device.url="http://192.168.1.120/post"
        device.opener=Opener()
        for body in ({"ReturnCode":0},{"error_code":"0"}):
            device.opener.body=body
            device.post({"Command":"Channel/GetAllConf"})
            payload=json.loads(device.opener.request.data)
            self.assertEqual(payload["LocalToken"],123)
        device.opener.body={"ReturnCode":1,"ReturnMessage":"bad token 123"}
        with self.assertRaises(DeviceError) as error:
            device.post({"Command":"Channel/GetAllConf"})
        self.assertNotIn("123",str(error.exception))

    def test_animated_panel_becomes_one_looping_gif(self):
        device = self.device()
        board = Board(codex=Snapshot(session_id="x",state="done",finished_at=90))
        panels = render(board,now=100)
        panels[0]=[panels[0][0].copy() for _ in range(8)]
        for i,frame in enumerate(panels[0]):
            frame.putpixel((0,0),(i*30,0,0))
        self.assertEqual(device.send(panels,speed=140),5)
        gif = Image.open(io.BytesIO(self.gifs[0]))
        self.assertEqual((gif.n_frames,gif.info["duration"]),(8,140))

    def test_failure_waits_before_reconnecting_and_logs_outage(self):
        online = False
        device = self.device()
        connected = device.post
        def post(payload,url=None):
            if not online:
                self.commands.append(payload)
                raise DeviceError("offline")
            return connected(payload,url)
        device.post = post
        panels = render(Board(),now=100)
        with self.assertRaises(DeviceError):
            device.send(panels)
        attempts = len(self.commands)
        # Within the cooldown nothing is sent to a device that may still be booting.
        with self.assertRaises(DeviceError) as error:
            device.send(panels)
        self.assertIn("retrying in",str(error.exception))
        self.assertEqual(len(self.commands),attempts)
        online = True
        device.failed_at -= RETRY_AFTER
        self.assertEqual(device.send(panels),5)
        messages = [call.args[0] for call in self.log.call_args_list]
        self.assertTrue(any(m.startswith("connect failed") for m in messages))
        self.assertRegex(messages[-6],r"^connected .* after \d+s offline$")

    def test_manual_send_skips_reconnect_cooldown(self):
        device = self.device()
        device.mark_offline()
        self.assertEqual(device.send(render(Board(),now=100),force=True),5)

    def test_expired_quota_renders_as_unknown_not_old_percentage(self):
        expired=render(Board(codex=Snapshot(five_hour=Quota(73,100,80))),now=101)[2][0]
        missing=render(Board(),now=101)[2][0]
        # Percent and progress bar have the same unknown appearance; the reset note differs.
        self.assertEqual(expired.crop((0,80,128,99)).tobytes(),missing.crop((0,80,128,99)).tobytes())
        self.assertEqual(overview(render(Board()),scale=1).size,(712,160))


if __name__ == "__main__":
    unittest.main()
