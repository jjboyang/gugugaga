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
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.exploration import Activity, AgentConnection, DIFY_ENDPOINT, Discovery, ExplorationSettings, OPENAI_ENDPOINT
from pet.exploration_agents import build_request, parse_result
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


def openai_connection():
    return AgentConnection("ai", "网页 Agent", "openai", OPENAI_ENDPOINT, "gpt-5-mini", "web", True, True, True)


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
        result = VIDEO_RESULT if self.path == "/video" else WEB_RESULT
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

    def test_custom_agent_redirect_is_not_followed(self):
        connection = self.connection("redirect", "web")
        self.assertEqual(self.controller.save_connection(connection, None, None), "")
        self.controller.start_exploring()
        self.finish_round()
        self.assertIn("307", self.controller.status)
        self.assertEqual(len(self.server.received), 1)
        self.assertFalse(self.controller.diary.recent())
