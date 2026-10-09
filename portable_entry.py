"""Shared entry point for the desktop executable and console helper."""
import json
import os
from pathlib import Path
import sys
import traceback

from times_gate.runtime import APP_ROOT, DATA_ROOT


def cli():
    if sys.stdout is not None and hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args=sys.argv[1:]
    if args==["--paths"]:
        print(json.dumps({"app_root":str(APP_ROOT),"data_root":str(DATA_ROOT),"frozen":bool(getattr(sys,"frozen",False))}))
        return 0
    if args==["--claude-statusline"]:
        import claude_statusline
        claude_statusline.main()
        return 0
    if args in (["--install-claude"],["--remove-claude"]):
        from setup_claude import configure
        try:
            configure(remove=args==["--remove-claude"])
            print("Claude bridge removed." if args==["--remove-claude"] else "Claude bridge installed.")
            return 0
        except (OSError,ValueError) as exc:
            print(str(exc),file=sys.stderr)
            return 1
    import app
    return app.main()


def gui():
    # Windowed Windows executables have no standard streams.
    if sys.stdout is None:
        sys.stdout=open(os.devnull,"w",encoding="utf-8")
    if sys.stderr is None:
        sys.stderr=open(os.devnull,"w",encoding="utf-8")
    try:
        if "--demo" not in sys.argv:
            home=Path(os.environ.get("CLAUDE_CONFIG_DIR",str(Path.home()/".claude")))
            if home.is_dir():
                from setup_claude import configure
                try:
                    configure()
                except (OSError,ValueError):
                    # The dashboard still works; the bridge is retried at the next start.
                    pass
        import app
        return app.main()
    except Exception:
        DATA_ROOT.mkdir(parents=True,exist_ok=True)
        log=DATA_ROOT/"startup-error.log"
        log.write_text(traceback.format_exc(),encoding="utf-8")
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,f"The app could not start. Details: {log}","Times Gate",0x10)
        return 1


if __name__=="__main__":
    console=Path(sys.executable).stem.casefold()=="timesgatecli"
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        console=True
    raise SystemExit(cli() if console else gui())
