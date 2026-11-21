"""The fish's journal and the settings for the Agents she can call."""
from __future__ import annotations

from datetime import datetime
import sqlite3
from uuid import uuid4

from PySide6.QtCore import QRect, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLineEdit, QProgressBar, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from pet.exploration import (
    AgentConnection, DEEPSEEK_MODEL, DEEPSEEK_SEARCH_ENDPOINT, DIFY_ENDPOINT,
    ExplorationSettings, OPENAI_ENDPOINT, public_url, read_url, website_domain,
)
from pet.exploration_ui import (
    ConnectorPicker, Toggle, add_card, button, card_list, character, header, label, surface, themed_layout,
)
from pet.exploration_video import playback_url, timestamp_text, video_page


def stamp(entry):
    date = datetime.fromtimestamp(entry["started"])
    return f"{date.month}月{date.day}日"


def heading_row(title, trailing):
    row = QHBoxLayout()
    row.addWidget(label(title, "section"))
    row.addStretch()
    row.addWidget(trailing)
    return row


def form_layout(parent):
    form = QFormLayout(parent)
    form.setContentsMargins(14, 13, 14, 13)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(8)
    form.setLabelAlignment(Qt.AlignLeft)
    form.setFormAlignment(Qt.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return form


def dialog_actions(parent, primary, cancel):
    actions = QDialogButtonBox(parent)
    actions.addButton(button(primary, "primary"), QDialogButtonBox.AcceptRole)
    actions.addButton(button(cancel), QDialogButtonBox.RejectRole)
    actions.accepted.connect(parent._save)
    actions.rejected.connect(parent.reject)
    return actions


class MemoryImage(QWidget):
    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.setAccessibleName("探索时留下的图片")

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, event):
        if self.image.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
        rect = QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2,
                     size.width(), size.height())
        painter.drawImage(rect, self.image)
        painter.end()


