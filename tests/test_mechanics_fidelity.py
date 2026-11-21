"""Pushes, hurts and gravity follow their brushes; block plates and switched triggers follow the map's logic.

1. A `trigger_push` or `trigger_hurt` drawn as a wedge or a diagonal sheet was imported as its whole
   bounding box: 409 non-box push brushes in 48 maps and 148 hurt brushes in 15 (2026-11-21 survey)
   pushed or killed a player well outside the brush. They are now cut by `bsp_import.hull_boxes`, as
   teleport pits are.
2. A block's teleport plate read raw `StartDisabled`, so a plate the map's logic_auto switches on at
   spawn left its block a floor nobody was ever taken off.
3. A trigger the map's logic switches on later (a button, a timer) is listed in the manifest's
   `not_run.switched_off`, so nothing the game does not run is dropped silently.
Run: python3 -P tests/test_mechanics_fidelity.py   (AIRDRIFT_TOOLS=<game-airdrift>/tools if not a sibling)
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
sys.path.insert(0, ROOT)

os.environ.setdefault("DOTBSP_PATH", ROOT)
for READER in (os.environ.get("AIRDRIFT_TOOLS", ""),
               os.path.join(os.path.dirname(ROOT), "game-airdrift", "tools"),
               "/home/gamedev/godot/game-airdrift/tools"):
    if READER and os.path.isfile(os.path.join(READER, "bsp_read.py")):
        sys.path.append(READER)
        break
try:
    import bsp_import  # noqa: E402
except ModuleNotFoundError as err:
    raise unittest.SkipTest("bsp_read not found (set AIRDRIFT_TOOLS): %s" % err)
import bsp_mechanics  # noqa: E402
from test_hull_diagonal import FakeBsp as Brush, unit  # noqa: E402


def box_planes(lo, hi):
    return [(1, 0, 0, hi[0]), (-1, 0, 0, -lo[0]), (0, 1, 0, hi[1]), (0, -1, 0, -lo[1]),
            (0, 0, 1, hi[2]), (0, 0, -1, -lo[2])]


class Map:
    """Brush entity `*n` is brush n-1; each brush is a convex `Brush` from test_hull_diagonal."""

    def __init__(self, entities, brushes):
        self.entities = entities
        self.models = [None] * (len(brushes) + 1)
        self.planes, self.brushes, self.brushsides, self._pts = [], [], [], []
        for b in brushes:
            self.brushes.append((len(self.brushsides), len(b.planes), 1))
            for pl in b.planes:
                self.brushsides.append((len(self.planes),))
                self.planes.append(pl)
            self._pts.append(b.points)

    def model_brushes(self, index):
        return [index - 1]

    def brush_hull(self, i):
        return self._pts[i]


def origin(_e):
    return (0.0, 0.0, 0.0)


def wedge():
    """1,024 long on x, 256 wide, floor at 0, roof climbing from 32 to 1,056 along x."""
    return Brush(box_planes((0, 0, 0), (1024, 256, 1056))[:4] + [(0, 0, -1, 0), unit(-1, 0, 1) + (32 / 2 ** 0.5,)])


class Wedges(unittest.TestCase):
    def setUp(self):
        self.w = wedge()
        self.bsp = Map([{"classname": "trigger_push", "model": "*1", "spawnflags": "1", "speed": "500",
                         "pushdir": "0 0 0"},
                        {"classname": "trigger_hurt", "model": "*1", "spawnflags": "1", "damage": "1000"}],
                       [self.w])

    def inside(self, boxes):
        for lo, hi in boxes:
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        self.assertTrue(self.w.inside((x, y, z), eps=0.6), (lo, hi))

    def test_box_without_cut_overreaches(self):
        (lo, hi), = bsp_mechanics.cut_brushes(self.bsp, self.bsp.entities[0], origin)
        self.assertFalse(self.w.inside((0, 0, hi[2])))

    def test_push_and_hurt_are_cut_inside_the_wedge(self):
        for e in self.bsp.entities:
            boxes = bsp_mechanics.cut_brushes(self.bsp, e, origin, bsp_import.hull_boxes)
            self.assertGreater(len(boxes), 1)
            self.inside(boxes)
        mech = bsp_mechanics.mechanics(self.bsp, origin, lambda _t: [], 0.0, lambda y: y,
                                       cut=bsp_import.hull_boxes)
        self.assertGreater(len(mech["push"]), 1)
        self.assertEqual(len(mech["push"]), len(mech["hurt"]))

    def test_a_box_brush_stays_one_box(self):
        b = Brush(box_planes((0, 0, 0), (64, 64, 16)))
        bsp = Map([{"classname": "trigger_hurt", "model": "*1"}], [b])
        self.assertEqual(len(bsp_mechanics.hurt_volumes(bsp, origin, bsp_import.hull_boxes)), 1)


def door_and_plate(plate_keys):
    door = {"classname": "func_door", "model": "*1", "speed": "100", "movedir": "90 0 0",
            "spawnflags": str(bsp_mechanics.SF_DOOR_TOUCH_OPENS)}
    plate = dict({"classname": "trigger_teleport", "model": "*2", "spawnflags": "1", "target": "back",
                  "targetname": "plate"}, **plate_keys)
    return Map([door, plate], [Brush(box_planes((0, 0, 0), (64, 64, 16))),
                               Brush(box_planes((0, 0, 0), (64, 64, 12)))])


def dest(_target):
    return [((0.0, 0.0, 0.0), 0.0)]


class Plates(unittest.TestCase):
    def test_door_sinks(self):
        self.assertLess(bsp_mechanics.angle_vector("90 0 0")[2], -0.7)

    def test_enabled_plate_makes_a_block(self):
        self.assertEqual(len(bsp_mechanics.bhop_blocks(door_and_plate({}), origin, dest, set())), 1)

    def test_plate_logic_auto_enables_makes_a_block(self):
        bsp = door_and_plate({"StartDisabled": "1"})
        bsp.entities.append({"classname": "logic_auto", "OnMapSpawn": "plate,Enable,,0,-1"})
        self.assertEqual(len(bsp_mechanics.bhop_blocks(bsp, origin, dest, set())), 1)

    def test_disabled_plate_makes_none(self):
        bsp = door_and_plate({"StartDisabled": "1"})
        self.assertEqual(bsp_mechanics.bhop_blocks(bsp, origin, dest, set()), [])


class SwitchedOff(unittest.TestCase):
    def test_button_switched_hurt_is_listed(self):
        bsp = door_and_plate({"StartDisabled": "1"})
        bsp.entities.append({"classname": "func_button", "OnPressed": "plate,Enable,,0,-1"})
        bsp.entities.append({"classname": "logic_timer", "OnTimer": "PLATE,Toggle,,0,-1"})
        (t,) = bsp_mechanics.switched_off(bsp, origin)
        self.assertEqual((t["class"], t["name"], t["by"]), ("trigger_teleport", "plate", ["func_button", "logic_timer"]))

    def test_spawn_enabled_and_never_enabled_are_not_listed(self):
        bsp = door_and_plate({"StartDisabled": "1"})
        self.assertEqual(bsp_mechanics.switched_off(bsp, origin), [])
        bsp.entities.append({"classname": "logic_auto", "OnMapSpawn": "plate,Enable,,0,-1"})
        self.assertEqual(bsp_mechanics.switched_off(bsp, origin), [])


if __name__ == "__main__":
    unittest.main()
