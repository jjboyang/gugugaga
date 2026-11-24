"""Exercise the listening diary, pitch-only audio, and browsing integration."""
import asyncio
from datetime import datetime, timedelta
from io import BytesIO
import math
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QPushButton

from pet.music_history import MusicMemory, Observation, _observe
from pet.music_melody import SAMPLE_RATE, extract_phrase, hum_wave
from pet.music_sources import PlayingTrack, _linux_track, _windows_track, sample_playback
from pet.rig_animator import RigAnimator
from pet.window import PetWindow


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"
NOTES = (60, 64, 67, 65, 62, 64, 60, 67, 69, 65)


def sample_song():
    samples = np.zeros(round(SAMPLE_RATE * 4.5))
    for index, pitch in enumerate(NOTES):
        t = np.arange(round(0.36 * SAMPLE_RATE)) / SAMPLE_RATE
        hz = 440 * 2 ** ((pitch - 69) / 12)
        attack = np.clip(np.minimum(t, 0.36 - t) / 0.025, 0, 1)
        voice = 0.22 * np.sin(math.tau * hz * t) + 0.08 * np.sin(2 * math.tau * hz * t)
        start = round(index * 0.43 * SAMPLE_RATE)
        samples[start:start + len(t)] += voice * attack
    t = np.arange(len(samples)) / SAMPLE_RATE
    return samples + 0.10 * np.sin(math.tau * 98 * t) + 0.05 * np.sin(math.tau * 146.83 * t)


