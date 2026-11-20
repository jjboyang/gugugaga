"""Local diary, connection preferences, and the fish's choice of what to explore."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit


OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
DIFY_ENDPOINT = "https://api.dify.ai/v1/chat-messages"
TOPICS = (
    "海鸥在海边是怎么找吃的", "水獭在水里做什么", "雨天的老街长什么样",
    "鸟是怎么选地方筑窝的", "窗边的光怎样影响照片", "潮水退下去能看到什么",
)
WORK_RETURN_DAYS = 3


def read_url(value):
    if (not isinstance(value, str) or len(value) > 2048 or "\\" in value
            or any(c.isspace() or ord(c) < 32 for c in value)):
        return None
    try:
        parts = urlsplit(value)
        if not parts.hostname or "%" in parts.hostname or parts.username is not None:
            return None
        # Accessing port also rejects malformed or out-of-range ports.
        return parts if parts.port is None or 1 <= parts.port <= 65535 else None
    except ValueError:
        return None


def public_url(value):
    parts = read_url(value)
    if not parts or parts.scheme not in {"http", "https"}:
        return False
    host = parts.hostname.rstrip(".")
    try:
        return ip_address(host).is_global
    except ValueError:
        return "." in host and not host.endswith((".localhost", ".local", ".internal"))


@dataclass(frozen=True)
class AgentConnection:
    id: str
    name: str
    provider: str
    endpoint: str
    model: str
    capability: str
    enabled: bool
    background: bool
    has_key: bool

    def validate(self):
        if not self.name.strip() or (self.provider != "dify" and not self.model.strip()):
            raise ValueError("请填写名称和模型或 Agent 标识。")
        if self.capability not in {"web", "video"}:
            raise ValueError("请选择探索能力。")
        if self.provider == "openai":
            if self.endpoint != OPENAI_ENDPOINT or not self.has_key or self.capability != "web":
                raise ValueError("OpenAI 网页探索需要 API Key。")
        elif self.provider in {"dify", "http"}:
            parts = read_url(self.endpoint)
            local_without_key = (self.provider == "http" and parts and parts.scheme == "http" and not self.has_key
                                 and parts.hostname in {"127.0.0.1", "::1", "localhost"})
            if not parts or parts.query or parts.fragment or (parts.scheme != "https" and not local_without_key):
                raise ValueError("请填写 HTTPS 地址。无密钥的本机连接可使用 HTTP。")
            if self.provider == "dify" and (not self.has_key or not parts.path.rstrip("/").endswith("/chat-messages")):
                raise ValueError("Dify 需要应用 API Key 和以 /chat-messages 结尾的地址。")
        else:
            raise ValueError("请选用支持的连接类型。")


@dataclass(frozen=True)
class Discovery:
    title: str
    url: str
    evidence_kind: str
    observation: str
    reaction: str
    next_topic: str = ""


@dataclass(frozen=True)
class Activity:
    topic: str
    capability: str
    interest: str
    previous_url: str = ""
    previous_reaction: str = ""


@dataclass(frozen=True)
class ExplorationSettings:
    automatic: bool = False
    daily_limit: int = 3
    share_after_work: bool = True


def choose_activity(history, capabilities, rng):
    """Revisit saved threads, with room for interests independent of the user."""
    if not capabilities:
        return None

    recent_topics = {entry["topic"] for entry in history[:5]}
    recent_interests = {entry["interest"] for entry in history[:5]}
    new_topics = [topic for topic in TOPICS if topic not in recent_interests] or list(TOPICS)
    # Threads left open on separate visits make the fish more likely to return to them.
    followups = [entry for entry in history if entry["next_topic"]
                 and entry["next_topic"] not in recent_topics]
    if followups and (len(history) == 1 or rng.random() < 0.7):
        visits = defaultdict(set)
        for item in history:
            if item["next_topic"]:
                visits[item["interest"]].add(item["local_day"])
        weights = [1 + len(visits[item["interest"]]) for item in followups]
        entry = rng.choices(followups, weights, k=1)[0]
        capability = entry["capability"] if entry["capability"] in capabilities else rng.choice(capabilities)
        return Activity(entry["next_topic"], capability, entry["interest"], entry["url"], entry["reaction"])
    topic = rng.choice(new_topics)
    return Activity(topic, rng.choice(capabilities), topic)


class ExplorationDiary:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0.15)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    automatic INTEGER NOT NULL, daily_limit INTEGER NOT NULL,
                    share_after_work INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
                    endpoint TEXT NOT NULL, model TEXT NOT NULL, capability TEXT NOT NULL,
                    enabled INTEGER NOT NULL, background INTEGER NOT NULL, has_key INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outings (
                    id INTEGER PRIMARY KEY, local_day TEXT NOT NULL, started REAL NOT NULL,
                    agent_name TEXT NOT NULL, topic TEXT NOT NULL, capability TEXT NOT NULL, interest TEXT NOT NULL,
                    state TEXT NOT NULL, title TEXT, url TEXT, evidence_kind TEXT,
                    observation TEXT, reaction TEXT, next_topic TEXT, shared INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS outings_by_day ON outings(local_day);
                CREATE TABLE IF NOT EXISTS work_returns (local_day TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS work_shares (local_day TEXT PRIMARY KEY);
            """)
        except sqlite3.Error:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def settings(self):
        row = self.db.execute("SELECT automatic, daily_limit, share_after_work FROM settings").fetchone()
        return ExplorationSettings(bool(row[0]), row[1], bool(row[2])) if row else ExplorationSettings()

    def save_settings(self, settings):
        if not 1 <= settings.daily_limit <= 20:
            raise ValueError("每日调用上限需要在 1 到 20 次之间。")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (1, ?, ?, ?)",
                            (settings.automatic, settings.daily_limit, settings.share_after_work))

    def connections(self):
        return [AgentConnection(**dict(row)) for row in self.db.execute("SELECT * FROM agents ORDER BY rowid")]

    def save_connection(self, connection):
        connection.validate()
        with self.db:
            self.db.execute("""
                INSERT INTO agents VALUES (:id, :name, :provider, :endpoint, :model,
                                           :capability, :enabled, :background, :has_key)
                ON CONFLICT (id) DO UPDATE SET name = excluded.name, provider = excluded.provider,
                    endpoint = excluded.endpoint, model = excluded.model, capability = excluded.capability,
                    enabled = excluded.enabled, background = excluded.background, has_key = excluded.has_key
                """, vars(connection))

    def remove_connection(self, connection_id):
        with self.db:
            self.db.execute("DELETE FROM agents WHERE id = ?", (connection_id,))

    def reserve(self, agent, activity, now, day, allowance):
        """Count every paid attempt and keep one request in flight across pet instances."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.calls_on(day) >= allowance:
                raise ValueError("今天的探索次数用完啦。")
            if self.db.execute(
                "SELECT 1 FROM outings WHERE state = 'pending' AND started > ? LIMIT 1", (now - 90,)
            ).fetchone():
                raise ValueError("已经在逛啦。")
            return self.db.execute("""
                INSERT INTO outings (local_day, started, agent_name, topic, capability, interest, state)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """, (day, now, agent.name, activity.topic, activity.capability, activity.interest)).lastrowid

    def calls_on(self, day):
        return self.db.execute("SELECT count(*) FROM outings WHERE local_day = ?", (day,)).fetchone()[0]

    def finish(self, outing_id, discovery=None):
        with self.db:
            if discovery is None:
                self.db.execute("UPDATE outings SET state = 'error' WHERE id = ?", (outing_id,))
            else:
                self.db.execute("""
                    UPDATE outings SET state = 'done', title = ?, url = ?, evidence_kind = ?,
                        observation = ?, reaction = ?, next_topic = ? WHERE id = ?
                    """, (discovery.title, discovery.url, discovery.evidence_kind, discovery.observation,
                          discovery.reaction, discovery.next_topic, outing_id))

    def recent(self, limit=25):
        return self.db.execute(
            "SELECT * FROM outings WHERE state = 'done' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def latest_unshared(self):
        return self.db.execute(
            "SELECT * FROM outings WHERE state = 'done' AND shared = 0 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def mark_shared(self, outing_id, work_day=None):
        with self.db:
            if work_day and not self.db.execute(
                "INSERT OR IGNORE INTO work_shares VALUES (?)", (work_day,)
            ).rowcount:
                return False
            self.db.execute("UPDATE outings SET shared = 1 WHERE id <= ? AND state = 'done'", (outing_id,))
        return True

    def remember_work_return(self, day):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO work_returns VALUES (?)", (day,))

    def work_return_days(self, now: datetime):
        start = (now.date() - timedelta(days=13)).isoformat()
        return self.db.execute(
            "SELECT count(*) FROM work_returns WHERE local_day BETWEEN ? AND ?",
            (start, now.date().isoformat()),
        ).fetchone()[0]
