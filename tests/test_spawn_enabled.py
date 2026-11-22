"""A StartDisabled trigger the map switches on as it spawns is imported as running.

surf_the_gloaming's lethal `owie` floor (trigger_hurt) and surf_japan_ptad's `afkpush` pushes start
disabled and are enabled by the map's logic_auto (directly, and through a relay 20 s in). The
importer dropped every StartDisabled push, gravity and hurt, so in Airdrift those floors did not
kill and those pushes did not push. Also covers the per-map DROPPED report and the entity diff tool.
Run: python3 -P tests/test_spawn_enabled.py   (AIRDRIFT_TOOLS=<game-airdrift>/tools if not a sibling)
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from gsbsp import reader  # noqa: E402
from gsbsp.movers import spawn_enabled  # noqa: E402

# bsp_mechanics imports the game's `bsp_read` shim, which is gsbsp.reader under another name.
sys.modules.setdefault("bsp_read", reader)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import bsp_mechanics  # noqa: E402
import airdrift_entity_diff  # noqa: E402

BOX = [(x, y, z) for x in (0.0, 64.0) for y in (0.0, 64.0) for z in (0.0, 16.0)]


class FakeBsp:
    """Every brush entity is model *1, one 64 x 64 x 16 box at the origin."""

    def __init__(self, entities):
        self.entities = entities
        self.models = [None, None]

    def model_brushes(self, _index):
        return [0]

    def brush_hull(self, _brush):
        return BOX


def auto(*links):
    return {"classname": "logic_auto", "OnMapSpawn": "\n".join(links)}


def hurt(name, disabled=1):
    return {"classname": "trigger_hurt", "targetname": name, "model": "*1", "spawnflags": "1",
            "StartDisabled": str(disabled), "damage": "1000"}


def origin(_e):
    return (0.0, 0.0, 0.0)


class SpawnEnabled(unittest.TestCase):
    def test_logic_auto_enable(self):
        self.assertEqual(spawn_enabled([auto("owie,Enable,,0,-1"), hurt("owie")]), {"owie"})

    def test_through_a_relay_with_delay(self):
        ents = [auto("afkrelay,Trigger,,0,-1"),
                {"classname": "logic_relay", "targetname": "afkrelay", "OnTrigger": "afkpush,Enable,,20,-1"}]
        self.assertEqual(spawn_enabled(ents), {"afkpush"})

    def test_enabled_then_disabled_is_an_event(self):
        ents = [auto("ppush,Enable,,0,-1\nppush,Disable,,5,-1")]
        self.assertEqual(spawn_enabled(ents), set())

    def test_a_button_enable_does_not_count(self):
        ents = [{"classname": "func_button", "OnPressed": "owie,Enable,,0,-1"}, hurt("owie")]
        self.assertEqual(spawn_enabled(ents), set())


class Mechanics(unittest.TestCase):
    def test_spawn_enabled_hurt_is_kept(self):
        bsp = FakeBsp([auto("owie,Enable,,0,-1"), hurt("owie")])
        self.assertEqual(len(bsp_mechanics.hurt_volumes(bsp, origin)), 1)
        self.assertEqual(bsp_mechanics.dropped_entities(bsp), {"logic_auto": 1})

    def test_gated_hurt_is_dropped_and_reported(self):
        bsp = FakeBsp([{"classname": "func_button", "OnPressed": "owie,Enable,,0,-1"}, hurt("owie")])
        self.assertEqual(bsp_mechanics.hurt_volumes(bsp, origin), [])
        self.assertEqual(bsp_mechanics.dropped_entities(bsp), {"StartDisabled trigger_hurt": 1})


class EntityDiff(unittest.TestCase):
    def manifest(self, hurts):
        return {"mechanics": {"hurt": hurts}, "teleport_audit": {"teleports": 0, "broken": []}}

    def test_missing_hurt_is_found(self):
        bsp = FakeBsp([auto("owie,Enable,,0,-1"), hurt("owie")])
        found = airdrift_entity_diff.diff_map(bsp, self.manifest([]))[0]
        self.assertEqual(len(found["missing"]), 1)

    def test_imported_hurt_passes(self):
        bsp = FakeBsp([auto("owie,Enable,,0,-1"), hurt("owie")])
        box = airdrift_entity_diff.entity_boxes(bsp, bsp.entities[1])[0]
        found, drop, wired, _delayed, _gated = airdrift_entity_diff.diff_map(
            bsp, self.manifest([{"min": box[0], "max": box[1], "damage": 1000}]))
        self.assertFalse(any(found.values()))
        self.assertEqual((drop["logic_auto"], wired), (1, 1))

    def test_teleport_count_mismatch(self):
        bsp = FakeBsp([{"classname": "trigger_teleport", "model": "*1"}])
        found = airdrift_entity_diff.diff_map(bsp, self.manifest([]))[0]
        self.assertEqual(len(found["teleports"]), 1)


if __name__ == "__main__":
    unittest.main()