class DiscoveryNote(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setAccessibleName("探索笔记")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setAutoFillBackground(False)
        content.setStyleSheet("QWidget#noteContents { background: #fcfdff; }")
        content.setObjectName("noteContents")
        self.viewport().setAutoFillBackground(False)
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 6)
        layout.setSpacing(11)

        self.title = label(role="noteTitle", wrap=True)
        self.provenance = label(role="muted", wrap=True)
        title_group = QVBoxLayout()
        title_group.setSpacing(4)
        title_group.addWidget(self.title)
        title_group.addWidget(self.provenance)
        layout.addLayout(title_group)

        reaction_card = surface("bubble")
        reaction_layout = QHBoxLayout(reaction_card)
        reaction_layout.setContentsMargins(10, 8, 12, 8)
        reaction_layout.setSpacing(9)
        reaction_layout.addWidget(character("thinking", 37), 0, Qt.AlignTop)
        thoughts = QVBoxLayout()
        thoughts.setSpacing(2)
        thoughts.addWidget(label("大肥鱼说", "muted"))
        self.reaction = label(role="reaction", wrap=True)
        thoughts.addWidget(self.reaction)
        reaction_layout.addLayout(thoughts, 1)
        layout.addWidget(reaction_card)

        self.picture_card = surface()
        picture_layout = QVBoxLayout(self.picture_card)
        picture_layout.setContentsMargins(11, 8, 11, 10)
        picture_layout.setSpacing(6)
        self.picture_heading = label(role="section")
        self.frame_source = button("播放这一刻")
        self.frame_source.clicked.connect(self._play_frame)
        self.frame_url = ""
        enlarge = button("查看大图")
        enlarge.clicked.connect(self._view_picture)
        controls = QHBoxLayout()
        controls.addWidget(self.picture_heading)
        controls.addStretch()
        controls.addWidget(self.frame_source)
        controls.addWidget(enlarge)
        picture_layout.addLayout(controls)
        self.picture_view = MemoryImage()
        self.picture_view.setFixedHeight(162)
        picture_layout.addWidget(self.picture_view)
        self.picture_reason = label(role="muted", wrap=True)
        picture_layout.addWidget(self.picture_reason)
        layout.addWidget(self.picture_card)
        self.picture_card.hide()

        evidence = QVBoxLayout()
        evidence.setContentsMargins(2, 0, 2, 0)
        evidence.setSpacing(5)
        self.observation_heading = label(role="section")
        self.observation = label(wrap=True)
        evidence.addWidget(self.observation_heading)
        evidence.addWidget(self.observation)
        layout.addLayout(evidence)

        self.followup = surface("followup")
        next_layout = QVBoxLayout(self.followup)
        next_layout.setContentsMargins(12, 8, 12, 9)
        next_layout.setSpacing(3)
        next_layout.addWidget(label("下次想找", "section"))
        self.next_topic = label(wrap=True)
        next_layout.addWidget(self.next_topic)
        layout.addWidget(self.followup)
        layout.addStretch()
        for text in (self.title, self.reaction, self.picture_reason, self.observation, self.next_topic):
            text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

    def show_entry(self, entry, picture=None):
        owner = read_url(entry["url"])
        domain = owner.hostname.removeprefix("www.") if owner else ""
        meta = [stamp(entry)]
        if domain:
            meta.append(domain)
        if entry["agent_name"]:
            meta.append(entry["agent_name"])
        self.title.setText(entry["title"])
        self.provenance.setText("  ·  ".join(meta))
        self.reaction.setText(entry["reaction"])
        image = QImage.fromData(picture.jpeg, "JPEG") if picture else QImage()
        self.picture_view.set_image(image)
        self.picture_card.setVisible(not image.isNull())
        picture_ms = entry["picture_ms"]
        self.frame_url = playback_url(entry["url"], picture_ms) if picture_ms is not None else ""
        self.frame_source.setVisible(bool(self.frame_url))
        if picture:
            origin = "来源页封面" if picture.kind == "cover" else "原页配图"
            if picture_ms is not None:
                origin = f"视频画面 {timestamp_text(picture_ms)}"
            self.picture_heading.setText(f"我留下的图  ·  {origin}")
            self.picture_reason.setText(picture.reason)
            self.picture_reason.setVisible(bool(picture.reason))
        evidence = {"article": "网页正文", "metadata": "标题或简介", "transcript": "字幕或转写",
                    "subtitle": "视频字幕", "audio_transcript": "音频转写", "video_frame": "视频画面"}
        source = evidence.get(entry["evidence_kind"], "来源内容")
        start_ms, end_ms = entry["video_start_ms"], entry["video_end_ms"]
        if start_ms is not None:
            source += f" {timestamp_text(start_ms)}"
            if end_ms is not None and end_ms // 1000 > start_ms // 1000:
                source += f"–{timestamp_text(end_ms)}"
        self.observation_heading.setText(f"我看到的  ·  {source}")
        self.observation.setText(entry["observation"])
        next_topic = entry["next_topic"] or ""
        self.next_topic.setText(next_topic)
        self.followup.setVisible(bool(next_topic))
        self.verticalScrollBar().setValue(0)

    def _play_frame(self):
        if public_url(self.frame_url):
            QDesktopServices.openUrl(QUrl(self.frame_url))

    def _view_picture(self):
        if self.picture_view.image.isNull():
            return
        viewer = QDialog(self)
        viewer.setWindowTitle(self.picture_heading.text())
        layout = themed_layout(viewer, 700, 541, minimum_width=360)
        large = MemoryImage()
        large.set_image(self.picture_view.image)
        layout.addWidget(large, 1)
        close_button = button("关闭")
        close_button.clicked.connect(viewer.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)
        viewer.exec()


