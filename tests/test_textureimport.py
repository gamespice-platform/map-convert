"""textureimport: a world's textures ask Godot for mipmaps.
Run: python3 -P tests/test_textureimport.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from gsbsp import textureimport  # noqa: E402

GODOT_WROTE = """[remap]

importer="texture"
type="CompressedTexture2D"
uid="uid://abc"
path="res://.godot/imported/x.ctex"

[deps]

source_file="res://x.webp"

[params]

compress/mode=0
mipmaps/generate=false
mipmaps/limit=-1
"""


class TextureImport(unittest.TestCase):
    def test_rewrites_godots_default_and_keeps_uid_and_params(self):
        with tempfile.TemporaryDirectory() as d:
            tex = os.path.join(d, "w", "textures")
            os.makedirs(tex)
            p = os.path.join(tex, "x.webp")
            open(p, "wb").close()
            with open(p + ".import", "w") as f:
                f.write(GODOT_WROTE)
            self.assertEqual(textureimport.fix_tree(d), 1)
            text = open(p + ".import").read()
            self.assertIn("mipmaps/generate=true", text)
            self.assertNotIn("mipmaps/generate=false", text)
            self.assertIn('uid="uid://abc"', text)
            self.assertIn("compress/mode=0", text)
            self.assertNotIn("[deps]", text)
            self.assertEqual(textureimport.fix_tree(d), 0, "idempotent")

    def test_new_texture_gets_an_import(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "textures", "y.png")
            os.makedirs(os.path.dirname(p))
            open(p, "wb").close()
            self.assertTrue(textureimport.ask_for_mipmaps(p))
            self.assertIn("mipmaps/generate=true", open(p + ".import").read())


if __name__ == "__main__":
    unittest.main()
