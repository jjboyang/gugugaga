"""Exercise the local diary and a full outing over the app's real HTTP path."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.exploration import (
    Activity, AgentConnection, DEEPSEEK_MODEL, DEEPSEEK_SEARCH_ENDPOINT, DIFY_ENDPOINT,
    Discovery, ExplorationSettings, OPENAI_ENDPOINT,
)
from pet.exploration_agents import (
    DEEPSEEK_CHAT_ENDPOINT, build_request, parse_bilibili_reaction, parse_bilibili_search, parse_result,
)
from pet.exploration_controller import ExplorationController, IDLE_BEFORE_EXPLORING
from pet.exploration_panel import AgentConnectionDialog, AgentSettingsPanel
from pet.window import PetWindow


WEB_RESULT = {
    "url": "https://example.org/seabirds",
    "title": "海边的一天",
    "evidence_kind": "article",
    "observation": "文章记录了海边的一次观鸟活动。",
    "reaction": "我想看看那只站在栏杆上的。",
    "next_topic": "海鸟怎样停在栏杆上",
}
VIDEO_RESULT = {
    "url": "https://example.org/coast/video",
    "title": "一段海岸影像",
    "evidence_kind": "metadata",
    "observation": "简介提到海鸟停在栏杆上。",
    "reaction": "这回先收藏一下。",
}
BILIBILI_URL = "https://www.bilibili.com/video/BV1TestFish/"
BILIBILI_SEARCH_RESULT = {"results": [
    {"url": "https://www.bilibili.com.example.org/video/BV1FakeFish/", "title": "其他网站"},
    {"url": "https://www.bilibili.com/read/cv1", "title": "专栏文章"},
    {"url": BILIBILI_URL + "?spm_id_from=fixture", "title": "海边的小鸟", "snippet": "这是观鸟记录。"},
    {"url": BILIBILI_URL, "title": "重复结果"},
]}
BILIBILI_REACTION = {"choices": [{"message": {"content": json.dumps(
    {"choice": 1, "reaction": "鲸鲸，想看看是哪种小鸟。", "next_topic": "海边常见小鸟",
     "url": "https://www.example.org/ignored", "observation": "我看到了未证实的画面。"},
)}}]}


def openai_connection():
    return AgentConnection("ai", "网页 Agent", "openai", OPENAI_ENDPOINT, "gpt-5-mini", "web", True, True, True)


def deepseek_connection():
    return AgentConnection("ds", "B 站视频", "deepseek", DEEPSEEK_SEARCH_ENDPOINT,
                           DEEPSEEK_MODEL, "video", True, True, True)


class AgentProtocolTests(unittest.TestCase):
    def test_openai_request_and_cited_responses_shape(self):
        connection = openai_connection()
        body = build_request(connection, Activity("海鸥", "web", "海鸟"))
        self.assertEqual(body["tools"][0]["type"], "web_search")
        self.assertFalse(body["store"])
        output = {
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {"type": "message", "content": [{
                    "type": "output_text",
                    "text": "看到：岸边有记录。\n想法：想找海边的鸟。\n下次：无。\n证据：正文",
                    "annotations": [{"type": "url_citation", "url": WEB_RESULT["url"], "title": WEB_RESULT["title"]}],
                }]},
            ],
        }
        discovery = parse_result(connection, json.dumps(output))
        self.assertEqual(discovery.url, WEB_RESULT["url"])
        self.assertEqual(discovery.reaction, "想找海边的鸟。")
        self.assertEqual(discovery.next_topic, "")
        self.assertEqual(discovery.evidence_kind, "metadata")
        output["output"][0]["action"] = {"type": "open_page", "url": WEB_RESULT["url"]}
        self.assertEqual(parse_result(connection, json.dumps(output)).evidence_kind, "article")
        output["output"][1]["content"][0]["annotations"] = 99
        with self.assertRaisesRegex(ValueError, "没有返回"):
            parse_result(connection, json.dumps(output))

    def test_invalid_custom_result_is_rejected_and_metadata_survives(self):
        connection = replace(openai_connection(), provider="http", capability="video")
        for changes in ({"url": "file:///tmp/oops"}, {"url": "http://127.0.0.1"}, {"evidence_kind": "article"},
                        {"evidence_kind": []}, {"reaction": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_result(connection, json.dumps(VIDEO_RESULT | changes))
        self.assertEqual(parse_result(connection, json.dumps(VIDEO_RESULT)).evidence_kind, "metadata")

    def test_dify_stream_uses_the_final_result_without_appending_deltas(self):
        connection = replace(openai_connection(), provider="dify", endpoint=DIFY_ENDPOINT, model="", capability="video")
        connection.validate()
        request = build_request(connection, Activity("海鸟视频", "video", "海鸟"))
        self.assertEqual(request["response_mode"], "streaming")
        self.assertIn("海鸟视频", request["query"])
        events = [{"event": "agent_message", "answer": "partial"},
                  {"event": "message", "answer": json.dumps(VIDEO_RESULT)},
                  {"event": "message_end"}]
        prefix = "".join("data: " + json.dumps(event) + "\r\n\r\n" for event in events[:-1])
        with self.assertRaisesRegex(ValueError, "没有返回完整"):
            parse_result(connection, prefix.encode())
        result = parse_result(connection, (prefix + "data: " + json.dumps(events[-1])).encode())
        self.assertEqual(result.url, VIDEO_RESULT["url"])

    def test_deepseek_requires_a_real_candidate_and_preserves_search_evidence(self):
        connection = deepseek_connection()
        connection.validate()
        with self.assertRaises(ValueError):
            replace(connection, endpoint=DIFY_ENDPOINT).validate()
        with self.assertRaises(ValueError):
            replace(connection, has_key=False).validate()
        request = build_request(connection, Activity("海鸟 OR site:example.org", "video", "海鸟"))
        self.assertTrue(request["query"].endswith(" site:www.bilibili.com"))
        self.assertEqual(request["query"].count("site:"), 1)
        candidates = parse_bilibili_search(json.dumps(BILIBILI_SEARCH_RESULT))
        self.assertEqual([entry["url"] for entry in candidates], [BILIBILI_URL])
        discovery = parse_bilibili_reaction(json.dumps(BILIBILI_REACTION), candidates)
        self.assertEqual(discovery.url, BILIBILI_URL)
        self.assertEqual(discovery.evidence_kind, "metadata")
        self.assertEqual(discovery.observation, "这是观鸟记录。")
        fake_choice = {"choices": [{"message": {"content": '{"choice":99,"reaction":"鲸鲸"}'}}]}
        with self.assertRaisesRegex(ValueError, "没有选中"):
            parse_bilibili_reaction(json.dumps(fake_choice), candidates)


class WorkSignals(QObject):
    active_changed = Signal(bool)


class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        received = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.received.append((self.path, received, self.headers.get("Authorization")))
        if self.path == "/redirect":
            self.send_response(307)
            self.send_header("Location", "/video")
            self.end_headers()
            return
        result = {
            "/video": VIDEO_RESULT,
            "/deepseek-search": BILIBILI_SEARCH_RESULT,
            "/deepseek-empty": {"results": BILIBILI_SEARCH_RESULT["results"][:2]},
            "/deepseek-chat": BILIBILI_REACTION,
        }.get(self.path, WEB_RESULT)
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ExplorationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), AgentHandler)
        cls.server.received = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.received.clear()
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "diary.sqlite3"
        self.credentials = Mock()
        self.make_pet()

    def make_pet(self):
        self.window = PetWindow()
        self.rig = Mock()
        self.work = WorkSignals()
        self.controller = ExplorationController(
            self.window, self.rig, self.work, is_active=lambda: True,
            diary_path=self.path, credentials=self.credentials,
        )
        self.addCleanup(self.close_pet, self.controller, self.window)

    def close_pet(self, controller, window):
        controller.shutdown()
        window.close()
        self.app.processEvents()

    def connection(self, id, capability, *, background=True):
        endpoint = f"http://127.0.0.1:{self.server.server_port}/{id}"
        return AgentConnection(id, f"{id} Agent", "http", endpoint, f"{id}-research", capability, True, background, False)

    def finish_round(self):
        stop = time.monotonic() + 5
        while self.controller.reply is not None and time.monotonic() < stop:
            QTest.qWait(20)
        self.assertIsNone(self.controller.reply, "the Qt network request did not finish")

    def test_idle_outing_follows_a_saved_thread_on_another_agent_after_restart(self):
        web = self.connection("web", "web")
        video = self.connection("video", "video", background=False)
        self.assertEqual(self.controller.save_connection(web, None, None), "")
        self.assertEqual(self.controller.save_connection(video, None, None), "")
        self.assertEqual(self.controller.save_settings(ExplorationSettings(True, 2)), "")

        self.controller.last_touch -= IDLE_BEFORE_EXPLORING + 1
        self.controller._tick()
        self.assertIsNotNone(self.controller.reply)
        self.finish_round()
        self.assertEqual(self.server.received[0][0], "/web")
        self.assertEqual(self.server.received[0][1]["previous"], {})
        self.rig.set_exploring.assert_any_call(True)
        self.rig.set_exploring.assert_called_with(False)
        self.assertEqual(self.controller.diary.recent()[0]["next_topic"], WEB_RESULT["next_topic"])
        self.close_pet(self.controller, self.window)

        self.make_pet()
        self.assertEqual(len(self.controller.diary.connections()), 2)
        self.assertEqual(self.controller.save_connection(replace(web, enabled=False), web, None), "")
        self.window.exploration_requested.emit()
        self.assertEqual(self.controller.panel.history.count(), 1)
        self.controller.panel.explore.click()
        self.finish_round()
        path, request, authorization = self.server.received[1]
        self.assertEqual(path, "/video")
        self.assertIsNone(authorization)
        self.assertEqual(request["topic"], WEB_RESULT["next_topic"])
        self.assertEqual(request["previous"]["url"], WEB_RESULT["url"])
        self.assertEqual(self.controller.panel.history.count(), 2)
        self.assertIn("标题或简介", self.controller.panel.detail.toPlainText())
        self.controller.start_exploring()
        self.assertIsNone(self.controller.reply)
        self.assertIn("次数用完", self.controller.status)
        self.assertEqual(len(self.server.received), 2)

    def test_work_end_sharing_uses_distinct_days_and_waits_for_the_pet(self):
        diary = self.controller.diary
        today = datetime.now()
        for offset in (1, 1, 2):
            diary.remember_work_return((today.date() - timedelta(days=offset)).isoformat())
        self.assertEqual(diary.work_return_days(today), 2)
        self.work.active_changed.emit(False)
        self.assertIsNone(self.controller.share_window)
        self.window.pet_tapped.emit()
        self.assertEqual(diary.work_return_days(today), 3)

        self.window.say = Mock()
        agent = self.connection("web", "web")
        outing_id = diary.reserve(agent, Activity("海鸟", "web", "海鸟"), today.timestamp(),
                                  today.date().isoformat(), 3)
        diary.finish(outing_id, Discovery(**WEB_RESULT))
        self.work.active_changed.emit(True)
        self.work.active_changed.emit(False)
        self.rig.can_show_exploration.return_value = False
        earliest, _, _ = self.controller.share_window
        self.controller._maybe_share(earliest + 1)
        self.window.say.assert_not_called()
        self.rig.can_show_exploration.return_value = True
        self.controller._maybe_share(earliest + 2)
        self.window.say.assert_called_once()
        self.assertIsNone(diary.latest_unshared())

    def test_authentication_is_stored_only_in_credentials(self):
        secret = "example-test-secret"
        conn = openai_connection()
        self.assertEqual(self.controller.save_connection(conn, None, secret), "")
        self.credentials.set.assert_called_once_with(conn.id, secret)
        self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.controller.open_panel()
        settings = AgentSettingsPanel(self.controller, self.controller.panel)
        self.assertEqual(settings.agents.count(), 1)
        edit = AgentConnectionDialog(self.controller, conn, settings)
        self.assertEqual(edit.key.text(), "")
        self.assertIn("钥匙串", edit.key.placeholderText())

    def test_deepseek_key_only_connection_searches_then_selects_a_bilibili_video(self):
        secret = "deepseek-test-key"
        self.credentials.get.return_value = secret
        self.controller.open_panel()
        settings = AgentSettingsPanel(self.controller, self.controller.panel)
        dialog = AgentConnectionDialog(self.controller, None, settings)
        dialog.provider.setCurrentIndex(dialog.provider.findData("deepseek"))
        dialog.key.setText(secret)
        self.assertEqual(dialog.endpoint.text(), DEEPSEEK_SEARCH_ENDPOINT)
        self.assertEqual(dialog.model.text(), DEEPSEEK_MODEL)
        self.assertEqual(dialog.capability.currentData(), "video")
        self.assertFalse(dialog.capability.isEnabled())
        dialog._save()
        connection, = self.controller.diary.connections()
        self.assertEqual(connection.provider, "deepseek")
        self.credentials.set.assert_called_once_with(connection.id, secret)

        send = self.controller.network.post
        fixture_paths = {
            DEEPSEEK_SEARCH_ENDPOINT: "/deepseek-search",
            DEEPSEEK_CHAT_ENDPOINT: "/deepseek-chat",
        }
        endpoints = []

        def fixture_post(request, body):
            endpoint = request.url().toString()
            endpoints.append(endpoint)
            request.setUrl(QUrl(f"http://127.0.0.1:{self.server.server_port}{fixture_paths[endpoint]}"))
            return send(request, body)

        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            self.controller.panel.explore.click()
            self.finish_round()
            self.assertEqual(endpoints, [DEEPSEEK_SEARCH_ENDPOINT, DEEPSEEK_CHAT_ENDPOINT])
            self.assertEqual(self.controller.panel.history.count(), 1)
            entry, = self.controller.diary.recent()
            self.assertEqual(entry["url"], BILIBILI_URL)
            self.assertEqual(entry["reaction"], "鲸鲸，想看看是哪种小鸟。")
            self.assertEqual(len(self.server.received), 2)
            self.assertTrue(all(record[2] == f"Bearer {secret}" for record in self.server.received))
            search_body = self.server.received[0][1]
            chat_body = self.server.received[1][1]
            self.assertTrue(search_body["query"].endswith("site:www.bilibili.com"))
            self.assertEqual(chat_body["model"], DEEPSEEK_MODEL)
            self.assertNotIn(secret, json.dumps(chat_body))
            self.assertIn("今日探索 1/3 轮", self.controller.panel.status.text())

            fixture_paths[DEEPSEEK_SEARCH_ENDPOINT] = "/deepseek-empty"
            self.controller.panel.explore.click()
            self.finish_round()
            self.assertEqual(endpoints[2:], [DEEPSEEK_SEARCH_ENDPOINT])
            self.assertIn("没搜到符合条件的 B 站公开视频", self.controller.status)
            self.assertEqual(self.controller.panel.history.count(), 1)
            self.assertIsNone(self.controller.video_candidates)

    def test_custom_agent_redirect_is_not_followed(self):
        connection = self.connection("redirect", "web")
        self.assertEqual(self.controller.save_connection(connection, None, None), "")
        self.controller.start_exploring()
        self.finish_round()
        self.assertIn("307", self.controller.status)
        self.assertEqual(len(self.server.received), 1)
        self.assertFalse(self.controller.diary.recent())
