"""Continuous, renderer-independent motion for the layered DaFeiYu character.

Coordinates are pixels on a 512-pixel canvas; angles are degrees.  This module
only animates bones inside that canvas and never changes the desktop position.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
import math
import random


@dataclass
class NodePose:
    dx: float = 0.0
    dy: float = 0.0
    angle: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    opacity: float = 1.0


@dataclass
class RigPose:
    nodes: dict[str, NodePose] = field(default_factory=dict)
    eye_open: float = 1.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    angry: float = 0.0
    mouth_open: float = 0.0
    mouth_surprised: float = 0.0


_BONES = (
    "root", "body", "head", "hair_left", "hair_right", "arm_left",
    "arm_right", "leg_left", "leg_right", "eyes", "mouth", "headdress", "book",
)
_PHASES = frozenset((
    "idle", "question", "reading", "thinking", "writing", "executing",
    "done", "sleep", "angry", "dragged", "waddle",
))
_CHANNELS = tuple(item.name for item in fields(NodePose))
_FACE_DEFAULTS = {
    "eye_open": 1.0, "gaze_x": 0.0, "gaze_y": 0.0,
    "angry": 0.0, "mouth_open": 0.0, "mouth_surprised": 0.0,
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _smoothstep(value):
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


class _Spring:
    """Exact critically damped spring for a target held during one time step."""

    def __init__(self, value):
        self.value = value
        self.velocity = 0.0

    def advance(self, target, dt, frequency):
        if dt <= 0:
            return self.value
        if dt * frequency > 60.0:
            # A suspended application resumes at rest, without catch-up loops
            # or an overflowing polynomial multiplied by an underflowed exp.
            self.value, self.velocity = target, 0.0
            return target
        offset = self.value - target
        impulse = self.velocity + frequency * offset
        decay = math.exp(-frequency * dt)
        self.value = target + (offset + impulse * dt) * decay
        self.velocity = (self.velocity - frequency * impulse * dt) * decay
        return self.value


class RigMotion:
    """Produce smooth poses without owning a timer, GUI, or state machine.

    ``pointer`` contains normalized gaze coordinates in [-1, 1].  ``phase`` is
    the logical AnimationEngine phase; repeated values do not restart actions.
    State changes preserve spring positions and velocities, including hair lag.
    """

    def __init__(self, seed=137, reduced_motion=False):
        self.seed = seed
        self.reduced_motion = reduced_motion
        self.reset()

    def reset(self, phase="idle"):
        self._random = random.Random(self.seed)
        self._time = 0.0
        self._phase = phase if phase in _PHASES else "idle"
        self._phase_elapsed = 0.0
        self._tap_elapsed = 100.0
        self._blink_start = None
        self._next_blink = self._random.uniform(2.2, 4.5)
        self._springs = {}
        for bone in _BONES:
            default = NodePose(opacity=0.0 if bone == "book" else 1.0)
            for channel in _CHANNELS:
                self._springs[(bone, channel)] = _Spring(getattr(default, channel))
        self._face = {name: _Spring(value) for name, value in _FACE_DEFAULTS.items()}
        if self._phase == "sleep":
            self._face["eye_open"].value = 0.0

    def tap(self):
        """Add a bounded physical impulse; rapid taps cannot accumulate energy."""
        self._tap_elapsed = 0.0
        strength = 0.25 if self.reduced_motion else 1.0
        for key, impulse, limit in (
            (("root", "dy"), -24.0, 42.0),
            (("body", "sx"), 0.20, 0.32),
            (("body", "sy"), -0.30, 0.45),
        ):
            spring = self._springs[key]
            spring.velocity = _clamp(spring.velocity + impulse * strength, -limit, limit)

    def _blink(self):
        if self._blink_start is None and self._time >= self._next_blink:
            self._blink_start = self._next_blink
        if self._blink_start is None:
            return 1.0
        elapsed = self._time - self._blink_start
        if elapsed < 0.085:
            return 1.0 - _smoothstep(elapsed / 0.085)
        if elapsed < 0.12:
            return 0.0
        if elapsed < 0.26:
            return _smoothstep((elapsed - 0.12) / 0.14)
        self._blink_start = None
        # Schedule from now so a long pause never causes a burst of old blinks.
        interval = 0.28 if self._random.random() < 0.12 else self._random.uniform(2.6, 5.2)
        self._next_blink = self._time + interval
        return 1.0

    def _targets(self, phase, drag_angle, pointer):
        nodes = {bone: NodePose() for bone in _BONES}
        nodes["book"].opacity = 0.0
        face = dict(_FACE_DEFAULTS)
        t, age = self._time, self._phase_elapsed
        motion = 0.2 if self.reduced_motion else 1.0

        def wave(hz, offset=0.0):
            return motion * math.sin(2.0 * math.pi * hz * t + offset)

        breath = wave(0.20 if phase == "sleep" else 0.31)
        body, head = nodes["body"], nodes["head"]
        left, right = nodes["arm_left"], nodes["arm_right"]
        root = nodes["root"]
        body.sy = 1.0 + 0.008 * breath
        body.sx = 1.0 - 0.004 * breath
        body.dy = -0.9 * breath
        head.angle = 1.0 * wave(0.16)
        head.dy = 0.45 * wave(0.31, -0.45)
        root.dx = 0.7 * wave(0.11)
        root.dy = 0.45 * wave(0.17)
        left.angle, right.angle = -1.3 * wave(0.27), 1.3 * wave(0.27, 0.35)
        face["gaze_x"], face["gaze_y"] = pointer[0] * 0.65, pointer[1] * 0.55

        if phase == "question":
            head.angle = -3.4 + 0.6 * wave(0.32)
            head.dy -= 1.0
            left.angle, right.angle = -4.0, 6.0
            body.sy += 0.004
            face["mouth_surprised"] = 0.75
            face["mouth_open"] = 0.20
        elif phase in ("reading", "writing"):
            head.angle = 2.6 + 0.5 * wave(0.26)
            head.dy += 1.2
            left.angle, right.angle = -8.0, 8.0
            nodes["book"].opacity = 1.0
            nodes["book"].dy = -0.4 * breath
            nodes["book"].angle = 0.45 * wave(0.26, 0.4)
            face["gaze_x"] = 0.22 * wave(0.52)
            face["gaze_y"] = 0.60
            if phase == "writing":
                right.angle += 3.0 * wave(1.8)
                right.dy = 0.65 * wave(1.8, 0.3)
                head.angle += 0.3 * wave(0.9)
                face["gaze_x"] = 0.13 * wave(1.0)
        elif phase == "thinking":
            head.angle = 3.5 + 0.5 * wave(0.23)
            left.angle, right.angle = -3.0, -12.0
            right.dy = -1.5
            face["gaze_x"], face["gaze_y"] = 0.35, -0.35
        elif phase == "executing":
            head.angle = -1.2 + 0.8 * wave(0.55)
            body.dy += 0.65 * wave(1.1)
            left.angle = -5.0 + 2.5 * wave(1.1)
            right.angle = 5.0 - 2.5 * wave(1.1)
            face["gaze_x"] = 0.30 * wave(0.6)
            face["gaze_y"] = 0.25
            face["mouth_open"] = 0.08
        elif phase == "done":
            greeting = math.exp(-age * 0.75)
            root.dy -= 3.0 * motion * greeting * max(0.0, math.sin(age * 6.0))
            head.angle = -2.0 * greeting + 0.7 * wave(0.4)
            left.angle = -4.0
            right.angle = -10.0 - 5.0 * wave(1.7)
            face["mouth_open"] = 0.30 + 0.22 * greeting
        elif phase == "sleep":
            head.angle = 4.3 + 0.35 * wave(0.14)
            head.dy += 1.7
            body.sy = 0.996 + 0.013 * breath
            body.sx = 1.004 - 0.006 * breath
            root.dy = 1.0 - 0.5 * breath
            left.angle, right.angle = 2.0, -2.0
            face["eye_open"] = 0.0
            face["gaze_x"], face["gaze_y"] = 0.0, 0.0
            face["mouth_open"] = 0.06 + 0.035 * (breath + motion)
        elif phase == "angry":
            head.angle = -2.0 + 0.5 * wave(2.4)
            left.angle, right.angle = -9.0, 9.0
            body.sx += 0.006
            face["angry"] = 1.0
            face["eye_open"] = 0.80
            face["mouth_open"] = 0.22
        elif phase == "dragged":
            # Keep the original wide sitting silhouette clear of the canvas
            # edge, even at the window's maximum drag velocity.
            root.angle = drag_angle * (0.25 if self.reduced_motion else 0.40)
            body.sy += 0.017
            body.sx -= 0.009
            left.angle = -10.0 - drag_angle * 0.09
            right.angle = 10.0 - drag_angle * 0.09
            nodes["leg_left"].angle = -3.0 + 1.5 * wave(0.8)
            nodes["leg_right"].angle = 3.0 + 1.5 * wave(0.8, 0.8)
            face["mouth_surprised"] = 0.55
            face["mouth_open"] = 0.24
        elif phase == "waddle":
            # Retain a local pose for compatibility, never translate the window.
            root.dx = 1.4 * wave(1.6)
            root.dy = -1.1 * abs(wave(1.6))
            body.angle = 1.6 * wave(1.6)
            left.angle, right.angle = -5.0 * wave(1.6), 5.0 * wave(1.6)
            nodes["leg_left"].angle = 4.0 * wave(1.6)
            nodes["leg_right"].angle = -4.0 * wave(1.6)

        # Hair follows the *actual* head angle through slower springs rather
        # than mirroring its target; this creates secondary motion and lag.
        head_angle = self._springs[("head", "angle")].value
        drag_lag = drag_angle * 0.11 if phase == "dragged" else 0.0
        softness = 0.4 if phase == "sleep" else 1.0
        nodes["hair_left"].angle = -0.55 * head_angle + softness * wave(0.28) - drag_lag
        nodes["hair_right"].angle = -0.5 * head_angle + softness * wave(0.28, -0.65) - drag_lag
        nodes["headdress"].angle = -0.15 * head_angle + 0.20 * wave(0.22)

        tap = motion * math.exp(-self._tap_elapsed * 7.0)
        body.sy -= 0.012 * tap
        body.sx += 0.009 * tap
        head.angle += 0.8 * tap
        face["gaze_x"] *= 0.5 if self.reduced_motion else 1.0
        face["gaze_y"] *= 0.5 if self.reduced_motion else 1.0
        if phase != "sleep":
            face["eye_open"] *= self._blink()
        return nodes, face

    def step(self, dt, phase, drag_angle=0.0, pointer=(0.0, 0.0)):
        """Advance by seconds and return a fresh pose; dt may include a pause."""
        dt = float(dt)
        dt = max(0.0, dt) if math.isfinite(dt) else 0.0
        phase = phase if phase in _PHASES else "idle"
        if phase != self._phase:
            self._phase = phase
            self._phase_elapsed = 0.0
        self._time += dt
        self._phase_elapsed += dt
        self._tap_elapsed = min(100.0, self._tap_elapsed + dt)
        drag_angle = float(drag_angle)
        drag_angle = _clamp(drag_angle, -26.0, 26.0) if math.isfinite(drag_angle) else 0.0
        gaze = tuple(_clamp(float(v), -1.0, 1.0) if math.isfinite(float(v)) else 0.0 for v in pointer)
        targets, face_targets = self._targets(phase, drag_angle, gaze)
        result = RigPose()
        for bone, target in targets.items():
            node = NodePose()
            frequency = 7.0 if bone.startswith("hair_") else 13.0
            for channel in _CHANNELS:
                value = self._springs[(bone, channel)].advance(getattr(target, channel), dt, frequency)
                if channel == "opacity":
                    value = _clamp(value, 0.0, 1.0)
                elif channel in ("sx", "sy"):
                    value = _clamp(value, 0.92, 1.08)
                elif channel in ("dx", "dy"):
                    value = _clamp(value, -10.0, 10.0)
                elif channel == "angle":
                    limit = 5.0 if bone == "head" else 16.0
                    value = _clamp(value, -limit, limit)
                setattr(node, channel, value)
            result.nodes[bone] = node
        for name, target in face_targets.items():
            frequency = 38.0 if name == "eye_open" else 15.0
            value = self._face[name].advance(target, dt, frequency)
            setattr(result, name, _clamp(value, -1.0 if name.startswith("gaze_") else 0.0, 1.0))
        return result
