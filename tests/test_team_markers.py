"""Team spawns, control points, resupply and flag spawns in the Airdrift importer.
Run: python3 -P tests/test_team_markers.py   (needs numpy, like the importer)
"""

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
sys.path.insert(0, ROOT)

os.environ.setdefault("GSBSP_PATH", ROOT)
for READER in (os.environ.get("AIRDRIFT_TOOLS", "") or os.environ.get("G2G_TOOLS", ""),
               os.path.join(os.path.dirname(ROOT), "game-airdrift", "tools"),
               "/home/gamedev/godot/game-airdrift/tools"):
    if READER and os.path.isfile(os.path.join(READER, "bsp_read.py")):
        sys.path.append(READER)
        break
try:
    import bsp_import  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
