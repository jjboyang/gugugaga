"""Local listening history and a bounded background sampler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import random
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout

from pet.exploration_ui import Toggle, add_card, card_list, label, themed_layout
from pet.music_melody import PitchPhrase, extract_phrase, hum_wave
from pet.music_sources import PlayingTrack, read_playback, sample_playback


_POLL_SECONDS = 4
_MIN_LISTEN_SECONDS = 8
_SAMPLE_RETRY_SECONDS = 18
_SAMPLE_LIMIT = 3
_RECENT_DAYS = 7


class ListeningHistory:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS music_memory (id INTEGER PRIMARY KEY CHECK (id = 1), enabled INTEGER NOT NULL);
            INSERT OR IGNORE INTO music_memory (id, enabled) VALUES (1, 0);
            CREATE TABLE IF NOT EXISTS music_tracks (
                track_key TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL, melody TEXT
            );
            CREATE TABLE IF NOT EXISTS music_days (
                day TEXT NOT NULL, track_key TEXT NOT NULL, seconds REAL NOT NULL, last_seen REAL NOT NULL,
                PRIMARY KEY (day, track_key),
                FOREIGN KEY (track_key) REFERENCES music_tracks (track_key)
            );
        """)

    def enabled(self):
        return bool(self.connection.execute("SELECT enabled FROM music_memory WHERE id = 1").fetchone()[0])

    def set_enabled(self, enabled):
        with self.connection:
            self.connection.execute("UPDATE music_memory SET enabled = ? WHERE id = 1", (bool(enabled),))

    def add_listen(self, track, day, seconds, last_seen):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO music_tracks (track_key, title, artist) VALUES (?, ?, ?)",
                (track.key, track.title, track.artist),
            )
            self.connection.execute("""
                INSERT INTO music_days (day, track_key, seconds, last_seen) VALUES (?, ?, ?, ?)
                ON CONFLICT (day, track_key) DO UPDATE SET
                    seconds = seconds + excluded.seconds, last_seen = excluded.last_seen
            """, (day, track.key, seconds, last_seen))

    def needs_melody(self, day, track):
        row = self.connection.execute("""
            SELECT t.melody, d.seconds FROM music_tracks t JOIN music_days d USING (track_key)
            WHERE d.day = ? AND t.track_key = ?
        """, (day, track.key)).fetchone()
        return row is not None and row["melody"] is None and row["seconds"] >= _MIN_LISTEN_SECONDS

    def save_melody(self, track, phrase):
        with self.connection:
            self.connection.execute("UPDATE music_tracks SET melody = ? WHERE track_key = ? AND melody IS NULL",
                                    (json.dumps(phrase), track.key))

    def days(self):
        return [row[0] for row in self.connection.execute(
            "SELECT DISTINCT day FROM music_days WHERE seconds >= ? ORDER BY day DESC",
            (_MIN_LISTEN_SECONDS,),
        )]

    def songs(self, day):
        return self.connection.execute("""
            SELECT t.title, t.artist, t.melody IS NOT NULL AS can_hum
            FROM music_days d JOIN music_tracks t USING (track_key)
            WHERE d.day = ? AND d.seconds >= ? ORDER BY d.last_seen DESC
        """, (day, _MIN_LISTEN_SECONDS)).fetchall()

    def hum_candidates(self, today):
        oldest = (today - timedelta(days=_RECENT_DAYS - 1)).isoformat()
        rows = self.connection.execute("""
            SELECT t.track_key, t.melody, MAX(d.day) AS day
            FROM music_days d JOIN music_tracks t USING (track_key)
            WHERE d.day BETWEEN ? AND ? AND d.seconds >= ? AND t.melody IS NOT NULL
            GROUP BY t.track_key ORDER BY day DESC, MAX(d.last_seen) DESC
        """, (oldest, today.isoformat(), _MIN_LISTEN_SECONDS)).fetchall()
        if rows and rows[0]["day"] == today.isoformat():
            return [row for row in rows if row["day"] == today.isoformat()]
        return rows


@dataclass(frozen=True)
class Observation:
    track: PlayingTrack | None
    wall: datetime
    monotonic: float
    melody: PitchPhrase = ()


