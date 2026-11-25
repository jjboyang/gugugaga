"""Schedule bounded background outings without blocking the pet window."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import random
import sqlite3
from threading import Event, Thread
import time

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from pet.exploration import (
    BILIBILI_DOMAIN, DAILY_LIMIT_REACHED, Activity, AgentConnection, ExplorationDiary, ExplorationWebsite,
    choose_activity, choose_website,
)
from pet.exploration_agents import (
    DEEPSEEK_ASR_ENDPOINT, DEEPSEEK_CHAT_ENDPOINT, DEEPSEEK_FETCH_ENDPOINT, build_audio_request,
    build_request, build_website_reaction, parse_result, parse_website_reaction, parse_website_search,
    read_audio_transcript, read_website_page, website_links,
)
from pet.exploration_panel import AgentSettingsPanel, ExplorationPanel, WebsiteSettingsPanel
from pet.exploration_pictures import PICTURE_TIMEOUT, PictureCandidate, collect_pictures
from pet.exploration_video import AudioSample, TimedText, VIDEO_TIMEOUT, VideoMaterial, collect_video, video_page


IDLE_BEFORE_EXPLORING = 10 * 60
OUTING_INTERVAL = 15 * 60
INVITATION_INTERVAL = (15 * 60, 45 * 60)
INVITATION_QUIET_SECONDS = 30
INVITATION_HOLD_MS = 8000
DAILY_INVITATION_LIMIT = 3
REQUEST_TIMEOUT_MS = 40_000
SITE_SEARCH_TIMEOUT_MS = 12_000
FETCH_TIMEOUT_MS = 8_000
ASR_TIMEOUT_MS = 24_000
MAX_RESPONSE_BYTES = 512 * 1024
DIARY_ERROR = "探索日记暂时读写不了。"
KEY_ERROR = "系统钥匙串不可用。请解锁钥匙串后再试。"


@dataclass
class Outing:
    id: int
    agent: AgentConnection
    automatic: bool
    activity: Activity
    website: ExplorationWebsite | None = None
    stage: str = "agent"
    page_url: str = ""
    results: list = field(default_factory=list)
    links: list = field(default_factory=list)
    pictures: list[PictureCandidate] = field(default_factory=list)
    timed_text: list[TimedText] = field(default_factory=list)
    audio: list[AudioSample] = field(default_factory=list)
    video_status: str = ""


class SystemCredentials:
    SERVICE = "gugugaga.dafeiyu.agents"
    NATIVE_BACKENDS = {
        "keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService",
        "keyring.backends.kwallet", "keyring.backends.libsecret",
    }

    @classmethod
    def _backend(cls):
        from keyring import get_keyring

        backend = get_keyring()
        choices = backend.backends if type(backend).__module__ == "keyring.backends.chainer" else [backend]
        for choice in choices:
            if type(choice).__module__ in cls.NATIVE_BACKENDS:
                return choice
        raise RuntimeError(KEY_ERROR)

    def get(self, connection_id):
        return self._backend().get_password(self.SERVICE, connection_id)

    def set(self, connection_id, secret):
        backend = self._backend()
        if secret:
            backend.set_password(self.SERVICE, connection_id, secret)
        elif backend.get_password(self.SERVICE, connection_id) is not None:
            backend.delete_password(self.SERVICE, connection_id)


class ExplorationController(QObject):
    def __init__(self, window, rig, *, is_active, diary_path=None, credentials=None):
        super().__init__(window)
        self.window = window
        self.rig = rig
        self.is_active = is_active
        self.credentials = credentials if credentials is not None else SystemCredentials()
        self.rng = random.Random()
        self.panel = None
        self.settings_panel = None
        self._displayed_quota_day = None
        self.reply = None
        self.media_job = None
        self.outing = None
        self.buffer = bytearray()
        self.request_key = ""
        self.request_error = ""
        self.status = ""
        self.last_touch = time.monotonic()
        self.next_outing = 0.0
        self.invitation = None
        self.invitation_day = None
        self.next_invitation = 0.0
        self.closing = False
        path = diary_path if diary_path is not None else Path(os.environ.get(
            "DESKTOP_PET_EXPLORATION_PATH", str(Path.home() / ".desktop-pet" / "exploration.sqlite3"),
        ))
        try:
            self.diary = ExplorationDiary(path)
        except (OSError, sqlite3.Error):
            self.diary = None
            self.status = DIARY_ERROR

        self.network = QNetworkAccessManager(self)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda: self._abort_request("这次逛得有点久，下次再去。"))
        self.media_timer = QTimer(self)
        self.media_timer.setInterval(70)
        self.media_timer.timeout.connect(self._check_media)
        window.exploration_requested.connect(self.open_panel)
        window.interaction_started.connect(self._touched)
        window.drag_started.connect(self._cancel_invitation)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        if self.diary is not None:
            self.timer.start()

    def open_panel(self, *, entry_id=None):
        if not self.is_active():
            return
        self._cancel_invitation()
        if self.panel is None:
            self.panel = ExplorationPanel(self)
        self._refresh()
        if entry_id is not None:
            for index, entry in enumerate(self.panel.entries):
                if entry["id"] == entry_id:
                    self.panel.history.setCurrentRow(index)
                    break
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def open_settings(self):
        if self.diary is None or self.settings_panel is not None:
            return
        try:
            self.settings_panel = AgentSettingsPanel(self, self.panel)
            self.settings_panel.exec()
        except sqlite3.Error:
            self.status = DIARY_ERROR
        finally:
            self.settings_panel = None
            self._refresh()

    def open_websites(self):
        if self.diary is None:
            return
        try:
            WebsiteSettingsPanel(self, self.panel).exec()
        except sqlite3.Error:
            self.status = DIARY_ERROR
        self._refresh()

    def remove_website(self, domain):
        self.diary.remove_website(domain)
        if self.outing and self.outing.website and self.outing.website.domain == domain:
            self._cancel("已移除这个探索网站。")

    def save_settings(self, settings):
        try:
            self.diary.save_settings(settings)
        except ValueError as error:
            return str(error)
        except sqlite3.Error:
            return DIARY_ERROR
        if not settings.automatic and self.outing and self.outing.automatic:
            self._cancel("已暂停自动探索。")
        if not settings.invite_to_share:
            self._cancel_invitation()
        self.status = ""
        self._refresh()
        return ""

    def save_connection(self, connection, old, secret):
        try:
            connection.validate()
            if secret and (not secret.isascii() or any(not 32 < ord(char) < 127 for char in secret)):
                raise ValueError("API Key 的格式有误。")
        except ValueError as error:
            return str(error)
        error = self._update_connection(connection.id, old, secret,
                                        lambda: self.diary.save_connection(connection))
        if not error and self.outing and self.outing.agent.id == connection.id:
            self._cancel("连接设置已更新。")
        return error

    def remove_connection(self, connection):
        error = self._update_connection(connection.id, connection, "" if connection.has_key else None,
                                        lambda: self.diary.remove_connection(connection.id))
        if not error and self.outing and self.outing.agent.id == connection.id:
            self._cancel("已移除此连接。")
        return error

    def _update_connection(self, connection_id, old, secret, write):
        previous_secret = None
        if secret is not None:
            try:
                previous_secret = self.credentials.get(connection_id) if old and old.has_key else None
                self.credentials.set(connection_id, secret)
            except Exception:
                return KEY_ERROR
        try:
            write()
        except (ValueError, sqlite3.Error):
            if secret is not None:
                try:
                    self.credentials.set(connection_id, previous_secret)
                except Exception:
                    return "连接更新失败，钥匙串也未能恢复。请重新保存此连接的 API Key。"
            return DIARY_ERROR
        self.status = ""
        self._refresh()
        return ""

    def _available_agents(self, automatic=False):
        return [agent for agent in self.diary.connections()
                if agent.enabled and (not automatic or agent.background)]

    def start_exploring(self, *, automatic=False):
        if self.outing is not None or not self.is_active() or self.diary is None or self.closing:
            return
        now = datetime.now()
        try:
            settings = self.diary.settings()
            if automatic and not settings.automatic:
                return
            agents = self._available_agents(automatic)
            if not agents:
                if not automatic:
                    self.status = "先在「Agent 连接」里添加一个可用的连接。"
                    self._refresh()
                return
            capabilities = sorted({agent.capability for agent in agents})
            activity = choose_activity(self.diary.recent(), capabilities, self.rng)
            matching = [agent for agent in agents if agent.capability == activity.capability]
            agent = self.rng.choice(matching)
            agent.validate()
            website = None
            if agent.provider == "deepseek":
                website = choose_website(self.diary.websites(), now.timestamp())
                if website is None:
                    raise ValueError("先在「探索网站」里加一个网站，我再去逛。")
                if website.kind == "learned" and website.topic:
                    activity = replace(activity, topic=website.topic)
            key = self._read_key(agent)
            if key is None:
                self._refresh()
                return
            outing_id = self.diary.reserve(agent, activity, now.timestamp(), now.date().isoformat(),
                                          settings.daily_limit, website=website)
        except ValueError as error:
            self.status = str(error)
            self._refresh()
            return
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()
            return

        self.next_outing = time.monotonic() + OUTING_INTERVAL
        self.outing = Outing(outing_id, agent, automatic, activity, website)
        self.request_key = key
        self._post(agent.endpoint, build_request(agent, activity, website=website),
                   stage="search" if website else "agent")
        where = f"在 {website.domain} " if website else "在"
        self.status = f"我正{where}找「{activity.topic}」。"
        self.rig.set_exploring(True)
        self._refresh()

    def _post(self, endpoint, body, *, stage, content_type="application/json"):
        self.outing.stage = stage
        request = QNetworkRequest(QUrl(endpoint))
        request.setRawHeader(b"Content-Type", content_type.encode("ascii"))
        accept = b"text/event-stream" if self.outing.agent.provider == "dify" else b"application/json"
        request.setRawHeader(b"Accept", accept)
        if self.request_key:
            request.setRawHeader(b"Authorization", f"Bearer {self.request_key}".encode("ascii"))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.buffer.clear()
        self.request_error = ""
        self.reply = self.network.post(request, payload)
        self.reply.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        timeout = {"site_search": SITE_SEARCH_TIMEOUT_MS, "fetch": FETCH_TIMEOUT_MS,
                   "transcribe": ASR_TIMEOUT_MS}.get(stage, REQUEST_TIMEOUT_MS)
        self.deadline.start(timeout)

    def _read_key(self, agent):
        if not agent.has_key:
            return ""
        try:
            key = self.credentials.get(agent.id)
        except Exception:
            self.status = KEY_ERROR
            return None
        if not key or not key.isascii() or any(not 32 < ord(char) < 127 for char in key):
            self.status = f"「{agent.name}」需要重新保存 API Key。"
            return None
        return key

    def _read(self):
        if self.reply is None:
            return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer) > MAX_RESPONSE_BYTES:
            self._abort_request("这次返回的内容太长了。")

    def _abort_request(self, reason):
        self._cancel("" if self.outing and self.outing.stage in {"fetch", "transcribe"} else reason)

    def _cancel(self, reason):
        if self.reply is not None:
            self.request_error = reason
            self.reply.abort()
        elif self.media_job is not None:
            self._stop_media()
            self._finish_outing(reason)

    def _finished(self):
        if self.reply is None:
            return
        reply, self.reply = self.reply, None
        outing = self.outing
        agent = outing.agent
        self.deadline.stop()
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        problem = self.request_error
        discovery = None
        learned = None
        if not problem:
            self.buffer.extend(bytes(reply.readAll()))
            if len(self.buffer) > MAX_RESPONSE_BYTES:
                problem = "这次返回的内容太长了。"
            elif status in {401, 403}:
                problem = f"「{agent.name}」拒绝了请求，请检查凭据和权限。"
            elif status == 429:
                problem = f"「{agent.name}」暂时限流或额度用完了。"
            elif status is not None and not 200 <= status < 300:
                problem = f"「{agent.name}」返回了 HTTP {status}。"
            elif reply.error() != QNetworkReply.NoError or status is None:
                problem = f"这次没连上「{agent.name}」。"
        reply.deleteLater()

        if outing.stage == "transcribe" and not self.request_error:
            self._receive_transcript(problem)
            return
        if (outing.pictures and outing.stage == "reaction" and not self.request_error
                and status in {400, 415, 422}):
            self._post_website_reaction(with_pictures=False)
            return
        try:
            if outing.website and self._continue_website(outing, problem):
                return
            if not problem:
                if outing.website:
                    discovery, learned = parse_website_reaction(
                        self.buffer, outing.results, outing.links, outing.activity, outing.pictures, outing.timed_text,
                    )
                else:
                    discovery = parse_result(agent, self.buffer)
                key = self.request_key
                if key and any(key == value or (len(key) >= 12 and key in value)
                               for record in (discovery, learned, discovery.picture if discovery else None) if record
                               for value in vars(record).values() if isinstance(value, str)):
                    discovery = learned = None
                    problem = "这个 Agent 把凭据写进了回复。"
        except (ValueError, RecursionError) as error:
            if outing.stage == "reaction" and outing.pictures and not problem:
                self._post_website_reaction(with_pictures=False)
                return
            problem = str(error)
        except sqlite3.Error:
            problem = DIARY_ERROR

        self._finish_outing(problem, discovery, learned)

    def _finish_outing(self, problem, discovery=None, learned=None):
        outing, self.outing = self.outing, None
        self.request_key = ""
        self.rig.set_exploring(False)
        self.buffer.clear()
        try:
            remembered = self.diary.finish(outing.id, discovery, website=learned)
            if remembered:
                self.status = f"我记住了 {learned.domain}，改天还想去看看。"
            elif discovery and discovery.picture:
                self.status = "这一轮我留了一张图。"
            else:
                self.status = problem
            if discovery and outing.video_status:
                self.status = " ".join(filter(None, (self.status, outing.video_status)))
        except sqlite3.Error:
            self.status = DIARY_ERROR
        if not self.closing:
            self._refresh()

    def _continue_website(self, outing, problem):
        if outing.stage in {"search", "site_search"} and not problem:
            website = outing.website
            outing.results = parse_website_search(self.buffer, website)
            outing.page_url = outing.results[0]["url"] if outing.results else website.link_url
            if not outing.page_url and outing.stage == "site_search":
                outing.page_url = f"https://{website.domain}/"
            if not outing.page_url and website.kind == "preset" and website.domain != BILIBILI_DOMAIN:
                self._post(outing.agent.endpoint, {"query": f"site:{website.domain}", "count": 8}, stage="site_search")
                self.status = f"刚才的话题没搜到，我在看看 {website.domain} 上的其他内容。"
                self._refresh()
                return True
            if not outing.page_url:
                raise ValueError(f"这次没在 {website.domain} 找到合适的公开内容。")
            self._post(DEEPSEEK_FETCH_ENDPOINT, {"url": outing.page_url}, stage="fetch")
            return True
        if outing.stage != "fetch" or self.request_error:
            return False

        title, page = "", ""
        if not problem:
            try:
                title, page = read_website_page(self.buffer)
            except ValueError:
                pass
        if not outing.results:
            if not page:
                if outing.website.kind == "preset":
                    raise ValueError(f"这次没能读取 {outing.website.domain} 的页面，可以在「探索网站」试试一条具体网址。")
                raise ValueError(f"这次没能打开 {outing.website.domain} 的公开页面。")
            outing.results = [{
                "url": outing.page_url, "title": title or outing.website.domain,
                "observation": " ".join(page.split())[:350],
                "evidence_kind": "metadata" if outing.website.domain == BILIBILI_DOMAIN else "article",
            }]
        known_domains = self.diary.known_website_domains()
        text = "\n".join((outing.results[0]["observation"], page))
        outing.links = website_links(text, known_domains)
        page_lower = page.lower()
        source = video_page(outing.page_url)
        if source or any(
                hint in page_lower for hint in ("![", "<img", "<video", "og:image", "twitter:image")):
            self._start_media(page, outing.page_url, source)
        else:
            self._post_website_reaction()
        return True

    def _start_media(self, page, url, source):
        result, cancelled = SimpleQueue(), Event()
        timeout = VIDEO_TIMEOUT + PICTURE_TIMEOUT if source else PICTURE_TIMEOUT

        def read_media():
            try:
                video = collect_video(source, cancelled) if source else VideoMaterial()
            except Exception:
                video = VideoMaterial(status="这次没读到可公开播放的视频片段。")
            pictures = video.frames
            if not pictures and not cancelled.is_set():
                try:
                    pictures = collect_pictures(page, url, cancelled)
                except (OSError, ValueError):
                    pictures = []
            if not cancelled.is_set():
                result.put((video, pictures))

        worker = Thread(target=read_media, name="exploration-media", daemon=True)
        self.media_job = (result, cancelled, time.monotonic() + timeout, worker)
        worker.start()
        self.media_timer.start()
        if source:
            self.status = "我在读取视频片段和字幕。"
            self._refresh()

    def _stop_media(self):
        _, cancelled, _, worker = self.media_job
        cancelled.set()
        self.media_job = None
        self.media_timer.stop()
        if self.closing:
            worker.join(timeout=0.4)

    def _check_media(self):
        if self.media_job is None:
            return
        result, _, expires, _ = self.media_job
        try:
            video, pictures = result.get_nowait()
        except Empty:
            if time.monotonic() < expires:
                return
            status = "这次读视频超时了。" if video_page(self.outing.page_url) else ""
            video, pictures = VideoMaterial(status=status), []
        self._stop_media()
        outing = self.outing
        outing.pictures = pictures
        outing.timed_text = video.captions
        outing.audio = video.audio
        outing.video_status = video.status
        self._transcribe_next()

    def _transcribe_next(self):
        if not self.outing.audio:
            self._post_website_reaction()
            return
        content_type, body = build_audio_request(self.outing.audio[0])
        self._post(DEEPSEEK_ASR_ENDPOINT, body, stage="transcribe", content_type=content_type)
        self.status = "我在把听到的话转成文字。"
        self._refresh()

    def _receive_transcript(self, problem):
        outing = self.outing
        sample = outing.audio.pop(0)
        if not problem:
            try:
                transcript = read_audio_transcript(self.buffer, sample)
                if transcript and (not self.request_key or self.request_key not in transcript.text):
                    outing.timed_text.append(transcript)
            except ValueError:
                problem = "没有可读取的转写。"
        if problem and not outing.video_status:
            outing.video_status = "部分音频没能转写，已保留读到的内容。"
        self._transcribe_next()

    def _post_website_reaction(self, *, with_pictures=True):
        outing = self.outing
        if not with_pictures:
            outing.pictures = []
        body = build_website_reaction(outing.agent, outing.activity, outing.results, outing.links,
                                      outing.pictures, outing.timed_text)
        self._post(DEEPSEEK_CHAT_ENDPOINT, body, stage="reaction")
        self.status = f"我在挑 {outing.website.domain} 上感兴趣的内容。"
        self._refresh()

    def _refresh(self, *, day=None):
        if self.panel is None:
            return
        status = self.status
        entries = []
        quota = None
        available = self.diary is not None
        connected = False
        if available:
            try:
                entries = self.diary.recent()
                connected = bool(self._available_agents())
                day = day or datetime.now().date().isoformat()
                used = self.diary.calls_on(day)
                daily_limit = self.diary.settings().daily_limit
                quota = (used, daily_limit)
                self._displayed_quota_day = day
                if status == DAILY_LIMIT_REACHED and used < daily_limit:
                    self.status = status = ""
            except sqlite3.Error:
                status = DIARY_ERROR
        self.panel.refresh(status, entries, available=available, connected=connected,
                           exploring=self.outing is not None, quota=quota)

    def _touched(self):
        self.last_touch = time.monotonic()

    def _accept_invitation(self, entry):
        if self.closing or not self.is_active() or self.diary is None:
            return
        self._touched()
        try:
            picture = self.diary.picture(entry["id"])
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()
            return

        image = QImage.fromData(picture.jpeg, "JPEG") if picture else QImage()
        if not image.isNull():
            def reveal():
                self._share_invited_note(entry["id"], picture.reason, image)

            if self.rig.social.show_exploration_photo(image, reveal):
                return

        reaction, observation = entry["reaction"], entry["observation"]
        text = reaction if reaction == observation else "\n".join(filter(None, (reaction, observation)))
        self._share_invited_note(entry["id"], text, QImage())

    def _share_invited_note(self, entry_id, text, image):
        if (self.closing or not self.is_active() or self.diary is None or not self.window.isVisible()
                or (self.panel is not None and self.panel.isVisible())):
            return
        try:
            if self.diary.mark_shared(entry_id):
                self.window.share_exploration_note(text, image)
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()

    def _cancel_invitation(self):
        if self.invitation is not None:
            self.invitation.close()

    def _maybe_invite(self, now, day):
        if day != self.invitation_day:
            self.invitation_day = day
            self.next_invitation = now + self.rng.uniform(*INVITATION_INTERVAL)
        if now < self.next_invitation or self.invitation is not None:
            return
        self.next_invitation = now + self.rng.uniform(*INVITATION_INTERVAL)
        if (self.outing is not None or now - self.last_touch < INVITATION_QUIET_SECONDS
                or (self.panel is not None and self.panel.isVisible())
                or not self.rig.can_show_exploration() or not self.diary.settings().invite_to_share):
            return
        entry = self.diary.latest_unshared()
        if entry is None:
            return
        if not self.diary.reserve_invitation(day, DAILY_INVITATION_LIMIT):
            self.next_invitation = float("inf")
            return
        prompt = self.window.ask_to_share_exploration(lambda: self._accept_invitation(entry), INVITATION_HOLD_MS)
        self.invitation = prompt
        prompt.dismissed.connect(lambda: setattr(self, "invitation", None))
        self.rig.start_exploration_gesture(self.rng.choice(("wave", "knock")), prompt)

    def _tick(self):
        if not self.is_active() or self.diary is None:
            self._cancel_invitation()
            return
        now = time.monotonic()
        try:
            day = datetime.now().date().isoformat()
            if self.panel is not None and self.panel.isVisible() and day != self._displayed_quota_day:
                self._refresh(day=day)
            self._maybe_invite(now, day)
            if (now - self.last_touch >= IDLE_BEFORE_EXPLORING and now >= self.next_outing
                    and self.outing is None and self.invitation is None
                    and self.rig.can_show_exploration(browsing=True)):
                self.next_outing = now + 60
                self.start_exploring(automatic=True)
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        self._cancel_invitation()
        if self.outing is not None:
            self._cancel("桌宠已退出。")
            if self.reply is not None:
                self._finished()
        if self.diary is not None:
            self.diary.close()
            self.diary = None
