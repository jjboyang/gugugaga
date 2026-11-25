"""Read short, timestamped samples from a publicly playable video."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from http.client import HTTPSConnection, HTTPException
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
from subprocess import DEVNULL, Popen, TimeoutExpired
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from time import monotonic
from urllib.parse import parse_qs, urlencode
import wave

from pet.exploration import read_url, video_page, within_website
from pet.exploration_pictures import PictureCandidate, _memory_jpeg


VIDEO_TIMEOUT = 57
SAMPLE_SECONDS = 18
FRAME_STEP = 6
MAX_SUBTITLE_BYTES = 512 * 1024
# Bilibili's CDN rejects the default FFmpeg Lavf User-Agent.
MEDIA_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CUE = re.compile(
    r"(?m)^((?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d+:)?\d{2}:\d{2}[.,]\d{3})[^\n]*\n"
)


@dataclass(frozen=True)
class TimedText:
    kind: str
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class AudioSample:
    start_ms: int
    end_ms: int
    wav: bytes


@dataclass
class VideoMaterial:
    frames: list[PictureCandidate] = field(default_factory=list)
    captions: list[TimedText] = field(default_factory=list)
    audio: list[AudioSample] = field(default_factory=list)
    status: str = ""


def playback_url(url, timestamp_ms):
    source = video_page(url)
    if source is None or timestamp_ms is None:
        return url
    extractor, canonical = source
    parts = read_url(canonical)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    seconds = max(0, timestamp_ms // 1000)
    query["t"] = f"{seconds}s" if extractor == "youtube" else str(seconds)
    return parts._replace(query=urlencode(query)).geturl()


def timestamp_text(ms):
    minutes, seconds = divmod(ms // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _run(command, cancelled, deadline, *, capture=0):
    """Run a single worker command with bounded output and cancellation."""
    if cancelled.is_set() or monotonic() >= deadline:
        return None
    try:
        with TemporaryFile() as stdout, Popen(
            command, stdin=DEVNULL, stdout=stdout if capture else DEVNULL, stderr=DEVNULL,
        ) as process:
            while process.poll() is None:
                if cancelled.is_set() or monotonic() >= deadline or (capture and stdout.tell() > capture):
                    process.kill()
                    return None
                try:
                    process.wait(timeout=0.15)
                except TimeoutExpired:
                    pass
            if process.returncode != 0 or (capture and stdout.tell() > capture):
                return None
            if not capture:
                return b""
            stdout.seek(0)
            return stdout.read(capture)
    except OSError:
        return None


def _metadata(extractor, url, cancelled, deadline):
    raw = _run([
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-plugin-dirs", "--no-cache-dir",
        "--use-extractors", extractor, "--no-playlist", "--no-warnings", "--quiet",
        "--socket-timeout", "6", "--retries", "0", "--extractor-retries", "0",
        "--write-subs", "--write-auto-subs", "--skip-download", "--dump-single-json", "--", url,
    ], cancelled, min(deadline, monotonic() + 15), capture=5 * 1024 * 1024)
    try:
        info = json.loads(raw or b"null")
    except (ValueError, RecursionError):
        return {}
    if (not isinstance(info, dict) or info.get("_type") not in {None, "video"}
            or info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}
            or info.get("availability") not in {None, "public", "unlisted"} or info.get("has_drm")):
        return {}
    return info


def _windows(duration):
    if type(duration) not in {int, float} or not math.isfinite(duration) or duration < 0.5:
        return []
    if duration <= SAMPLE_SECONDS * 2:
        return [(0, duration)]
    late_start = min(int(duration * 0.58), int(duration - SAMPLE_SECONDS))
    early_start = min(int(duration * 0.12), late_start - SAMPLE_SECONDS)
    return [(early_start, SAMPLE_SECONDS), (late_start, SAMPLE_SECONDS)]


def _media_address(value, extractor, *, captions=False):
    parts = read_url(value)
    if not parts or parts.scheme != "https" or parts.port not in (None, 443):
        return None
    host = parts.hostname
    if extractor == "BiliBili":
        domains = ("bilivideo.com", "bilivideo.cn", "mcdn.bilivideo.cn")
        if captions:
            domains += ("hdslb.com", "bilibili.com", "biliapi.net")
        if host.startswith("upos-") and within_website(host, "akamaized.net"):
            return parts
    else:
        domains = ("googlevideo.com",)
        if captions:
            domains += ("youtube.com",)
    return parts if any(within_website(host, domain) for domain in domains) else None


def _streams(info, extractor):
    media = [
        fmt for fmt in info.get("formats", [])
        if isinstance(fmt, dict) and not fmt.get("has_drm") and fmt.get("protocol") == "https"
        and fmt.get("ext") in {"mp4", "m4a", "webm"}
        and _media_address(fmt.get("url"), extractor)
    ]
    videos = [fmt for fmt in media if fmt.get("vcodec") not in {None, "none"}
              and type(fmt.get("height")) is int and 0 < fmt["height"] <= 720]
    video = min(videos, key=lambda fmt: abs(fmt["height"] - 480), default=None)
    audio = next((fmt for fmt in media if fmt.get("vcodec") == "none"
                  and fmt.get("acodec") not in {None, "none"}), None)
    if audio is None:
        audio = next((fmt for fmt in media if fmt.get("acodec") not in {None, "none"}), None)
    return video, audio


def _time_ms(value):
    result = 0
    parts = value.replace(",", ".").split(":")
    for part in parts[:-1]:
        result = (result + int(part)) * 60
    return result * 1000 + int(parts[-1].replace(".", ""))


def _parse_captions(raw, windows):
    raw = raw.lstrip("\ufeff").replace("\r", "")
    matches = list(CUE.finditer(raw))
    cues = []
    for index, match in enumerate(matches):
        start, end = _time_ms(match[1]), _time_ms(match[2])
        if start >= end:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        text = raw[match.end():next_start].strip().split("\n\n", 1)[0]
        text = " ".join(unescape(re.sub(r"<[^>]*>", "", text)).split())[:160]
        if text and (not cues or cues[-1].text != text):
            cues.append(TimedText("subtitle", start, end, text))

    selected = {}
    for start, duration in windows:
        in_window = [cue for cue in cues if cue.end_ms > start * 1000
                     and cue.start_ms < (start + duration) * 1000]
        if len(in_window) > 8:
            in_window = [in_window[i * (len(in_window) - 1) // 7] for i in range(8)]
        selected.update({(cue.start_ms, cue.end_ms): cue for cue in in_window})
    return list(selected.values())


def _subtitle_text(track, extractor):
    data = track.get("data")
    if isinstance(data, str):
        return data[:MAX_SUBTITLE_BYTES]
    parts = _media_address(track.get("url"), extractor, captions=True)
    if parts is None:
        return ""
    try:
        connection = HTTPSConnection(parts.hostname, timeout=4)
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200:
                return ""
            raw = response.read(MAX_SUBTITLE_BYTES + 1)
            return raw.decode("utf-8", errors="replace") if len(raw) <= MAX_SUBTITLE_BYTES else ""
        finally:
            connection.close()
    except (OSError, HTTPException, ValueError):
        return ""


def _captions(info, extractor, windows, cancelled):
    for group in ("subtitles", "automatic_captions"):
        languages = info.get(group) or {}
        # Prefer Chinese, then an original track, then other available captions.
        def language_order(language):
            return (not language.removeprefix("ai-").startswith(("zh", "yue")),
                    not language.endswith("-orig"), len(language))

        tried = 0
        for language in sorted(languages, key=language_order):
            if cancelled.is_set() or tried >= 2:
                break
            track = next((item for item in languages[language] if item.get("ext") in {"srt", "vtt"}), None)
            if track:
                tried += 1
                cues = _parse_captions(_subtitle_text(track, extractor), windows)
                if cues:
                    return cues
    return []


def _input(ffmpeg, url, referer, start, *, remote):
    command = [ffmpeg, "-nostdin", "-loglevel", "error", "-y"]
    if remote:
        command += [
            "-protocol_whitelist", "https,tls,tcp", "-format_whitelist", "mov,matroska,webm",
            "-tls_verify", "1", "-max_redirects", "0", "-rw_timeout", "6000000",
            "-referer", referer, "-user_agent", MEDIA_USER_AGENT,
        ]
    return command + ["-threads", "2", "-ss", str(start), "-i", str(url)]


def _frames(ffmpeg, url, page, start, duration, folder, cancelled, deadline, *, remote=True):
    pattern = folder / "frame-%02d.jpg"
    lead = 1 if duration > 2 else 0
    step = max(FRAME_STEP, int(duration / 3))
    command = _input(ffmpeg, url, page, start + lead, remote=remote) + [
        "-map", "0:v:0", "-an", "-t", str(duration - lead),
        "-vf", f"select='gte(t,selected_n*{step})',scale='min(768,iw)':-2",
        "-fps_mode", "passthrough", "-frames:v", "3", "-threads", "1", "-q:v", "4", str(pattern),
    ]
    _run(command, cancelled, min(deadline, monotonic() + 10))
    result = []
    for path in sorted(folder.glob("frame-*.jpg")):
        index = int(path.stem.rsplit("-", 1)[1]) - 1
        ms = round((start + lead + index * step) * 1000)
        jpeg = _memory_jpeg(path.read_bytes())
        if jpeg:
            result.append(PictureCandidate(page, "frame", "", jpeg, ms))
        path.unlink()
    return result


def _audio(ffmpeg, url, page, start, duration, folder, cancelled, deadline, *, remote=True):
    target = folder / "audio.wav"
    command = _input(ffmpeg, url, page, start, remote=remote) + [
        "-map", "0:a:0", "-vn", "-t", str(duration), "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(target),
    ]
    if _run(command, cancelled, min(deadline, monotonic() + 10)) is None:
        return None
    try:
        with wave.open(str(target), "rb") as stream:
            elapsed = stream.getnframes() * 1000 // stream.getframerate()
        start_ms = round(start * 1000)
        return AudioSample(start_ms, start_ms + elapsed, target.read_bytes()) if elapsed >= 500 else None
    except (OSError, EOFError, wave.Error):
        return None


def collect_video(source, cancelled):
    extractor, page = source
    ffmpeg = shutil.which("ffmpeg")
    if importlib.util.find_spec("yt_dlp") is None:
        return VideoMaterial(status="安装 yt-dlp 后，我就能试着读取视频片段。")
    deadline = monotonic() + VIDEO_TIMEOUT - 3
    info = _metadata(extractor, page, cancelled, deadline)
    windows = _windows(info.get("duration"))
    if not windows:
        return VideoMaterial(status="这次没读到可公开播放的视频片段。")
    material = VideoMaterial(captions=_captions(info, extractor, windows, cancelled))
    if ffmpeg is None:
        material.status = "安装 FFmpeg 后，我就能截取画面和音频。"
        return material
    video, audio = _streams(info, extractor)
    with TemporaryDirectory(prefix="dafeiyu-video-") as tmp:
        folder = Path(tmp)
        for start, duration in windows:
            if video:
                material.frames.extend(_frames(ffmpeg, video["url"], page, start, duration, folder, cancelled, deadline))
            if audio:
                sample = _audio(ffmpeg, audio["url"], page, start, duration, folder, cancelled, deadline)
                if sample:
                    material.audio.append(sample)
    if not (material.frames or material.captions or material.audio):
        material.status = "这次没读到可公开播放的视频片段。"
    return material
