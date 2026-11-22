"""sill_boxes: the sill and frame rail under a barricade's boards are found, the wall, the posts and the lintel are not."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault("GSBSP_PATH", ROOT)
sys.path.insert(0, ROOT)
from gsbsp import docboxes as I  # noqa: E402


def box(x, y, z, sx, sy, sz):
    return {"at": [x, y, z], "size": [sx, sy, sz], "mat": "brick"}


class OpenSills(unittest.TestCase):
    # Raven Street's window at x 16.2..17.7, z -6.3: boards from 0.65 m up to 1.79 m.
    OPENINGS = [([16.19, 0.65, -6.33], [17.72, 1.79, -6.17])]

    def test_sill_and_rail_found(self):
        sill = box(16.916, 0.305, -6.248, 1.524, 0.61, 0.305)
        rail = box(16.935, 0.61, -6.248, 1.41, 0.076, 0.381)
        self.assertEqual(I.sill_boxes([sill, rail], self.OPENINGS), [sill, rail])

    def test_wall_posts_lintel_and_far_boxes_kept(self):
        wall = box(18.593, 1.219, -6.248, 1.829, 2.438, 0.305)     # beside the window, tall
        lintel = box(16.916, 2.134, -6.248, 1.524, 0.61, 0.305)    # above the boards
        top_rail = box(16.935, 1.829, -6.248, 1.41, 0.076, 0.381)
        far_sill = box(30.0, 0.305, -6.248, 1.524, 0.61, 0.305)    # another wall's sill, no barricade
        ground = box(16.9, -0.1, -6.2, 4.0, 0.2, 4.0)              # a slab whose top is the floor
        boxes = [wall, lintel, top_rail, far_sill, ground]
        self.assertEqual(I.sill_boxes(boxes, self.OPENINGS), [])

    def test_barricade_on_the_floor_has_no_sill(self):
        low = [([16.19, 0.0, -6.33], [17.72, 1.2, -6.17])]
        self.assertEqual(I.sill_boxes([box(16.9, 0.3, -6.25, 1.5, 0.6, 0.3)], low), [])

    def test_props_near_openings(self):
        chairs = [{"id": "c", "at": [17.1, 0.0, -7.6]}, {"id": "c", "at": [17.1, 0.0, -9.9]}, {"id": "c", "at": [30.0, 0.0, -7.0]}]
        gone = I.props_near_openings(chairs, [(16.95, -6.26)], 1.6)
        self.assertEqual([c["at"] for c in gone], [[17.1, 0.0, -7.6]])
        self.assertEqual(I.props_near_openings(chairs, [], 1.6), [])


if __name__ == "__main__":
    unittest.main()
