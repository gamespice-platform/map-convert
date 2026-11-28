"""Team spawns, control points, resupply and flag spawns in the Airdrift importer.
Run: python3 -P tests/test_team_markers.py   (needs numpy, like the importer)
"""

import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

os.environ.setdefault("GSBSP_PATH", ROOT)
for READER in (os.environ.get("AIRDRIFT_TOOLS", "") or os.environ.get("G2G_TOOLS", ""),
               os.path.join(os.path.dirname(ROOT), "game-airdrift", "tools"),
               "/home/gamedev/godot/game-airdrift/tools"):
    if READER and os.path.isfile(os.path.join(READER, "bsp_read.py")):
        sys.path.append(READER)
        break
try:
    import bsp_import  # noqa: E402
    import synth  # noqa: E402
    from bsp_read import Bsp  # noqa: E402
except ModuleNotFoundError as err:
    raise unittest.SkipTest("bsp_read or numpy not found (set AIRDRIFT_TOOLS): %s" % err)


def spawn(team, origin="0 0 0"):
    return {"classname": "info_player_teamspawn", "origin": origin, "angles": "0 90 0", "TeamNum": team}


class TeamMarkers(unittest.TestCase):
    def test_team_numbers_become_red_and_blue_and_the_rest_stay_untagged(self):
        z = types.SimpleNamespace(entities=[spawn("2"), spawn("3"), spawn("0"),
                                            {"classname": "info_player_deathmatch", "origin": "5 5 5"}])
        sides = [bsp_import.SPAWN_TEAMS.get((e["classname"], str(e.get("TeamNum", "")))) for e in z.entities]
        self.assertEqual(sides, ["red", "blue", None, None])

    def test_control_points_and_flag_spawns(self):
        bsp = types.SimpleNamespace(entities=[
            {"classname": "team_control_point", "origin": "10 20 30", "point_index": "2",
             "point_printname": "B", "point_default_owner": "3"},
            {"classname": "team_control_point", "origin": "0 0 0", "point_index": "1",
             "point_printname": "A", "point_default_owner": "2"}])
        doc = {"flag_spawns": [{"team": "red", "origin_src": [100, 200, 30], "yaw_src": 90}]}
        points, resupply, flags = bsp_import.objective_markers(bsp, doc)
        self.assertEqual([(p["index"], p["owner"]) for p in points], [(1, "red"), (2, "blue")])
        self.assertEqual(resupply, [])
        # the control point mode's schema rides beside the first one
        self.assertEqual([(p["id"], p["order"], p["radius"]) for p in points],
                         [(1, 1, bsp_import.DEFAULT_CAPTURE_RADIUS), (2, 2, bsp_import.DEFAULT_CAPTURE_RADIUS)])
        self.assertEqual(points[1]["position"], points[1]["origin"])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["team"], "red")
        self.assertEqual(flags[0]["origin"], list(bsp_import.to_godot([100.0, 200.0, 30.0])))

    def test_round_lists_the_play_order(self):
        bsp = types.SimpleNamespace(entities=[
            {"classname": "team_control_point", "origin": "0 0 0", "point_index": "0", "targetname": "a"},
            {"classname": "team_control_point", "origin": "9 0 0", "point_index": "1", "targetname": "b"},
            {"classname": "team_control_point_round", "cpr_cp_names": "b a"}])
        points, _, _ = bsp_import.objective_markers(bsp, {})
        self.assertEqual([(p["targetname"] if "targetname" in p else p["index"], p["order"]) for p in points], [(1, 0), (0, 1)])


def side_spawns(doc, *extra):
    """classify_zones' spawns on a floor with a terrorist at -x, a counter-terrorist at +x and `extra`."""
    ents = [{"classname": "worldspawn"},
            {"classname": "info_player_terrorist", "origin": "-200 0 1", "angles": "0 0 0"},
            {"classname": "info_player_counterterrorist", "origin": "200 0 1", "angles": "0 180 0"}]
    ents += list(extra)
    with tempfile.NamedTemporaryFile(suffix=".bsp") as fh:
        fh.write(synth.build(boxes=((-512, -512, -64, 512, 512, 0),), entities=ents))
        fh.flush()
        bsp = Bsp(fh.name).load()
        z, spawns = bsp_import.classify_zones(bsp, doc=doc)[:2]
    return z, [(sp.get("team"), sp["origin_src"][0]) for sp in spawns]