class MelodyTests(unittest.TestCase):
    def test_reconstructs_lead_pitch_and_rhythm_from_audio_with_accompaniment(self):
        phrase = extract_phrase(sample_song())
        pitches = tuple(pitch for pitch, _, _ in phrase)
        self.assertGreaterEqual(len(pitches), 4)
        self.assertTrue(any(NOTES[i:i + len(pitches)] == pitches for i in range(len(NOTES))), pitches)
        self.assertEqual(phrase[0][1], 0)
        self.assertGreater(phrase[1][1], phrase[0][2])
        with wave.open(BytesIO(hum_wave(phrase))) as hum:
            self.assertEqual(hum.getnchannels(), 1)
            self.assertAlmostEqual(hum.getnframes() / hum.getframerate(), 1.78)
            pcm = np.frombuffer(hum.readframes(hum.getnframes()), dtype="<i2")
            self.assertGreater(np.max(np.abs(pcm)), 3000)
        t = np.arange(SAMPLE_RATE * 3) / SAMPLE_RATE
        self.assertEqual(extract_phrase(t * 0), ())
        self.assertEqual(extract_phrase(np.sin(math.tau * 440 * t)), ())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for a real local sample")
    def test_decodes_a_local_song_without_keeping_a_recording(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "my song.wav"
            with wave.open(str(source), "wb") as recording:
                recording.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
                recording.writeframes((sample_song() * 32767).astype("<i2").tobytes())
            track = PlayingTrack("歌", "歌手", "file-player", local_file=source, loopback=False)
            phrase = extract_phrase(sample_playback(track, Event()))
            self.assertGreaterEqual(len(phrase), 4)
            self.assertEqual(list(Path(directory).iterdir()), [source])

    def test_mpris_skips_paused_players_and_decodes_local_file_uris(self):
        rows = [
            ("Paused", "other", "跳过这首", "歌手", "5", ""),
            ("Playing", "player", "  晚上的歌  ", "歌手", "12000000", "file:///music/A%20B.flac"),
            ("Playing", "browser", "网页视频", "", "0", "https://example.com"),
        ]
        with patch("pet.music_sources._command", return_value="\n".join("\x1f".join(row) for row in rows)):
            playing = _linux_track()
        self.assertEqual((playing.title, playing.artist, playing.position), ("晚上的歌", "歌手", 12))
        self.assertEqual(playing.local_file, Path("/music/A B.flac"))
        self.assertFalse(playing.loopback)

    def test_windows_ignores_a_foreground_video_and_skips_a_mixed_loopback(self):
        def session(name, kind):
            info = SimpleNamespace(playback_status=4, playback_type=kind)
            media = SimpleNamespace(title=name, artist="歌手", album_artist="", playback_type=kind)
            return SimpleNamespace(source_app_user_model_id=name, get_playback_info=lambda: info,
                                   try_get_media_properties_async=AsyncMock(return_value=media))

        video, music = session("视频", 2), session("今天的歌", 1)
        manager = SimpleNamespace(get_current_session=lambda: video, get_sessions=lambda: [video, music])
        api = {
            "winrt.windows.media": SimpleNamespace(MediaPlaybackType=SimpleNamespace(UNKNOWN=0, MUSIC=1)),
            "winrt.windows.media.control": SimpleNamespace(
                GlobalSystemMediaTransportControlsSessionManager=SimpleNamespace(
                    request_async=AsyncMock(return_value=manager)
                ),
                GlobalSystemMediaTransportControlsSessionPlaybackStatus=SimpleNamespace(PLAYING=4),
            ),
        }
        with patch.dict(sys.modules, api):
            track = asyncio.run(_windows_track())
        self.assertEqual(track.title, "今天的歌")
        self.assertFalse(track.loopback)
        video.try_get_media_properties_async.assert_not_called()

    def test_sampler_drops_a_clip_when_the_song_changes_mid_capture(self):
        track = PlayingTrack("这首", "歌手", "player")
        another = PlayingTrack("下一首", "歌手", "player")
        with patch("pet.music_history.read_playback", side_effect=(track, another)), \
                patch("pet.music_history.sample_playback", return_value=sample_song()), \
                patch("pet.music_history.extract_phrase") as extract:
            observation = _observe(track.playback_id, Event())
        self.assertEqual(observation.track, another)
        self.assertEqual(observation.melody, ())
        extract.assert_not_called()


class MusicMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "history.sqlite3"
        self.window = PetWindow()
        self.rig = RigAnimator(SimpleNamespace(current_phase="idle"), self.window, ASSETS, parent=self.window)
        self.memory = MusicMemory(self.window, self.rig, path=self.path)
        self.addCleanup(self.close)

    def close(self):
        self.memory.shutdown()
        if self.memory.panel is not None:
            self.memory.panel.close()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def enable(self):
        with patch.object(self.memory, "_tick"):
            self.memory.set_enabled(True)
            self.memory.timer.stop()

    def test_opt_in_is_persistent_and_accessible_from_dafeiyus_menu(self):
        self.assertFalse(self.memory.enabled)
        self.assertFalse(self.memory.timer.isActive())
        self.window.contextMenuEvent(None)
        menu = self.app.activePopupWidget()
        item = next(button for button in menu.findChildren(QPushButton) if button.text() == "听歌记忆")
        item.click()
        self.assertTrue(self.memory.panel.isVisible())
        self.assertFalse(self.memory.panel.toggle.isChecked())
        with patch.object(self.memory, "_tick"):
            self.memory.panel.toggle.click()
        self.assertTrue(self.memory.enabled)
        self.assertTrue(self.memory.history.enabled())
        self.memory.panel.toggle.click()
        self.assertFalse(self.memory.history.enabled())
        self.assertFalse(self.memory.timer.isActive())

    def test_day_rollover_deduplicates_plays_and_filters_a_quick_skip(self):
        track = PlayingTrack("晚上的歌", "歌手", "player")
        skip = PlayingTrack("一划而过", "歌手", "player")
        day_one = datetime(2026, 11, 24, 23, 59, 50)
        for offset, song in ((0, track), (4, track), (8, track), (12, track), (16, track),
                             (20, track), (24, skip), (28, None), (32, track), (36, track)):
            self.memory._record(Observation(song, day_one + timedelta(seconds=offset), offset))
        history = self.memory.history
        self.assertEqual(history.days(), ["2026-11-25", "2026-11-24"])
        for day in history.days():
            self.assertEqual([row["title"] for row in history.songs(day)], ["晚上的歌"])
        seconds = dict(history.connection.execute("SELECT day, seconds FROM music_days"))
        self.assertEqual(seconds, {"2026-11-24": 10, "2026-11-25": 14})

    def test_polling_builds_a_phrase_after_the_song_has_been_playing(self):
        track = PlayingTrack("继续播放", "歌手", "music-player")
        start = datetime(2026, 11, 24, 18, 30)
        seconds = 0
        with patch("pet.music_history.time.monotonic", side_effect=lambda: seconds), \
                patch("pet.music_history.datetime", wraps=datetime) as wall, \
                patch("pet.music_history.Thread", side_effect=lambda **kw: SimpleNamespace(start=kw["target"])), \
                patch("pet.music_history.read_playback", return_value=track) as read, \
                patch("pet.music_history.sample_playback", return_value=sample_song()) as sample:
            wall.now.side_effect = lambda: start + timedelta(seconds=seconds)
            self.memory._tick()
            read.assert_not_called()
            self.memory.set_enabled(True)
            self.memory.timer.stop()
            for seconds in (4, 8, 12, 13):
                self.memory._tick()
            sample.assert_called_once()
        song, = self.memory.history.songs(start.date().isoformat())
        self.assertEqual((song["title"], song["can_hum"]), (track.title, 1))

    def test_browsing_prefers_todays_melody_and_opt_out_restores_stock_hum(self):
        history = self.memory.history
        today = datetime.now().date()
        old_track = PlayingTrack("昨天的歌", "歌手", "player")
        track = PlayingTrack("今天的歌", "歌手", "player")
        phrase = extract_phrase(sample_song())
        history.add_listen(old_track, (today - timedelta(days=1)).isoformat(), 18, 1)
        history.save_melody(old_track, ((54, 0.0, 0.5), (57, 0.54, 0.5), (60, 1.08, 0.5)))
        history.add_listen(track, today.isoformat(), 18, 2)
        history.save_melody(track, phrase)
        self.assertIsNone(self.memory.choose_hum())
        self.enable()
        fallback = QUrl.fromLocalFile(str(ASSETS / "browsing_hum.wav"))
        sound = Mock()
        sound.source.return_value = fallback
        sound.isPlaying.return_value = False
        sound.setSource.side_effect = lambda url: setattr(sound.source, "return_value", url)
        with patch.object(self.rig, "_load_exploration_sound", return_value=sound):
            self.rig.set_exploring(True)
        chosen = Path(sound.source().toLocalFile())
        self.assertEqual(chosen.read_bytes(), hum_wave(phrase))
        self.assertEqual(self.memory.last_hum, track.key)
        self.memory.set_enabled(False)
        self.assertEqual(sound.source(), fallback)
