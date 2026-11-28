"""Every row of rules/models/picks.tsv names a free or own model with its source, author, URL and an allowed licence, and
never a Valve model. Run: python3 -P tests/test_model_picks_licence.py"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from gsbsp import licence  # noqa: E402


class PicksLicence(unittest.TestCase):
    def rows(self):
        with open(os.path.join(ROOT, "rules", "models", "picks.tsv")) as f:
            return [l.rstrip("\n").split("\t") for l in f if l.strip() and not l.startswith("#")]

    def test_every_pick_is_credited_and_allowed(self):
        for r in self.rows():
            self.assertGreaterEqual(len(r), 12, r[:2])
            model, lib = r[0], r[1]
            self.assertTrue(r[7] and r[8].startswith("http") and r[9], "no source/url/author: " + model)
            self.assertIn(r[10], licence.ALLOWED, "licence not allowed: " + model)
            self.assertFalse(r[11].lower().endswith((".mdl", ".vtf", ".vmt", ".vvd")), "Valve file: " + model)
            self.assertNotEqual(lib, "")


if __name__ == "__main__":
    unittest.main()
