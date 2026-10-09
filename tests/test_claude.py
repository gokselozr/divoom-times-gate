import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_statusline import capture, run_original
from setup_claude import install
from times_gate.claude import ClaudeSession, ClaudeReader, status_snapshot, merge
from times_gate.codex import Snapshot
from times_gate.render import Board, ICON_FRAMES, model_parts, render


def native(session="main",repo="studio",used=70):
    return {"session_id":session,"cwd":f"C:/workspaces/{repo}/nested",
            "workspace":{"project_dir":f"C:/workspaces/{repo}"},
            "model":{"id":"claude-opus-5","display_name":"Opus 5"},
            "effort":{"level":"high"},"observed_at":200,
            "context_window":{"context_window_size":200000,"used_percentage":used,
                              "remaining_percentage":100-used,"current_usage":{
                                  "input_tokens":10000,"cache_creation_input_tokens":30000,
                                  "cache_read_input_tokens":100000,"output_tokens":9000}},
            "rate_limits":{"five_hour":{"used_percentage":35,"resets_at":500},
                           "seven_day":{"used_percentage":18,"resets_at":800}}}


class ClaudeTelemetryTests(unittest.TestCase):
    def test_compaction_invalidates_old_native_context_until_fresh_usage(self):
        session=ClaudeSession(Path("unused"))
        session.apply({"type":"assistant","sessionId":"main","timestamp":"2026-10-07T18:00:00Z",
                       "message":{"model":"claude-opus-5","context_window":{"context_window_size":200000},
                                  "usage":{"input_tokens":140000}}})
        old=status_snapshot(native(),session.snapshot.context_observed_at)
        session.apply({"type":"system","subtype":"compact_boundary","timestamp":"2026-10-07T18:01:00Z"})
        self.assertIsNone(merge(old,session.snapshot).context_left)
        self.assertEqual(merge(old,session.snapshot).five_hour.remaining,65)
        fresh=status_snapshot(native(used=10),session.snapshot.observed_at+1)
        self.assertEqual(merge(fresh,session.snapshot).context_left,90)
        session.apply({"type":"assistant","sessionId":"main","timestamp":"2026-10-07T18:02:00Z",
                       "message":{"model":"claude-opus-5","usage":{"input_tokens":50000}}})
        self.assertEqual(merge(old,session.snapshot).context_left,75)

    def test_native_left_context_excludes_output_and_uses_project_root(self):
        snapshot=status_snapshot(native(),200)
        self.assertEqual(snapshot.repo,"studio")
        self.assertEqual(snapshot.context_tokens,140000)
        self.assertEqual(snapshot.context_left,30)
        self.assertEqual(snapshot.context_tokens_left,60000)
        self.assertEqual(snapshot.five_hour.remaining,65)
        self.assertEqual(snapshot.weekly.remaining,82)
        self.assertFalse(snapshot.five_hour.available(500))
        payload=native()
        payload["context_window"].pop("remaining_percentage")
        self.assertEqual(status_snapshot(payload,200).context_left,30)
        payload["context_window"]={"current_usage":None}
        payload["rate_limits"]={"five_hour":None}
        self.assertIsNone(status_snapshot(payload,200).context_left)
        self.assertIsNone(status_snapshot(payload,200).five_hour.remaining)

    def test_log_uses_recorded_window_and_invalidates_compacted_context(self):
        s=ClaudeSession(Path("unused"))
        event={"type":"assistant","timestamp":"2026-10-07T18:00:00Z","sessionId":"main",
               "cwd":"C:/workspaces/studio","effort":"high","message":{
                   "model":"claude-opus-5","usage":native()["context_window"]["current_usage"]}}
        s.apply(event)
        self.assertIsNone(s.snapshot.context_left)
        s.apply({"type":"cost-state","modelUsage":{"claude-opus-5[1m]":{}}})
        self.assertEqual(s.snapshot.context_left,86)
        s.apply({**event,"cwd":"C:/workspaces/studio/nested"})
        self.assertEqual(s.snapshot.repo,"studio")
        s.apply({**event,"isSidechain":True,"message":{"model":"claude-haiku-test"}})
        self.assertEqual(s.snapshot.model,"claude-opus-5")
        s.apply({"type":"system","subtype":"compact_boundary"})
        self.assertIsNone(s.snapshot.context_left)

    def test_account_limits_are_available_when_repo_is_pinned_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            home=root/"home"
            folder=home/"projects/studio"
            folder.mkdir(parents=True)
            (folder/"main.jsonl").write_text(json.dumps({"type":"user","sessionId":"main",
                "cwd":"C:/workspaces/studio","timestamp":"2026-01-01T00:00:00Z"})+"\n")
            telemetry=root/"telemetry"
            telemetry.mkdir()
            payload=native("other","elsewhere")
            payload["observed_at"]=2000000000
            (telemetry/"other.json").write_text(json.dumps(payload))
            selected=ClaudeReader(home,repo="studio",telemetry=telemetry).poll()
            self.assertEqual(selected.session_id,"main")
            self.assertEqual(selected.five_hour.remaining,65)
            self.assertEqual(ClaudeReader(home,telemetry=telemetry).poll().session_id,"other")

    def test_transcript_activity_does_not_hide_native_status_and_limits_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/"home/projects/studio"
            folder.mkdir(parents=True)
            log=folder/"main.jsonl"
            # A newer user message without usage data must not replace status-line fields.
            log.write_text(json.dumps({"type":"user","sessionId":"main","cwd":"C:/workspaces/studio",
                                       "timestamp":"2033-01-01T00:00:00Z"})+"\n")
            telemetry=root/"telemetry"
            telemetry.mkdir()
            (telemetry/"main.json").write_text(json.dumps(native()))
            reader=ClaudeReader(root/"home",telemetry=telemetry)
            snap=reader.poll()
            self.assertEqual((snap.effort,snap.context_left,snap.five_hour.remaining),("high",30,65))
            self.assertGreater(snap.observed_at,200)
            (telemetry/"main.json").unlink()
            snap=reader.poll()
            self.assertIsNone(snap.five_hour.remaining)
            self.assertIsNone(reader.poll().weekly.remaining)

    def test_same_model_keeps_recorded_window(self):
        s=ClaudeSession(Path("unused"))
        event={"type":"assistant","timestamp":"2026-10-07T18:00:00Z","sessionId":"main",
               "message":{"model":"claude-opus-5","context_window":{"context_window_size":200000},
                          "usage":{"input_tokens":50000}}}
        s.apply(event)
        s.apply({**event,"message":{"model":"claude-opus-5","usage":{"input_tokens":100000}}})
        self.assertEqual(s.snapshot.context_left,50)
        s.apply({**event,"message":{"model":"claude-haiku-5","usage":{"input_tokens":100000}}})
        self.assertIsNone(s.snapshot.context_left)

    def test_turn_state_follows_prompts_end_turn_and_interrupts(self):
        s=ClaudeSession(Path("unused"))
        prompt={"type":"user","sessionId":"main","timestamp":"2026-10-07T18:00:00Z","message":{"content":"fix it"}}
        s.apply(prompt)
        self.assertEqual(s.snapshot.state,"working")
        s.apply({"type":"assistant","sessionId":"main","timestamp":"2026-10-07T18:01:00Z",
                 "message":{"model":"claude-opus-5","stop_reason":"tool_use"}})
        self.assertEqual(s.snapshot.state,"working")
        s.apply({"type":"assistant","sessionId":"main","timestamp":"2026-10-07T18:02:00Z",
                 "message":{"model":"claude-opus-5","stop_reason":"end_turn"}})
        self.assertEqual(s.snapshot.state,"done")
        s.apply({**prompt,"isMeta":True})
        s.apply({"type":"system","subtype":"turn_duration"})
        self.assertEqual(s.snapshot.state,"done")
        s.apply(prompt)
        s.apply({**prompt,"message":{"content":[{"type":"text","text":"[Request interrupted by user]"}]}})
        self.assertEqual(s.snapshot.state,"")

    def test_agents_panel_is_static_when_ready_and_shows_busy_ready(self):
        claude=Snapshot(provider="claude",session_id="a",state="done",finished_at=1000)
        codex=Snapshot(session_id="b",state="done",finished_at=1500)
        board=Board(claude=claude,codex=codex)
        frames=render(board,1600)[0]
        self.assertEqual(len(frames),1)
        busy=render(Board(claude=claude,codex=Snapshot(session_id="b",state="working")),1600)[0]
        self.assertNotEqual(frames[0].tobytes(),busy[0].tobytes())
        board.claude.state=""
        board.codex.state=""
        self.assertEqual(frames[0].tobytes(),render(board,1600)[0][0].tobytes())

    def test_busy_agent_icon_animates_and_ready_icon_stays_still(self):
        ready=Snapshot(provider="claude",session_id="a",state="done",finished_at=1000)
        busy=Snapshot(session_id="b",state="working")
        frames=render(Board(claude=ready,codex=busy),1600)[0]
        self.assertEqual(len(frames),ICON_FRAMES)
        claude_icon=lambda f: f.crop((8,27,120,66)).tobytes()
        codex_icon=lambda f: f.crop((8,71,42,110)).tobytes()
        self.assertEqual(len({claude_icon(f) for f in frames}),1)
        self.assertGreater(len({codex_icon(f) for f in frames}),1)
        # Frames do not depend on the clock, so a busy panel is not re-sent every tick.
        self.assertEqual([f.tobytes() for f in frames],[f.tobytes() for f in render(Board(claude=ready,codex=busy),9999)[0]])
        both=render(Board(claude=Snapshot(provider="claude",session_id="a",state="working"),codex=busy),1600)[0]
        self.assertGreater(len({claude_icon(f) for f in both}),1)

    def test_any_claude_family_name(self):
        self.assertEqual(model_parts("claude-fable-5-1","claude")[0],"FABLE 5.1")
        self.assertEqual(model_parts("claude-opus-5-5[1m]","claude")[0],"OPUS 5.5")
        self.assertEqual(model_parts("claude-sonnet-4-5-20250929","claude")[0],"SONNET 4.5")
        # Three repo rows stay above the branch footer (y=101).
        self.assertEqual(model_parts("gpt-6.1-sol","codex"),["GPT 6.1","SOL"])

    def test_bridge_exports_allowlist_and_blocks_session_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            payload=native()
            payload.update({"transcript_path":"secret-log","messages":["SECRET MESSAGE"],"api_key":"SECRET KEY"})
            payload["workspace"]["repo"]={"name":"studio","remote":"SECRET REMOTE"}
            capture(payload,folder)
            raw=(folder/"main.json").read_text()
            self.assertNotIn("SECRET",raw)
            self.assertNotIn("transcript_path",raw)
            self.assertNotIn("output_tokens",raw)
            self.assertEqual(status_snapshot(json.loads(raw),200).context_left,30)
            capture({**payload,"session_id":"../escape"},folder)
            self.assertEqual(len(list(folder.iterdir())),1)


