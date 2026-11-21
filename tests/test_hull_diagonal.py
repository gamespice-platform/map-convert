"""A sloped teleport sheet drawn on the diagonal is cut to boxes along it, not given its whole bounding box.

bhop_arcane_v2's stage 2 pits (`trigger_teleport` *184 and *185) are thin sloped sheets that run at
24 degrees across the axes. Every slab hull_boxes cut had a corner column outside the brush, so it
returned the whole 711 by 1,024 unit box with a roof above the red blocks the sheet runs beneath, and
a player jumping across them was respawned in mid-air (the 2026-11-21 footage, 4:11 on the timer).
Run: python3 -P tests/test_hull_diagonal.py   (AIRDRIFT_TOOLS=<game-airdrift>/tools if not a sibling)
"""

import itertools
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
sys.path.insert(0, ROOT)

# bsp_import reads through game-airdrift's `bsp_read` shim, which lives in that game's repo.
os.environ.setdefault("DOTBSP_PATH", ROOT)
for READER in (os.environ.get("AIRDRIFT_TOOLS", ""),
               os.path.join(os.path.dirname(ROOT), "game-airdrift", "tools"),
               "/home/gamedev/projects/godot/game-airdrift/tools"):
    if READER and os.path.isfile(os.path.join(READER, "bsp_read.py")):
        sys.path.append(READER)
        break
try:
    import bsp_import  # noqa: E402
except ModuleNotFoundError as err:
    raise unittest.SkipTest("bsp_read not found (set AIRDRIFT_TOOLS): %s" % err)


def unit(x, y, z):
    n = math.sqrt(x * x + y * y + z * z)
    return x / n, y / n, z / n


class FakeBsp:
    """One convex brush as Source stores it: planes n.p <= d, and the hull's corners."""

    def __init__(self, planes):
        self.planes = [tuple(p) for p in planes]
        self.brushes = [(0, len(planes), 1)]
        self.brushsides = [(i,) for i in range(len(planes))]
        self.points = self._corners()

    def inside(self, p, eps=0.01):
        return all(n[0] * p[0] + n[1] * p[1] + n[2] * p[2] <= n[3] + eps for n in self.planes)

    def _corners(self):
        out = []
        for a, b, c in itertools.combinations(self.planes, 3):
            m = [a[:3], b[:3], c[:3]]
            det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                   - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                   + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
            if abs(det) < 1e-9:
                continue
            d = (a[3], b[3], c[3])
            p = []
            for col in range(3):
                mm = [list(r) for r in m]
                for r in range(3):
                    mm[r][col] = d[r]
                p.append((mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
                          - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
                          + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0])) / det)
            if self.inside(p):
                out.append(p)
        return out

    def brush_hull(self, _brush):
        return self.points

    def box(self):
        return ([min(p[a] for p in self.points) for a in range(3)],
                [max(p[a] for p in self.points) for a in range(3)])


def arcane_sheet():
    """The shape of arcane's brush 3019: a strip 220 wide at 24 degrees, roof and floor both sloped."""
    across = unit(-math.sin(math.radians(24)), math.cos(math.radians(24)), 0)
    roof = unit(0, 0.164, 0.986)
    floor = unit(-0.351, 0, -0.936)
    return FakeBsp([
        (across[0], across[1], 0.0, 110.0), (-across[0], -across[1], 0.0, 110.0),   # the strip
        (1.0, 0.0, 0.0, 360.0), (-1.0, 0.0, 0.0, 360.0),                           # its ends
        (roof[0], roof[1], roof[2], roof[2] * 140.0),                               # roof ~140
        (floor[0], floor[1], floor[2], -floor[2] * 40.0),                           # floor ~40
    ])


class Diagonal(unittest.TestCase):
    def setUp(self):
        self.bsp = arcane_sheet()
        self.box = self.bsp.box()
        self.out = bsp_import.hull_boxes(self.bsp, 0, (0.0, 0.0, 0.0), self.box)

    def test_not_the_bounding_box(self):
        self.assertNotEqual(self.out, [self.box])
        self.assertGreater(len(self.out), 1)

    def test_every_box_stands_on_the_brush(self):
        for a, b in self.out:
            hit = any(self.bsp.inside((a[0] + (b[0] - a[0]) * i / 4.0, a[1] + (b[1] - a[1]) * j / 4.0, z))
                      for i in range(5) for j in range(5) for z in range(int(a[2]), int(b[2]) + 1, 2))
            self.assertTrue(hit, "box %s..%s holds none of the brush" % (a, b))

    def test_the_corners_of_the_box_are_clear(self):
        # The two plan corners the strip runs away from: inside the bounding box, far outside the brush,
        # where arcane's red blocks stand.
        (x0, y0, _), (x1, y1, _) = self.box
        for x, y in ((x0 + 40, y1 - 40), (x1 - 40, y0 + 40)):
            self.assertFalse(self.bsp.inside((x, y, 100.0)))
            for a, b in self.out:
                self.assertFalse(a[0] <= x <= b[0] and a[1] <= y <= b[1],
                                 "box %s..%s covers (%s, %s), off the strip" % (a, b, x, y))

    def test_reach_off_the_strip_is_one_cell(self):
        across = unit(-math.sin(math.radians(24)), math.cos(math.radians(24)), 0)
        (x0, y0, _), (x1, y1, _) = self.box
        side = max(bsp_import.HULL_SLAB_MIN, math.sqrt((x1 - x0) * (y1 - y0) / bsp_import.HULL_GRID_CELLS))
        reach = side * math.sqrt(2.0)
        for a, b in self.out:
            for x in (a[0], b[0]):
                for y in (a[1], b[1]):
                    self.assertLess(abs(across[0] * x + across[1] * y), 110.0 + reach)


class Square(unittest.TestCase):
    def test_a_wedge_keeps_its_box(self):
        # Half its box in plan: the grid would cost zones for little, so the box stays.
        bsp = FakeBsp([(1, 0, 0, 100), (-1, 0, 0, 100), (0, 1, 0, 100), (0, -1, 0, 100),
                       (0, 0, 1, 20), (0, 0, -1, 0), (unit(1, 1, 0)[0], unit(1, 1, 0)[1], 0, 0.0)])
        box = bsp.box()
        self.assertEqual(bsp_import.hull_boxes(bsp, 0, (0.0, 0.0, 0.0), box), [box])

    def test_a_box_brush_is_its_box(self):
        bsp = FakeBsp([(1, 0, 0, 100), (-1, 0, 0, 100), (0, 1, 0, 50), (0, -1, 0, 50), (0, 0, 1, 20), (0, 0, -1, 0)])
        box = bsp.box()
        self.assertEqual(bsp_import.hull_boxes(bsp, 0, (0.0, 0.0, 0.0), box), [box])


if __name__ == "__main__":
    unittest.main()
