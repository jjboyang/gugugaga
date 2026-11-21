"""The fish's journal and the settings for the Agents she can call."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
)

from pet.exploration import (
    AgentConnection, DEEPSEEK_MODEL, DEEPSEEK_SEARCH_ENDPOINT, DIFY_ENDPOINT,
    ExplorationSettings, OPENAI_ENDPOINT, public_url,
)


def plain_label(parent):
    label = QLabel(parent)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


class ExplorationPanel(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window, Qt.Window)
        self.controller = controller
        self.setWindowTitle("大肥鱼在干嘛")
        self.resize(520, 510)

        layout = QVBoxLayout(self)
        self.status = plain_label(self)
        layout.addWidget(self.status)
        self.history = QListWidget(self)
        self.history.setAccessibleName("探索记录")
        self.history.currentRowChanged.connect(self._show_entry)
        layout.addWidget(self.history, 1)
        self.detail = QTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("探索笔记")
        layout.addWidget(self.detail, 1)

        actions = QHBoxLayout()
        self.source = QPushButton("打开来源", self)
        self.source.clicked.connect(self._open_source)
        actions.addWidget(self.source)
        actions.addStretch()
        self.settings_button = QPushButton("Agent 连接", self)
        self.settings_button.clicked.connect(controller.open_settings)
        actions.addWidget(self.settings_button)
        self.explore = QPushButton("去逛一会儿", self)
        self.explore.clicked.connect(lambda: controller.start_exploring())
        actions.addWidget(self.explore)
        layout.addLayout(actions)
        self.entries = []

    def refresh(self, status, entries, *, available, can_start):
        previous = self.history.currentRow()
        previous_id = self.entries[previous]["id"] if 0 < previous < len(self.entries) else None
        if [row["id"] for row in self.entries] != [row["id"] for row in entries]:
            self.entries = entries
            self.history.blockSignals(True)
            self.history.clear()
            for entry in entries:
                stamp = datetime.fromtimestamp(entry["started"]).strftime("%m-%d")
                self.history.addItem(f'{stamp}  {entry["title"]}')
            selected = next((i for i, row in enumerate(entries) if row["id"] == previous_id), 0)
            self.history.setCurrentRow(selected)
            self.history.blockSignals(False)
        self._show_entry(self.history.currentRow())
        self.status.setText(status)
        self.settings_button.setEnabled(available)
        self.explore.setEnabled(can_start)

    def _show_entry(self, index):
        valid = 0 <= index < len(self.entries)
        entry = self.entries[index] if valid else None
        self.source.setEnabled(bool(entry and public_url(entry["url"])))
        if entry is None:
            self.detail.setPlainText("有了发现，我会记在这里。")
            return
        kind = {"article": "网页正文", "metadata": "标题或简介", "transcript": "字幕或转写"}[entry["evidence_kind"]]
        note = f'{entry["reaction"]}\n\n我看到的（{kind}）\n{entry["observation"]}'
        if entry["next_topic"]:
            note += f'\n\n下次想找\n{entry["next_topic"]}'
        self.detail.setPlainText(f'{note}\n\n通过 {entry["agent_name"]} 找到')

    def _open_source(self):
        index = self.history.currentRow()
        if 0 <= index < len(self.entries):
            url = self.entries[index]["url"]
            if public_url(url):
                QDesktopServices.openUrl(QUrl(url))


class AgentSettingsPanel(QDialog):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Agent 连接")
        self.resize(480, 405)

        layout = QVBoxLayout(self)
        self.agents = QListWidget(self)
        self.agents.setAccessibleName("已配置的 Agent")
        self.agents.currentItemChanged.connect(self._selection_changed)
        self.agents.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self.agents)

        buttons = QHBoxLayout()
        add = QPushButton("添加连接", self)
        add.clicked.connect(lambda: self._edit(new=True))
        buttons.addWidget(add)
        self.edit = QPushButton("编辑", self)
        self.edit.clicked.connect(self._edit)
        buttons.addWidget(self.edit)
        self.remove = QPushButton("移除", self)
        self.remove.clicked.connect(self._remove)
        buttons.addWidget(self.remove)
        buttons.addStretch()
        layout.addLayout(buttons)

        form = QFormLayout()
        self.automatic = QCheckBox("大肥鱼空闲时可以自己去逛", self)
        self.limit = QSpinBox(self)
        self.limit.setRange(1, 20)
        self.limit.setSuffix(" 轮")
        self.share = QCheckBox("熟悉我的节奏后，忙完时偶尔来分享", self)
        form.addRow("自动探索", self.automatic)
        form.addRow("每日探索上限", self.limit)
        form.addRow("工作结束", self.share)
        layout.addLayout(form)
        self.error = plain_label(self)
        layout.addWidget(self.error)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        actions.button(QDialogButtonBox.Save).setText("保存探索设置")
        actions.button(QDialogButtonBox.Cancel).setText("关闭")
        actions.accepted.connect(self._save)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        settings = controller.diary.settings()
        self.automatic.setChecked(settings.automatic)
        self.limit.setValue(settings.daily_limit)
        self.share.setChecked(settings.share_after_work)
        self._refresh_agents()

    def _refresh_agents(self):
        self.agents.clear()
        for connection in self.controller.diary.connections():
            capability = "网页" if connection.capability == "web" else "视频"
            visibility = ("可后台调用" if connection.background else "手动探索") if connection.enabled else "已暂停"
            item = QListWidgetItem(f"{connection.name} · {capability} · {visibility}")
            item.setData(Qt.UserRole, connection)
            self.agents.addItem(item)
        self.agents.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self):
        item = self.agents.currentItem()
        self.edit.setEnabled(item is not None)
        self.remove.setEnabled(item is not None)

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
            if not error:
                self._refresh_agents()

    def _save(self):
        settings = ExplorationSettings(
            self.automatic.isChecked(), self.limit.value(), self.share.isChecked(),
        )
        error = self.controller.save_settings(settings)
        if error:
            self.error.setText(error)
        else:
            self.accept()


class AgentConnectionDialog(QDialog):
    def __init__(self, controller, existing, parent):
        super().__init__(parent)
        self.controller = controller
        self.existing = existing
        self.setWindowTitle("编辑连接" if existing else "添加连接")
        self.resize(490, 325)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QComboBox(self)
        self.provider.addItem("OpenAI Responses · 网页搜索", "openai")
        self.provider.addItem("DeepSeek · B 站", "deepseek")
        self.provider.addItem("Dify Agent", "dify")
        self.provider.addItem("自定义 Agent · HTTP JSON", "http")
        self.name = QLineEdit(existing.name if existing else "网页探索", self)
        self.endpoint = QLineEdit(existing.endpoint if existing else OPENAI_ENDPOINT, self)
        self.model = QLineEdit(existing.model if existing else "gpt-5-mini", self)
        self.name.setMaxLength(64)
        self.endpoint.setMaxLength(2048)
        self.model.setMaxLength(150)
        self.capability = QComboBox(self)
        self.capability.addItem("搜网页", "web")
        self.capability.addItem("找视频", "video")
        self.key = QLineEdit(self)
        self.key.setEchoMode(QLineEdit.Password)
        if existing and existing.has_key:
            self.key.setPlaceholderText("已存到钥匙串，留空可保留")
        self.clear_key = QCheckBox("清除已保存的 API Key", self)
        self.clear_key.setVisible(bool(existing and existing.has_key))
        self.enabled = QCheckBox("启用这个连接", self)
        self.background = QCheckBox("允许大肥鱼在后台自主调用", self)

        form.addRow("接入方式", self.provider)
        form.addRow("连接名称", self.name)
        form.addRow("API 地址", self.endpoint)
        form.addRow("模型或 Agent 标识", self.model)
        form.addRow("能力", self.capability)
        form.addRow("API Key", self.key)
        form.addRow("", self.clear_key)
        form.addRow("", self.enabled)
        form.addRow("", self.background)
        layout.addLayout(form)

        self.error = plain_label(self)
        layout.addWidget(self.error)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        actions.button(QDialogButtonBox.Save).setText("保存")
        actions.button(QDialogButtonBox.Cancel).setText("取消")
        actions.accepted.connect(self._save)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
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
        fixed_endpoints = {OPENAI_ENDPOINT, DEEPSEEK_SEARCH_ENDPOINT}
        if openai:
            self.endpoint.setText(OPENAI_ENDPOINT)
            self.capability.setCurrentIndex(0)
        elif deepseek:
            self.endpoint.setText(DEEPSEEK_SEARCH_ENDPOINT)
            self.model.setText(DEEPSEEK_MODEL)
            self.capability.setCurrentIndex(1)
            if self.name.text() == "网页探索":
                self.name.setText("B 站视频")
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
        self.clear_key.setEnabled(provider == "http")

    def _save(self):
        old = self.existing
        secret = self.key.text().strip()
        endpoint = self.endpoint.text().strip()
        provider = self.provider.currentData()
        clear = self.clear_key.isVisible() and self.clear_key.isEnabled() and self.clear_key.isChecked()
        if old and old.has_key and not (secret or clear) and (provider, endpoint) != (old.provider, old.endpoint):
            self.error.setText("API 地址已改变。请填写该服务的 API Key，或选择清除已保存的 Key。")
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
        else:
            self.key.clear()
            self.accept()
