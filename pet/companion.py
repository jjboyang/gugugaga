"""Short, user-initiated gestures for the original seated Dafeiyu rig."""
import math
import time

from PySide6.QtCore import QPoint

from pet.idle_behavior import IdleBehavior, IdleCue


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


class CallWalk:
    """Give the user a moment to point, then walk once to that spot."""
    POINT_SECONDS = 1.2

    def __init__(self):
        self.elapsed = 0.0
        self.origin = None
        self.finished = False
        self.nearby = False

    def advance(self, dt, window, cursor):
        self.elapsed += dt
        if self.elapsed < self.POINT_SECONDS:
            return IdleCue()
        if self.origin is None:
            self.origin = window.pos()
            bounds = window.screen().availableGeometry()
            size = window.width()
            if window.frameGeometry().adjusted(size // 5, size // 5, -size // 5, 0).contains(cursor):
                self.nearby = self.finished = True
                return IdleCue()
            side = 1 if window.frameGeometry().center().x() >= cursor.x() else -1
            # Leave the pointer just outside the character's silhouette.
            x = cursor.x() - size / 2 + side * size * 0.48
            y = cursor.y() - size * 0.65
            self.target = QPoint(round(max(bounds.left(), min(x, bounds.right() + 1 - size))),
                                 round(max(bounds.top(), min(y, bounds.bottom() + 1 - window.height()))))
            delta = self.target - self.origin
            distance = math.hypot(delta.x(), delta.y())
            if distance < size * 0.16:
                self.nearby = self.finished = True
                return IdleCue()
            step_length = IdleBehavior.WALK_STEP_PX * size / 140
            self.steps = max(1, round(distance / step_length))
            self.stride = distance / self.steps / step_length
            self.heading = 1 if delta.x() >= 0 else -1
            self.travel_seconds = max(0.4, self.steps / 5.4)
        settle = IdleBehavior.WALK_SETTLE_SECONDS
        age = self.elapsed - self.POINT_SECONDS
        duration = self.travel_seconds + 2 * settle
        fraction = max(0.0, min(1.0, (age - settle) / self.travel_seconds))
        travel = IdleBehavior.walk_progress(fraction)
        window.move(self.origin + (self.target - self.origin) * travel)
        self.finished = age >= duration
        effort = smooth(min(fraction, 1 - fraction) * self.steps * 2)
        return IdleCue(action="walk", elapsed=min(age, duration), duration=duration,
                       walk_cycle=self.steps * travel / 2, walk_direction=self.heading,
                       walk_stride=self.stride, walk_effort=effort, finished=self.finished)


class FaceReaction:
    def __init__(self):
        self.clear()

    def clear(self):
        self.kind = ""
        self.age = 0.0
        self.cheek_times = []
        self.side = 1

    def tap(self, region, side):
        now = time.monotonic()
        self.side = side
        if region == "cheek" and self.kind == "cover":
            self.age = min(self.age, 0.32)
            return False
        self.age = 0.0
        if region == "cheek":
            self.cheek_times = [t for t in self.cheek_times if now - t < 1.5]
            self.cheek_times.append(now)
            if len(self.cheek_times) >= 3:
                self.kind = "cover"
                self.cheek_times.clear()
                return True
        else:
            self.cheek_times.clear()
        self.kind = region
        return False

    def apply(self, pose, dt):
        self.age += dt
        age = self.age
        head = pose.nodes["head"]
        if self.kind == "cover":
            lift = smooth(age / 0.17)
            release = 1 - smooth((age - 1.8) / 0.38)
            peek = smooth((age - 0.92) / 0.30)
            pose.cover_hands = lift * release
            pose.peek = peek
            head.angle += self.side * 3 * peek * release
            pose.eye_open = min(pose.eye_open, 1 - lift * release * (1 - peek))
            if age >= 2.18:
                self.kind = ""
        else:
            weight = smooth(age / 0.12) * (1 - smooth((age - 0.40) / 0.30))
            if self.kind == "head":
                pose.eye_open = min(pose.eye_open, 1 - weight)
                head.dy += 4 * weight
            elif self.kind == "cheek":
                head.angle -= self.side * 5 * weight
                head.dx -= self.side * 4 * weight
            if age >= 0.70:
                self.kind = ""
