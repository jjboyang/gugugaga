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
    sleep_blend: float = 0.0
    drag_blend: float = 0.0
    suspension: float = 0.0
    # These describe the logical action, rather than a discontinuity in the
    # physical pose; zero-time transitions may update them without moving bones.
    phase: str = field(default="idle", compare=False)
    idle_action: str = field(default="", compare=False)
    action_elapsed: float = field(default=0.0, compare=False)
    action_progress: float = field(default=0.0, compare=False)
    walk_blend: float = 0.0
    knock_blend: float = 0.0
    hop_blend: float = 0.0
    knock_impact: float = 0.0
    anger_action: float = 0.0


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
    "sleep_blend": 0.0, "drag_blend": 0.0,
    "suspension": 0.0,
    "walk_blend": 0.0, "knock_blend": 0.0, "hop_blend": 0.0,
    "knock_impact": 0.0, "anger_action": 0.0,
}
_IDLE_ACTIONS = frozenset(("walk", "knock", "hop"))


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


class _Pendulum(_Spring):
    """Exact underdamped angular spring: a held body can swing past vertical."""

    def advance(self, target, dt, frequency):
        if dt <= 0:
            return self.value
        damping = 0.48
        decay_rate = damping * frequency
        if dt * decay_rate > 60:
            self.value, self.velocity = target, 0.0
            return target
        damped_frequency = frequency * math.sqrt(1.0 - damping * damping)
        offset = self.value - target
        quadrature = (self.velocity + decay_rate * offset) / damped_frequency
        phase = damped_frequency * dt
        sine, cosine = math.sin(phase), math.cos(phase)
        decay = math.exp(-decay_rate * dt)
        self.value = target + decay * (offset * cosine + quadrature * sine)
        self.velocity = decay * (
            (-decay_rate * offset + damped_frequency * quadrature) * cosine
            + (-decay_rate * quadrature - damped_frequency * offset) * sine
        )
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
        self._drag_event_driven = False
        self._last_drag_event = 0.0
        self._drag_event_angle = 0.0
        self._springs = {}
        for bone in _BONES:
            default = NodePose(opacity=0.0 if bone == "book" else 1.0)
            for channel in _CHANNELS:
                self._springs[(bone, channel)] = _Spring(getattr(default, channel))
        self._springs[("root", "angle")] = _Pendulum(0.0)
        self._face = {name: _Spring(value) for name, value in _FACE_DEFAULTS.items()}
        if self._phase == "sleep":
            self._face["eye_open"].value = 0.0
            self._face["sleep_blend"].value = 1.0
        elif self._phase == "dragged":
            self._face["drag_blend"].value = 1.0
            self._face["suspension"].value = 1.0

    def begin_drag(self):
        """Show the picked-up drawing on the input event, before timer ticks."""
        self.cancel_idle_actions()
        self._drag_event_driven = True
        self._last_drag_event = self._time
        self._drag_event_angle = 0.0
        for name, value in (("drag_blend", 1.0), ("sleep_blend", 0.0),
                            ("eye_open", 1.0), ("suspension", 1.0)):
            self._face[name].value = value
            self._face[name].velocity = 0.0

    def end_drag(self):
        """Restore the released pose while keeping all bone spring momentum."""
        self._face["drag_blend"].value = 0.0
        self._face["drag_blend"].velocity = 0.0
        self._drag_event_driven = False

    def note_drag_motion(self, angle):
        """Record fresh input separately from timer samples of an old angle."""
        angle = float(angle)
        self._drag_event_angle = _clamp(angle, -26.0, 26.0) if math.isfinite(angle) else 0.0
        self._last_drag_event = self._time
        self._drag_event_driven = True

    def tap(self):
        """Add a bounded physical impulse; rapid taps cannot accumulate energy."""
        self.cancel_idle_actions()
        self._tap_elapsed = 0.0
        strength = 0.25 if self.reduced_motion else 1.0
        for key, impulse, limit in (
            (("root", "dy"), -24.0, 42.0),
            (("body", "sx"), 0.20, 0.32),
            (("body", "sy"), -0.30, 0.45),
        ):
            spring = self._springs[key]
            spring.velocity = _clamp(spring.velocity + impulse * strength, -limit, limit)

    def cancel_idle_actions(self):
        """Stop optional idle textures immediately; let bone motion settle."""
        for name in ("walk_blend", "knock_blend", "hop_blend", "knock_impact"):
            self._face[name].value = 0.0
            self._face[name].velocity = 0.0

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

    def _targets(self, phase, drag_angle, pointer, action="", elapsed=0.0, duration=4.8):
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
            face["sleep_blend"] = 1.0
            # The original sleep drawing already bows its head. Only breathe
            # around that pose so its ZZZ stays clear of the canvas edge.
            head.angle = 0.35 * wave(0.14)
            head.dy += 0.8
            body.sy = 0.996 + 0.013 * breath
            body.sx = 1.004 - 0.006 * breath
            root.dy = 1.0 - 0.5 * breath
            left.angle, right.angle = 2.0, -2.0
            face["eye_open"] = 0.0
            face["gaze_x"], face["gaze_y"] = 0.0, 0.0
            face["mouth_open"] = 0.06 + 0.035 * (breath + motion)
        elif phase == "angry":
            # A short sequence reads as annoyance: alternate foot stamps,
            # hold fists at the waist, then give a small emphatic head shake.
            # The renderer uses the original standing angry pose for this
            # channel, while angry=1 alone can still mean a seated angry face.
            face["anger_action"] = 1.0
            sequence = age % 3.6
            if sequence < 1.45 or sequence > 2.65:
                beat = (age * 2.4) % 1.0
                lift = motion * math.sin(math.pi * beat) ** 2
                left_stamp = int(age * 2.4) % 2 == 0
                nodes["leg_left"].dy = -7.5 * lift if left_stamp else 0.0
                nodes["leg_right"].dy = 0.0 if left_stamp else -7.5 * lift
                nodes["leg_left"].angle = -5.0 * lift if left_stamp else 0.0
                nodes["leg_right"].angle = 0.0 if left_stamp else 5.0 * lift
                root.dx = (1.4 if left_stamp else -1.4) * lift
                root.dy = -1.2 * lift
                body.angle = (1.0 if left_stamp else -1.0) * lift
            else:
                body.angle = 0.9 * wave(1.3)
                root.dx = 0.7 * wave(1.3)
            head.angle = -1.5 + 2.2 * wave(1.8)
            left.angle, right.angle = -11.0 - 2.0 * wave(1.2), 11.0 + 2.0 * wave(1.2)
            left.dy = right.dy = -2.5 * motion
            body.sx += 0.009
            face["angry"] = 1.0
            face["eye_open"] = 0.80
            face["mouth_open"] = 0.22
        elif phase == "dragged":
            face["drag_blend"] = 1.0
            face["suspension"] = 1.0
            # In Qt's y-down coordinates a clockwise rotation about the grip
            # makes the body below it lag left during a rightward mouse move.
            root.angle = drag_angle * (0.12 if self.reduced_motion else 0.25)
            root.dx = root.dy = 0.0
            body.dx = body.dy = head.dx = head.dy = 0.0
            body.sx = body.sy = 1.0
            head.angle = 0.0
            swinging = self._springs[("root", "angle")].value
            left.angle = right.angle = 0.30 * swinging
            nodes["leg_left"].angle = 0.42 * swinging
            nodes["leg_right"].angle = 0.48 * swinging
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

        if phase == "idle" and action:
            self._idle_targets(nodes, face, action, elapsed, duration, motion)

        # Hair follows the *actual* head angle through slower springs rather
        # than mirroring its target; this creates secondary motion and lag.
        head_angle = self._springs[("head", "angle")].value
        drag_lag = self._springs[("root", "angle")].value * 0.40 if phase == "dragged" else 0.0
        softness = 0.0 if phase == "dragged" else 0.4 if phase == "sleep" else 1.0
        nodes["hair_left"].angle = -0.55 * head_angle + softness * wave(0.28) + drag_lag
        nodes["hair_right"].angle = -0.5 * head_angle + softness * wave(0.28, -0.65) + drag_lag
        nodes["headdress"].angle = -0.15 * head_angle + 0.20 * wave(0.22)
        if phase == "dragged":
            nodes["headdress"].angle = 0.0

        tap = 0.0 if phase == "dragged" else motion * math.exp(-self._tap_elapsed * 7.0)
        body.sy -= 0.012 * tap
        body.sx += 0.009 * tap
        head.angle += 0.8 * tap
        face["gaze_x"] *= 0.5 if self.reduced_motion else 1.0
        face["gaze_y"] *= 0.5 if self.reduced_motion else 1.0
        if phase != "sleep":
            face["eye_open"] *= self._blink()
        return nodes, face

    def _idle_targets(self, nodes, face, action, elapsed, duration, motion):
        """Layer a complete, bounded action over breathing without moving a window."""
        progress = _clamp(elapsed / duration, 0.0, 1.0)
        envelope = _smoothstep(elapsed / 0.18) * _smoothstep((duration - elapsed) / 0.28)
        face[action + "_blend"] = envelope
        root, body, head = nodes["root"], nodes["body"], nodes["head"]
        left, right = nodes["arm_left"], nodes["arm_right"]

        def mix(node, attribute, value):
            current = getattr(node, attribute)
            setattr(node, attribute, current + (value - current) * envelope)

        if action == "walk":
            stride = motion * math.sin(2.0 * math.pi * 1.8 * elapsed)
            left_lift, right_lift = max(0.0, stride), max(0.0, -stride)
            mix(root, "dy", -2.6 * abs(stride))
            mix(body, "angle", 1.7 * stride)
            mix(head, "angle", -1.1 * stride)
            mix(left, "angle", -9.5 * stride)
            mix(right, "angle", 9.5 * stride)
            mix(nodes["leg_left"], "dy", -7.5 * left_lift)
            mix(nodes["leg_right"], "dy", -7.5 * right_lift)
            mix(nodes["leg_left"], "angle", -7.0 * stride)
            mix(nodes["leg_right"], "angle", 7.0 * stride)
            face["gaze_x"] = 0.15 * stride
        elif action == "knock":
            # Three deliberate forward taps, separated enough to read at the
            # default 140px size. The renderer can also use this pulse for a
            # contact ripple on the screen-facing hand.
            impact = max(math.exp(-((progress - center) / 0.035) ** 2)
                         for center in (0.22, 0.43, 0.64)) * motion
            face["knock_impact"] = impact * envelope
            mix(body, "sx", 1.0 + 0.014 * motion + 0.010 * impact)
            mix(body, "sy", 1.0 - 0.005 * impact)
            mix(body, "angle", -0.8 * motion)
            mix(head, "dy", 1.2 * motion + 0.8 * impact)
            mix(head, "angle", -1.0 * motion)
            mix(right, "angle", -5.0 * motion - 7.0 * impact)
            mix(right, "dy", -1.0 * motion - 7.0 * impact)
            mix(left, "angle", 2.5 * motion)
            mix(root, "dy", -0.5 * impact)
            face["gaze_x"] = 0.0
            face["gaze_y"] = -0.1
        elif action == "hop":
            # Each of three hops has a crouch, a parabolic flight, and a soft
            # landing. Keeping all movement inside this canvas avoids desktop
            # drift and makes click/drag interruption straightforward.
            lift = compression = stretch = 0.0
            for center in (0.24, 0.49, 0.74):
                part = (progress - (center - 0.10)) / 0.20
                if not 0.0 <= part <= 1.0:
                    continue
                if part < 0.18:
                    compression = math.sin(math.pi * part / 0.18)
                elif part < 0.80:
                    flight = (part - 0.18) / 0.62
                    lift = 4.0 * flight * (1.0 - flight)
                    stretch = math.sin(math.pi * flight)
                else:
                    compression = math.sin(math.pi * (part - 0.80) / 0.20)
                break
            mix(root, "dy", motion * (-22.0 * lift + 2.3 * compression))
            mix(body, "sy", 1.0 + motion * (0.020 * stretch - 0.052 * compression))
            mix(body, "sx", 1.0 + motion * (0.027 * compression - 0.010 * stretch))
            mix(head, "angle", 0.7 * motion * math.sin(progress * 6.0 * math.pi))
            mix(left, "angle", -7.0 * motion * stretch)
            mix(right, "angle", 7.0 * motion * stretch)
            face["mouth_open"] = 0.28 * lift

    def step(self, dt, phase, drag_angle=0.0, pointer=(0.0, 0.0),
             idle_action="", action_elapsed=0.0, action_duration=0.0):
        """Advance by seconds and return a fresh pose; dt may include a pause."""
        dt = float(dt)
        dt = max(0.0, dt) if math.isfinite(dt) else 0.0
        phase = phase if phase in _PHASES else "idle"
        action = idle_action if phase == "idle" and idle_action in _IDLE_ACTIONS else ""
        elapsed = float(action_elapsed)
        elapsed = max(0.0, elapsed) if math.isfinite(elapsed) else 0.0
        duration = float(action_duration)
        duration = duration if math.isfinite(duration) and duration > 0 else 4.8
        if phase != "idle":
            self.cancel_idle_actions()
        if phase != self._phase:
            self._phase = phase
            self._phase_elapsed = 0.0
        self._time += dt
        self._phase_elapsed += dt
        self._tap_elapsed = min(100.0, self._tap_elapsed + dt)
        drag_angle = float(drag_angle)
        drag_angle = _clamp(drag_angle, -26.0, 26.0) if math.isfinite(drag_angle) else 0.0
        if phase == "dragged" and self._drag_event_driven:
            stale = max(0.0, self._time - self._last_drag_event - 0.035)
            drag_angle = self._drag_event_angle * math.exp(-stale * 10.0)
        gaze = tuple(_clamp(float(v), -1.0, 1.0) if math.isfinite(float(v)) else 0.0 for v in pointer)
        targets, face_targets = self._targets(phase, drag_angle, gaze, action, elapsed, duration)
        result = RigPose(phase=phase, idle_action=action,
                         action_elapsed=elapsed if action else 0.0,
                         action_progress=_clamp(elapsed / duration, 0.0, 1.0) if action else 0.0)
        for bone, target in targets.items():
            node = NodePose()
            frequency = 7.0 if bone.startswith("hair_") else 13.0
            for channel in _CHANNELS:
                channel_frequency = 7.0 if bone == "root" and channel == "angle" else frequency
                value = self._springs[(bone, channel)].advance(getattr(target, channel), dt, channel_frequency)
                if channel == "opacity":
                    value = _clamp(value, 0.0, 1.0)
                elif channel in ("sx", "sy"):
                    value = _clamp(value, 0.92, 1.08)
                elif channel in ("dx", "dy"):
                    limit = 10.0
                    if bone == "root" and channel == "dy" and (action == "hop" or value < -10.0):
                        limit = 24.0
                    value = _clamp(value, -limit, 10.0)
                elif channel == "angle":
                    limit = 5.0 if bone == "head" else 16.0
                    value = _clamp(value, -limit, limit)
                setattr(node, channel, value)
            result.nodes[bone] = node
        for name, target in face_targets.items():
            if name == "drag_blend":
                frequency = 60.0
            elif name == "suspension":
                frequency = 5.0
            elif name == "sleep_blend":
                frequency = 28.0
            elif name == "eye_open":
                frequency = 38.0
            elif name in ("walk_blend", "knock_blend", "hop_blend", "knock_impact", "anger_action"):
                frequency = 24.0
            else:
                frequency = 15.0
            value = self._face[name].advance(target, dt, frequency)
            setattr(result, name, _clamp(value, -1.0 if name.startswith("gaze_") else 0.0, 1.0))
        return result
