"""Schedule bounded background outings without blocking the pet window."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import random
import sqlite3
import time

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from pet.exploration import ExplorationDiary, WORK_RETURN_DAYS, choose_activity
from pet.exploration_agents import (
    DEEPSEEK_CHAT_ENDPOINT, build_bilibili_reaction, build_request,
    parse_bilibili_reaction, parse_bilibili_search, parse_result,
)
from pet.exploration_panel import AgentSettingsPanel, ExplorationPanel


IDLE_BEFORE_EXPLORING = 10 * 60
OUTING_INTERVAL = 15 * 60
REQUEST_TIMEOUT_MS = 40_000
MAX_RESPONSE_BYTES = 512 * 1024
DIARY_ERROR = "探索日记暂时读写不了。"
KEY_ERROR = "系统钥匙串不可用。请解锁钥匙串后再试。"


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
    def __init__(self, window, rig, work, *, is_active, diary_path=None, credentials=None):
        super().__init__(window)
        self.window = window
        self.rig = rig
        self.is_active = is_active
        self.credentials = credentials if credentials is not None else SystemCredentials()
        self.rng = random.Random()
        self.panel = None
        self.settings_panel = None
        self.reply = None
        self.outing = None
        self.video_candidates = None
        self.buffer = bytearray()
        self.request_key = ""
        self.request_error = ""
        self.status = ""
        self.last_touch = time.monotonic()
        self.next_outing = 0.0
        self.work_ended = None
        self.share_window = None
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
        self.deadline.timeout.connect(lambda: self._cancel("这次逛得有点久，下次再去。"))
        window.exploration_requested.connect(self.open_panel)
        window.interaction_started.connect(self._touched)
        window.pet_tapped.connect(self._on_pet_tapped)
        window.face_tapped.connect(self._on_face_tapped)
        work.active_changed.connect(self._on_work_changed)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        if self.diary is not None:
            self.timer.start()

    def open_panel(self):
        if not self.is_active():
            return
        if self.panel is None:
            self.panel = ExplorationPanel(self)
        self._refresh()
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

    def save_settings(self, settings):
        try:
            self.diary.save_settings(settings)
        except ValueError as error:
            return str(error)
        except sqlite3.Error:
            return DIARY_ERROR
        if not settings.automatic and self.outing and self.outing[2]:
            self._cancel("已暂停自动探索。")
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
        if not error and self.outing and self.outing[1].id == connection.id:
            self._cancel("连接设置已更新。")
        return error

    def remove_connection(self, connection):
        error = self._update_connection(connection.id, connection, "" if connection.has_key else None,
                                        lambda: self.diary.remove_connection(connection.id))
        if not error and self.outing and self.outing[1].id == connection.id:
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
        if self.reply is not None or not self.is_active() or self.diary is None or self.closing:
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
            self.next_outing = time.monotonic() + OUTING_INTERVAL
            key = self._read_key(agent)
            if key is None:
                self._refresh()
                return
            outing_id = self.diary.reserve(agent, activity, now.timestamp(), now.date().isoformat(),
                                          settings.daily_limit)
        except ValueError as error:
            self.status = str(error)
            self._refresh()
            return
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()
            return

        self.outing = (outing_id, agent, automatic, activity)
        self.request_key = key
        self._post(agent, agent.endpoint, build_request(agent, activity))
        self.deadline.start(REQUEST_TIMEOUT_MS)
        self.status = f"我正在找「{activity.topic}」。"
        self.rig.set_exploring(True)
        self._refresh()

    def _post(self, agent, endpoint, body):
        request = QNetworkRequest(QUrl(endpoint))
        request.setRawHeader(b"Content-Type", b"application/json")
        request.setRawHeader(b"Accept", b"text/event-stream" if agent.provider == "dify" else b"application/json")
        if self.request_key:
            request.setRawHeader(b"Authorization", f"Bearer {self.request_key}".encode("ascii"))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.buffer.clear()
        self.request_error = ""
        self.reply = self.network.post(request, payload)
        self.reply.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)

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
            self._cancel("这次返回的内容太长了。")

    def _cancel(self, reason):
        if self.reply is not None:
            self.request_error = reason
            self.reply.abort()

    def _finished(self):
        if self.reply is None:
            return
        reply, self.reply = self.reply, None
        outing_id, agent, _, activity = self.outing
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        problem = self.request_error
        discovery = None
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

        if not problem:
            try:
                if agent.provider == "deepseek":
                    if self.video_candidates is None:
                        self.video_candidates = parse_bilibili_search(self.buffer)
                        body = build_bilibili_reaction(agent, activity, self.video_candidates)
                        self._post(agent, DEEPSEEK_CHAT_ENDPOINT, body)
                        self.status = "我在挑一条 B 站视频。"
                        self._refresh()
                        return
                    discovery = parse_bilibili_reaction(self.buffer, self.video_candidates)
                else:
                    discovery = parse_result(agent, self.buffer)
                key = self.request_key
                if key and any(key == value or (len(key) >= 12 and key in value)
                               for value in vars(discovery).values()):
                    discovery = None
                    problem = "这个 Agent 把凭据写进了回复。"
            except (ValueError, RecursionError) as error:
                problem = str(error)

        self.outing = None
        self.video_candidates = None
        self.request_key = ""
        self.deadline.stop()
        self.rig.set_exploring(False)
        self.buffer.clear()
        try:
            self.diary.finish(outing_id, discovery)
            self.status = problem or "我找到了一条。想看的话，点一下最新的记录。"
        except sqlite3.Error:
            self.status = DIARY_ERROR
        if not self.closing:
            self._refresh()

    def _refresh(self):
        if self.panel is None:
            return
        status = self.status
        entries = []
        available = self.diary is not None
        can_start = False
        if available:
            try:
                entries = self.diary.recent()
                can_start = bool(self._available_agents()) and self.reply is None
                if not status:
                    if entries:
                        status = "今天还想再看看别的。"
                    elif can_start:
                        status = "可以点「去逛一会儿」，陪我试一轮。"
                    else:
                        status = "可以先加一个 Agent，陪我试逛一轮。"
                used = self.diary.calls_on(datetime.now().date().isoformat())
                status += f"\n今日探索 {used}/{self.diary.settings().daily_limit} 轮"
            except sqlite3.Error:
                status = DIARY_ERROR
        self.panel.refresh(status, entries, available=available, can_start=can_start)

    def _touched(self):
        self.last_touch = time.monotonic()

    def _on_work_changed(self, active):
        if active:
            self.work_ended = self.share_window = None
        elif self.is_active() and self.diary is not None:
            self.work_ended = time.monotonic()
            try:
                if (self.diary.settings().share_after_work
                        and self.diary.work_return_days(datetime.now()) >= WORK_RETURN_DAYS):
                    self.share_window = (self.work_ended + 3, self.work_ended + 60, True)
            except sqlite3.Error:
                self.status = DIARY_ERROR

    def _on_face_tapped(self, region, _side):
        # Head taps also emit pet_tapped, so only the cheek path needs this hook.
        if region == "cheek":
            self._on_pet_tapped()

    def _on_pet_tapped(self):
        if not self.is_active() or self.diary is None:
            return
        now = time.monotonic()
        if self.work_ended is not None and now - self.work_ended <= 5 * 60:
            try:
                self.diary.remember_work_return(datetime.now().date().isoformat())
                self.work_ended = None
            except sqlite3.Error:
                self.status = DIARY_ERROR
        self.share_window = (now + 0.5, now + 7, False)

    def _maybe_share(self, now):
        if self.share_window is None:
            return
        earliest, latest, after_work = self.share_window
        if now > latest:
            self.share_window = None
        elif now >= earliest and self.rig.can_show_exploration() and not (self.panel and self.panel.isVisible()):
            self.share_window = None
            entry = self.diary.latest_unshared()
            work_day = datetime.now().date().isoformat() if after_work else None
            if entry and self.diary.mark_shared(entry["id"], work_day):
                teaser = entry["reaction"]
                if len(teaser) > 18:
                    teaser = teaser[:17] + "…"
                self.window.say(teaser, "whale", hold_ms=3600)

    def _tick(self):
        if not self.is_active() or self.diary is None:
            return
        now = time.monotonic()
        try:
            self._maybe_share(now)
            if now - self.last_touch >= IDLE_BEFORE_EXPLORING and now >= self.next_outing and self.reply is None:
                self.next_outing = now + 60
                self.start_exploring(automatic=True)
        except sqlite3.Error:
            self.status = DIARY_ERROR
            self._refresh()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        if self.reply is not None:
            self._cancel("桌宠已退出。")
            if self.reply is not None:
                self._finished()
        if self.diary is not None:
            self.diary.close()
            self.diary = None
