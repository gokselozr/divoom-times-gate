"""Capture allowlisted telemetry and delegate to the user's existing status line."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from times_gate.runtime import APP_ROOT, DATA_ROOT

ROOT=APP_ROOT
BRIDGE_CONFIG=DATA_ROOT/"output"/"claude"/"statusline-install.json"


def run_original(command,raw):
    if getattr(sys,"frozen",False) and sys.platform=="win32":
        # External Git Bash / PowerShell must use their own system DLLs.
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    # Match Claude Code's Windows shell so ~ and Bash syntax keep working.
    if os.name == "nt":
        candidates=[os.environ.get("CLAUDE_CODE_GIT_BASH_PATH","")]
        for base in (os.environ.get("ProgramFiles","C:/Program Files"),
                     os.environ.get("ProgramFiles(x86)","C:/Program Files (x86)"),
                     str(Path(os.environ.get("LOCALAPPDATA",""))/"Programs")):
            candidates.append(str(Path(base)/"Git/bin/bash.exe"))
        bash=next((p for p in candidates if p and Path(p).is_file()),None)
        executable=[bash,"-c",command] if bash else [shutil.which("powershell") or "powershell",
                                                    "-NoProfile","-Command",command]
        return subprocess.run(executable,input=raw,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,timeout=3)
    return subprocess.run(command,shell=True,input=raw,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,timeout=3)


def sanitize(data):
    workspace=data.get("workspace") or {}
    context=data.get("context_window") or {}
    rates=data.get("rate_limits") or {}
    result={"session_id":data.get("session_id"),"cwd":data.get("cwd"),"observed_at":time.time(),
            "workspace":{k:workspace[k] for k in ("current_dir","project_dir","repo") if k in workspace},
            "model":{k:v for k,v in (data.get("model") or {}).items() if k in ("id","display_name")},
            "effort":{k:v for k,v in (data.get("effort") or {}).items() if k=="level"},
            "context_window":{k:context[k] for k in ("remaining_percentage","used_percentage","context_window_size") if k in context},
            "rate_limits":{key:{k:v for k,v in item.items() if k in ("used_percentage","resets_at")}
                           for key,item in rates.items() if key in ("five_hour","seven_day") and isinstance(item,dict)},
            "worktree":{k:v for k,v in (data.get("worktree") or {}).items() if k=="branch"}}
    usage=context.get("current_usage")
    result["context_window"]["current_usage"]={k:v for k,v in usage.items() if k in (
        "input_tokens","cache_creation_input_tokens","cache_read_input_tokens")} if isinstance(usage,dict) else None
    if isinstance(result["workspace"].get("repo"),dict):
        result["workspace"]["repo"]={"name":result["workspace"]["repo"].get("name")}
    return result


def capture(data,directory=None):
    session_id=data.get("session_id","")
    if not isinstance(session_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",session_id):
        return
    directory=directory or DATA_ROOT/"output"/"claude"/"telemetry"
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/f"{session_id}.json"
    temporary=directory/f"{session_id}.{os.getpid()}.tmp"
    try:
        temporary.write_text(json.dumps(sanitize(data),ensure_ascii=False),encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if sys.stdout is not None and hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    raw=sys.stdin.buffer.read()
    data={}
    try:
        data=json.loads(raw)
        capture(data)
    except (ValueError,OSError,TypeError,AttributeError):
        pass
    try:
        bridge=json.loads(BRIDGE_CONFIG.read_text(encoding="utf-8"))
        original=(bridge.get("original_statusLine") or {}).get("command")
        if original:
            child=run_original(original,raw)
            if child.returncode==0 and child.stdout:
                sys.stdout.buffer.write(child.stdout)
                return
    except (OSError,ValueError,subprocess.TimeoutExpired):
        pass
    remaining=(data.get("context_window") or {}).get("remaining_percentage")
    model=(data.get("model") or {}).get("display_name","Claude")
    print(f"{model} | {round(remaining)}% context left" if isinstance(remaining,(int,float)) else model)


if __name__=="__main__":
    main()
