#!/usr/bin/env python3 -P
"""Put fields a regeneration must not change back into the regenerated world manifest.

    tools/keep_world_fields.py <old world.json> <new world.json> [field ...]

Default fields: name volumes spawns skin_materials surfaces licence.textures licence.pbr_store licence.model_store licence.sounds (dotted = inside a section),
so a regen changes only props and the model licence rows. `bsp.py regen` rebuilds both from the raw BSP, so a world whose settled spawns
(yaw, floor height, team padding) or tuned skin materials came from elsewhere drifted on every regen. Only fields present
in the old manifest are restored; a field it lacks is left as regenerated. Prints the names it restored.
"""
import json
import sys

DEFAULT = ("name", "volumes", "spawns", "skin_materials", "surfaces", "licence.textures", "licence.pbr_store", "licence.model_store", "licence.sounds")


def _get(doc, path):
    for k in path.split("."):
        if not isinstance(doc, dict) or k not in doc:
            return None, False
        doc = doc[k]
    return doc, True


def _set(doc, path, value):
    *head, last = path.split(".")
    for k in head:
        doc = doc.setdefault(k, {})
    doc[last] = value


def keep(old_doc, new_doc, fields=DEFAULT):
    done = []
    for f in fields:
        old, there = _get(old_doc, f)
        if there and _get(new_doc, f)[0] != old:
            _set(new_doc, f, old)
            done.append(f)
    return done


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    old = json.load(open(argv[0]))
    new = json.load(open(argv[1]))
    done = keep(old, new, tuple(argv[2:]) or DEFAULT)
    if done:
        with open(argv[1], "w") as f:
            json.dump(new, f, separators=(",", ":"), sort_keys=True)
    print(" ".join(done))


if __name__ == "__main__":
    main(sys.argv[1:])