def _observe(expected, cancel):
    track = read_playback()
    wall, monotonic = datetime.now(), time.monotonic()
    if track is None or expected != track.playback_id:
        return Observation(track, wall, monotonic)
    samples = sample_playback(track, cancel)
    if samples is None or cancel.is_set():
        return Observation(track, wall, monotonic)
    confirmed = read_playback()
    if (confirmed is not None and confirmed.playback_id == expected and not cancel.is_set()
            and (track.local_file is not None or confirmed.loopback)):
        return Observation(confirmed, datetime.now(), time.monotonic(), extract_phrase(samples))
    return Observation(confirmed, datetime.now(), time.monotonic())


class MusicMemory(QObject):
    def __init__(self, window, rig, *, path=None):
        super().__init__(window)
        self.rig = rig
        self.window = window
        self.panel = None
        self.error = ""
        self.previous = None
        self.next_poll = 0.0
        self.attempts = {}
        self.attempt_day = None
        self.last_hum = None
        self.temp = None
        self.cancel = None
        self.replies = SimpleQueue()
        self.epoch = 0
        self.rng = random.Random()
        self.history = None
        path = path if path is not None else os.environ.get(
            "DESKTOP_PET_MUSIC_HISTORY_PATH", Path.home() / ".desktop-pet" / "music.sqlite3",
        )
        try:
            self.history = ListeningHistory(path)
            self.enabled = self.history.enabled()
        except (OSError, sqlite3.Error):
            self.enabled = False
            self.error = "暂时无法打开听歌记忆。"

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        if self.enabled:
            self.timer.start()
        window.music_history_requested.connect(self.open_panel)
        rig.browsing_hum_source = self.choose_hum

    def set_enabled(self, enabled):
        if self.history is None or self.enabled == enabled:
            return
        try:
            self.history.set_enabled(enabled)
        except sqlite3.Error:
            self.error = "暂时无法保存听歌设置。"
            self._refresh()
            return
        self.enabled = enabled
        self.error = ""
        self.epoch += 1
        self.previous = None
        self.next_poll = 0.0
        if enabled:
            self.timer.start()
            self._tick()
        else:
            self.timer.stop()
            if self.cancel is not None:
                self.cancel.set()
            self.rig.refresh_browsing_hum()
        self._refresh()

    def _sample_target(self, now):
        day = datetime.now().date().isoformat()
        if day != self.attempt_day:
            self.attempt_day = day
            self.attempts.clear()
        track = self.previous.track if self.previous is not None else None
        if (track is None or (not track.loopback and track.local_file is None)
                or self.rig.is_browsing or not self.history.needs_melody(day, track)):
            return None
        count, retry = self.attempts.get(track.key, (0, 0.0))
        if count >= _SAMPLE_LIMIT or now < retry:
            return None
        self.attempts[track.key] = count + 1, now + _SAMPLE_RETRY_SECONDS
        return track.playback_id

    def _record(self, observation):
        previous, self.previous = self.previous, observation
        track = observation.track
        if previous is None or track is None or previous.track is None or previous.track.playback_id != track.playback_id:
            return
        elapsed = observation.monotonic - previous.monotonic
        if not 0 < elapsed <= 16:
            return
        day = observation.wall.date().isoformat()
        previous_day = previous.wall.date().isoformat()
        if day != previous_day:
            if observation.wall.date() - previous.wall.date() != timedelta(days=1):
                return
            midnight = observation.wall.replace(hour=0, minute=0, second=0, microsecond=0)
            since_midnight = (observation.wall - midnight).total_seconds()
            today_seconds = min(elapsed, since_midnight)
            if elapsed > today_seconds:
                self.history.add_listen(track, previous_day, elapsed - today_seconds, previous.wall.timestamp())
            elapsed = today_seconds
        if elapsed:
            self.history.add_listen(track, day, elapsed, observation.wall.timestamp())
        if observation.melody:
            self.history.save_melody(track, observation.melody)

    def _tick(self):
        try:
            epoch, observation = self.replies.get_nowait()
        except Empty:
            pass
        else:
            self.cancel = None
            if self.enabled and epoch == self.epoch:
                try:
                    self._record(observation)
                except sqlite3.Error:
                    self.error = "暂时无法写入听歌记忆。"
                if self.panel is not None and self.panel.isVisible():
                    self._refresh()
        now = time.monotonic()
        if not self.enabled or self.cancel is not None or now < self.next_poll:
            return
        self.next_poll = now + _POLL_SECONDS
        try:
            expected = self._sample_target(now)
        except sqlite3.Error:
            return
        cancel = self.cancel = Event()
        epoch = self.epoch

        def poll():
            try:
                observation = _observe(expected, cancel)
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                observation = Observation(None, datetime.now(), time.monotonic())
            self.replies.put((epoch, observation))

        Thread(target=poll, name="music-playback", daemon=True).start()

    def choose_hum(self):
        if not self.enabled or self.history is None:
            return None
        # Exclude our own output from any speaker sample already in flight.
        if self.cancel is not None:
            self.cancel.set()
        try:
            rows = self.history.hum_candidates(datetime.now().date())
            if not rows:
                return None
            choices = [row for row in rows if row["track_key"] != self.last_hum]
            row = self.rng.choice(choices or rows)
            raw = row["melody"]
            if self.temp is None:
                self.temp = TemporaryDirectory(prefix="dafeiyu-hum-")
            name = sha256(raw.encode()).hexdigest()[:24]
            target = Path(self.temp.name) / f"{name}.wav"
            if not target.is_file():
                phrase = tuple(tuple(note) for note in json.loads(raw))
                target.write_bytes(hum_wave(phrase))
            self.last_hum = row["track_key"]
            return target
        except (OSError, sqlite3.Error, ValueError, IndexError, TypeError):
            return None

    def open_panel(self):
        if self.panel is None:
            self.panel = MusicHistoryPanel(self)
        self._refresh()
        self.panel.show()
        self.panel.raise_()

    def _refresh(self):
        if self.panel is not None:
            self.panel.refresh()

    def shutdown(self):
        self.timer.stop()
        if self.cancel is not None:
            self.cancel.set()
        self.enabled = False
        self.rig.refresh_browsing_hum()
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None
        if self.history is not None:
            self.history.connection.close()
            self.history = None


