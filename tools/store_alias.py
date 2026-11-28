"""Print the store entry to regen for `<game>/<id>`: a hashed alias `<game>/<id>~<hash>` before the bare one, only if its source is a real BSP.

A bare `<game>/<id>` alias can point at a stale or cut-off first extraction while the hashed alias holds the settled file, so a unique hashed
alias wins. Several hashed aliases are ambiguous: nothing is printed (the caller reports NO SOURCE) rather than guessing.
Usage: store_alias.py <store root> <game>/<id>
"""
import json
import os
import sys


def usable(root, h):
    p = os.path.join(root, h, "source.bsp")
    try:
        with open(p, "rb") as f:
            return f.read(4) == b"VBSP" and os.path.getsize(p) > 1024
    except OSError:
        return False


def pick(root, spec):
    try:
        with open(os.path.join(root, "index.json")) as f:
            index = json.load(f)
    except (OSError, ValueError):
        return None
    hashed = sorted(k for k in index if k.startswith(spec + "~") and usable(root, index[k]))
    if len(hashed) == 1:
        return hashed[0]
    if len(hashed) > 1:
        return None
    if spec in index and usable(root, index[spec]):
        return spec
    return None


if __name__ == "__main__":
    e = pick(sys.argv[1], sys.argv[2])
    if e:
        print(e)
