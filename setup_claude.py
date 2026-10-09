"""Install or remove the bridge without replacing the user's existing status line."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys
from times_gate.runtime import APP_ROOT, DATA_ROOT

ROOT=APP_ROOT


def decoded_command(command):
    match=re.search(r"-EncodedCommand\s+(\S+)",command,re.I)
    if match:
        try:
            return base64.b64decode(match.group(1)).decode("utf-16-le")
        except (ValueError,UnicodeError):
            pass
    return command


def is_bridge(command):
    command=decoded_command(command)
    return "claude_statusline.py" in command or ("TimesGateCLI.exe" in command and "--claude-statusline" in command)


def bridge_command():
    if getattr(sys,"frozen",False):
        helper=ROOT/"TimesGateCLI.exe"
        if not helper.is_file():
            raise ValueError("TimesGateCLI.exe not found; extract the whole package into one folder.")
        executable=helper.as_posix().replace("'","''")
        script=("[Console]::InputEncoding = [Text.UTF8Encoding]::new($false); "
                "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
                "$OutputEncoding = [Text.UTF8Encoding]::new($false); "
                f"[Console]::In.ReadToEnd() | & '{executable}' --claude-statusline; exit $LASTEXITCODE")
        encoded=base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"
    return f'"{Path(sys.executable).as_posix()}" "{(ROOT/"claude_statusline.py").as_posix()}"'


def previous_original(command,backup_file):
    """Recover the user's own status line from this or the old bridge's install record."""
    candidates=[backup_file]
    found=re.search(r'"([^"]*claude_statusline\.py)"',decoded_command(command))
    if found:
        candidates.append(Path(found.group(1)).parent/"output/claude/statusline-install.json")
    for path in candidates:
        try:
            original=json.loads(path.read_text(encoding="utf-8")).get("original_statusLine")
        except (OSError,ValueError,AttributeError):
            continue
        if not is_bridge((original or {}).get("command","")):
            return original
    return None


def install(settings_file,backup_file,command,remove=False):
    settings=json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
    original=settings.get("statusLine")
    if remove:
        backup=json.loads(backup_file.read_text(encoding="utf-8"))
        if (original or {}).get("command")!=backup.get("installed_command"):
            raise ValueError("The status line was changed since install; keeping the current settings.")
        restored=backup.get("original_statusLine")
        if restored is None:
            settings.pop("statusLine",None)
        else:
            settings["statusLine"]=restored
    else:
        if (original or {}).get("command")==command:
            return False
        # The project moved or its venv was rebuilt: re-point the bridge, never wrap it in itself.
        if is_bridge((original or {}).get("command","")):
            original=previous_original(original["command"],backup_file)
        backup_file.parent.mkdir(parents=True,exist_ok=True)
        backup_file.write_text(json.dumps({"original_statusLine":original,"installed_command":command},
                                         indent=2,ensure_ascii=False),encoding="utf-8")
        settings["statusLine"]={**(original or {}),"type":"command","command":command}
    settings_file.parent.mkdir(parents=True,exist_ok=True)
    temporary=settings_file.with_name(settings_file.name+".times-gate.tmp")
    temporary.write_text(json.dumps(settings,indent=2,ensure_ascii=False),encoding="utf-8")
    temporary.replace(settings_file)
    return True


def configure(remove=False):
    home=Path(os.environ.get("CLAUDE_CONFIG_DIR",str(Path.home()/".claude")))
    return install(home/"settings.json",DATA_ROOT/"output/claude/statusline-install.json",bridge_command(),remove)


def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description="Install the Claude Code status-line telemetry bridge")
    parser.add_argument("--remove",action="store_true")
    args=parser.parse_args()
    changed=configure(args.remove)
    print("Claude status line restored." if args.remove else
          "Claude telemetry bridge installed; your existing status line output is kept." if changed else
          "Claude telemetry bridge is already installed.")


if __name__=="__main__":
    main()
