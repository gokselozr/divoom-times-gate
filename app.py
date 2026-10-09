"""Times Gate desk terminal: work, game, daylight and night modes, export and headless watch."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from times_gate.codex import CodexReader, demo_snapshot as codex_demo_snapshot
from times_gate.claude import ClaudeReader, demo_snapshot as claude_demo_snapshot
from times_gate.device import TimesGate, DeviceError
from times_gate.render import Board, FRAME_MS, render, overview, agent_state
from times_gate import daylight, game, night, schedule
from times_gate.polling import AsyncSource
from times_gate.codex import Snapshot
from times_gate.runtime import APP_ROOT, DATA_ROOT

ROOT = APP_ROOT
CONFIG = DATA_ROOT / "config.local.json"
OUTPUT = DATA_ROOT / "output" / "panels"
MODES = ("work","game","daylight","night")
# What the user can pick: a fixed mode, or auto (clock schedule, with games taking over after hours).
CHOICES = ("auto",) + MODES
MODE_TITLES = {"work":("AGENTS","CLAUDE","CODEX","SCENE","WEEKLY"),"game":game.TITLES,
               "daylight":daylight.TITLES,"night":night.TITLES}
DEFAULTS = {"device_ip":"", "local_token":"", "endpoint":"auto", "codex_home":"", "claude_home":"",
            "repo":"", "poll_seconds":5, "send_seconds":20, "auto_send":False, "mode":"work",
            "latitude":daylight.ISTANBUL[0], "longitude":daylight.ISTANBUL[1]}


def load_config():
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8"))
        config = {**DEFAULTS, **{k:v for k,v in value.items() if k in DEFAULTS}}
        # Chill mode was renamed to night.
        if config["mode"] == "chill":
            config["mode"] = "night"
        return config
    except (FileNotFoundError, ValueError):
        return dict(DEFAULTS)


def save_config(value):
    # Atomic write; the local device token is never included in exported snapshots.
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")
    temporary.replace(CONFIG)


def demo_board():
    board = Board(claude=claude_demo_snapshot(), codex=codex_demo_snapshot())
    board.claude.state, board.claude.finished_at = "done", time.time() - 60
    board.codex.state = "working"
    return board


def demo_game():
    return game.GameSnapshot(name="Pixel Quest",source="demo",started_at=time.time()-47*60,cpu=42,ram=58)


def location(config):
    try:
        return float(config["latitude"]), float(config["longitude"])
    except (KeyError, TypeError, ValueError):
        return daylight.ISTANBUL


def panel_names(mode):
    return [f"{i+1:02}-{title.lower().replace(' ','-')}" for i,title in enumerate(MODE_TITLES[mode])]


def durations(frames):
    return [frame.info.get("duration",FRAME_MS) for frame in frames]


class Engine:
    AGENT_SOURCES = ("claude","codex")

    def __init__(self, config, demo=False):
        self.config = config
        self.demo = demo
        home = lambda key: Path(config[key]) if config.get(key) else None
        self.claude = ClaudeReader(home("claude_home"),config["repo"])
        self.codex = CodexReader(home("codex_home"),config["repo"])
        self.ready=threading.Event()
        self.sources={key:AsyncSource(reader,snapshot,self.ready,config["poll_seconds"])
                      for key,reader,snapshot in (("claude",self.claude,Snapshot(provider="claude")),
                                                  ("codex",self.codex,Snapshot()),
                                                  ("game",game.GameReader(),game.GameSnapshot()))}
        self.device = None
        self.last_send = 0
        self.hashes = {}
        self.status = "Preview ready · sending to the device is off"
        self.active_mode = self.mode if self.mode in MODES else schedule.scheduled_mode(time.time())

    @property
    def mode(self):
        """The configured choice: a fixed mode or "auto"."""
        return self.config.get("mode") if self.config.get("mode") in CHOICES else "work"

    def resolve(self, now, wait=False):
        """The mode to show now and the game snapshot it needs."""
        choice = self.mode
        if choice != "auto":
            return choice, (self.game(wait) if choice == "game" else game.GameSnapshot())
        mode = schedule.scheduled_mode(now)
        # Game detection only runs when a game is allowed to take over; work hours never poll it.
        if schedule.game_allowed(now):
            playing = self.game(wait)
            if playing.name:
                return "game", playing
        return mode, game.GameSnapshot()

    def board(self,wait=False):
        if self.demo:
            return demo_board()
        self.ready.clear()
        for key in self.AGENT_SOURCES:
            self.sources[key].request()
        if wait:
            # One-shot exports get a bounded initial read; desktop updates never wait on network IO.
            deadline=time.monotonic()+5
            for key in self.AGENT_SOURCES:
                self.sources[key].wait(deadline-time.monotonic())
        board = Board()
        for key in self.AGENT_SOURCES:
            snapshot,error=self.sources[key].current()
            setattr(board,key,snapshot)
            if error:
                self.status=f"Could not read {key.upper()}: {error}"
        return board

    def game(self,wait=False):
        if self.demo:
            return demo_game()
        source = self.sources["game"]
        source.request()
        if wait:
            source.wait(2)
        snapshot,error = source.current()
        if error:
            self.status = f"Game detection: {error}"
        return snapshot

    def close(self):
        for source in self.sources.values():
            source.close()
        if self.device is not None:
            self.device.close()

    def tick(self, force=False, wait=False):
        # Cleared here, not only in board(): demo boards return early and would leave the worker spinning.
        self.ready.clear()
        now = time.time()
        board = self.board(wait)
        mode, playing = self.resolve(now, wait)
        self.active_mode = mode
        if mode == "game":
            panels = game.render_game(playing,now)
        elif mode == "night":
            panels = night.render_night(now)
        elif mode == "daylight":
            panels = daylight.render_daylight(now,location(self.config))
        else:
            panels = render(board,now,location(self.config))
        names = panel_names(mode)
        OUTPUT.mkdir(parents=True,exist_ok=True)
        changed = set()
        for name,frames in zip(names,panels):
            digest = hashlib.sha256(b"".join(f.tobytes() for f in frames)).hexdigest()
            if self.hashes.get(name) != digest:
                frames[0].save(OUTPUT / f"{name}.png")
                if len(frames) > 1:
                    frames[0].save(OUTPUT / f"{name}.gif",save_all=True,append_images=frames[1:],
                                   duration=durations(frames),loop=0)
                self.hashes[name] = digest
                changed.add(name)
        if changed:
            overview(panels).save(OUTPUT / "preview.png")
        data = {"demo":self.demo,"mode":mode,"choice":self.mode,"captured_at":now,**{k:asdict(v) for k,v in vars(board).items()},
                "game":{"name":playing.name,"source":playing.source,"started_at":playing.started_at},
                "claude_context_left":board.claude.context_left,"codex_context_left":board.codex.context_left}
        (OUTPUT / "status.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
        # BUSY / READY and a newly detected game should not wait for the normal send throttle.
        due = force or now-self.last_send >= self.config["send_seconds"] or names[0] in changed
        if (force or self.config["auto_send"]) and not self.demo and due:
            self.last_send = now
            try:
                if self.device is None:
                    self.device = TimesGate(self.config["device_ip"],int(self.config["local_token"]),self.config["endpoint"])
                count = self.device.send(panels,force,FRAME_MS)
                self.status = f"Connected · {count} panels updated"
            except (ValueError,DeviceError) as exc:
                self.status = str(exc)
        elif self.demo:
            self.status = "DEMO · sample data · nothing is sent to the device"
        return panels,board,playing,self.status


def open_folder(path):
    path.mkdir(parents=True,exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open",str(path)])


def elapsed(seconds):
    minutes = max(0,int(seconds//60))
    return f"{minutes//60} h {minutes%60:02} min"


def desktop(config,demo=False):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from PIL import ImageTk, Image

    window = tk.Tk()
    config = {**DEFAULTS,**config}
    window.title("Times Gate · Desk Terminal")
    window.geometry("1420x740")
    window.minsize(1120,680)
    bg = "#0b1418"
    card = "#122126"
    edge = "#25393e"
    fg = "#dfe8d3"
    muted = "#8ca09c"
    accents = {"auto":"#c0cbdc","work":"#ffbf69","game":"#2ce8f5","daylight":"#fee761","night":"#f6757a"}
    window.configure(bg=bg)
    style = ttk.Style(window)
    style.theme_use("clam")
    for name,background in (("",bg),("Card.",card)):
        style.configure(f"{name}TFrame",background=background)
        style.configure(f"{name}TLabel",background=background,foreground=muted,font=("Consolas",9))
        style.configure(f"{name}TCheckbutton",background=background,foreground=fg,font=("Consolas",10))
        style.map(f"{name}TCheckbutton",background=[("active",background)])
    style.configure("TButton",background="#23383c",foreground=fg,font=("Consolas",10),padding=(10,6),borderwidth=0)
    style.map("TButton",background=[("active","#365255"),("disabled","#162529")])
    style.configure("TEntry",fieldbackground="#0e1a1e",foreground=fg,insertcolor=fg,padding=5)
    style.configure("TCombobox",fieldbackground="#0e1a1e",foreground=fg,padding=5)
    style.map("TCombobox",fieldbackground=[("readonly","#0e1a1e")],
              foreground=[("readonly",fg)],selectbackground=[("readonly","#0e1a1e")],
              selectforeground=[("readonly",fg)])

    # Header: name on the left, the three modes as one segmented switch on the right.
    header = tk.Frame(window,bg=bg)
    header.pack(fill="x",padx=26,pady=(20,6))
    title = tk.Label(header,text="DESK // TERMINAL",font=("Consolas",22,"bold"),bg=bg)
    title.pack(side="left")
    tk.Label(header,text="TIMES GATE  ·  5 x 128",font=("Consolas",10),fg=muted,bg=bg).pack(side="left",padx=(16,0),pady=(8,0))
    switch = tk.Frame(header,bg=edge,padx=1,pady=1)
    switch.pack(side="right")
    mode_buttons = {}
    for key,label in (("auto","AUTO"),("work","WORK"),("game","GAME"),("daylight","DAYLIGHT"),("night","NIGHT")):
        button = tk.Button(switch,text=label,font=("Consolas",11,"bold"),relief="flat",bd=0,padx=22,pady=7,
                           cursor="hand2",command=lambda k=key: set_mode(k))
        button.pack(side="left",padx=(0 if key == "auto" else 1,0))
        mode_buttons[key] = button

    board_frame = tk.Frame(window,bg=bg)
    board_frame.pack(fill="x",padx=20,pady=(8,0))
    labels, captions = [], []
    for i in range(5):
        board_frame.columnconfigure(i,weight=1,uniform="panels")
        frame = tk.Frame(board_frame,bg=card,highlightbackground=edge,highlightthickness=1)
        frame.grid(row=0,column=i,padx=5,pady=6,sticky="nsew")
        caption = tk.Label(frame,fg=muted,bg=card,font=("Consolas",9),anchor="w")
        caption.pack(fill="x",padx=10,pady=(8,0))
        label = tk.Label(frame,bg=card)
        label.pack(expand=True,padx=8,pady=(5,10))
        label.frames, label.durations, label.frame, label.next_at = [], [], 0, 0
        labels.append(label)
        captions.append(caption)

    status = tk.StringVar(value="Reading sessions...")
    details = tk.StringVar(value="")
    status_bar = tk.Frame(window,bg=bg)
    status_bar.pack(fill="x",padx=26,pady=(4,8))
    status_label = tk.Label(status_bar,textvariable=status,font=("Consolas",10),bg=bg,anchor="w")
    status_label.pack(fill="x")
    tk.Label(status_bar,textvariable=details,font=("Consolas",9),bg=bg,fg=muted,anchor="w").pack(fill="x")

    cards = tk.Frame(window,bg=bg)
    cards.pack(fill="x",padx=20,pady=(0,18))
    cards.columnconfigure(0,weight=1,uniform="cards")
    cards.columnconfigure(1,weight=1,uniform="cards")

    def make_card(column,heading):
        frame = tk.Frame(cards,bg=card,highlightbackground=edge,highlightthickness=1,padx=14,pady=10)
        frame.grid(row=0,column=column,padx=5,sticky="nsew")
        tk.Label(frame,text=heading,font=("Consolas",10,"bold"),fg=fg,bg=card,anchor="w").grid(
            row=0,column=0,columnspan=4,sticky="w",pady=(0,8))
        return frame

    def field(parent,row,column,label,variable,width,show="",values=None,span=1):
        box = ttk.Frame(parent,style="Card.TFrame")
        box.grid(row=row,column=column,columnspan=span,padx=(0,12),pady=(0,8),sticky="w")
        ttk.Label(box,text=label,style="Card.TLabel").pack(anchor="w",pady=(0,3))
        if values:
            ttk.Combobox(box,textvariable=variable,values=values,state="readonly",width=width).pack(anchor="w")
        else:
            ttk.Entry(box,textvariable=variable,width=width,show=show).pack(anchor="w")

    variables = {k:tk.StringVar(value=str(config[k])) for k in ("device_ip","local_token","endpoint","repo")}
    auto = tk.BooleanVar(value=config["auto_send"])

    device_card = make_card(0,"DEVICE")
    field(device_card,1,0,"Device IP",variables["device_ip"],16)
    field(device_card,1,1,"LocalToken",variables["local_token"],10,"*")
    field(device_card,1,2,"API",variables["endpoint"],7,values=("auto","9000","80"))
    ttk.Checkbutton(device_card,text="Auto send",variable=auto,style="Card.TCheckbutton").grid(
        row=1,column=3,sticky="sw",pady=(0,12))
    device_actions = ttk.Frame(device_card,style="Card.TFrame")
    device_actions.grid(row=2,column=0,columnspan=4,sticky="w")

    sources_card = make_card(1,"CLAUDE & CODEX")
    field(sources_card,1,0,"Pin repo (empty = latest session)",variables["repo"],30,span=2)
    tk.Label(sources_card,text="Usage is read from this computer's Claude Code and Codex sessions.",
             font=("Consolas",9),bg=card,fg=muted,anchor="w").grid(row=2,column=0,columnspan=4,sticky="w")

    events = queue.Queue()
    requests = queue.Queue()
    stop = threading.Event()
    running = {}
    shown = {"mode":config["mode"] if config["mode"] in MODES else schedule.scheduled_mode(time.time())}

    def request(values,force):
        requests.put((values,force))
        # Wake the worker so a mode switch or "send now" does not wait for the next poll.
        if "engine" in running:
            running["engine"].ready.set()

    def paint_mode(active=None):
        """Highlight the chosen button; colour and captions follow the mode actually shown."""
        choice = config["mode"] if config["mode"] in CHOICES else "work"
        if active is None:
            active = shown["mode"] if choice == "auto" else choice
        shown["mode"] = active
        accent = accents[active]
        title.configure(fg=accent)
        status_label.configure(fg=accent)
        for key,button in mode_buttons.items():
            selected = key == choice
            button.configure(bg=accents[key] if selected else card,fg=bg if selected else muted,
                             activebackground=accents[key],activeforeground=bg)
        for i,caption in enumerate(captions):
            caption.configure(text=f"LCD {i+1:02} · {MODE_TITLES[active][i]}")

    def set_mode(mode):
        if config["mode"] == mode:
            return
        config["mode"] = mode
        save_config(config)
        paint_mode()
        # With auto send on, a new mode reaches the device right away.
        request(dict(config),bool(config["auto_send"]) and not demo)

    def settings_values():
        return {**config,**{k:v.get().strip() for k,v in variables.items()},"auto_send":auto.get()}

    def submit(force=False):
        updated = settings_values()
        if (force or updated["auto_send"]) and not demo:
            try:
                from times_gate.device import validate_address
                validate_address(updated["device_ip"])
                int(updated["local_token"])
            except ValueError:
                messagebox.showerror("Connection","Enter a valid device IP address and a numeric LocalToken.")
                return
        config.update(updated)
        save_config(config)
        request(dict(config),force)

    ttk.Button(device_actions,text="SAVE",command=submit).pack(side="left")
    ttk.Button(device_actions,text="SEND NOW",command=lambda:submit(True)).pack(side="left",padx=8)
    ttk.Button(device_actions,text="PREVIEW FILES",command=lambda:open_folder(OUTPUT)).pack(side="left")

    def same_engine(a,b):
        # Switching modes keeps the engine, its device link and frame server.
        return {k:v for k,v in a.items() if k != "mode"} == {k:v for k,v in b.items() if k != "mode"}

    def worker():
        engine = running["engine"] = Engine(dict(config),demo)
        try:
            while not stop.is_set():
                force = False
                try:
                    while True:
                        updated,send_now = requests.get_nowait()
                        if not same_engine(updated,engine.config):
                            engine.close()
                            engine = running["engine"] = Engine(updated,demo)
                        else:
                            engine.config = updated
                        force = force or send_now
                except queue.Empty:
                    pass
                try:
                    events.put(("board",(*engine.tick(force),engine.active_mode)))
                except Exception as exc:
                    events.put(("error",f"Could not read data: {type(exc).__name__}"))
                engine.ready.wait(max(1,float(engine.config["poll_seconds"])))
        finally:
            engine.close()

    def describe(mode,board,playing):
        detail = describe_mode(mode,board,playing)
        if config["mode"] != "auto" or demo:
            return detail
        upcoming = time.strftime("%H:%M",time.localtime(schedule.next_change(time.time())))
        return f"AUTO → {mode.upper()} · next change {upcoming}   |   {detail}"

    def describe_mode(mode,board,playing):
        if demo:
            return "DEMO"
        if mode == "game":
            if not playing.name:
                return "No game detected · watching Steam, Xbox and fullscreen apps"
            source = {"steam":"Steam","xbox":"Xbox","window":"Fullscreen"}.get(playing.source,playing.source)
            return f"GAME: {playing.name} · {source} · {elapsed(time.time()-playing.started_at)}"
        if mode == "night":
            angle = night.moon_phase(time.time())
            return f"NIGHT · Moon: {night.phase_name(angle).title()} · scenes are drawn on this computer"
        if mode == "daylight":
            lat,lon = location(config)
            rise,sets,_ = daylight.sun_day(daylight.local_midnight(time.time()),lat,lon)
            return (f"DAYLIGHT · sunrise {daylight.hhmm(rise)} · sunset {daylight.hhmm(sets)}"
                    f" · location {lat:.2f}, {lon:.2f}")
        parts = []
        for key in ("claude","codex"):
            snap = getattr(board,key)
            age = int(max(0,time.time()-snap.observed_at)) if snap.observed_at else None
            parts.append(f"{key.upper()}: {snap.session_id[:8] or '--'} · {age if age is not None else '--'} s ago")
        return "   |   ".join(parts)

    def show(panels):
        size = max(140,min(256,(window.winfo_width()-110)//5))
        for label,frames in zip(labels,panels):
            # Unchanged panels keep their images and their place in the animation.
            key = (size,tuple(id(f) for f in frames),hash(b"".join(f.tobytes() for f in frames)))
            if getattr(label,"key",None) == key:
                continue
            label.key = key
            label.frames = [ImageTk.PhotoImage(f.resize((size,size),Image.Resampling.NEAREST)) for f in frames]
            label.durations = durations(frames)
            label.frame, label.next_at = 0, 0
            label.configure(image=label.frames[0])

    def update():
        latest = None
        try:
            while True:
                kind,value = events.get_nowait()
                if kind == "error":
                    status.set(value)
                else:
                    # Only the newest board is drawn; older ones in the queue are already stale.
                    latest = value
        except queue.Empty:
            pass
        if latest is not None:
            panels,board,playing,message,mode = latest
            if mode != shown["mode"]:
                paint_mode(mode)
            show(panels)
            status.set(message)
            details.set(describe(mode,board,playing))
        if not stop.is_set():
            window.after(500,update)

    def animate():
        # Each panel keeps its own pace: rain is quick, the cat breathes slowly.
        now = time.monotonic()
        for label in labels:
            if len(label.frames) > 1 and now >= label.next_at:
                label.frame = (label.frame + 1) % len(label.frames)
                label.configure(image=label.frames[label.frame])
                label.next_at = now + label.durations[label.frame] / 1000
        if not stop.is_set():
            window.after(20,animate)

    def close():
        stop.set()
        window.destroy()

    paint_mode()
    threading.Thread(target=worker,daemon=True,name="ai-dashboard").start()
    window.protocol("WM_DELETE_WINDOW",close)
    window.after(100,update)
    window.after(20,animate)
    window.mainloop()


def main():
    if sys.stdout is not None and hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8",errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Claude / Codex usage, games and pixel scenes on a Divoom Times Gate")
    parser.add_argument("--once",action="store_true",help="Export current panels and exit")
    parser.add_argument("--watch",action="store_true",help="Refresh continuously without a desktop window")
    parser.add_argument("--send",action="store_true",help="Send live panels to the configured device")
    parser.add_argument("--demo",action="store_true",help="Preview sample data without device writes")
    parser.add_argument("--repo",help="Pin a workspace by name or exact path")
    parser.add_argument("--mode",choices=CHOICES,help="Panel set: auto, work, game, daylight or night")
    args = parser.parse_args()
    config = load_config()
    if args.repo is not None:
        config["repo"] = args.repo
    if args.mode is not None:
        config["mode"] = args.mode
    if args.demo and args.send:
        parser.error("Demo data is never sent to the device. Remove --send.")
    if args.once or args.watch:
        # CLI export is read-only unless --send is explicitly supplied.
        config["auto_send"] = args.send
        engine = Engine(config,args.demo)
        try:
            while True:
                _,board,playing,status = engine.tick(force=args.once and args.send,wait=args.once)
                observed=time.time()
                if engine.active_mode == "game":
                    line = f"GAME {playing.name or '--'} | CPU {playing.cpu or 0:.0f}% RAM {playing.ram or 0:.0f}%"
                elif engine.active_mode == "night":
                    line = f"NIGHT | {night.phase_name(night.moon_phase(observed))}"
                elif engine.active_mode == "daylight":
                    rise,sets,_ = daylight.sun_day(daylight.local_midnight(observed),*location(config))
                    line = f"DAYLIGHT | SUN {daylight.hhmm(rise)}-{daylight.hhmm(sets)}"
                else:
                    line = (f"CLAUDE {board.claude.model} {agent_state(board.claude,observed)} | CODEX {board.codex.model} "
                            f"{agent_state(board.codex,observed)}")
                print(f"{line} | {status}",flush=True)
                if args.once:
                    return 1 if args.send and not status.startswith("Connected") else 0
                engine.ready.wait(max(1,float(config["poll_seconds"])))
        except KeyboardInterrupt:
            return 0
        finally:
            engine.close()
    else:
        if args.send:
            config["auto_send"] = True
        desktop(config,args.demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
