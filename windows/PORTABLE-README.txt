TIMES GATE DESK TERMINAL - WINDOWS 64 BIT

Windows 10/11 64 bit. No Python install or administrator rights needed.

GETTING STARTED
1. Extract the whole ZIP into a permanent folder. Do not run it from inside the ZIP.
2. Double-click TimesGate.exe.
3. Allow TimesGate.exe on private networks when Windows Firewall asks.
   The Times Gate downloads every panel from this app; without the permission
   the screens do not update.
4. Enter the Times Gate IP address and the Divoom LocalToken, then SAVE.
5. Press SEND NOW once, and turn on "Auto send" for continuous updates.

Keep the app running while you use the display. If the app is closed and the
Times Gate restarts, its screens can stay on "loading" until the app is back.

MODES
AUTO      Follows the clock:
            Weekdays  07:00-09:00 DAYLIGHT, 09:00-18:00 WORK, 18:00-07:00 NIGHT
            Weekends  07:00-19:00 DAYLIGHT, 19:00-07:00 NIGHT
          A detected game switches to GAME on weekday evenings/nights and at
          weekends, and the clock takes over again when the game closes.
WORK      Claude and Codex usage, a scene for the time of day, weekly limits
          and the clock.
GAME      The game you are playing: cover art, session time, a break reminder,
          CPU/RAM and an arcade clock. Steam and Xbox (Game Pass) games show
          their own art; other fullscreen games show their icon.
DAYLIGHT  Sun path for today, meadow, sea, lemonade with the clock, resting knight.
NIGHT     Rain on the window, campfire, today's moon phase, coffee with the
          clock, sleeping cat.

The sun panel uses Istanbul by default. To use another place, set "latitude"
and "longitude" in %LOCALAPPDATA%\TimesGateAI\config.local.json.

CLAUDE AND CODEX
Claude and Codex usage is read from this computer's own sessions, so use
Claude Code / Codex on this computer. Codex is read directly from its session
files. Claude Code only hands these numbers to its status line, so the app adds
a small bridge to Claude Code's settings at every start; your own status line
keeps working. Limits refresh with the next Claude reply.

YOUR DATA: %LOCALAPPDATA%\TimesGateAI
config.local.json   device settings and preferences
device.log          device connection log
output              panel previews and Claude telemetry

UPDATING
Extract the new files into the same folder. Keep TimesGateCLI.exe and the
_internal folder next to TimesGate.exe. On a new computer, enter the device
settings again. This ZIP contains no personal settings, tokens or telemetry.

COMMAND LINE (PowerShell)
./TimesGateCLI.exe --once --demo        Write sample PNGs, nothing is sent
./TimesGateCLI.exe --once --send        Send to the device once
./TimesGateCLI.exe --watch --send       Keep sending
./TimesGateCLI.exe --mode night ...     Pick a mode: auto, work, game, daylight, night
./TimesGateCLI.exe --install-claude     Install the Claude bridge
./TimesGateCLI.exe --remove-claude      Restore your previous Claude status line
./TimesGateCLI.exe --paths              Show the program and data folders

You need access to the Times Gate on your local network.
If the app does not start, see %LOCALAPPDATA%\TimesGateAI\startup-error.log.