class MusicHistoryPanel(QDialog):
    def __init__(self, memory):
        super().__init__(memory.window, Qt.Window)
        self.memory = memory
        self.setWindowTitle("听歌记忆")
        layout = themed_layout(self, 500, 430)
        self.toggle = Toggle("记住我听过的音乐，用来哼唱")
        self.toggle.toggled.connect(memory.set_enabled)
        layout.addWidget(self.toggle)
        layout.addWidget(label("开启后读取播放器曲名，并短暂分析播放输出或本地音乐文件。曲名、歌手和提取的旋律留在本机。", "muted", wrap=True))
        self.day = QComboBox()
        self.day.setAccessibleName("听歌日期")
        dates = QHBoxLayout()
        dates.addWidget(label("听歌记录", "section"), 1)
        dates.addWidget(self.day)
        layout.addLayout(dates)
        self.songs = card_list("听歌记录")
        layout.addWidget(self.songs, 1)
        self.empty = label(role="muted", wrap=True)
        layout.addWidget(self.empty)
        self._rendered = None
        self._today = None
        self.day.currentTextChanged.connect(self.refresh)

    def refresh(self):
        memory = self.memory
        self.toggle.blockSignals(True)
        self.toggle.setEnabled(memory.history is not None)
        self.toggle.setChecked(memory.enabled)
        self.toggle.blockSignals(False)
        today = datetime.now().date().isoformat()
        selected = self.day.currentText()
        day = selected if selected and selected != self._today else today
        self._today = today
        try:
            stored_days = memory.history.days() if memory.history is not None else []
            days = list(dict.fromkeys([today, *stored_days]))
            if day not in days:
                day = today
            songs = tuple(tuple(row) for row in memory.history.songs(day)) if memory.history is not None else ()
        except sqlite3.Error:
            self.empty.setText("暂时无法读取听歌记忆。")
            self.empty.show()
            return
        if [self.day.itemText(i) for i in range(self.day.count())] != days:
            self.day.blockSignals(True)
            self.day.clear()
            self.day.addItems(days)
            self.day.setCurrentText(day)
            self.day.blockSignals(False)
        if songs != self._rendered:
            self._rendered = songs
            self.songs.clear()
            for title, artist, can_hum in songs:
                detail = " · ".join(filter(None, (artist, "已记住旋律" if can_hum else "")))
                add_card(self.songs, title, detail)
        if day == today and memory.enabled:
            empty = "今天还没有听歌记录。播放一首能提供曲名的歌，听一会儿就会出现。"
        else:
            empty = "这天还没有听歌记录。"
        self.empty.setText(memory.error or (empty if not songs else ""))
        self.empty.setVisible(bool(memory.error or not songs))