class ExplorationPanel(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window, Qt.Window)
        self.controller = controller
        self.entries = []
        self.entry_id = None
        self.setWindowTitle("大肥鱼在干嘛")
        self.setMinimumHeight(420)
        layout = themed_layout(self, 736, 580, minimum_width=620)

        metric = QWidget()
        metric_layout = QVBoxLayout(metric)
        metric_layout.setSpacing(3)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setAlignment(Qt.AlignVCenter)
        self.quota = label(role="section")
        self.quota.setAlignment(Qt.AlignRight)
        metric_layout.addWidget(self.quota)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("今日探索进度")
        self.progress.setTextVisible(False)
        metric_layout.addWidget(self.progress)
        metric.setFixedWidth(108)
        self.metric = metric
        banner, self.status = header("探索日记", "reading", metric=metric, art_size=70)
        layout.addWidget(banner)

        content = QHBoxLayout()
        content.setSpacing(11)
        timeline = surface()
        timeline.setFixedWidth(208)
        timeline_layout = QVBoxLayout(timeline)
        timeline_layout.setContentsMargins(11, 12, 11, 10)
        timeline_layout.setSpacing(8)
        self.history_count = label(role="muted")
        timeline_layout.addLayout(heading_row("探索记录", self.history_count))
        self.history = card_list("探索记录")
        self.history.currentRowChanged.connect(self._show_entry)
        timeline_layout.addWidget(self.history, 1)
        content.addWidget(timeline, 0, Qt.AlignTop)

        sheet = surface()
        sheet_layout = QVBoxLayout(sheet)
        sheet_layout.setContentsMargins(15, 12, 13, 11)
        sheet_layout.setSpacing(7)
        self.pages = QStackedWidget()
        self.detail = DiscoveryNote()
        self.pages.addWidget(self.detail)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(9)
        empty_layout.addWidget(character("thinking", 87), 0, Qt.AlignHCenter)
        self.empty_text = label("去逛一会儿，我会把新发现记下来。", "muted", wrap=True)
        self.empty_text.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_text)
        self.pages.addWidget(empty)
        sheet_layout.addWidget(self.pages, 1)

        self.source = button("打开来源")
        self.source_url = ""
        self.source.clicked.connect(self._open_source)
        sheet_layout.addWidget(self.source, 0, Qt.AlignRight)
        content.addWidget(sheet, 1)
        layout.addLayout(content, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.websites_button = button("探索网站")
        self.websites_button.clicked.connect(controller.open_websites)
        actions.addWidget(self.websites_button)
        self.settings_button = button("Agent 连接")
        self.settings_button.clicked.connect(controller.open_settings)
        actions.addWidget(self.settings_button)
        actions.addStretch()
        self.explore = button("去逛一会儿", "primary")
        self.explore.clicked.connect(lambda: controller.start_exploring())
        actions.addWidget(self.explore)
        layout.addLayout(actions)

    def refresh(self, status, entries, *, available, connected, exploring, quota):
        previous = self.history.currentRow()
        previous_id = self.entries[previous]["id"] if 0 < previous < len(self.entries) else None
        if [row["id"] for row in self.entries] != [row["id"] for row in entries]:
            self.entries = entries
            self.history.blockSignals(True)
            self.history.clear()
            for entry in entries:
                origin = read_url(entry["url"])
                site = origin.hostname.removeprefix("www.") if origin else entry["agent_name"]
                picture_tag = "  ·  有图" if entry["has_picture"] else ""
                add_card(self.history, entry["title"], f"{stamp(entry)}  ·  {site}{picture_tag}")
            selected = next((i for i, row in enumerate(entries) if row["id"] == previous_id), 0)
            self.history.setCurrentRow(selected)
            self.history.blockSignals(False)
        self.history_count.setText(f"{len(entries)} 条" if entries else "")
        self.history.setVisible(bool(entries))
        self.history.setMaximumHeight(max(56, min(len(entries), 5) * 56))
        self._show_entry(self.history.currentRow())
        self.status.setText(status)
        self.status.setVisible(bool(status))
        self.metric.setVisible(quota is not None)
        if quota is not None:
            used, daily_limit = quota
            self.quota.setText(f"今日探索 {used}/{daily_limit} 轮")
            self.progress.setRange(0, daily_limit)
            self.progress.setValue(min(used, daily_limit))
        if not entries:
            if not available:
                message = "探索记录暂时无法读取。"
            elif exploring:
                message = "新发现会记在这里。"
            elif connected:
                message = "去逛一会儿，我会把新发现记下来。"
            else:
                message = "在「Agent 连接」里添加一个连接，就能开始探索。"
            self.empty_text.setText(message)
        self.websites_button.setEnabled(available)
        self.settings_button.setEnabled(available)
        self.explore.setEnabled(connected and not exploring)

    def _show_entry(self, index):
        entry = self.entries[index] if 0 <= index < len(self.entries) else None
        self.pages.setCurrentIndex(0 if entry else 1)
        self.source.setVisible(entry is not None)
        self.source_url = entry["url"] if entry else ""
        self.source.setText("打开来源")
        if entry and video_page(self.source_url):
            start_ms = entry["video_start_ms"]
            if start_ms is None:
                start_ms = entry["picture_ms"]
            self.source_url = playback_url(self.source_url, start_ms)
            self.source.setText("播放原视频" if start_ms is None else f"从 {timestamp_text(start_ms)} 播放")
        self.source.setEnabled(public_url(self.source_url))
        if entry is None:
            self.entry_id = None
        elif self.entry_id != entry["id"]:
            self.entry_id = entry["id"]
            picture = None
            if entry["has_picture"] and self.controller.diary is not None:
                try:
                    picture = self.controller.diary.picture(self.entry_id)
                except sqlite3.Error:
                    pass
            self.detail.show_entry(entry, picture)

    def _open_source(self):
        if public_url(self.source_url):
            QDesktopServices.openUrl(QUrl(self.source_url))


class WebsiteSettingsPanel(QDialog):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("探索网站")
        layout = themed_layout(self, 522, 451)
        banner, _ = header("探索网站", "reading", subtitle="你选她先去哪，也可以查看她后来发现的新网站。")
        layout.addWidget(banner)

        section = surface()
        sites_layout = QVBoxLayout(section)
        sites_layout.setContentsMargins(13, 11, 13, 12)
        sites_layout.setSpacing(8)
        self.address = QLineEdit()
        self.address.setPlaceholderText("输入域名或网址")
        self.address.setAccessibleName("网站域名或网址")
        self.address.returnPressed.connect(self._add)
        add_row = QHBoxLayout()
        add_row.addWidget(self.address, 1)
        add_button = button("添加网站", "primary")
        add_button.clicked.connect(self._add)
        add_row.addWidget(add_button)
        sites_layout.addLayout(add_row)
        self.sites = card_list("探索网站列表")
        self.sites.currentItemChanged.connect(self._selection_changed)
        sites_layout.addWidget(self.sites, 1)
        self.empty = label("添加一个网站，让大肥鱼有地方逛。", "muted", wrap=True)
        sites_layout.addWidget(self.empty)
        self.info = label(role="muted", wrap=True)
        sites_layout.addWidget(self.info)
        self.error = label(role="error", wrap=True)
        sites_layout.addWidget(self.error)
        layout.addWidget(section, 1)

        actions = QHBoxLayout()
        self.source = button("打开发现来源")
        self.source.clicked.connect(self._open_source)
        actions.addWidget(self.source)
        self.remove = button("移除", "remove")
        self.remove.clicked.connect(self._remove)
        actions.addWidget(self.remove)
        actions.addStretch()
        close_button = button("关闭")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self, selected_domain=None):
        self.sites.clear()
        sites = self.controller.diary.websites()
        for site in sites:
            kind = "你预设的" if site.kind == "preset" else "她自己发现的"
            add_card(self.sites, site.domain, kind, value=site)
        self.empty.setVisible(not sites)
        self.sites.setVisible(bool(sites))
        selected = next((i for i, site in enumerate(sites) if site.domain == selected_domain), 0)
        self.sites.setCurrentRow(selected)
        self._selection_changed()

    def _selection_changed(self):
        item = self.sites.currentItem()
        site = item.data(Qt.UserRole) if item else None
        self.remove.setEnabled(site is not None)
        self.source.setEnabled(bool(site and public_url(site.source_url)))
        topic = site.topic if site else ""
        self.info.setText(f"她还想找「{topic}」。" if topic else "")
        self.info.setVisible(bool(topic))
        self.error.hide()

    def _show_error(self, text):
        self.error.setText(text)
        self.error.show()

    def _add(self):
        try:
            address = self.address.text()
            self.controller.diary.add_website(address)
            self.refresh(website_domain(address))
        except ValueError as error:
            self._show_error(str(error))
            return
        except sqlite3.Error:
            self._show_error("网站列表暂时读写不了。")
            return
        self.address.clear()

    def _remove(self):
        item = self.sites.currentItem()
        if item:
            try:
                self.controller.remove_website(item.data(Qt.UserRole).domain)
                self.refresh()
            except sqlite3.Error:
                self._show_error("网站列表暂时读写不了。")

    def _open_source(self):
        item = self.sites.currentItem()
        if item:
            url = item.data(Qt.UserRole).source_url
            if public_url(url):
                QDesktopServices.openUrl(QUrl(url))


