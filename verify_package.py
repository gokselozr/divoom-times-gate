"""Smoke-test the extracted Windows ZIP with isolated profiles and no Python on PATH."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import zipfile

from PIL import Image, ImageGrab

ROOT=Path(__file__).resolve().parent


def windows_for(pid):
    handles=[]
    user=ctypes.windll.user32
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @callback
    def visit(hwnd,_):
        owner=wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True
    user.EnumWindows(visit,0)
    return handles


def verify():
    archive=ROOT/"releases/TimesGateAI-Windows-x64.zip"
    artifacts=ROOT/"output/package-verification"
    artifacts.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.with_suffix(".zip.sha256").read_text().split()[0]==digest
    checks=[]
    with tempfile.TemporaryDirectory(prefix="verification-",dir=artifacts) as temporary:
        root=Path(temporary)
        destination=root/"Türkçe O'Brien $folder"
        with zipfile.ZipFile(archive) as zipped:
            assert zipped.testzip() is None
            names=zipped.namelist()
            assert not any(name.endswith(".local.json") or "/output/" in name for name in names)
            zipped.extractall(destination)
        bundle=destination/"TimesGateAI"
        helper=bundle/"TimesGateCLI.exe"
        env=os.environ.copy()
        system=Path(os.environ["SystemRoot"])
        env["PATH"]=os.pathsep.join(map(str,(system/"System32",system,system/"System32/WindowsPowerShell/v1.0")))
        env.pop("PYTHONHOME",None)
        env.pop("PYTHONPATH",None)
        env.pop("TIMES_GATE_DATA_DIR",None)
        env["LOCALAPPDATA"]=str(root/"Local data")
        env["CLAUDE_CONFIG_DIR"]=str(root/"Claude home")
        env["CODEX_HOME"]=str(root/"Codex home")
        data=root/"Local data/TimesGateAI"
        settings=Path(env["CLAUDE_CONFIG_DIR"])/"settings.json"
        settings.parent.mkdir()
        original={"theme":"dark","statusLine":{"type":"command","command":"echo ORIGINAL","padding":2}}
        settings.write_text(json.dumps(original),encoding="utf-8")

        def run(args,stdin=None):
            result=subprocess.run(args,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                env=env,cwd=root,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode==0,(args,result.returncode,result.stderr.decode("utf-8",errors="replace"))
            return result.stdout.decode("utf-8-sig")

        paths=json.loads(run([str(helper),"--paths"]))
        assert paths=={"app_root":str(bundle),"data_root":str(data),"frozen":True},paths
        checks.append("Extracted executable paths and per-user storage without Python on PATH")
        stdout=run([str(helper),"--once","--demo"])
        assert "READY" in stdout and "BUSY" in stdout,stdout
        panels=data/"output/panels"
        demo=json.loads((panels/"status.json").read_text(encoding="utf-8"))
        assert demo["demo"] is True
        for name in ("01-agents","02-claude","03-codex","04-scene","05-weekly"):
            with Image.open(panels/f"{name}.png") as panel:
                assert panel.size==(128,128)
        checks.append("Five 128x128 panels and BUSY/READY from the packaged CLI")

        run([str(helper),"--install-claude"])
        command=json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"]
        assert "-EncodedCommand" in command
        payload={"session_id":"package-smoke","cwd":"C:/workspaces/Türkçe proje",
            "workspace":{"project_dir":"C:/workspaces/Türkçe proje"},
            "model":{"id":"claude-opus-5","display_name":"Opus"},
            "context_window":{"remaining_percentage":30,"used_percentage":70,"context_window_size":200000},
            "rate_limits":{"five_hour":{"used_percentage":35},"seven_day":{"used_percentage":18}}}
        raw=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        assert "ORIGINAL" in run(command.split(),raw)
        telemetry=data/"output/claude/telemetry/package-smoke.json"
        saved=json.loads(telemetry.read_text(encoding="utf-8"))
        assert saved["cwd"]==payload["cwd"]
        assert saved["context_window"]["remaining_percentage"]==30
        # Claude Code on Windows may route the hook through Git Bash.
        bash=Path(os.environ.get("ProgramFiles","C:/Program Files"))/"Git/bin/bash.exe"
        if bash.is_file():
            telemetry.unlink()
            assert "ORIGINAL" in run([str(bash),"-c",command],raw)
            assert json.loads(telemetry.read_text(encoding="utf-8"))["cwd"]==payload["cwd"]
            checks.append("Packaged Claude hook through PowerShell and Git Bash, with UTF-8 input")
        else:
            checks.append("Packaged Claude hook through PowerShell, with UTF-8 input")
        run([str(helper),"--remove-claude"])
        assert json.loads(settings.read_text(encoding="utf-8"))==original
        checks.append("Claude install/remove preserves the original status line")

        process=subprocess.Popen([str(bundle/"TimesGate.exe")],env=env,cwd=root,
            creationflags=subprocess.CREATE_NO_WINDOW)
        handles=[]
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                handles=windows_for(process.pid)
                try:
                    live=json.loads((panels/"status.json").read_text(encoding="utf-8"))
                except (OSError,ValueError):
                    live={"demo":True}
                if handles and live["demo"] is False:
                    break
                assert process.poll() is None,"GUI exited before startup"
                assert not (data/"startup-error.log").exists(),"GUI reported a startup error"
                time.sleep(.2)
            assert handles,"GUI window missing"
            assert live["demo"] is False,"GUI did not export live data"
            assert ctypes.windll.user32.IsHungAppWindow(handles[0])==0
            assert "-EncodedCommand" in json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"]
            assert not (data/"startup-error.log").exists()
            ImageGrab.grab(window=handles[0]).save(artifacts/"packaged-window.png")
            checks.append("Responsive desktop GUI with automatic Claude setup in an isolated profile")
        finally:
            for hwnd in windows_for(process.pid):
                ctypes.windll.user32.PostMessageW(hwnd,0x10,0,0)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        assert process.returncode==0,process.returncode
        assert not (bundle/"config.local.json").exists()
        assert not (bundle/"output").exists()
        checks.append("Clean shutdown; application directory remains free of user data")
    report={"archive":archive.name,"sha256":digest,"checks":checks}
    (artifacts/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    for check in checks:
        print("PASS:",check)


if __name__=="__main__":
    verify()
