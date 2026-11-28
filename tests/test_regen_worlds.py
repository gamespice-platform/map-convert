"""tools/regen_worlds.sh finds a source BSP by the map id, hyphen or underscore. Run: python3 -P tests/test_regen_worlds.py"""

import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "tools", "regen_worlds.sh")
FAKE_BSP = """import os, sys
with open(os.path.join(os.path.dirname(sys.argv[0]), 'calls.log'), 'a') as f:
    f.write(' '.join(sys.argv[1:3]) + '\\n')
"""


class RegenWorldsSource(unittest.TestCase):
    def run_regen(self, sources, ids):
        d = tempfile.mkdtemp()
        repo, fake = os.path.join(d, "repo"), os.path.join(d, "fake")
        os.makedirs(os.path.join(repo, "sources"))
        os.makedirs(fake)
        with open(os.path.join(fake, "bsp.py"), "w") as f:
            f.write(FAKE_BSP)
        for name in sources:
            open(os.path.join(repo, "sources", name), "w").close()
        env = dict(os.environ, GSBSP_PATH=fake, HEAVY="", TMPDIR=d)
        p = subprocess.run(["bash", SCRIPT, repo] + ids, env=env, capture_output=True, text=True)
        self.last_repo = repo
        calls = os.path.join(fake, "calls.log")
        log = ""
        if os.path.exists(calls):
            with open(calls) as f:
                log = f.read()
        return p, log

    def test_underscore_bsp_matches_hyphen_id(self):
        p, log = self.run_regen(["cp_orange_x3.bsp"], ["cp-orange-x3"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("NO SOURCE", p.stdout)
        self.assertIn("cp-orange-x3 exit 0", p.stdout)
        # the regen names the stored entry by the file's hash (sha256 of the empty fake source), not <game>/<name>
        self.assertIn("store %s" % os.path.join(self.last_repo, "sources", "cp_orange_x3.bsp"), log)
        self.assertIn("regen e3b0c44298fc1c14", log)

    def test_hyphen_bsp_still_matches(self):
        p, _ = self.run_regen(["gg-woods.bsp"], ["gg-woods"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("gg-woods exit 0", p.stdout)

    def test_missing_source_is_reported(self):
        p, _ = self.run_regen(["other.bsp"], ["cp-orange-x3"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("cp-orange-x3 NO SOURCE", p.stdout)


REGEN_BSP = """import json, sys
out = sys.argv[sys.argv.index('--out') + 1]
json.dump({'spawns': [{'yaw': 0}], 'skin_materials': [], 'props': [{'model': 'new'}]}, open(out + '.json', 'w'))
"""


class RegenKeepsSettledFields(unittest.TestCase):
    def run_world(self, importer):
        import json
        d = tempfile.mkdtemp()
        repo, fake = os.path.join(d, "repo"), os.path.join(d, "fake")
        os.makedirs(os.path.join(repo, "sources"))
        os.makedirs(os.path.join(repo, "worlds", "w"))
        os.makedirs(fake)
        open(os.path.join(repo, "sources", "w.bsp"), "w").close()
        open(os.path.join(fake, "bsp.py"), "w").write(REGEN_BSP)
        json.dump({"spawns": [{"yaw": 90}], "skin_materials": ["tuned"], "props": [{"model": "old"}]},
                  open(os.path.join(repo, "worlds", "w", "w.json"), "w"))
        if importer:
            os.makedirs(os.path.join(repo, "maps", "w"))
            json.dump({}, open(os.path.join(repo, "maps", "w", "w.json"), "w"))
        env = dict(os.environ, GSBSP_PATH=fake, HEAVY="", TMPDIR=d)
        p = subprocess.run(["bash", SCRIPT, repo, "w"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.load(open(os.path.join(repo, "worlds", "w", "w.json")))

    def test_spawns_and_skins_survive_without_importer(self):
        doc = self.run_world(importer=False)
        self.assertEqual(doc["spawns"], [{"yaw": 90}])
        self.assertEqual(doc["skin_materials"], ["tuned"])
        self.assertEqual(doc["props"], [{"model": "new"}])

    def test_importer_run_keeps_settled_spawns(self):
        doc = self.run_world(importer=True)
        self.assertEqual(doc["spawns"], [{"yaw": 90}])

    def test_licence_models_regenerated_textures_kept(self):
        from importlib.machinery import SourceFileLoader
        mod = SourceFileLoader("kwf", os.path.join(os.path.dirname(HERE), "tools", "keep_world_fields.py")).load_module()
        new = {"licence": {"models": [1], "textures": ["new"]}, "surfaces": ["n"]}
        done = mod.keep({"licence": {"models": [0], "textures": ["old"]}, "surfaces": ["o"]}, new)
        self.assertEqual(new, {"licence": {"models": [1], "textures": ["old"]}, "surfaces": ["o"]})
        self.assertEqual(sorted(done), ["licence.textures", "surfaces"])


if __name__ == "__main__":
    unittest.main()