class ArenaSpawnSides(unittest.TestCase):
    def setUp(self):
        # these cases are about which spawns survive and their sides, not the padding settle_spawns adds
        self._min = bsp_import.SPAWN_MIN_COUNT
        bsp_import.SPAWN_MIN_COUNT = 0
        self.addCleanup(setattr, bsp_import, "SPAWN_MIN_COUNT", self._min)

    def test_combat_map_tags_terrorists_red_and_counter_terrorists_blue(self):
        # The mapper's sides, not the game's positional split, decide a team's spawns.
        _, got = side_spawns({"kind": "arena"})
        self.assertEqual(got, [("red", -200.0), ("blue", 200.0)])

    def test_course_keeps_one_shared_pool(self):
        _, got = side_spawns({})
        self.assertEqual(got, [(None, -200.0), (None, 200.0)])

    def test_switched_off_spawns_are_dropped(self):
        z, got = side_spawns({"kind": "arena"},
                             {"classname": "info_player_counterterrorist", "origin": "220 0 1",
                              "targetname": "late", "StartDisabled": "1"},
                             {"classname": "info_player_counterterrorist", "origin": "240 0 1", "enabled": "0"})
        self.assertEqual(got, [("red", -200.0), ("blue", 200.0)])
        self.assertIn("2 spawn point(s) dropped that the map switches off", z.notes)

    def test_spawn_the_map_enables_at_once_is_kept(self):
        _, got = side_spawns({"kind": "arena"},
                             {"classname": "info_player_counterterrorist", "origin": "220 0 1",
                              "targetname": "late", "StartDisabled": "1"},
                             {"classname": "logic_auto", "OnMapSpawn": "late,Enable,,0,-1"})
        self.assertEqual(got, [("red", -200.0), ("blue", 200.0), ("blue", 220.0)])

    def test_all_switched_off_keeps_them_rather_than_none(self):
        ents = [{"classname": "worldspawn"},
                {"classname": "info_player_deathmatch", "origin": "0 0 1", "enabled": "0"}]
        with tempfile.NamedTemporaryFile(suffix=".bsp") as fh:
            fh.write(synth.build(boxes=((-512, -512, -64, 512, 512, 0),), entities=ents))
            fh.flush()
            spawns = bsp_import.classify_zones(Bsp(fh.name).load(), doc={"kind": "arena"})[1]
        self.assertEqual(len(spawns), 1)

    def test_points_are_numbered_from_reds_end(self):
        def pts():
            return [{"position": [x, 0, 0], "order": i} for i, x in enumerate((0, 500, 1000))]
        sp = lambda red, blue: [{"team": "red", "origin": [red, 0, 0]}, {"team": "blue", "origin": [blue, 0, 0]}]
        wrong = pts()
        bsp_import.orient_points(wrong, sp(1000, 0))   # red nearest the highest order: reversed
        self.assertEqual([p["order"] for p in wrong], [2, 1, 0])
        right = pts()
        bsp_import.orient_points(right, sp(0, 1000))
        self.assertEqual([p["order"] for p in right], [0, 1, 2])
        axis = [{"position": [x, 0, 0], "order": i} for i, x in enumerate((500, 1000, 0))]   # entity order, not geographic
        bsp_import.orient_points(axis, sp(1000, 0), by_axis=True)
        self.assertEqual([p["order"] for p in axis], [1, 0, 2])
        owned = pts()
        for p, o in zip(owned, ("red", "", "blue")):
            p["owner"] = o
        bsp_import.orient_points(owned, sp(1000, 0), by_axis=True)   # red owns the point at blue's end: swapped
        self.assertEqual([p["owner"] for p in owned], ["blue", "", "red"])
        alone = pts()
        bsp_import.orient_points(alone, [{"team": "blue", "origin": [0, 0, 0]}])   # no red spawns: untouched
        self.assertEqual([p["order"] for p in alone], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