class IntegrationTests(unittest.TestCase):
    def test_moved_bridge_is_repointed_and_keeps_users_original(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            old=folder/"old"
            (old/"output/claude").mkdir(parents=True)
            (old/"output/claude/statusline-install.json").write_text(json.dumps(
                {"original_statusLine":{"type":"command","command":"bash mine.sh"}}))
            settings=folder/"settings.json"
            old_command=f'"python" "{(old/"claude_statusline.py").as_posix()}"'
            settings.write_text(json.dumps({"statusLine":{"type":"command","command":old_command}}))
            backup=folder/"new/install.json"
            self.assertTrue(install(settings,backup,'"python" "new/claude_statusline.py"'))
            self.assertEqual(json.loads(settings.read_text())["statusLine"]["command"],'"python" "new/claude_statusline.py"')
            self.assertEqual(json.loads(backup.read_text())["original_statusLine"]["command"],"bash mine.sh")

    def test_statusline_install_is_idempotent_and_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            settings=folder/"settings.json"
            backup=folder/"install.json"
            original={"model":"opus[1m]","theme":"dark","statusLine":{
                "type":"command","command":"bash ~/.claude/statusline.sh","padding":2}}
            settings.write_text(json.dumps(original))
            self.assertTrue(install(settings,backup,'python bridge.py'))
            self.assertFalse(install(settings,backup,'python bridge.py'))
            configured=json.loads(settings.read_text())
            self.assertEqual(configured["model"],original["model"])
            self.assertEqual(configured["statusLine"]["padding"],2)
            self.assertTrue(install(settings,backup,'python bridge.py',remove=True))
            self.assertEqual(json.loads(settings.read_text()),original)

    def test_original_statusline_receives_raw_stdin_and_uses_git_bash(self):
        with patch("claude_statusline.os.name","nt"), \
             patch("claude_statusline.Path.is_file",return_value=True), \
             patch("claude_statusline.subprocess.run") as execute:
            run_original('bash ~/.claude/statusline.sh',b'{"hello":1}')
            command=execute.call_args.args[0]
            self.assertEqual(command[-2:],["-c","bash ~/.claude/statusline.sh"])
            self.assertEqual(execute.call_args.kwargs["input"],b'{"hello":1}')
            self.assertNotIn("shell",execute.call_args.kwargs)

    def test_context_row_shows_thirty_left_from_tokens_or_native_percent(self):
        snapshot=Snapshot(provider="claude",context_tokens=140000,context_window=200000,context_observed_at=100)
        self.assertEqual(snapshot.context_left,30)
        expected=Snapshot(provider="claude",context_window=200000,context_remaining_override=30,context_observed_at=100)
        panel=lambda s:render(Board(claude=s),100)[1][0].tobytes()
        self.assertEqual(panel(snapshot),panel(expected))
        self.assertNotEqual(panel(snapshot),panel(Snapshot(provider="claude",context_remaining_override=70,context_observed_at=100)))


if __name__=="__main__":
    unittest.main()
