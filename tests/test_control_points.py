"""gsbsp.controlpoints: the regen path's control points. Run: python3 -P tests/test_control_points.py"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gsbsp import controlpoints, units  # noqa: E402

S = units.VISUAL


def bsp(entities, bounds=None):
    return types.SimpleNamespace(entities=entities, model_bounds=lambda i: bounds[i])


def spawn(team, origin):
    return {"classname": "info_player_teamspawn", "TeamNum": team, "origin": origin}


def cp(index, origin, name="", owner="", target=None):
    e = {"classname": "team_control_point", "point_index": str(index), "origin": origin, "point_printname": name,
         "point_default_owner": owner}
    if target:
        e["targetname"] = target
    return e


class ControlPoints(unittest.TestCase):
    def test_stage_disabled_spawns_still_orient_the_points(self):
        # Gold Rush style: red's spawns all start disabled (stage logic enables them); blue's are on
        red = dict(spawn("2", "0 0 0"), StartDisabled="1")
        ents = [red, spawn("3", "1000 0 0"), cp(1, "900 0 0", "near blue"), cp(2, "100 0 0", "near red")]
        pts = controlpoints.points(bsp(ents))
        self.assertEqual([p["name"] for p in pts], ["near red", "near blue"])
        self.assertEqual([p["order"] for p in pts], [0, 1])
        # a team with an enabled spawn keeps ignoring its disabled ones
        spawns = controlpoints.team_spawns(bsp([red, spawn("2", "5 0 0"), spawn("3", "1 0 0")]))
        self.assertEqual(len([x for x in spawns if x["team"] == "red"]), 1)

    def test_fields_and_metres(self):
        pts = controlpoints.points(bsp([cp(1, "100 200 300", "A", "2"), cp(2, "0 0 0", "B", "3")]))
        self.assertEqual([p["id"] for p in pts], [1, 2])
        self.assertEqual(pts[0]["owner"], "red")
        self.assertEqual(pts[0]["position"], [round(100 * S, 4), round(300 * S, 4), round(-200 * S, 4)])
        self.assertEqual(pts[0]["origin"], pts[0]["position"])
        # no capture area: the default radius, never below the minimum
        self.assertAlmostEqual(pts[0]["radius"], controlpoints.DEFAULT_CAPTURE_RADIUS * S, 3)

    def test_capture_area_sets_radius_with_a_floor(self):
        ents = [cp(1, "0 0 0", target="a"), cp(2, "500 0 0", target="b"),
                {"classname": "trigger_capture_area", "area_cap_point": "a", "model": "*1", "origin": "0 0 0"},
                {"classname": "trigger_capture_area", "area_cap_point": "b", "model": "*2", "origin": "0 0 0"}]
        pts = controlpoints.points(bsp(ents, {1: ((-300, -100, 0), (300, 100, 50)), 2: ((-3, -3, 0), (3, 3, 9))}))
        self.assertAlmostEqual(pts[0]["radius"], 300 * S, 3)
        self.assertAlmostEqual(pts[1]["radius"], controlpoints.MIN_CAPTURE_RADIUS * S, 3)

    def test_area_without_a_point_entity_becomes_a_point(self):
        ents = [{"classname": "trigger_capture_area", "area_cap_point": "mid", "model": "*1", "origin": "0 0 0"},
                {"classname": "trigger_capture_area", "area_cap_point": "end", "model": "*2", "origin": "0 0 0"}]
        pts = controlpoints.points(bsp(ents, {1: ((0, 0, 0), (200, 200, 20)), 2: ((1000, 0, 0), (1200, 200, 20))}))
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[0]["position"][0], 100 * S, 3)
        self.assertEqual({p["owner"] for p in pts}, {""})

    def test_orders_run_from_reds_end(self):
        # points listed blue-first by the map's round; red spawns sit beside the last one
        ents = [cp(0, "0 0 0", target="a"), cp(1, "1000 0 0", target="b"), cp(2, "2000 0 0", target="c"),
                {"classname": "team_control_point_round", "cpr_cp_names": "a b c"},
                spawn("3", "0 0 0"), spawn("2", "2000 0 0")]
        pts = controlpoints.points(bsp(ents))
        self.assertEqual([p["index"] for p in pts], [2, 1, 0])   # red's end is order 0
        self.assertEqual([p["order"] for p in pts], [0, 1, 2])

    def test_round_list_sets_the_order(self):
        ents = [cp(0, "0 0 0", target="a"), cp(1, "9 0 0", target="b"),
                {"classname": "team_control_point_round", "cpr_cp_names": "b a"}]
        self.assertEqual([p["index"] for p in controlpoints.points(bsp(ents))], [1, 0])

    def test_dod_points_are_numbered_along_the_spawn_axis(self):
        ents = [{"classname": "dod_control_point", "origin": "%d 0 0" % x, "point_printname": n, "point_default_owner": "0"}
                for x, n in ((2000, "far"), (0, "home"), (1000, "mid"))]
        ents += [{"classname": "info_player_axis", "origin": "-100 0 0"}, {"classname": "info_player_allies", "origin": "2100 0 0"}]
        pts = controlpoints.points(bsp(ents))
        self.assertEqual([p["name"] for p in pts], ["home", "mid", "far"])
        self.assertEqual([p["order"] for p in pts], [0, 1, 2])

    def test_disabled_and_one_sided_spawns_keep_the_map_order(self):
        ents = [cp(0, "0 0 0"), cp(1, "9 0 0"), spawn("3", "0 0 0")]
        self.assertEqual([p["index"] for p in controlpoints.points(bsp(ents))], [0, 1])
        # a team with only disabled spawns keeps them (stage logic enables them); the other team has none
        self.assertEqual(len(controlpoints.team_spawns(bsp([dict(spawn("2", "0 0 0"), StartDisabled="1")]))), 1)

    def test_attack_map_without_two_sided_spawns_still_leaves_the_last_point_neutral(self):
        # Corporation style: every point red's, the spawns are team 0: the owners alone must not give the far end to red
        ents = [cp(1, "0 0 0", owner="2"), cp(2, "9 0 0", owner="2"), cp(3, "99 0 0", owner="2"), spawn("0", "0 0 0")]
        pts = controlpoints.points(bsp(ents))
        self.assertEqual([p["owner"] for p in pts], ["red", "red", ""])

    def test_no_points(self):
        self.assertEqual(controlpoints.points(bsp([spawn("2", "0 0 0")])), [])


    def test_owners_fit_the_line(self):
        def line(owners):
            return [{"order": i, "owner": o} for i, o in enumerate(owners)]
        for owners, want in ((("blue", "", "red"), ["red", "", "blue"]),        # inverted: swapped
                             (("red", "red", "red"), ["red", "red", ""]),       # attack/defend: the far end is not red's
                             (("", "", "red"), ["", "", "blue"]),               # one owner at the far end: blue's
                             (("red", "", "blue"), ["red", "", "blue"])):
            pts = line(owners)
            controlpoints.fit_owners(pts)
            self.assertEqual([p["owner"] for p in pts], want)


class SnapToFloor(unittest.TestCase):
    def snap(self, pos, floors):
        from gsbsp import audit
        real = audit.floors
        audit.floors = lambda b: [(f, None) for f in floors]
        try:
            return controlpoints.snap_to_floor(None, [("t", 1, "", "", pos)])[0][4]
        finally:
            audit.floors = real

    def test_point_with_floor_under_it_stays(self):
        self.assertEqual(self.snap([100, 100, 40], [(100, 100, 0), (300, 100, 0)]), [100, 100, 40])

    def test_floating_point_moves_to_nearest_floor(self):
        self.assertEqual(self.snap([100, 100, 500], [(100, 100, 0), (300, 100, 480)]), [300, 100, 480])

    def test_no_floor_in_radius_stays(self):
        self.assertEqual(self.snap([100, 100, 500], [(5000, 100, 0)]), [100, 100, 500])


if __name__ == "__main__":
    unittest.main()
