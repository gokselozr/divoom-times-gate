import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import app
from times_gate.codex import Snapshot
from times_gate.render import render, Board
from times_gate.polling import AsyncSource


class EngineTests(unittest.TestCase):
    def test_slow_source_does_not_delay_agent_updates_or_rendering(self):
        entered=threading.Event()
        release=threading.Event()
        def slow():
            entered.set()
            release.wait(3)
            return Snapshot(provider="claude")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app,"OUTPUT",Path(directory)), \
                 patch.object(app.ClaudeReader,"poll",side_effect=slow), \
                 patch.object(app.CodexReader,"poll",return_value=Snapshot(session_id="main",state="done",finished_at=100)):
                engine=app.Engine(dict(app.DEFAULTS))
                try:
                    # Wait for the quick read only; the slow one remains in flight.
                    engine.board()
                    self.assertTrue(entered.wait(1))
                    engine.sources["codex"].wait(1)
                    completed=threading.Event()
                    result=[]
                    thread=threading.Thread(target=lambda:(result.append(engine.tick()),completed.set()),daemon=True)
                    thread.start()
                    self.assertTrue(completed.wait(2),"Rendering waited for the slow Claude read")
                    self.assertEqual(result[0][1].codex.state,"done")
                    self.assertFalse(release.is_set())
                    self.assertTrue((Path(directory)/"preview.png").exists())
                finally:
                    release.set()
                    engine.close()

    def test_completed_reads_are_copied_throttled_and_retained_on_failure(self):
        reader=Mock()
        value=Snapshot(context_tokens=50000,context_window=200000)
        reader.poll.side_effect=[value,RuntimeError("offline")]
        ready=threading.Event()
        source=AsyncSource(reader,Snapshot(),ready,interval=5)
        with patch("times_gate.polling.time.monotonic",return_value=100) as now:
            source.request()
            source.wait(1)
            value.context_tokens=100000
            self.assertEqual(source.current()[0].context_left,75)
            now.return_value=101
            source.request()
            self.assertEqual(reader.poll.call_count,1)
            now.return_value=106
            source.request()
            source.wait(1)
            snapshot,error=source.current()
            self.assertEqual((snapshot.context_left,error),(75,"RuntimeError"))
            source.close()
            now.return_value=200
            source.request()
            self.assertEqual(reader.poll.call_count,2)


if __name__=="__main__":
    unittest.main()
