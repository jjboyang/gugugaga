"""Local diary, connection preferences, and the fish's choice of what to explore."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit


OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
DIFY_ENDPOINT = "https://api.dify.ai/v1/chat-messages"
DEEPSEEK_SEARCH_ENDPOINT = "https://api.deepseek.com/v1/tools/search"
DEEPSEEK_MODEL = "deepseek-flash"
BILIBILI_DOMAIN = "bilibili.com"
DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
TOPICS = (
    "海鸥在海边是怎么找吃的", "水獭在水里做什么", "雨天的老街长什么样",
    "鸟是怎么选地方筑窝的", "窗边的光怎样影响照片", "潮水退下去能看到什么",
)
WORK_RETURN_DAYS = 3
PENDING_OUTING_SECONDS = 260
DAILY_LIMIT_REACHED = "今天的探索次数用完啦。"


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


def website_domain(value):
    """Normalize a website address, retaining distinct non-www subdomains."""
    if not isinstance(value, str):
        return None
    address = value.strip()
    if "://" not in address:
        address = "https://" + address
    parts = read_url(address)
    if not parts or parts.scheme not in {"http", "https"} or parts.port not in (None, 80, 443):
        return None
    try:
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").removeprefix("www.")
    except UnicodeError:
        return None
    labels = host.split(".")
    if (len(labels) < 2 or len(host) > 120 or not labels[-1][0:1].isalpha()
            or labels[-1] in {"localhost", "local", "internal", "lan", "onion", "test", "invalid"}
            or not all(DOMAIN_LABEL.fullmatch(label) for label in labels)):
        return None
    return host


def within_website(host, domain):
    return host == domain or host.endswith("." + domain)


@dataclass(frozen=True)
class ExplorationWebsite:
    domain: str
    kind: str = "preset"
    link_url: str = ""
    source_url: str = ""
    topic: str = ""
    last_visited: float = 0.0


def choose_website(sites, now):
    if not sites:
        return None
    presets = [site for site in sites if site.kind == "preset"]
    learned = [site for site in sites if site.kind == "learned"]
    due = [site for site in learned if site.last_visited <= now - 24 * 3600]
    if due and (not presets or max(sites, key=lambda site: site.last_visited).kind == "preset"):
        return min(due, key=lambda site: site.last_visited)
    return min(presets or learned, key=lambda site: site.last_visited)


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
        elif self.provider == "deepseek":
            if (self.endpoint, self.capability, self.model) != (DEEPSEEK_SEARCH_ENDPOINT, "video", DEEPSEEK_MODEL):
                raise ValueError("DeepSeek 网站探索使用内置的搜索配置。")
            if not self.has_key:
                raise ValueError("请填写 DeepSeek API Key。")
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
class ExplorationPicture:
    url: str
    kind: str
    reason: str
    jpeg: bytes


@dataclass(frozen=True)
class VideoMoment:
    start_ms: int | None = None
    end_ms: int | None = None
    picture_ms: int | None = None


@dataclass(frozen=True)
class Discovery:
    title: str
    url: str
    evidence_kind: str
    observation: str
    reaction: str
    next_topic: str = ""
    picture: ExplorationPicture | None = None
    video: VideoMoment | None = None


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
                CREATE TABLE IF NOT EXISTS exploration_pictures (
                    outing_id INTEGER PRIMARY KEY REFERENCES outings (id) ON DELETE CASCADE,
                    url TEXT NOT NULL, kind TEXT NOT NULL, reason TEXT NOT NULL, jpeg BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exploration_video_moments (
                    outing_id INTEGER PRIMARY KEY REFERENCES outings (id) ON DELETE CASCADE,
                    start_ms INTEGER, end_ms INTEGER, picture_ms INTEGER
                );
                CREATE TABLE IF NOT EXISTS exploration_websites (
                    domain TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    link_url TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '', last_visited REAL NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO exploration_websites (domain, kind) VALUES ('bilibili.com', 'preset');
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
            raise ValueError("每日探索上限需要在 1 到 20 轮之间。")
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

    def websites(self):
        return [ExplorationWebsite(**dict(row)) for row in self.db.execute(
            "SELECT * FROM exploration_websites WHERE kind != 'removed' ORDER BY rowid"
        )]

    def known_website_domains(self):
        return [row[0] for row in self.db.execute("SELECT domain FROM exploration_websites")]

    def add_website(self, address):
        domain = website_domain(address)
        if not domain:
            raise ValueError("请输入公开网站的网址或域名。")
        address = address.strip()
        link_url = ""
        if address.lower() != domain:
            parts = read_url(address if "://" in address else "https://" + address)
            link_url = parts._replace(path=parts.path or "/", fragment="").geturl()
        with self.db:
            self.db.execute("""
                INSERT INTO exploration_websites (domain, kind, link_url) VALUES (?, 'preset', ?)
                ON CONFLICT (domain) DO UPDATE SET kind = 'preset',
                    link_url = coalesce(nullif(excluded.link_url, ''), exploration_websites.link_url)
                """, (domain, link_url))

    def remove_website(self, domain):
        with self.db:
            self.db.execute("UPDATE exploration_websites SET kind = 'removed' WHERE domain = ?", (domain,))

    def reserve(self, agent, activity, now, day, allowance, *, website=None):
        """Count attempted outings and keep one in flight across pet instances."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.calls_on(day) >= allowance:
                raise ValueError(DAILY_LIMIT_REACHED)
            if self.db.execute(
                "SELECT 1 FROM outings WHERE state = 'pending' AND started > ? LIMIT 1",
                (now - PENDING_OUTING_SECONDS,),
            ).fetchone():
                raise ValueError("已经在逛啦。")
            if website and not self.db.execute("""
                UPDATE exploration_websites SET last_visited = ? WHERE domain = ? AND kind != 'removed'
                """, (now, website.domain)).rowcount:
                raise ValueError("这个网站已移除，选一个别的网站再去逛吧。")
            return self.db.execute("""
                INSERT INTO outings (local_day, started, agent_name, topic, capability, interest, state)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """, (day, now, agent.name, activity.topic, activity.capability, activity.interest)).lastrowid

    def calls_on(self, day):
        return self.db.execute("SELECT count(*) FROM outings WHERE local_day = ?", (day,)).fetchone()[0]

    def finish(self, outing_id, discovery=None, *, website=None):
        with self.db:
            if discovery is None:
                self.db.execute("UPDATE outings SET state = 'error' WHERE id = ?", (outing_id,))
            else:
                self.db.execute("""
                    UPDATE outings SET state = 'done', title = ?, url = ?, evidence_kind = ?,
                        observation = ?, reaction = ?, next_topic = ? WHERE id = ?
                    """, (discovery.title, discovery.url, discovery.evidence_kind, discovery.observation,
                          discovery.reaction, discovery.next_topic, outing_id))
                if discovery.picture:
                    picture = discovery.picture
                    self.db.execute("""
                        INSERT OR REPLACE INTO exploration_pictures VALUES (?, ?, ?, ?, ?)
                        """, (outing_id, picture.url, picture.kind, picture.reason, picture.jpeg))
                if discovery.video:
                    video = discovery.video
                    self.db.execute("""
                        INSERT OR REPLACE INTO exploration_video_moments VALUES (?, ?, ?, ?)
                        """, (outing_id, video.start_ms, video.end_ms, video.picture_ms))
                if website:
                    inserted = self.db.execute("""
                        INSERT OR IGNORE INTO exploration_websites (domain, kind, link_url, source_url, topic)
                        VALUES (?, 'learned', ?, ?, ?)
                        """, (website.domain, website.link_url, website.source_url, website.topic))
                    return inserted.rowcount == 1
        return False

    def recent(self, limit=25):
        return self.db.execute(
            """SELECT outings.*, EXISTS (
                   SELECT 1 FROM exploration_pictures WHERE outing_id = outings.id
               ) AS has_picture, video.start_ms AS video_start_ms, video.end_ms AS video_end_ms,
                   video.picture_ms AS picture_ms FROM outings LEFT JOIN exploration_video_moments AS video
                   ON video.outing_id = outings.id WHERE state = 'done' ORDER BY outings.id DESC LIMIT ?""", (limit,)
        ).fetchall()

    def picture(self, outing_id):
        row = self.db.execute(
            "SELECT url, kind, reason, jpeg FROM exploration_pictures WHERE outing_id = ?", (outing_id,)
        ).fetchone()
        return ExplorationPicture(**dict(row)) if row is not None else None

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
