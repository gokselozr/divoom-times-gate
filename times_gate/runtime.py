"""Stable paths for source checkouts and the Windows distribution."""
import os
from pathlib import Path
import sys


def app_root():
    if getattr(sys,"frozen",False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_root():
    override=os.environ.get("TIMES_GATE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys,"frozen",False):
        local=Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home()/"AppData/Local"
        return local/"TimesGateAI"
    return app_root()


APP_ROOT=app_root()
DATA_ROOT=data_root()
