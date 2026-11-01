"""A picked-up pet hangs from its grip and settles when the mouse stops."""
from dataclasses import asdict
import math
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from pet.rig_mesh import OriginalMeshRenderer
from pet.rig_motion import NodePose, RigMotion, RigPose


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"


def drive(motion, seconds, angle=26, fps=60):
    pose = None
    for _ in range(round(seconds * fps)):
        motion.note_drag_motion(angle)
        pose = motion.step(1 / fps, "dragged", drag_angle=angle)
    return pose


def sampled_mesh_point(renderer, pose, point):
    """Interpolate the same shared triangle that actually paints the grip."""
    deformed = renderer.deformed_vertices(pose)
    for triangle in renderer.triangles:
        a, b, c = (renderer.vertices[index] for index in triangle)
        determinant = ((b.y() - c.y()) * (a.x() - c.x())
                       + (c.x() - b.x()) * (a.y() - c.y()))
        wa = ((b.y() - c.y()) * (point.x() - c.x())
              + (c.x() - b.x()) * (point.y() - c.y())) / determinant
        wb = ((c.y() - a.y()) * (point.x() - c.x())
              + (a.x() - c.x()) * (point.y() - c.y())) / determinant
        wc = 1 - wa - wb
        if min(wa, wb, wc) >= -1e-9:
            points = [deformed[index] for index in triangle]
            return QPointF(sum(weight * value.x() for weight, value in zip((wa, wb, wc), points)),
                           sum(weight * value.y() for weight, value in zip((wa, wb, wc), points)))
    raise AssertionError("Suspension grip must be inside the rendered mesh")


class SuspensionMotionTests(unittest.TestCase):
    def test_stationary_hold_dangles_without_a_permanent_idle_sway(self):
        motion = RigMotion()
        motion.begin_drag()
        poses = [motion.step(1 / 60, "dragged") for _ in range(180)]
        self.assertGreater(poses[-1].suspension, 0.95)
        self.assertLess(max(abs(pose.nodes["root"].angle) for pose in poses[-60:]), 0.1)

    def test_stale_mouse_velocity_decays_and_the_body_swings_back(self):
        motion = RigMotion()
        motion.begin_drag()
        moving = drive(motion, 0.4)
        self.assertGreater(moving.nodes["root"].angle, 1)
        # The window can keep its last nonzero angle after move events stop.
        # It must not hold the body at that angle forever.
        angles = [motion.step(1 / 60, "dragged", drag_angle=26).nodes["root"].angle
                  for _ in range(180)]
        self.assertLess(min(angles), -0.05)
        self.assertLess(abs(angles[-1]), 0.1)

    def test_release_preserves_momentum_and_returns_to_the_rest_pose(self):
        motion = RigMotion()
        motion.begin_drag()
        before = drive(motion, 0.3)
        motion.end_drag()
        same_instant = motion.step(0, "idle")
        self.assertAlmostEqual(same_instant.nodes["root"].angle, before.nodes["root"].angle)
        released = motion.step(1 / 60, "idle")
        self.assertLess(abs(released.nodes["root"].angle - before.nodes["root"].angle), 1)
        self.assertGreater(released.suspension, 0.5)
        for _ in range(240):
            rested = motion.step(1 / 60, "idle")
        self.assertLess(abs(rested.nodes["root"].angle), 0.1)
        self.assertLess(rested.suspension, 0.05)

    def test_reduced_motion_has_a_smaller_hanging_response(self):
        peaks = []
        for reduced in (False, True):
            motion = RigMotion(reduced_motion=reduced)
            motion.begin_drag()
            angles = []
            for _ in range(60):
                motion.note_drag_motion(26)
                angles.append(motion.step(1 / 60, "dragged", drag_angle=26).nodes["root"].angle)
            peaks.append(max(map(abs, angles)))
        self.assertGreater(peaks[0], 1)
        self.assertLess(peaks[1], peaks[0] * 0.7)

    def test_hanging_motion_is_consistent_across_refresh_rates(self):
        samples = []
        for fps in (30, 60, 120):
            motion = RigMotion()
            motion.begin_drag()
            drive(motion, 0.4, fps=fps)
            for _ in range(round(0.5 * fps)):
                pose = motion.step(1 / fps, "dragged", drag_angle=26)
            samples.append(pose.nodes["root"].angle)
        self.assertLess(max(samples) - min(samples), 0.4)

    def test_suspended_motion_survives_a_long_pause(self):
        motion = RigMotion()
        motion.begin_drag()
        drive(motion, 0.2)
        for dt in (0, 0.4, 30, 100000, float("nan"), float("inf"), -1):
            pose = motion.step(dt, "dragged", drag_angle=26)
            self.assertTrue(math.isfinite(pose.suspension))
            self.assertGreaterEqual(pose.suspension, 0)
            self.assertLessEqual(pose.suspension, 1)
            for node in pose.nodes.values():
                self.assertTrue(all(math.isfinite(value) for value in asdict(node).values()))
            self.assertLessEqual(abs(pose.nodes["root"].angle), 16)


class SuspensionGripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = OriginalMeshRenderer(ASSETS)

    def test_clockwise_swing_from_the_grip_lags_a_rightward_drag(self):
        renderer = self.renderer
        grip = QPointF(*renderer.suspension_anchor)
        pose = RigPose(nodes={"root": NodePose(angle=8)}, suspension=1)
        transform = renderer.transforms(pose)["root"][0]
        root_x, root_y = renderer.pivots["root"]
        actual_grip = transform.map(QPointF(grip.x() - root_x, grip.y() - root_y))
        self.assertAlmostEqual(actual_grip.x(), grip.x(), places=6)
        self.assertAlmostEqual(actual_grip.y(), grip.y(), places=6)
        lower_body = transform.map(QPointF(grip.x() - root_x, 448 - root_y))
        self.assertLess(lower_body.x(), grip.x() - 20)

    def test_grip_does_not_drift_when_secondary_bones_move(self):
        renderer = self.renderer
        grip = QPointF(*renderer.suspension_anchor)
        pose = RigPose(nodes={
            "root": NodePose(angle=8, dx=1, dy=2),
            "body": NodePose(sy=1.03),
            "head": NodePose(angle=2, dy=1),
        }, suspension=1)
        actual = sampled_mesh_point(renderer, pose, grip)
        self.assertLess(math.hypot(actual.x() - grip.x(), actual.y() - grip.y()), 0.8)

    def test_no_suspension_keeps_the_existing_bind_pose(self):
        renderer = self.renderer
        neutral = RigPose()
        actual = renderer.render(neutral)
        self.assertEqual(actual.toImage(), renderer.base_pixmap.toImage())
        vertices = renderer.deformed_vertices(neutral)
        for before, after in zip(renderer.vertices, vertices):
            self.assertAlmostEqual(before.x(), after.x())
            self.assertAlmostEqual(before.y(), after.y())


if __name__ == "__main__":
    unittest.main()
