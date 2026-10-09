import calendar
import io
import math
import tempfile
import time
from pathlib import Path
import unittest
from unittest import mock

from PIL import Image

import app
from times_gate import daylight, game, night, schedule
from times_gate.device import gif_bytes


def utc(*parts):
    return calendar.timegm((*parts, 0, 0, 0))


def png(color, size):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class NightTests(unittest.TestCase):
    def test_moon_phase_matches_known_new_and_full_moons(self):
        new = night.moon_phase(utc(2024, 4, 8, 18, 21))
        full = night.moon_phase(utc(2024, 4, 23, 23, 49))
        self.assertLess(min(new, 2 * math.pi - new), 0.1)
        self.assertLess(abs(full - math.pi), 0.1)
        self.assertEqual(night.phase_name(full), "FULL MOON")
        self.assertEqual(night.phase_name(math.pi / 2), "FIRST QUARTER")

    def test_scenes_animate_and_stay_identical_within_a_minute(self):
        now = utc(2026, 10, 9, 20, 15) + 5
        panels = night.render_night(now)
        self.assertEqual(len(panels), 5)
        for frames in panels:
            self.assertGreater(len(frames), 1)
            self.assertTrue(all(f.size == (128, 128) and f.info["duration"] > 0 for f in frames))
        later = night.render_night(now + 40)
        self.assertEqual([[f.tobytes() for f in p] for p in panels], [[f.tobytes() for f in p] for p in later])


class DaylightTests(unittest.TestCase):
    def test_istanbul_sunrise_and_sunset_match_published_times(self):
        # 21 June 2024 in Istanbul: sunrise 05:32, sunset 20:39 local time (UTC+3).
        midnight = utc(2024, 6, 21, 0, 0) - 3 * 3600
        rise, sets, peak = daylight.sun_day(midnight, *daylight.ISTANBUL)
        self.assertLess(abs(rise - (midnight + 5 * 3600 + 32 * 60)), 5 * 60)
        self.assertLess(abs(sets - (midnight + 20 * 3600 + 39 * 60)), 5 * 60)
        self.assertAlmostEqual(peak, 90 - 41.01 + 23.44, delta=1)

    def test_scenes_animate_and_sun_panel_follows_the_day(self):
        noon = utc(2026, 10, 9, 10, 0)
        panels = daylight.render_daylight(noon)
        self.assertEqual(len(panels), 5)
        for frames in panels:
            self.assertGreater(len(frames), 1)
            self.assertTrue(all(f.size == (128, 128) and f.info["duration"] > 0 for f in frames))
        evening = daylight.render_daylight(noon + 9 * 3600)
        self.assertNotEqual(panels[0][0].tobytes(), evening[0][0].tobytes())
        self.assertEqual(panels[2][0].tobytes(), evening[2][0].tobytes())


class GameRenderTests(unittest.TestCase):
    def test_panels_for_idle_and_playing(self):
        now = utc(2026, 10, 9, 20, 15)
        idle = game.render_game(game.GameSnapshot(cpu=10, ram=40), now)
        playing = game.GameSnapshot(name="Kerbal Space Program", source="steam", started_at=now - 83 * 60,
                                    icon=png("#336699", (32, 32)), cover=png("#cc4422", (300, 450)), cpu=37, ram=61)
        busy = game.render_game(playing, now)
        self.assertEqual(len(idle), len(busy))
        for frames in idle + busy:
            self.assertTrue(all(f.size == (128, 128) for f in frames))
        # The cartridge label carries the cover art, posterized into the palette's red.
        row = [busy[0][0].getpixel((x, 60)) for x in range(28, 100)]
        self.assertTrue(any(r > 150 and g < 100 and b < 100 for r, g, b in row))
        self.assertNotEqual(idle[1][0].tobytes(), busy[1][0].tobytes())

    def test_health_runs_out_after_an_hour_and_score_counts_minutes(self):
        now = utc(2026, 10, 9, 20, 15)
        fresh = game.health_panel(game.GameSnapshot(name="x", started_at=now - 60), now)
        tired = game.health_panel(game.GameSnapshot(name="x", started_at=now - 61 * 60), now)
        self.assertNotEqual(fresh[0].tobytes(), tired[0].tobytes())
        self.assertEqual(game.wrap("Kerbal Space Program", 13, 2), ["KERBAL SPACE", "PROGRAM"])


