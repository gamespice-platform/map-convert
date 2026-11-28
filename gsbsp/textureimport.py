"""Ask Godot to import a world's texture with mipmaps, by writing its `.import` before Godot does.

Godot writes a new `.webp.import` / `.png.import` with `mipmaps/generate=false` and only turns mipmaps on itself on
seeing the texture in a 3D material, which a texture handed to a shader parameter from a script never is. The lit
shaders sample with `filter_linear_mipmap_anisotropic` and had one level to sample, so a textured wall or floor
shimmered at distance and anisotropy did nothing (fc-video-game-ui-fx-1, "stretched and blurry" brick and floor).
Every world in fc-dm-maps was converted that way. This is the one place that knows how to fix it:

    python3 -m gsbsp.textureimport <worlds dir>...   # rewrites the textures' .import files, idempotent
"""
import os
import sys

EXTS = (".webp", ".png", ".jpg", ".jpeg")


def ask_for_mipmaps(tex_path):
    """Make Godot import [param tex_path] with mipmaps. An existing `.import` keeps its params and uid and loses its
    `[deps]` and cached path, so the next `--import` rebuilds the texture; a new one is the lines Godot needs.
    Returns True if it wrote the file, False if the texture already asked for mipmaps."""
    imp = tex_path + ".import"
    params, uid = {}, None
    if os.path.exists(imp):
        with open(imp, encoding="utf-8") as f:
            text = f.read()
        if "mipmaps/generate=true" in text:
            return False
        section = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section == "remap" and line.startswith("uid="):
                uid = line
            elif section == "params" and "=" in line:
                k, v = line.split("=", 1)
                params[k] = v
    params["mipmaps/generate"] = "true"
    with open(imp, "w", encoding="utf-8") as f:
        f.write('[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n')
        if uid:
            f.write(uid + "\n")
        f.write("\n[params]\n\n")
        for k, v in params.items():
            f.write("%s=%s\n" % (k, v))
    return True


def fix_tree(root):
    """Every texture in a `textures` folder under [param root]; returns how many `.import` files were written."""
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        if "textures" not in dirpath.split(os.sep):
            continue
        for name in files:
            if name.lower().endswith(EXTS) and ask_for_mipmaps(os.path.join(dirpath, name)):
                n += 1
    return n


if __name__ == "__main__":
    print("textureimport: %d .import file(s) now ask for mipmaps" % sum(fix_tree(p) for p in sys.argv[1:]))