class AgentSettingsPanel(QDialog):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Agent 连接")
        layout = themed_layout(self, 538, 520)
        banner, _ = header("Agent 连接", "thinking")
        layout.addWidget(banner)

        section = surface()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(13, 10, 13, 11)
        section_layout.setSpacing(7)
        add = button("添加连接")
        add.clicked.connect(lambda: self._edit(new=True))
        section_layout.addLayout(heading_row("已配置的连接", add))
        self.agents = card_list("已配置的 Agent")
        self.agents.currentItemChanged.connect(self._selection_changed)
        self.agents.itemDoubleClicked.connect(lambda _item: self._edit())
        section_layout.addWidget(self.agents, 1)
        self.empty = label("添加一个 Agent，帮大肥鱼去找有意思的内容。", "muted", wrap=True)
        section_layout.addWidget(self.empty)
        edit_row = QHBoxLayout()
        edit_row.addStretch()
        self.edit = button("编辑")
        self.edit.clicked.connect(self._edit)
        edit_row.addWidget(self.edit)
        self.remove = button("移除", "remove")
        self.remove.clicked.connect(self._remove)
        edit_row.addWidget(self.remove)
        section_layout.addLayout(edit_row)
        layout.addWidget(section)

        preferences = surface()
        pref_layout = QVBoxLayout(preferences)
        pref_layout.setContentsMargins(13, 11, 13, 11)
        pref_layout.setSpacing(8)
        pref_layout.addWidget(label("探索设置", "section"))
        self.automatic = Toggle("允许她空闲时自行探索")
        self.share = Toggle("熟悉我的节奏后，工作结束时偶尔来分享")
        pref_layout.addWidget(self.automatic)
        pref_layout.addWidget(self.share)
        quota = QHBoxLayout()
        quota.addWidget(label("每日探索上限"))
        quota.addStretch()
        self.limit = QSpinBox()
        self.limit.setAccessibleName("每日探索上限")
        self.limit.setRange(1, 20)
        self.limit.setSuffix(" 轮")
        self.limit.setAlignment(Qt.AlignCenter)
        self.limit.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.limit.setFixedWidth(68)
        minus = button("−")
        plus = button("+")
        for control, name in ((minus, "减少每日探索上限"), (plus, "增加每日探索上限")):
            control.setFixedWidth(34)
            control.setAccessibleName(name)
        minus.clicked.connect(self.limit.stepDown)
        plus.clicked.connect(self.limit.stepUp)
        self.limit.valueChanged.connect(lambda value: minus.setEnabled(value > self.limit.minimum()))
        self.limit.valueChanged.connect(lambda value: plus.setEnabled(value < self.limit.maximum()))
        quota.addWidget(minus)
        quota.addWidget(self.limit)
        quota.addWidget(plus)
        pref_layout.addLayout(quota)
        layout.addWidget(preferences)
        layout.addStretch()

        self.error = label(role="error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(dialog_actions(self, "保存探索设置", "关闭"))
        settings = controller.diary.settings()
        self.automatic.setChecked(settings.automatic)
        self.limit.setValue(settings.daily_limit)
        self.share.setChecked(settings.share_after_work)
        self._refresh_agents()

    def _refresh_agents(self):
        self.agents.clear()
        connections = self.controller.diary.connections()
        for connection in connections:
            capability = "网页" if connection.capability == "web" else "视频"
            if connection.provider == "deepseek":
                capability = "网站探索"
            state = ("可后台调用" if connection.background else "手动探索") if connection.enabled else "已暂停"
            add_card(self.agents, connection.name, f"{capability}  ·  {state}", value=connection)
        self.agents.setCurrentRow(0)
        self.agents.setVisible(bool(connections))
        self.agents.setMaximumHeight(max(56, min(len(connections), 3) * 56))
        self.empty.setVisible(not connections)
        self._selection_changed()

    def _selection_changed(self):
        has_selection = self.agents.currentItem() is not None
        self.edit.setEnabled(has_selection)
        self.remove.setEnabled(has_selection)

    def _edit(self, _checked=False, *, new=False):
        item = self.agents.currentItem()
        existing = item.data(Qt.UserRole) if item is not None and not new else None
        if AgentConnectionDialog(self.controller, existing, self).exec() == QDialog.Accepted:
            self._refresh_agents()

    def _remove(self):
        item = self.agents.currentItem()
        if item is not None:
            connection = item.data(Qt.UserRole)
            error = self.controller.remove_connection(connection)
            self.error.setText(error)
            self.error.setVisible(bool(error))
            if not error:
                self._refresh_agents()

    def _save(self):
        settings = ExplorationSettings(
            self.automatic.isChecked(), self.limit.value(), self.share.isChecked(),
        )
        error = self.controller.save_settings(settings)
        if error:
            self.error.setText(error)
            self.error.show()
        else:
            self.accept()


class AgentConnectionDialog(QDialog):
    def __init__(self, controller, existing, parent):
        super().__init__(parent)
        self.controller = controller
        self.existing = existing
        title = "编辑连接" if existing else "添加连接"
        self.setWindowTitle(title)
        layout = themed_layout(self, 536, 494)
        banner, _ = header(title, "idle", art_size=52)
        layout.addWidget(banner)
        fields = surface()
        form = form_layout(fields)
        self.provider = ConnectorPicker(self)
        self.provider.addItem("OpenAI Responses · 网页搜索", "openai")
        self.provider.addItem("DeepSeek · 网站探索", "deepseek")
        self.provider.addItem("Dify Agent", "dify")
        self.provider.addItem("自定义 Agent · HTTP JSON", "http")
        self.name = QLineEdit(existing.name if existing else "网页探索", self)
        self.endpoint = QLineEdit(existing.endpoint if existing else OPENAI_ENDPOINT, self)
        self.model = QLineEdit(existing.model if existing else "gpt-5-mini", self)
        self.name.setMaxLength(64)
        self.endpoint.setMaxLength(2048)
        self.model.setMaxLength(150)
        self.capability = ConnectorPicker(self)
        self.capability.addItem("搜网页", "web")
        self.capability.addItem("找视频", "video")
        self.key = QLineEdit(self)
        self.key.setEchoMode(QLineEdit.Password)
        if existing and existing.has_key:
            self.key.setPlaceholderText("已存到钥匙串，留空可保留")
        self.clear_key = Toggle("清除已保存的 API Key")
        self.enabled = Toggle("启用这个连接")
        self.background = Toggle("允许大肥鱼在后台自主调用")

        form.addRow("接入方式", self.provider)
        form.addRow("连接名称", self.name)
        form.addRow("API 地址", self.endpoint)
        form.addRow("模型或 Agent 标识", self.model)
        form.addRow("能力", self.capability)
        form.addRow("API Key", self.key)
        layout.addWidget(fields)

        options = surface("bubble")
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(13, 9, 13, 10)
        options_layout.setSpacing(7)
        options_layout.addWidget(self.clear_key)
        options_layout.addWidget(self.enabled)
        options_layout.addWidget(self.background)
        layout.addWidget(options)
        layout.addStretch()

        self.error = label(role="error", wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(dialog_actions(self, "保存连接", "取消"))
        self.key.setAccessibleName("API Key")
        self.enabled.setChecked(existing.enabled if existing else True)
        self.background.setChecked(existing.background if existing else False)
        if existing:
            self.provider.setCurrentIndex(self.provider.findData(existing.provider))
            self.capability.setCurrentIndex(self.capability.findData(existing.capability))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed()

    def _provider_changed(self):
        provider = self.provider.currentData()
        openai = provider == "openai"
        deepseek = provider == "deepseek"
        dify = provider == "dify"
        self.capability.setItemText(1, "探索网站" if deepseek else "找视频")
        fixed_endpoints = {OPENAI_ENDPOINT, DEEPSEEK_SEARCH_ENDPOINT}
        if openai:
            self.endpoint.setText(OPENAI_ENDPOINT)
            self.capability.setCurrentIndex(0)
        elif deepseek:
            self.endpoint.setText(DEEPSEEK_SEARCH_ENDPOINT)
            self.model.setText(DEEPSEEK_MODEL)
            self.capability.setCurrentIndex(1)
            if self.name.text() == "网页探索":
                self.name.setText("网站探索")
        elif dify:
            if not self.endpoint.text() or self.endpoint.text() in fixed_endpoints:
                self.endpoint.setText(DIFY_ENDPOINT)
        elif self.endpoint.text() in fixed_endpoints | {DIFY_ENDPOINT}:
            self.endpoint.setText("")
        if not deepseek and self.model.isReadOnly():
            if self.existing and self.existing.provider == provider:
                self.model.setText(self.existing.model)
            else:
                self.model.setText("gpt-5-mini" if openai else "")
        self.endpoint.setPlaceholderText(DIFY_ENDPOINT if dify else "https://你的服务地址/agent/run")
        self.endpoint.setReadOnly(openai or deepseek)
        self.model.setEnabled(not dify)
        self.model.setReadOnly(deepseek)
        self.capability.setEnabled(not (openai or deepseek))
        self.clear_key.setVisible(bool(provider == "http" and self.existing and self.existing.has_key))

    def _save(self):
        old = self.existing
        secret = self.key.text().strip()
        endpoint = self.endpoint.text().strip()
        provider = self.provider.currentData()
        clear = not self.clear_key.isHidden() and self.clear_key.isEnabled() and self.clear_key.isChecked()
        if old and old.has_key and not (secret or clear) and (provider, endpoint) != (old.provider, old.endpoint):
            self.error.setText("API 地址已改变。请填写该服务的 API Key，或选择清除已保存的 Key。")
            self.error.show()
            return
        connection = AgentConnection(
            old.id if old else uuid4().hex, self.name.text().strip(), provider, endpoint,
            "" if provider == "dify" else self.model.text().strip(),
            self.capability.currentData(), self.enabled.isChecked(),
            self.background.isChecked(), bool(secret or (old and old.has_key and not clear)),
        )
        error = self.controller.save_connection(connection, old, secret if secret else "" if clear else None)
        if error:
            self.error.setText(error)
            self.error.show()
        else:
            self.key.clear()
            self.accept()
