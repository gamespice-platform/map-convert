"""Team deathmatch on every map: the default modes, the position cut into two teams and the check that holds repositories to it."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from gsbsp import teams  # noqa: E402
import check_modes  # noqa: E402


def make_repo(root, modes, spawns, readme=True):
    (root / "zones").mkdir()
    (root / "worlds" / "m").mkdir(parents=True)
    (root / "zones" / "m.json").write_text(json.dumps({"id": "m", "kind": "arena", "modes": modes}))
    (root / "worlds" / "m" / "m.json").write_text(json.dumps({"spawns": spawns}))
    if readme:
        (root / "README.md").write_text("x\n" + check_modes.START + "\n" + check_modes.END + "\n")


def row(n, spread=10.0):
    return [{"at": [i * spread, 0, 0], "yaw": 0} for i in range(n)]


class TestTeams(unittest.TestCase):
    def test_merge_adds_required_modes_and_keeps_extras(self):
        m = teams.merge_modes(["cp", "ffa"])
        for need in ("ffa", "tdm", "gungame", "cp"):
            self.assertIn(need, m)
        self.assertEqual(len(m), len(set(m)))
        self.assertEqual(set(teams.merge_modes(None)), {"ffa", "tdm", "gungame"})

    def test_split_sides_separates_two_clusters(self):
        pts = [[x, 0, 0] for x in (0, 1, 2, 3)] + [[x, 0, 0] for x in (100, 101, 102, 103)]
        sides = teams.split_sides(pts)
        self.assertEqual(sides[:4], [sides[0]] * 4)
        self.assertEqual(sides[4:], [sides[4]] * 4)
        self.assertNotEqual(sides[0], sides[4])
        self.assertEqual(set(sides), {"red", "blue"})


class TestCheck(unittest.TestCase):
    def run_check(self, modes, spawns):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, modes, spawns)
            check_modes.main(["--write"], root=root)
            return check_modes.main([], root=root)

    def test_passes_with_all_modes_and_spawns(self):
        self.assertEqual(self.run_check(["ffa", "tdm", "gungame"], row(8)), 0)

    def test_fails_when_tdm_missing(self):
        self.assertEqual(self.run_check(["ffa", "gungame"], row(8)), 1)

    def test_fails_when_too_few_spawns(self):
        self.assertEqual(self.run_check(["ffa", "tdm", "gungame"], row(3)), 1)

    def test_stale_readme_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, ["ffa", "tdm", "gungame"], row(8))
            self.assertEqual(check_modes.main([], root=root), 1)

    def test_held_map_that_passes_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            make_repo(root, ["ffa", "tdm", "gungame"], row(8))
            (root / "tools").mkdir()
            (root / "tools" / "modes_known.json").write_text(json.dumps({"m": "reason"}))
            check_modes.main(["--write"], root=root)
            self.assertEqual(check_modes.main([], root=root), 1)


if __name__ == "__main__":
    unittest.main()
