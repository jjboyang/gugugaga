"""Read desktop media metadata and sample only the corresponding playback."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event
import time
import unicodedata
from urllib.parse import unquote, urlsplit

import numpy as np

from pet.music_melody import SAMPLE_RATE, SAMPLE_SECONDS


_FIELD_SEPARATOR = "\x1f"
_AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".alac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"}
_HIDDEN_PROCESS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class PlayingTrack:
    title: str
    artist: str
    player: str
    position: float = 0.0
    local_file: Path | None = None
    loopback: bool = True

    @property
    def key(self):
        return json.dumps([unicodedata.normalize("NFKC", item).casefold()
                           for item in (self.title, self.artist)], ensure_ascii=False)

    @property
    def playback_id(self):
        return self.player, self.key


def _track(title, artist, player, *, position=0.0, path=None, loopback=True, music=False):
    title, artist = (" ".join(value.split())[:250] for value in (title, artist))
    if not title or not (artist or music):
        return None
    elapsed = 0.0
    try:
        seconds = float(position)
        if math.isfinite(seconds):
            elapsed = max(0.0, seconds)
    except (ValueError, TypeError):
        pass
    return PlayingTrack(title, artist, player, elapsed, path, loopback)


def _command(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
                            encoding="utf-8", errors="replace", creationflags=_HIDDEN_PROCESS)
    return result.stdout.rstrip("\r\n") if result.returncode == 0 else ""


async def _windows_track():
    from winrt.windows.media import MediaPlaybackType
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    current = manager.get_current_session()
    sessions = [(session, session.get_playback_info()) for session in manager.get_sessions()]
    playing = [(session, info) for session, info in sessions
               if info is not None and info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING]
    if current is not None:
        playing.sort(key=lambda pair: pair[0].source_app_user_model_id != current.source_app_user_model_id)
    for session, info in playing:
        if info.playback_type not in (None, MediaPlaybackType.UNKNOWN, MediaPlaybackType.MUSIC):
            continue
        media = await session.try_get_media_properties_async()
        if media is None:
            continue
        content_type = media.playback_type if media.playback_type is not None else info.playback_type
        if content_type not in (None, MediaPlaybackType.UNKNOWN, MediaPlaybackType.MUSIC):
            continue
        track = _track(media.title, media.artist or media.album_artist, session.source_app_user_model_id,
                       loopback=len(playing) == 1, music=content_type == MediaPlaybackType.MUSIC)
        if track is not None:
            return track
    return None


_MAC_METADATA = """
if application id "{app_id}" is running then
    set sep to character id 31
    tell application id "{app_id}"
        if player state is playing then
            set audioPath to ""
            {local_file}
            return (name of current track) & sep & (artist of current track) & sep & (player position as text) & sep & audioPath
        end if
    end tell
end if
return ""
"""


def _mac_track():
    for app_id, local_file in (
        ("com.apple.Music", 'try\nset audioPath to POSIX path of (location of current track as alias)\nend try'),
        ("com.spotify.client", ""),
    ):
        fields = _command(["osascript", "-e", _MAC_METADATA.format(app_id=app_id, local_file=local_file)])
        if fields:
            title, artist, position, path = fields.split(_FIELD_SEPARATOR, 3)
            track = _track(title, artist, app_id, position=position, path=Path(path) if path else None,
                           loopback=False, music=app_id == "com.apple.Music")
            if track is not None:
                return track
    return None


def _linux_track():
    fields = ("status", "playerName", "title", "artist", "position", "xesam:url")
    format_string = _FIELD_SEPARATOR.join("{{" + name + "}}" for name in fields)
    results = _command(["playerctl", "--all-players", "metadata", "--format", format_string])
    playing = [line.split(_FIELD_SEPARATOR, 5) for line in results.splitlines()
               if line.startswith("Playing" + _FIELD_SEPARATOR)]
    for row in playing:
        if len(row) != len(fields):
            continue
        _, player, title, artist, position, url = row
        source = urlsplit(url)
        path = Path(unquote(source.path)) if source.scheme == "file" and source.netloc in ("", "localhost") else None
        seconds = float(position) / 1_000_000 if position.isdecimal() else 0.0
        track = _track(title, artist, player, position=seconds, path=path,
                       loopback=len(playing) == 1, music=path is not None and path.suffix.lower() in _AUDIO_EXTENSIONS)
        if track is not None:
            return track
    return None


def read_playback():
    try:
        if sys.platform == "win32":
            return asyncio.run(asyncio.wait_for(_windows_track(), 3))
        if sys.platform == "darwin":
            return _mac_track()
        if sys.platform.startswith("linux"):
            return _linux_track()
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, asyncio.TimeoutError):
        pass
    return None


def _ffmpeg_sample(input_options, cancel):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return None
    args = [ffmpeg, "-nostdin", "-loglevel", "error", *input_options, "-t", str(SAMPLE_SECONDS),
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"]
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=_HIDDEN_PROCESS) as process:
        deadline = time.monotonic() + SAMPLE_SECONDS + 2
        while not cancel.is_set() and time.monotonic() < deadline:
            try:
                pcm, _ = process.communicate(timeout=0.2)
                if process.returncode == 0:
                    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
                return None
            except subprocess.TimeoutExpired:
                continue
        process.kill()
    return None


def _wasapi_sample(cancel):
    import pyaudiowpatch as audio

    with audio.PyAudio() as device:
        loopback = device.get_default_wasapi_loopback()
        if not loopback.get("isLoopbackDevice"):
            return None
        rate = int(loopback["defaultSampleRate"])
        channels = int(loopback["maxInputChannels"])
        if min(rate, channels) <= 0:
            return None
        target = round(rate * SAMPLE_SECONDS)
        done = Event()
        chunks = []
        received = 0

        def collect(pcm, frames, _time, _status):
            nonlocal received
            if pcm:
                chunks.append(pcm)
                received += frames
            if received >= target or cancel.is_set():
                done.set()
                return None, audio.paComplete
            return None, audio.paContinue

        with device.open(format=audio.paInt16, channels=channels, rate=rate, input=True,
                         input_device_index=loopback["index"], frames_per_buffer=1024, stream_callback=collect):
            deadline = time.monotonic() + SAMPLE_SECONDS + 1.5
            while not done.wait(0.10) and not cancel.is_set() and time.monotonic() < deadline:
                pass
        if cancel.is_set() or received < target:
            return None
        samples = np.frombuffer(b"".join(chunks), dtype="<i2").reshape(-1, channels)[:target]
        mono = samples.mean(axis=1)
        positions = np.arange(round(len(mono) * SAMPLE_RATE / rate)) * rate / SAMPLE_RATE
        return np.interp(positions, np.arange(len(mono)), mono).astype(np.float32) / 32768


def sample_playback(track, cancel):
    if cancel.is_set():
        return None
    try:
        path = track.local_file
        if path is not None and path.suffix.lower() in _AUDIO_EXTENSIONS and path.is_file():
            return _ffmpeg_sample(["-protocol_whitelist", "file,pipe", "-ss", str(track.position),
                                   "-i", str(path.resolve())], cancel)
        if not track.loopback:
            return None
        if sys.platform == "win32":
            return _wasapi_sample(cancel)
        if sys.platform.startswith("linux"):
            sink = _command(["pactl", "get-default-sink"])
            if sink:
                return _ffmpeg_sample(["-f", "pulse", "-i", f"{sink}.monitor"], cancel)
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        pass
    return None
