"""Schedule small, local attention gestures without owning windows or IPC.

The caller applies ``offset_x`` relative to the position where a walk started.
Returning zero on completion/cancellation lets it restore that position.  A
gesture never changes the logical AnimationEngine phase or wakes a sleeping pet.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random


@dataclass(frozen=True)
class IdleCue:
    action: str = ""
    elapsed: float = 0.0
    duration: float = 0.0
    progress: float = 0.0
    offset_x: float = 0.0
    finished: bool = False


class IdleBehavior:
    """Choose one non-repeating idle gesture after a quiet interval.

    ``nearby`` walks stay within 80 logical pixels of their starting position.
    ``none`` still produces the walk pose but no desktop displacement.  The
    optional ``desktop`` policy emits the same bounded relative cue: mapping a
    larger allowed route to available screen geometry belongs to the caller.

    A completed action is returned once with ``finished=True`` and zero offset.
    Cancellation returns an empty cue immediately. A gap longer than 30 seconds
    is treated as application suspension and starts a fresh quiet interval.
    """

    ACTIONS = ("walk", "knock", "hop")
    WALK_RADIUS_PX = 80.0
    RESUME_GAP_S = 30.0

    def __init__(self, seed=None, walk_mode="nearby"):
        if walk_mode not in ("nearby", "none", "desktop"):
            raise ValueError("walk_mode must be nearby, none, or desktop")
        self.enabled = True
        self.walk_mode = walk_mode
        self._random = random.Random(seed)
        self._action = ""
        self._elapsed = 0.0
        self._duration = 0.0
        self._direction = 1.0
        self._last_action = ""
        self._eligible = False
        self._idle_elapsed = 0.0
        self._wait = self._random.uniform(8.0, 12.0)

    def _reset_wait(self, *, first):
        self._action = ""
        self._elapsed = self._duration = 0.0
        self._idle_elapsed = 0.0
        self._wait = self._random.uniform(8.0, 12.0) if first else self._random.uniform(10.0, 18.0)

    def notify_activity(self):
        """Stop attention seeking and require a new full quiet interval."""
        self._reset_wait(first=True)

    def cancel(self):
        """Clear an active cue without emitting a successful-completion event."""
        if self._action or self._idle_elapsed:
            self._reset_wait(first=True)
        return IdleCue()

    def force_action(self, action):
        """Start a named gesture immediately for an editor or deterministic demo.

        Eligibility is still checked by the next ``step``; this cannot make a
        sleeping/working/disabled pet run a gesture in the background.
        """
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown idle action: {action}")
        if not self.enabled:
            return IdleCue()
        self._action = action
        self._last_action = action
        self._elapsed = 0.0
        self._duration = self._random.uniform(4.0, 6.0)
        self._direction = self._random.choice((-1.0, 1.0))
        return self._cue()

    def _cue(self, *, finished=False):
        if not self._action:
            return IdleCue()
        progress = min(1.0, max(0.0, self._elapsed / self._duration))
        offset = 0.0
        if self._action == "walk" and self.walk_mode != "none" and not finished:
            # This out-and-back curve visits both sides, has zero velocity at
            # either endpoint, and reaches exactly +/-WALK_RADIUS_PX.
            normalization = 4.0 / (3.0 * math.sqrt(3.0))
            offset = (self._direction * self.WALK_RADIUS_PX / normalization
                      * math.sin(2.0 * math.pi * progress) * math.sin(math.pi * progress))
            offset = max(-self.WALK_RADIUS_PX, min(self.WALK_RADIUS_PX, offset))
        return IdleCue(
            action=self._action, elapsed=self._elapsed, duration=self._duration,
            progress=progress, offset_x=offset, finished=finished,
        )

    def step(self, dt, phase, blocked=False):
        """Advance real seconds; only ordinary, unobstructed idle is eligible."""
        elapsed = float(dt)
        elapsed = max(0.0, elapsed) if math.isfinite(elapsed) else 0.0
        eligible = self.enabled and phase == "idle" and not blocked
        if not eligible:
            # Do not draw a new random deadline every blocked frame: refresh
            # rate must not change the action sequence or quiet-time policy.
            if self._eligible or self._action:
                self._reset_wait(first=True)
            self._eligible = False
            return IdleCue()
        self._eligible = True
        if elapsed > self.RESUME_GAP_S:
            self.notify_activity()
            return IdleCue()

        if self._action:
            self._elapsed = min(self._duration, self._elapsed + elapsed)
            if self._elapsed >= self._duration:
                completed = self._cue(finished=True)
                self._reset_wait(first=False)
                return completed
            return self._cue()

        self._idle_elapsed += elapsed
        if self._idle_elapsed < self._wait:
            return IdleCue()
        choices = [action for action in self.ACTIONS if action != self._last_action]
        # Start one gesture, never a catch-up loop of missed attention events.
        return self.force_action(self._random.choice(choices))