class SteamDataTests(unittest.TestCase):
    def test_playtime_is_read_from_the_active_users_localconfig(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = folder / "userdata" / "42" / "config"
            config.mkdir(parents=True)
            (config / "localconfig.vdf").write_text('''"UserLocalConfigStore"
{
	"Software" { "Valve" { "Steam" { "apps" {
		"220200" { "cloud" { "last_sync_state" "synchronized" } "LastPlayed" "1734874771" "Playtime" "2553" }
		"730" { "Playtime" "12" }
	} } } }
}''', encoding="utf-8")
            with mock.patch.object(game, "sys") as fake:
                fake.platform = "linux"
                self.assertEqual(game.steam_playtime(folder, 220200), 2553)
                self.assertEqual(game.steam_playtime(folder, 999), 0)
            self.assertEqual(game.steam_playtime(folder / "missing", 220200), 0)

    def test_arcade_spins_the_game_icon_instead_of_the_coin(self):
        coin = game.arcade_frames(100, 0, True)
        icon = game.arcade_frames(100, 0, True, png("#336699", (32, 32)))
        self.assertEqual(len(coin), len(icon))
        self.assertNotEqual(coin[0].tobytes(), icon[0].tobytes())
        # The blue icon shows up (mapped onto a palette blue) where the coin would be.
        row = [icon[0].getpixel((x, 38)) for x in range(40, 90)]
        self.assertTrue(any(b > 120 and b > r + 40 for r, g, b in row))


class LauncherDataTests(unittest.TestCase):
    def test_xbox_game_uses_its_config_name_and_logos(self):
        with tempfile.TemporaryDirectory() as directory:
            content = Path(directory) / "Brotato" / "Content"
            content.mkdir(parents=True)
            (content / "MicrosoftGame.config").write_text(
                '<Game configVersion="1"><ShellVisuals DefaultDisplayName="Brotato" '
                'Square150x150Logo="Square150x150Logo.png" Square44x44Logo="Square44x44Logo.png"/></Game>',
                encoding="utf-8")
            Image.new("RGB", (150, 150), "#aa3311").save(content / "Square150x150Logo.png")
            Image.new("RGB", (44, 44), "#11aa33").save(content / "Square44x44Logo.png")
            name, icon, cover = game.xbox_details(str(content / "Brotato.exe"))
            self.assertEqual(name, "Brotato")
            self.assertEqual(Image.open(io.BytesIO(icon)).size, (44, 44))
            self.assertEqual(Image.open(io.BytesIO(cover)).size, (150, 150))
            self.assertIsNone(game.xbox_details(str(Path(directory) / "elsewhere" / "x.exe")))

    def test_steam_game_started_outside_steam_is_matched_by_its_install_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            steam = Path(directory) / "Steam"
            library = Path(directory) / "Library"
            (steam / "steamapps").mkdir(parents=True)
            (library / "steamapps").mkdir(parents=True)
            (steam / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders" { "0" { "path" "' + str(steam).replace("\\", "\\\\") + '" } '
                '"1" { "path" "' + str(library).replace("\\", "\\\\") + '" } }', encoding="utf-8")
            (library / "steamapps" / "appmanifest_1145360.acf").write_text(
                '"AppState" { "appid" "1145360" "name" "Hades" "installdir" "Hades" }', encoding="utf-8")
            self.assertEqual(game.steam_installs(steam), {"hades": (1145360, "Hades")})
            reader = game.GameReader()
            with mock.patch.object(game, "steam_folder", return_value=steam),                  mock.patch.object(game, "steam_art", return_value=(b"icon", b"cover")),                  mock.patch.object(game, "steam_playtime", return_value=600),                  mock.patch.object(game, "exe_icon", return_value=b"exe"):
                described = reader.describe(str(library / "steamapps" / "common" / "Hades" / "x64" / "Hades.exe"),
                                            "HADES", 5.0)
            self.assertEqual(described, ("Hades", "steam", 5.0, b"icon", b"cover", 600))


class GameReaderTests(unittest.TestCase):
    def reader(self, steam=None, front=None, processes=None):
        patches = [mock.patch.object(game, "steam_running", return_value=steam),
                   mock.patch.object(game, "steam_art", return_value=(b"icon", b"cover")),
                   mock.patch.object(game, "foreground", side_effect=lambda: front[0] if front else None),
                   mock.patch.object(game, "process_info", side_effect=lambda pid: (processes or {}).get(pid)),
                   mock.patch.object(game, "exe_icon", return_value=b"exe"),
                   mock.patch.object(game, "system_times", return_value=(0, 0)),
                   mock.patch.object(game, "memory_load", return_value=50.0),
                   mock.patch.object(game, "steam_folder", return_value=None)]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return game.GameReader()

    def test_steam_game_keeps_its_start_time(self):
        reader = self.reader(steam=(220200, "Kerbal Space Program", Path("steam")))
        first = reader.poll()
        self.assertEqual((first.name, first.source, first.icon, first.cover),
                         ("Kerbal Space Program", "steam", b"icon", b"cover"))
        self.assertEqual(reader.poll().started_at, first.started_at)

    def test_browser_is_not_a_game_but_a_game_folder_is_even_windowed(self):
        processes = {1: (r"C:\Program Files\Google\Chrome\chrome.exe", 100.0),
                     2: (r"D:\SteamLibrary\steamapps\common\Hades\Hades.exe", 200.0),
                     3: (r"C:\Tools\emulator.exe", 300.0)}
        front = [(1, "YouTube", True)]
        reader = self.reader(front=front, processes=processes)
        self.assertEqual(reader.poll().name, "")
        front[0] = (2, "Hades", False)
        self.assertEqual((reader.poll().name, reader.poll().started_at), ("Hades", 200.0))
        # Alt-tabbing keeps the session until the game exits.
        front[0] = (1, "YouTube", True)
        self.assertEqual(reader.poll().name, "Hades")
        del processes[2]
        front[0] = (3, "", True)
        self.assertEqual(reader.poll().name, "emulator")


class ModeEngineTests(unittest.TestCase):
    def test_each_mode_renders_its_own_panel_set(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(app, "OUTPUT", Path(directory)), \
                 mock.patch.object(app.ClaudeReader, "poll", return_value=app.Snapshot(provider="claude")), \
                 mock.patch.object(app.CodexReader, "poll", return_value=app.Snapshot()), \
                 mock.patch.object(game.GameReader, "poll", return_value=game.GameSnapshot(name="Hades", started_at=1)):
                for mode in app.MODES:
                    engine = app.Engine({**app.DEFAULTS, "mode": mode})
                    self.assertEqual(engine.mode, mode)
                    try:
                        engine.sources["game"].request()
                        engine.sources["game"].wait(1)
                        panels, board, playing, status = engine.tick()
                    finally:
                        engine.close()
                    self.assertEqual(len(panels), 5)
                    self.assertTrue((Path(directory) / f"{app.panel_names(mode)[0]}.png").exists())
                    self.assertEqual(playing.name, "Hades" if mode == "game" else "")


class GifTimingTests(unittest.TestCase):
    def test_each_frame_keeps_its_own_duration(self):
        frames = night.cat_frames()
        gif = Image.open(io.BytesIO(gif_bytes(frames, 140)))
        # Pillow folds identical neighbouring frames into one longer frame; the loop length must not change.
        total = 0
        for index in range(gif.n_frames):
            gif.seek(index)
            total += gif.info["duration"]
        self.assertEqual(total, sum(f.info["duration"] for f in frames))


if __name__ == "__main__":
    unittest.main()


class ConfigMigrationTests(unittest.TestCase):
    def test_chill_mode_is_loaded_as_night(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"mode": "chill"}', encoding="utf-8")
            with mock.patch.object(app, "CONFIG", config):
                self.assertEqual(app.load_config()["mode"], "night")


def local(day, hour, minute=0):
    """Local timestamp for a day in the week of Monday 12 October 2026 (0 = Monday)."""
    return time.mktime((2026, 10, 12 + day, hour, minute, 0, 0, 0, -1))


class ScheduleTests(unittest.TestCase):
    def test_weekday_and_weekend_slots(self):
        cases = [(0, 6, 59, "night"), (0, 7, 0, "daylight"), (0, 8, 59, "daylight"), (0, 9, 0, "work"),
                 (4, 17, 59, "work"), (4, 18, 0, "night"), (4, 23, 30, "night"),
                 (5, 6, 59, "night"), (5, 7, 0, "daylight"), (6, 18, 59, "daylight"), (6, 19, 0, "night")]
        for day, hour, minute, mode in cases:
            self.assertEqual(schedule.scheduled_mode(local(day, hour, minute)), mode, (day, hour, minute))

    def test_games_take_over_only_after_hours_and_at_weekends(self):
        self.assertFalse(schedule.game_allowed(local(0, 10)))
        self.assertFalse(schedule.game_allowed(local(2, 7, 30)))
        self.assertTrue(schedule.game_allowed(local(2, 18)))
        self.assertTrue(schedule.game_allowed(local(3, 1)))
        self.assertTrue(schedule.game_allowed(local(5, 11)))

    def test_next_change_is_the_following_boundary(self):
        self.assertEqual(schedule.next_change(local(0, 10, 15)), local(0, 18))
        self.assertEqual(schedule.next_change(local(5, 12)), local(5, 19))


class AutoModeTests(unittest.TestCase):
    def engine(self):
        engine = app.Engine({**app.DEFAULTS, "mode": "auto"})
        self.addCleanup(engine.close)
        return engine

    def test_work_hours_ignore_games_and_never_poll_detection(self):
        engine = self.engine()
        with mock.patch.object(engine, "game") as detect:
            mode, playing = engine.resolve(local(1, 11))
        self.assertEqual((mode, playing.name), ("work", ""))
        detect.assert_not_called()

    def test_a_game_takes_over_in_the_evening_and_the_clock_returns_after(self):
        engine = self.engine()
        hades = game.GameSnapshot(name="Hades", started_at=1)
        with mock.patch.object(engine, "game", return_value=hades):
            self.assertEqual(engine.resolve(local(1, 21))[0], "game")
        with mock.patch.object(engine, "game", return_value=game.GameSnapshot()):
            self.assertEqual(engine.resolve(local(1, 21))[0], "night")
            self.assertEqual(engine.resolve(local(5, 10))[0], "daylight")


class WorkScenePanelTests(unittest.TestCase):
    def test_fourth_work_screen_follows_the_sun_and_rotates(self):
        from times_gate.render import scene_panel
        noon, midnight = local(1, 12), local(1, 23, 30)
        day_scenes = [id(f()) for f in (daylight.knight_frames, daylight.meadow_frames, daylight.sea_frames)]
        night_scenes = [id(night.campfire_frames_cached()), id(night.rain_frames_cached()), id(night.cat_frames())]
        self.assertIn(id(scene_panel(noon, daylight.ISTANBUL)), day_scenes)
        self.assertNotIn(id(scene_panel(midnight, daylight.ISTANBUL)), day_scenes)
        # Same scene within a 20-minute slot, so the panel is not re-sent every tick.
        self.assertIs(scene_panel(noon, daylight.ISTANBUL), scene_panel(noon + 60, daylight.ISTANBUL))
        self.assertIsNot(scene_panel(noon, daylight.ISTANBUL), scene_panel(noon + 20 * 60, daylight.ISTANBUL))
        self.assertTrue(night_scenes)
