# Times Gate Desk Terminal

Five 128×128 pixel-art panels for the [Divoom Times Gate](https://divoom.com), driven from a Windows PC:
Claude Code and Codex usage while you work, the game you are playing in the evening, and hand-built
day and night scenes in between.

## Modes

| Mode | LCD 1 | LCD 2 | LCD 3 | LCD 4 | LCD 5 |
|---|---|---|---|---|---|
| **WORK** | Agents (BUSY / READY) | Claude | Codex | Scene for the time of day | Weekly limits + clock |
| **GAME** | Cartridge with cover art | Session, level, XP | Health / break reminder | CPU / RAM | Arcade clock |
| **DAYLIGHT** | Today's sun path | Meadow | Sea | Lemonade + clock | Resting knight |
| **NIGHT** | Rain on the window | Campfire | Today's moon phase | Coffee + clock | Cat nap |

**AUTO** follows the clock: weekdays 07–09 DAYLIGHT, 09–18 WORK, 18–07 NIGHT; weekends 07–19 DAYLIGHT,
19–07 NIGHT. On weekday evenings/nights and at weekends a detected game switches the display to GAME
until the game closes. The rules live in `times_gate/schedule.py`.

- **Claude / Codex:** model, effort, context left, 5-hour and weekly limits left, BUSY / READY.
- **Games:** Steam games (running or launched directly from `steamapps`) show their cover, icon and
  total hours played; Xbox / Game Pass games use their `MicrosoftGame.config` name and logos; other
  fullscreen games show their executable's icon. Browsers, video players and office apps are ignored.
- **Scenes:** drawn procedurally on one ENDESGA 32 palette; the sun and moon panels use real
  astronomy (Istanbul by default, see `latitude` / `longitude` in the config).

## Windows package (no Python needed)

Copy `releases/TimesGateAI-Windows-x64.zip` to a Windows 10/11 64-bit PC, extract it to a permanent
folder and open **TimesGate.exe**. Allow it on private networks when Windows Firewall asks: the device
downloads every panel from the app. Enter the device IP and Divoom LocalToken, press **SEND NOW**, then
turn on **Auto send**. Keep the app running while you use the display. See `PORTABLE-README.txt`
(shipped as `README.txt`) for details and command-line options.

User data lives in `%LOCALAPPDATA%\TimesGateAI` and survives package updates. The package contains
no personal settings or tokens.

Build the package with `./build-package.ps1`: it runs the tests, builds `TimesGate.exe` and
`TimesGateCLI.exe` with PyInstaller, and writes the ZIP plus its SHA256.

## Running from source

Windows, Python 3.11+:

```powershell
./start.ps1          # creates .venv, connects the Claude bridge, opens the window
./start.ps1 -Demo    # sample data, nothing is sent to the device
./.venv/Scripts/python.exe app.py --once --mode night   # write PNG/GIF previews to output/panels
./.venv/Scripts/python.exe app.py --watch --send        # keep sending without a window
```

Machine-specific state stays in git-ignored files: `config.local.json` (device IP, LocalToken,
mode, location) and `output/` (previews and Claude telemetry).

## Where the data comes from

**Codex:** the JSONL session logs in `$CODEX_HOME/sessions` or `~/.codex/sessions` are read-only
watched. The latest main session is used (review/sub-agents are skipped); limits come from the
account-wide `codex` bucket.

**Claude Code** does not write usage to disk; it only passes it to its status line. The app adds a small
bridge to the `statusLine` command in `~/.claude/settings.json` (installed at every start, your own
status line keeps running). The bridge saves model, effort, context and limits to
`output/claude/telemetry/`. Remove it with `TimesGateCLI.exe --remove-claude` or
`python setup_claude.py --remove`.

The app never reads, stores or sends message contents. Missing data shows `--`; after a reset time
passes, `AWAITING UPDATE` is shown instead of guessing.

## Talking to the Times Gate

Panels are sent with `Device/PlayGif`: the app runs a small HTTP server (port 8477, answering only the
device's IP), and the device downloads each panel as a lossless GIF. Only changed panels are sent;
animated panels carry per-frame timing.

Lessons from the firmware, kept in `times_gate/device.py`:

- Pushing ~20 KB base64 JPEGs with `Draw/SendHttpGif` made the device drop off Wi-Fi after a few hundred
  uploads; the pull-based `Device/PlayGif` path with ~2 KB GIFs has been stable.
- The firmware draws GIF palette entry 0 as see-through, so every frame keeps that entry unused.
- After a failure the app waits 60 s before reconnecting, giving a rebooting device time for its cloud
  handshake. `device.log` records connects, uploads and failures.

## Tests

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```
