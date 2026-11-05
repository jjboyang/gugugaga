"""A Qt-independent 25/5 minute timer with local, atomic focus records.

Only time observed by this process is recorded. Restoring an active session
always pauses it at its last checkpoint; closing or crashing never earns offline
focus time. Phase transitions require user input, so an unattended computer
cannot manufacture a sequence of completed tomatoes.
"""
from __future__ import annotations

from datetime import date, datetime, time as daytime, timedelta
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Callable


class PomodoroTimer:
    FOCUS_SECONDS = 25 * 60
    BREAK_SECONDS = 5 * 60
    ACTIVITY_SECONDS = 2 * 60 * 60
    CHECKPOINT_SECONDS = 5
    PHASES = {"idle", "focus", "focus_done", "break", "break_done"}

    def __init__(self, path: str | Path | None = None, *,
                 now: Callable[[], datetime] = datetime.now,
                 monotonic: Callable[[], float] = time.monotonic):
        self.path = Path(path) if path is not None else None
        self._now = now
        self._monotonic = monotonic
        self.phase = "idle"
        self.paused = False
        self.remaining_seconds = float(self.FOCUS_SECONDS)
        self.focus_since_activity = 0.0
        self.activity_reminded = False
        self.storage_error: str | None = None
        self._load_failed = False
        self._days: dict[str, dict] = {}
        self._last_wall = self._now()
        self._last_mono = self._monotonic()
        self._last_saved_mono = self._last_mono
        self._load()

    @property
    def elapsed_seconds(self) -> float:
        if self.phase == "idle":
            return 0.0
        duration = self.BREAK_SECONDS if self.phase.startswith("break") else self.FOCUS_SECONDS
        return float(duration) - self.remaining_seconds

    @property
    def running(self) -> bool:
        return self.phase in {"focus", "break"} and not self.paused

    def _anchor(self):
        self._last_wall = self._now()
        self._last_mono = self._monotonic()

    def start_focus(self) -> list[str]:
        events = self.tick()
        if self.phase == "focus":
            return events
        self.phase = "focus"
        self.paused = False
        self.remaining_seconds = float(self.FOCUS_SECONDS)
        self._anchor()
        self.save()
        return events

    def start_break(self) -> list[str]:
        events = self.tick()
        if self.phase == "break":
            return events
        self.phase = "break"
        self.paused = False
        self.remaining_seconds = float(self.BREAK_SECONDS)
        self._anchor()
        self.save()
        return events

    def pause(self) -> list[str]:
        events = self.tick()
        if self.phase in {"focus", "break"}:
            self.paused = True
            self.save()
        return events

    def resume(self) -> list[str]:
        if self.phase in {"focus", "break"} and self.paused:
            self.paused = False
            self._anchor()
            self.save()
        return []

    def reset(self) -> list[str]:
        """End this session while preserving its actual focus seconds."""
        events = self.tick()
        self.phase = "idle"
        self.paused = False
        self.remaining_seconds = float(self.FOCUS_SECONDS)
        self.save()
        return events

    def mark_activity(self) -> list[str]:
        """Acknowledge getting up; short rests alone do not reset this count."""
        events = [event for event in self.tick() if event != "activity_due"]
        self.focus_since_activity = 0.0
        self.activity_reminded = False
        self.save()
        return events

    def shutdown(self) -> list[str]:
        events = self.tick()
        if self.phase in {"focus", "break"}:
            self.paused = True
        self.save()
        return events

    def _day(self, day: date) -> dict:
        return self._days.setdefault(day.isoformat(), {"focus_seconds": 0.0, "pomodoros": 0})

    def _record_focus(self, start: datetime, seconds: float):
        """Split a running interval at local midnight, including partial work."""
        remaining = seconds
        cursor = start
        while remaining > 0:
            midnight = datetime.combine(cursor.date() + timedelta(days=1), daytime.min,
                                        tzinfo=cursor.tzinfo)
            until_midnight = max(0.0, (midnight - cursor).total_seconds())
            portion = min(remaining, until_midnight)
            if portion <= 0:
                cursor = midnight
                continue
            self._day(cursor.date())["focus_seconds"] += portion
            remaining -= portion
            cursor = midnight

    def tick(self) -> list[str]:
        wall = self._now()
        mono = self._monotonic()
        delta = mono - self._last_mono
        elapsed = max(0.0, delta) if math.isfinite(delta) else 0.0
        events = []
        if self.running:
            used = min(elapsed, self.remaining_seconds)
            ended_at = self._last_wall + timedelta(seconds=used)
            if self.phase == "focus" and used:
                self._record_focus(self._last_wall, used)
                self.focus_since_activity += used
                if (self.focus_since_activity >= self.ACTIVITY_SECONDS
                        and not self.activity_reminded):
                    self.activity_reminded = True
                    events.append("activity_due")
            self.remaining_seconds = max(0.0, self.remaining_seconds - used)
            if self.remaining_seconds <= 1e-7:
                self.remaining_seconds = 0.0
                if self.phase == "focus":
                    self._day(ended_at.date())["pomodoros"] += 1
                    self.phase = "focus_done"
                    events.append("focus_done")
                else:
                    self.phase = "break_done"
                    events.append("break_done")
                self.paused = False
        self._last_wall, self._last_mono = wall, mono
        checkpoint_interval = 15 if self.storage_error else self.CHECKPOINT_SECONDS
        if events or (self.running and mono - self._last_saved_mono >= checkpoint_interval):
            self.save()
        return events

    def stats(self) -> dict:
        """Current local day and Monday–Sunday week; call tick before refreshing."""
        today = self._now().date()
        first = today - timedelta(days=today.weekday())
        week_days = []
        for index in range(7):
            day = first + timedelta(days=index)
            record = self._days.get(day.isoformat(), {})
            week_days.append({"date": day.isoformat(),
                              "focus_seconds": record.get("focus_seconds", 0.0),
                              "pomodoros": record.get("pomodoros", 0)})
        today_record = self._days.get(today.isoformat(), {})
        streak_day = today
        if not today_record.get("pomodoros", 0):
            streak_day -= timedelta(days=1)
        streak = 0
        while self._days.get(streak_day.isoformat(), {}).get("pomodoros", 0):
            streak += 1
            streak_day -= timedelta(days=1)
        return {
            "today_focus_seconds": today_record.get("focus_seconds", 0.0),
            "today_pomodoros": today_record.get("pomodoros", 0),
            "streak_days": streak,
            "week_focus_seconds": sum(day["focus_seconds"] for day in week_days),
            "week_days": week_days,
        }

    @staticmethod
    def _number(value, *, maximum=None):
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or value < 0
                or (maximum is not None and value > maximum)):
            raise ValueError("Invalid focus duration")
        return float(value)

    def _load(self):
        if self.path is None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                raise ValueError("Unsupported focus record version")
            phase = raw["phase"]
            if phase not in self.PHASES:
                raise ValueError("Invalid timer phase")
            duration = self.BREAK_SECONDS if phase.startswith("break") else self.FOCUS_SECONDS
            remaining = self._number(raw["remaining_seconds"], maximum=duration)
            focus_since_activity = self._number(raw["focus_since_activity"])
            reminded = raw["activity_reminded"]
            if not isinstance(reminded, bool):
                raise ValueError("Invalid activity reminder state")
            days = {}
            for key, value in raw["days"].items():
                if date.fromisoformat(key).isoformat() != key:
                    raise ValueError("Invalid local focus day")
                focus = self._number(value["focus_seconds"])
                count = value["pomodoros"]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError("Invalid completed tomato count")
                days[key] = {"focus_seconds": focus, "pomodoros": count}
            self.phase = phase
            self.remaining_seconds = remaining
            self.focus_since_activity = focus_since_activity
            self.activity_reminded = reminded
            self._days = days
            self.paused = phase in {"focus", "break"}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            # Preserve unreadable records instead of overwriting a user's history.
            self._load_failed = True
            self.storage_error = f"无法读取专注记录：{exc}"

    def save(self) -> bool:
        """Atomically checkpoint; keep counting in memory if persistence fails."""
        if self.path is None:
            return True
        self._last_saved_mono = self._monotonic()
        if self._load_failed:
            return False
        raw = {
            "version": 1, "phase": self.phase,
            "remaining_seconds": self.remaining_seconds,
            "focus_since_activity": self.focus_since_activity,
            "activity_reminded": self.activity_reminded,
            "days": self._days,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=self.path.parent, delete=False,
                                             prefix=f".{self.path.name}.", suffix=".tmp") as stream:
                temporary = Path(stream.name)
                json.dump(raw, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.storage_error = None
            self._last_saved_mono = self._monotonic()
            return True
        except (OSError, ValueError) as exc:
            self.storage_error = f"无法保存专注记录：{exc}"
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
