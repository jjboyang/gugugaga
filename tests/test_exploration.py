"""Exercise the local diary and a full outing over the app's real HTTP path."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from pet.exploration import (
    Activity, AgentConnection, BILIBILI_DOMAIN, DEEPSEEK_MODEL, DEEPSEEK_SEARCH_ENDPOINT, DIFY_ENDPOINT,
    Discovery, ExplorationSettings, ExplorationWebsite, OPENAI_ENDPOINT,
)
from pet.exploration_agents import (
    DEEPSEEK_ASR_ENDPOINT, DEEPSEEK_CHAT_ENDPOINT, DEEPSEEK_FETCH_ENDPOINT, build_request, parse_result,
    parse_website_reaction, parse_website_search, website_links,
)
from pet.exploration_controller import DAILY_INVITATION_LIMIT, ExplorationController, IDLE_BEFORE_EXPLORING
from pet.exploration_panel import AgentConnectionDialog, AgentSettingsPanel, WebsiteSettingsPanel
from pet.exploration_pictures import PictureCandidate, collect_pictures
from pet.exploration_video import AudioSample, TimedText, VideoMaterial, _audio, _frames, _parse_captions, playback_url, video_page
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
PICTURE_URL = "https://images.example.net/art.png"
PICTURE_REASON = "这张图里的海蓝色我想留着。"
LINKED_SITE = "birdnotes.example.org"
LINKED_PAGE = f"https://{LINKED_SITE}/shore"
BILIBILI_SEARCH_RESULT = {"results": [
    {"url": "https://www.bilibili.com.example.org/video/BV1FakeFish/", "title": "其他网站"},
    {"url": "https://www.bilibili.com/read/cv1", "title": "专栏文章"},
    {"url": BILIBILI_URL + "?spm_id_from=fixture", "title": "海边的小鸟", "snippet": "这是观鸟记录。"},
    {"url": BILIBILI_URL, "title": "重复结果"},
]}
BILIBILI_REACTION = {"choices": [{"message": {"content": json.dumps(
    {"choice": 1, "reaction": "鲸鲸，想看看是哪种小鸟。", "next_topic": "海边常见小鸟",
     "site_choice": 1, "url": "https://www.example.org/ignored", "observation": "我看到了未证实的画面。",
     "picture_choice": 1, "picture_reason": PICTURE_REASON},
)}}]}
BILIBILI_PAGE = {"title": "海边的小鸟", "content": (
    f"视频简介推荐了[海边观鸟资料]({LINKED_PAGE}?from=video)。\n"
    "![截图](https://images.example.net/art.png)\n"
    "[另一个站内视频](https://www.bilibili.com/video/BV1MoreFish/)"
)}
LINKED_DOCUMENT = {"title": "岸边观鸟笔记", "content": "这里整理了岸边常见的小鸟。"}


def picture_bytes(format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (320, 240), "#70a6dc").save(buffer, format=format)
    return buffer.getvalue()


class PictureCollectionTests(unittest.TestCase):
    def test_video_cover_comes_from_page_metadata_and_decodes(self):
        legacy_url = PICTURE_URL.replace("https:", "http:", 1)
        html = f'<meta property="og:image" content="{legacy_url}">'
        with patch("pet.exploration_pictures._download", side_effect=[html.encode(), picture_bytes()]) as get:
            pictures = collect_pictures("", BILIBILI_URL, threading.Event())
        self.assertEqual([call.args[0] for call in get.call_args_list], [BILIBILI_URL, PICTURE_URL])
        picture, = pictures
        self.assertEqual((picture.url, picture.kind), (PICTURE_URL, "cover"))
        with Image.open(BytesIO(picture.jpeg)) as image:
            self.assertEqual(image.size, (320, 240))

    def test_article_uses_public_picture_links_and_skips_non_images(self):
        page = (
            "![不可用](https://127.0.0.1/image.png)\n"
            "![相对链接](/bird.png)\n"
            "![配图](https://images.example.net/art.png)"
        )
        with patch("pet.exploration_pictures._download", side_effect=[b"<html>", picture_bytes()]) as get:
            pictures = collect_pictures(page, "https://example.org/articles/1", threading.Event())
        self.assertEqual([call.args[0] for call in get.call_args_list], ["https://example.org/bird.png", PICTURE_URL])
        self.assertEqual([p.url for p in pictures], [PICTURE_URL])


class VideoCollectionTests(unittest.TestCase):
    def test_bilibili_video_and_audio_send_a_browser_user_agent_before_the_input(self):
        video_url = "https://upos.example.bilivideo.com/video.m4s"
        audio_url = "https://upos.example.bilivideo.com/audio.m4s"
        cancelled, deadline = threading.Event(), time.monotonic() + 5
        with TemporaryDirectory() as tmp, patch("pet.exploration_video._run", return_value=None) as run:
            _frames("ffmpeg", video_url, BILIBILI_URL, 0, 18, Path(tmp), cancelled, deadline)
            _audio("ffmpeg", audio_url, BILIBILI_URL, 0, 18, Path(tmp), cancelled, deadline)

        self.assertEqual(run.call_count, 2)
        for call, url in zip(run.call_args_list, (video_url, audio_url)):
            command = call.args[0]
            input_at = command.index("-i")
            self.assertIn("-user_agent", command[:input_at])
            user_agent_at = command.index("-user_agent")
            self.assertTrue(command[user_agent_at + 1].startswith("Mozilla/5.0 "))
            self.assertEqual(command[input_at + 1], url)

    def test_caption_times_and_playback_keep_the_original_part(self):
        source = video_page(BILIBILI_URL + "?p=3&spm_id_from=foo")
        self.assertEqual(source, ("BiliBili", BILIBILI_URL + "?p=3"))
        self.assertEqual(playback_url(source[1], 2520), BILIBILI_URL + "?p=3&t=2")
        self.assertEqual(playback_url("https://youtu.be/M7lc1UVf-VE", 2520),
                         "https://www.youtube.com/watch?v=M7lc1UVf-VE&t=2s")
        srt = ("1\r\n00:00:01,100 --> 00:00:03,350\r\n<i>一只白鹭</i>停在栏杆上。\r\n\r\n"
               "2\r\n00:01:00,000 --> 00:01:10,000\r\n远处的渔船。")
        self.assertEqual(_parse_captions(srt, [(0, 18)]),
                         [TimedText("subtitle", 1100, 3350, "一只白鹭停在栏杆上。")])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is unavailable")
    def test_ffmpeg_decodes_real_video_and_audio_at_requested_times(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "fixture.mp4"
            subprocess.run([
                shutil.which("ffmpeg"), "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
                "-t", "18", "-c:v", "mpeg4", "-c:a", "aac", "-threads", "1", str(source),
            ], check=True, timeout=15)
            cancelled, deadline = threading.Event(), time.monotonic() + 15
            args = (shutil.which("ffmpeg"), source, BILIBILI_URL, 2, 14, folder, cancelled, deadline)
            frames = _frames(*args, remote=False)
            self.assertEqual([frame.timestamp_ms for frame in frames], [3000, 9000, 15000])
            self.assertEqual(len({frame.jpeg for frame in frames}), 3)
            audio = _audio(*args, remote=False)
            self.assertEqual((audio.start_ms, audio.end_ms, audio.wav[:4]), (2000, 16000, b"RIFF"))


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
        activity = Activity("海鸟 OR site:example.org", "video", "海鸟")
        website = ExplorationWebsite(BILIBILI_DOMAIN)
        request = build_request(connection, activity, website=website)
        self.assertTrue(request["query"].endswith(" site:bilibili.com"))
        self.assertEqual(request["query"].count("site:"), 1)
        candidates = parse_website_search(json.dumps(BILIBILI_SEARCH_RESULT), website)
        self.assertEqual([entry["url"] for entry in candidates], [BILIBILI_URL])
        links = website_links(BILIBILI_PAGE["content"], [BILIBILI_DOMAIN])
        self.assertEqual([site["domain"] for site in links], [LINKED_SITE])
        discovery, learned = parse_website_reaction(json.dumps(BILIBILI_REACTION), candidates, links, activity)
        self.assertEqual(discovery.url, BILIBILI_URL)
        self.assertEqual(discovery.evidence_kind, "metadata")
        self.assertEqual(discovery.observation, "这是观鸟记录。")
        self.assertEqual(learned.domain, LINKED_SITE)
        self.assertEqual(learned.source_url, BILIBILI_URL)
        self.assertEqual(learned.link_url, LINKED_PAGE)
        _, no_link = parse_website_reaction(json.dumps(BILIBILI_REACTION), candidates, [], activity)
        self.assertIsNone(no_link)
        other = dict(candidates[0], url="https://www.bilibili.com/video/BV2TestFish/")
        other_choice = {"choices": [{"message": {"content": '{"choice":2,"site_choice":1,"reaction":"鲸鲸"}'}}]}
        discovery, wrong_page = parse_website_reaction(json.dumps(other_choice), candidates + [other], links, activity)
        self.assertEqual(discovery.url, other["url"])
        self.assertIsNone(wrong_page)
        fake_choice = {"choices": [{"message": {"content": '{"choice":99,"reaction":"鲸鲸"}'}}]}
        with self.assertRaisesRegex(ValueError, "没有选中"):
            parse_website_reaction(json.dumps(fake_choice), candidates, links, activity)


class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        received = raw if self.path == "/deepseek-asr" else json.loads(raw)
        self.server.received.append((self.path, received, self.headers.get("Authorization")))
        if self.path == "/redirect":
            self.send_response(307)
            self.send_header("Location", "/video")
            self.end_headers()
            return
        if self.path == "/vision-error":
            self.send_response(400)
            self.end_headers()
            return
        result = {
            "/video": VIDEO_RESULT,
            "/deepseek-search": BILIBILI_SEARCH_RESULT,
            "/deepseek-empty": {"results": BILIBILI_SEARCH_RESULT["results"][:2]},
            "/deepseek-site-search": {"results": [
                {"url": "https://movie.ysjf.com/", "title": "观影信息发布平台"},
            ]},
            "/deepseek-bilibili-page": BILIBILI_PAGE,
            "/deepseek-linked-page": LINKED_DOCUMENT,
            "/deepseek-chat": BILIBILI_REACTION,
            "/deepseek-asr": {"text": "它顺着潮水退去的方向往前走。", "duration_ms": 2800},
            "/deepseek-video-chat": {"choices": [{"message": {"content": json.dumps(
                {"choice": 1, "reaction": "鲸鲸，原来退潮后它会跟着水走。", "video_choice": 2,
                 "picture_choice": 1, "picture_reason": "我想记住它停在湿石头上的样子。"},
            )}}]},
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
        fixture = patch("pet.exploration_pictures._download", return_value=b"")
        self.image_download = fixture.start()
        self.addCleanup(fixture.stop)
        video_fixture = patch("pet.exploration_controller.collect_video", return_value=VideoMaterial())
        self.video_read = video_fixture.start()
        self.addCleanup(video_fixture.stop)
        self.make_pet()

    def make_pet(self):
        self.window = PetWindow()
        self.rig = Mock()
        self.controller = ExplorationController(
            self.window, self.rig, is_active=lambda: True,
            diary_path=self.path, credentials=self.credentials,
        )
        self.addCleanup(self.close_pet, self.controller, self.window)

    def close_pet(self, controller, window):
        if controller.closing:
            return
        controller.shutdown()
        if controller.panel:
            controller.panel.close()
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def connection(self, id, capability, *, background=True):
        endpoint = f"http://127.0.0.1:{self.server.server_port}/{id}"
        return AgentConnection(id, f"{id} Agent", "http", endpoint, f"{id}-research", capability, True, background, False)

    def finish_round(self):
        stop = time.monotonic() + 5
        while self.controller.outing is not None and time.monotonic() < stop:
            QTest.qWait(20)
        self.assertIsNone(self.controller.outing, "the exploration outing did not finish")

    def test_reading_an_older_note_keeps_its_scroll_and_source_on_refresh(self):
        diary = self.controller.diary
        agent = self.connection("web", "web")
        now = datetime.now()
        for offset in (2, 1):
            item = diary.reserve(agent, Activity("海鸟", "web", "海鸟"), now.timestamp() - offset,
                                 now.date().isoformat(), 3)
            note = Discovery(**WEB_RESULT)
            if offset == 2:
                note = replace(note, title="第一次的探索", observation=note.observation * 25)
            else:
                note = replace(note, title="刚带回来的发现", url="https://example.org/recent")
            diary.finish(item, note)
        self.window.exploration_requested.emit()
        panel = self.controller.panel
        panel.resize(620, 420)
        panel.history.setCurrentRow(1)
        self.app.processEvents()
        scroll = panel.detail.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 0)
        scroll.setValue(scroll.maximum())
        self.controller._refresh()
        self.assertEqual(panel.detail.title.text(), "第一次的探索")
        self.assertGreater(scroll.value(), 0)
        self.assertTrue(panel.source.isVisible())
        with patch("pet.exploration_panel.QDesktopServices.openUrl") as open_url:
            panel.source.click()
        self.assertEqual(open_url.call_args.args[0].toString(), WEB_RESULT["url"])

    def test_open_exploration_panel_resets_daily_quota_at_local_midnight(self):
        controller = self.controller
        self.assertEqual(controller.save_connection(self.connection("web", "web"), None, None), "")
        self.assertEqual(controller.save_settings(ExplorationSettings(False, 1)), "")
        with patch("pet.exploration_controller.datetime", wraps=datetime) as clock:
            yesterday = datetime(2026, 11, 21, 23, 59, 58)
            today = yesterday + timedelta(seconds=2)
            clock.now.return_value = yesterday
            controller.open_panel()
            panel = controller.panel
            panel.explore.click()
            self.finish_round()
            self.assertEqual(panel.quota.text(), "今日探索 1/1 轮")
            next_outing = controller.next_outing
            panel.explore.click()
            self.assertIn("次数用完", panel.status.text())
            self.assertEqual(len(self.server.received), 1)
            self.assertEqual(controller.next_outing, next_outing)

            clock.now.return_value = today
            controller._tick()
            self.assertEqual(panel.quota.text(), "今日探索 0/1 轮")
            self.assertEqual(panel.progress.value(), 0)
            self.assertFalse(panel.status.isVisible())
            self.assertEqual(panel.history.count(), 1)

            panel.explore.click()
            self.finish_round()
            self.assertEqual(panel.quota.text(), "今日探索 1/1 轮")
            self.assertEqual(len(self.server.received), 2)
            self.assertEqual(controller.diary.calls_on(yesterday.date().isoformat()), 1)
            self.assertEqual(controller.diary.calls_on(today.date().isoformat()), 1)
            self.assertEqual(panel.history.count(), 2)

    def test_desktop_menu_omits_hook_configuration_for_both_characters(self):
        for character in ("dafeiyu", "penguin"):
            with self.subTest(character=character):
                self.window.set_character(character)
                self.window.contextMenuEvent(None)
                popup = self.app.activePopupWidget()
                try:
                    names = [item.text() for item in popup.findChildren(QPushButton)]
                    self.assertIn("设置", names)
                    self.assertFalse(any("hook" in name.lower() for name in names))
                finally:
                    popup.close()
                    self.app.processEvents()

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
        self.assertIn("标题或简介", self.controller.panel.detail.observation_heading.text())
        self.controller.start_exploring()
        self.assertIsNone(self.controller.reply)
        self.assertIn("次数用完", self.controller.status)
        self.assertEqual(len(self.server.received), 2)

    def test_ignored_invitation_retries_later_and_a_click_shares_the_note(self):
        controller = self.controller
        diary = controller.diary
        date = datetime.now()
        day = date.date().isoformat()
        activity = Activity("海鸟", "web", "海鸟")
        agent = self.connection("web", "web")
        outing_id = diary.reserve(agent, activity, date.timestamp(), day, 3)
        diary.finish(outing_id, Discovery(**WEB_RESULT))
        self.window.show()
        now = time.monotonic()
        controller._maybe_invite(now, day)
        self.assertIsNone(controller.invitation)
        self.assertGreater(controller.next_invitation, now)

        self.rig.can_show_exploration.return_value = False
        controller._maybe_invite(controller.next_invitation, day)
        self.assertIsNone(controller.invitation)
        self.rig.can_show_exploration.return_value = True
        choice = Mock(side_effect=("knock", "wave"))
        with patch.object(controller.rng, "choice", choice):
            controller._maybe_invite(controller.next_invitation, day)
            prompt = controller.invitation
            self.assertEqual(prompt.reply.text, "在吗？")
            self.rig.start_exploration_gesture.assert_called_with("knock", prompt)
            prompt.fade_out()
            self.assertFalse(prompt.accept_answer())
            QTest.qWait(250)
            self.assertIsNone(controller.invitation)
            self.assertEqual(diary.latest_unshared()["id"], outing_id)
            QTest.mouseClick(self.window, Qt.LeftButton, pos=self.window.rect().center())
            self.assertIsNone(self.window._speech_popup)

            controller._maybe_invite(controller.next_invitation - 1, day)
            self.assertIsNone(controller.invitation)
            controller._maybe_invite(controller.next_invitation, day)
            self.rig.start_exploration_gesture.assert_called_with("wave", controller.invitation)
            QTest.mouseClick(self.window, Qt.LeftButton, pos=self.window.rect().center())

        self.assertIsNone(controller.invitation)
        self.assertIsNone(diary.latest_unshared())
        share = self.window._speech_popup
        self.assertIn("我想看看", share.reply.text)
        self.assertEqual(share.answer_button.text(), "看看")
        newer = diary.reserve(agent, activity, date.timestamp() + 1, day, 3)
        diary.finish(newer, replace(Discovery(**WEB_RESULT), title="更新的探索记录"))
        QTest.mouseClick(share.answer_button, Qt.LeftButton)
        self.assertEqual(controller.panel.entry_id, outing_id)

    def test_invitation_limit_survives_restart_and_resets_on_a_new_local_day(self):
        day = "2026-11-23"
        for _ in range(DAILY_INVITATION_LIMIT):
            self.assertTrue(self.controller.diary.reserve_invitation(day, DAILY_INVITATION_LIMIT))
        self.assertEqual(self.controller.save_settings(ExplorationSettings(invite_to_share=False)), "")
        self.close_pet(self.controller, self.window)
        self.make_pet()
        diary = self.controller.diary
        self.assertFalse(diary.settings().invite_to_share)
        self.assertFalse(diary.reserve_invitation(day, DAILY_INVITATION_LIMIT))
        self.assertTrue(diary.reserve_invitation("2026-11-24", DAILY_INVITATION_LIMIT))

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

    def test_deepseek_rotates_presets_and_revisits_a_learned_website_after_restart(self):
        secret = "deepseek-test-key"
        self.image_download.side_effect = lambda url, **_kw: picture_bytes() if url == PICTURE_URL else b""
        self.credentials.get.return_value = secret
        self.controller.open_panel()
        settings = AgentSettingsPanel(self.controller, self.controller.panel)
        dialog = AgentConnectionDialog(self.controller, None, settings)
        dialog.provider.setCurrentIndex(dialog.provider.findData("deepseek"))
        dialog.key.setText(secret)
        dialog.background.setChecked(True)
        self.assertEqual(dialog.endpoint.text(), DEEPSEEK_SEARCH_ENDPOINT)
        self.assertEqual(dialog.model.text(), DEEPSEEK_MODEL)
        self.assertEqual(dialog.capability.currentData(), "video")
        self.assertFalse(dialog.capability.isEnabled())
        dialog._save()
        connection, = self.controller.diary.connections()
        self.assertEqual(connection.provider, "deepseek")
        self.credentials.set.assert_called_once_with(connection.id, secret)
        self.assertEqual(self.controller.save_settings(ExplorationSettings(True, 4)), "")

        websites = WebsiteSettingsPanel(self.controller, self.controller.panel)
        websites.address.setText("https://www.example.net/videos")
        websites._add()
        self.assertEqual([site.domain for site in self.controller.diary.websites()], [BILIBILI_DOMAIN, "example.net"])
        self.assertEqual(self.controller.diary.websites()[-1].link_url, "https://www.example.net/videos")
        websites.close()

        send = self.controller.network.post
        fixture_paths = {
            DEEPSEEK_SEARCH_ENDPOINT: "/deepseek-search",
            DEEPSEEK_FETCH_ENDPOINT: "/deepseek-bilibili-page",
            DEEPSEEK_CHAT_ENDPOINT: "/deepseek-chat",
        }
        full_round = [DEEPSEEK_SEARCH_ENDPOINT, DEEPSEEK_FETCH_ENDPOINT, DEEPSEEK_CHAT_ENDPOINT]
        endpoints = []

        def fixture_post(request, body):
            endpoint = request.url().toString()
            endpoints.append(endpoint)
            request.setUrl(QUrl(f"http://127.0.0.1:{self.server.server_port}{fixture_paths[endpoint]}"))
            return send(request, body)

        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            self.controller.panel.explore.click()
            self.assertEqual(self.controller.panel.empty_text.text(), "新发现会记在这里。")
            self.assertFalse(self.controller.panel.explore.isEnabled())
            self.finish_round()
            self.assertEqual(endpoints, full_round)
            self.assertEqual(self.controller.panel.history.count(), 1)
            entry, = self.controller.diary.recent()
            self.assertEqual(entry["url"], BILIBILI_URL)
            self.assertEqual(entry["reaction"], "鲸鲸，想看看是哪种小鸟。")
            self.assertEqual(len(self.server.received), 3)
            self.assertTrue(all(record[2] == f"Bearer {secret}" for record in self.server.received))
            search_body = self.server.received[0][1]
            self.assertEqual(self.server.received[1][1]["url"], BILIBILI_URL)
            chat_body = self.server.received[2][1]
            self.assertTrue(search_body["query"].endswith("site:bilibili.com"))
            self.assertEqual(chat_body["model"], DEEPSEEK_MODEL)
            parts = chat_body["messages"][1]["content"]
            self.assertTrue(parts[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
            self.assertNotIn(secret, json.dumps(chat_body))
            self.assertEqual(self.controller.panel.quota.text(), "今日探索 1/4 轮")
            self.assertIn(f"记住了 {LINKED_SITE}", self.controller.status)
            remembered = self.controller.diary.websites()[-1]
            self.assertEqual((remembered.kind, remembered.source_url, remembered.link_url),
                             ("learned", BILIBILI_URL, LINKED_PAGE))
            self.assertTrue(entry["has_picture"])
            picture = self.controller.diary.picture(entry["id"])
            self.assertEqual((picture.url, picture.reason), (PICTURE_URL, PICTURE_REASON))
            self.assertFalse(self.controller.panel.detail.picture_view.image.isNull())

        self.close_pet(self.controller, self.window)
        self.make_pet()
        self.image_download.reset_mock()
        self.controller.open_panel()
        self.assertFalse(self.controller.panel.detail.picture_view.image.isNull())
        self.assertEqual(self.controller.panel.detail.picture_reason.text(), PICTURE_REASON)
        self.image_download.assert_not_called()
        send = self.controller.network.post
        fixture_paths[DEEPSEEK_SEARCH_ENDPOINT] = "/deepseek-empty"
        fixture_paths[DEEPSEEK_FETCH_ENDPOINT] = "/deepseek-linked-page"
        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            self.controller.last_touch -= IDLE_BEFORE_EXPLORING + 1
            self.controller._tick()
            self.finish_round()
            self.assertEqual(endpoints[3:], full_round)
            self.assertTrue(self.server.received[3][1]["query"].endswith(f"site:{LINKED_SITE}"))
            self.assertEqual(self.server.received[4][1]["url"], LINKED_PAGE)
            self.assertEqual(self.controller.diary.recent()[0]["url"], LINKED_PAGE)
            self.assertEqual(self.controller.diary.recent()[0]["evidence_kind"], "article")
            self.assertFalse(self.controller.diary.recent()[0]["has_picture"])

            self.controller.remove_website(LINKED_SITE)
            self.assertNotIn(LINKED_SITE, {site.domain for site in self.controller.diary.websites()})
            self.assertIn(LINKED_SITE, self.controller.diary.known_website_domains())
            self.controller.start_exploring()
            self.finish_round()
            self.assertEqual(endpoints[6:], full_round)
            self.assertTrue(self.server.received[6][1]["query"].endswith("site:example.net"))
            url = "https://www.example.net/videos"
            self.assertEqual(self.server.received[7][1]["url"], url)
            self.assertEqual(self.controller.diary.recent()[0]["url"], url)
            self.assertIsNone(self.controller.outing)

    def test_bare_domain_retry_without_topic_and_then_falls_back_to_homepage(self):
        secret = "deepseek-test-key"
        self.credentials.get.return_value = secret
        self.assertEqual(self.controller.save_connection(deepseek_connection(), None, secret), "")
        self.controller.remove_website(BILIBILI_DOMAIN)
        self.controller.diary.add_website("ysjf.com")
        site, = self.controller.diary.websites()
        self.assertEqual(site.link_url, "")
        send = self.controller.network.post
        site_search_result = "/deepseek-site-search"

        def fixture_post(request, body):
            endpoint = request.url().toString()
            if endpoint == DEEPSEEK_SEARCH_ENDPOINT:
                query = json.loads(bytes(body))["query"]
                path = site_search_result if query == "site:ysjf.com" else "/deepseek-empty"
            elif endpoint == DEEPSEEK_FETCH_ENDPOINT:
                path = "/deepseek-linked-page"
            else:
                self.assertEqual(endpoint, DEEPSEEK_CHAT_ENDPOINT)
                path = "/deepseek-chat"
            request.setUrl(QUrl(f"http://127.0.0.1:{self.server.server_port}{path}"))
            return send(request, body)

        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            for site_search_result, url in (
                ("/deepseek-site-search", "https://movie.ysjf.com/"),
                ("/deepseek-empty", "https://ysjf.com/"),
            ):
                self.server.received.clear()
                self.controller.start_exploring()
                self.finish_round()
                self.assertEqual([record[0] for record in self.server.received], [
                    "/deepseek-empty", site_search_result, "/deepseek-linked-page", "/deepseek-chat",
                ])
                topic_query = self.server.received[0][1]["query"]
                self.assertTrue(topic_query.endswith(" site:ysjf.com"))
                self.assertEqual(self.server.received[1][1]["query"], "site:ysjf.com")
                self.assertEqual(self.server.received[2][1]["url"], url)
                self.assertEqual(self.controller.diary.recent()[0]["url"], url)

    def test_vision_rejection_retries_as_text_without_losing_the_note(self):
        secret = "deepseek-test-key"
        self.credentials.get.return_value = secret
        self.image_download.side_effect = lambda url, **_kw: picture_bytes() if url == PICTURE_URL else b""
        self.assertEqual(self.controller.save_connection(deepseek_connection(), None, secret), "")
        send = self.controller.network.post

        def fixture_post(request, body):
            endpoint = request.url().toString()
            if endpoint == DEEPSEEK_SEARCH_ENDPOINT:
                path = "/deepseek-search"
            elif endpoint == DEEPSEEK_FETCH_ENDPOINT:
                path = "/deepseek-bilibili-page"
            else:
                content = json.loads(bytes(body))["messages"][1]["content"]
                path = "/vision-error" if isinstance(content, list) else "/deepseek-chat"
            request.setUrl(QUrl(f"http://127.0.0.1:{self.server.server_port}{path}"))
            return send(request, body)

        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            self.controller.start_exploring()
            self.finish_round()
        self.assertEqual([record[0] for record in self.server.received][-2:], ["/vision-error", "/deepseek-chat"])
        note, = self.controller.diary.recent()
        self.assertEqual(note["url"], BILIBILI_URL)
        self.assertFalse(note["has_picture"])

    def test_video_evidence_and_frame_play_from_distinct_timestamps_after_restart(self):
        secret = "deepseek-test-key"
        self.credentials.get.return_value = secret
        self.assertEqual(self.controller.save_connection(deepseek_connection(), None, secret), "")
        self.video_read.return_value = VideoMaterial(
            frames=[PictureCandidate(BILIBILI_URL, "frame", "", picture_bytes("JPEG"), 15300)],
            captions=[TimedText("subtitle", 11200, 13000, "潮水退得很快。")],
            audio=[AudioSample(11000, 13800, b"RIFFsample")],
        )
        fixture_paths = {
            DEEPSEEK_SEARCH_ENDPOINT: "/deepseek-search",
            DEEPSEEK_FETCH_ENDPOINT: "/deepseek-bilibili-page",
            DEEPSEEK_ASR_ENDPOINT: "/deepseek-asr",
            DEEPSEEK_CHAT_ENDPOINT: "/deepseek-video-chat",
        }
        send = self.controller.network.post

        def fixture_post(request, body):
            path = fixture_paths[request.url().toString()]
            if path == "/deepseek-asr":
                self.assertTrue(bytes(request.rawHeader("Content-Type")).startswith(b"multipart/form-data; boundary="))
            request.setUrl(QUrl(f"http://127.0.0.1:{self.server.server_port}{path}"))
            return send(request, body)

        with patch.object(self.controller.network, "post", side_effect=fixture_post):
            self.controller.start_exploring()
            self.finish_round()
        self.assertEqual([record[0] for record in self.server.received], list(fixture_paths.values()))
        self.assertIn(b'name="file"; filename="speech.wav"', self.server.received[2][1])
        self.assertIn(b"RIFFsample", self.server.received[2][1])
        self.assertEqual(self.server.received[2][2], f"Bearer {secret}")
        parts = self.server.received[3][1]["messages"][1]["content"]
        evidence = json.loads(parts[0]["text"])["results"][0]["video_evidence"]
        self.assertEqual([item["kind"] for item in evidence], ["subtitle", "audio_transcript", "video_frame"])
        self.assertIn("画面依据 3 · 00:15", parts[1]["text"])
        note, = self.controller.diary.recent()
        self.assertEqual((note["evidence_kind"], note["observation"]),
                         ("audio_transcript", "它顺着潮水退去的方向往前走。"))
        self.assertEqual((note["video_start_ms"], note["video_end_ms"], note["picture_ms"]), (11000, 13800, 15300))

        self.close_pet(self.controller, self.window)
        self.make_pet()
        self.controller.open_panel()
        panel = self.controller.panel
        self.assertEqual(panel.source.text(), "从 00:11 播放")
        self.assertIn("视频画面 00:15", panel.detail.picture_heading.text())
        with patch("pet.exploration_panel.QDesktopServices.openUrl") as open_url:
            panel.source.click()
            panel.detail.frame_source.click()
        self.assertEqual([call.args[0].toString() for call in open_url.call_args_list],
                         [BILIBILI_URL + "?t=11", BILIBILI_URL + "?t=15"])

    def test_custom_agent_redirect_is_not_followed(self):
        connection = self.connection("redirect", "web")
        self.assertEqual(self.controller.save_connection(connection, None, None), "")
        self.controller.start_exploring()
        self.finish_round()
        self.assertIn("307", self.controller.status)
        self.assertEqual(len(self.server.received), 1)
        self.assertFalse(self.controller.diary.recent())
