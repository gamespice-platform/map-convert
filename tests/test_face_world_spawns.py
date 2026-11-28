"""face_world_spawns counts a solid prop as a wall: a crate or tree in a spawn's face turns it.
Run: python3 -P tests/test_face_world_spawns.py
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import face_world_spawns  # noqa: E402


def doc(*props):
    return {"hulls": [], "props": list(props)}


class PropColumns(unittest.TestCase):
    def test_a_solid_prop_blocks_the_view_at_eye_height(self):
        # yaw 0 looks along -z; a 2 m crate 3 m ahead stops the view at its near face (2 m)
        s = face_world_spawns.Solids(doc({"solid": True, "size": 2.0, "at": [0.0, 0.0, -3.0]}), b"")
        self.assertAlmostEqual(s.clearance((0.0, 0.0, 0.0), 0.0), 2.0, delta=face_world_spawns.STEP)
        self.assertEqual(s.clearance((0.0, 0.0, 0.0), 180.0), face_world_spawns.MAXD)

    def test_a_prop_shorter_than_the_eye_or_not_solid_does_not(self):
        low = {"solid": True, "size": 1.0, "at": [0.0, 0.0, -3.0]}       # top at 1 m, eye at 1.22 m
        ghost = {"solid": False, "size": 4.0, "at": [0.0, 0.0, -3.0]}
        for p in (low, ghost):
            self.assertEqual(face_world_spawns.Solids(doc(p), b"").clearance((0.0, 0.0, 0.0), 0.0), face_world_spawns.MAXD)

    def test_a_prop_without_a_size_is_skipped(self):
        s = face_world_spawns.Solids(doc({"solid": True, "at": [0.0, 0.0, -3.0]}), b"")
        self.assertEqual(s.hulls, [])


if __name__ == "__main__":
    unittest.main()
