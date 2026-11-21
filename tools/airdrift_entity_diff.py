#!/usr/bin/env python3
"""Diff Airdrift's converted maps against the entities in their source BSPs, one line per map.

    python3 -P tools/airdrift_entity_diff.py REPO [REPO ...] [--src DIR ...] [--json OUT] [-v]

REPO is a map repository (a path, or a name under --godot, default ~/godot) whose maps/<id>/<id>.json
are game-airdrift manifests (bsp_import.py: `respawn_volumes`, `mechanics`). Each manifest's
`source` is looked up by name under --src (default ~/godot/../mapsrc/maps, then
~/godot/inspirations; recursive, first found wins).

Read from the BSP, not from the importer, so it checks what the map holds against what the
manifest kept:

    missing      an entity of a class the game runs (push, gravity, hurt, ladder, water, conveyor)
                 that has no box in the manifest overlapping its brushes
                 (a StartDisabled one the map switches on as it spawns, dotbsp.movers
                 .spawn_enabled, counts as running; one only a button or a timer enables
                 is counted as `gated`, part of the logic the game does not run)
    extra        a trigger_hurt behind a filter no player passes that the manifest kept
    teleports    the manifest's teleport_audit counts a different number of trigger_teleports
                 than the BSP has, or lists broken ones
    dropped      the logic the game does not run, counted: logic_*, math_*, filter_*,
                 point_teleport, trigger_proximity/wind/look/playermovement, and how many
                 outputs (and of those, delayed ones) the map wires

`missing`, `extra` and `teleports` fail the run; `dropped` is the report. The class table this
checks against is game-airdrift docs/brush-entities.md.
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotbsp import reader  # noqa: E402
from dotbsp.movers import outputs as _outputs, spawn_enabled  # noqa: E402
from dotbsp.reader import Bsp  # noqa: E402

# Which filters no player passes is the importer's own verdict (bsp_mechanics.inert_filters, a
# fact read off the entity lump), reused rather than restated. bsp_mechanics imports the game's
# `bsp_read` shim, which is dotbsp.reader under another name.
sys.modules.setdefault("bsp_read", reader)
sys.path.insert(0, os.path.join(ROOT, "adapters", "game-airdrift"))
from bsp_mechanics import DROPPED_CLASSES as DROPPED, DROPPED_PREFIXES, inert_filters  # noqa: E402

SF_CLIENTS = 1
SF_CONVEYOR_NO_PUSH = 1
CONTENTS_WATER, CONTENTS_SLIME, CONTENTS_LADDER = 0x20, 0x10, 0x20000000
SLACK = 2.0

# class -> (mechanics list, rule a run entity of the class passes)
RUN = {
    "trigger_push": ("push", lambda e: _flags(e, SF_CLIENTS) & SF_CLIENTS),
    "trigger_gravity": ("gravity", lambda e: True),
    "trigger_hurt": ("hurt", lambda e: _flags(e, SF_CLIENTS) & SF_CLIENTS),
    "func_ladder": ("ladders", lambda e: True),
    "func_water_analog": ("water", lambda e: True),
    "func_water": ("water", lambda e: True),
    "func_conveyor": ("conveyors", lambda e: not _flags(e, 0) & SF_CONVEYOR_NO_PUSH),
}
# StartDisabled teleports stay pits unless a per-map rule claims them (bsp_import.round_teleports),
# so only these are dropped for starting off.
SKIPPED_WHEN_DISABLED = ("trigger_push", "trigger_gravity", "trigger_hurt")
# Kept as still, solid geometry (docs/brush-entities.md); only their motion and outputs are dropped.
STILL = ("func_tracktrain", "func_movelinear", "func_rotating", "func_train", "func_door", "func_door_rotating",
         "func_button", "func_rot_button", "func_physbox", "func_physbox_multiplayer", "func_breakable")


def _flags(e, default):
    try:
        return int(float(e.get("spawnflags", default)))
    except ValueError:
        return default


def godot_box(lo, hi):
    """Source (x, y, z up) to the manifest's Godot axes (x, up, -y)."""
    a, b = (lo[0], lo[2], -lo[1]), (hi[0], hi[2], -hi[1])
    return [min(a[i], b[i]) for i in range(3)], [max(a[i], b[i]) for i in range(3)]


def entity_boxes(bsp, e):
    m = e.get("model", "")
    if not m.startswith("*"):
        return []
    try:
        o = [float(v) for v in e.get("origin", "0 0 0").split()[:3]]
    except ValueError:
        o = [0.0, 0.0, 0.0]
    out = []
    for br in bsp.model_brushes(int(m[1:])):
        pts = bsp.brush_hull(br)
        if len(pts) < 4:
            continue
        lo = [min(p[a] for p in pts) + o[a] for a in range(3)]
        hi = [max(p[a] for p in pts) + o[a] for a in range(3)]
        out.append(godot_box(lo, hi))
    return out


def overlaps(a, b):
    return all(a[0][i] - SLACK <= b[1][i] and b[0][i] - SLACK <= a[1][i] for i in range(3))


def outputs(e):
    """(target, input, delay), lower case, of every output on an entity (dotbsp.movers.outputs)."""
    return [(o["target"].lower(), o["input"].lower(), o["delay"]) for o in _outputs(e)]


def diff_map(bsp, manifest):
    """The findings of one map: {kind: [text]}, plus the dropped-logic counts."""
    found = collections.defaultdict(list)
    mech = manifest.get("mechanics", {})
    ents = bsp.entities
    woken = spawn_enabled(ents)
    gated = set()
    wired = delayed = 0
    for e in ents:
        for target, inp, delay in outputs(e):
            wired += 1
            delayed += delay > 0
            if inp in ("enable", "toggle"):
                gated.add(target)
    gated_n = 0
    inert = inert_filters(bsp)
    for idx, e in enumerate(ents):
        cls = e.get("classname", "")
        disabled = str(e.get("StartDisabled", "0")).strip() == "1"
        name = e.get("targetname", "").strip().lower()
        if disabled and name in woken:
            disabled = False    # switched on as the map spawns: it runs all round in Source
        elif cls in SKIPPED_WHEN_DISABLED and disabled and name in gated:
            gated_n += 1
        if cls not in RUN or disabled:
            continue
        key, runs = RUN[cls]
        if not runs(e):
            continue
        boxes = entity_boxes(bsp, e)
        have = [(r["min"], r["max"]) for r in mech.get(key, [])]
        if e.get("filtername", "").strip().lower() in inert:
            # Behind a filter no player passes: in Source it touches nobody, so a box for it is
            # one too many (a hurt that kills where Source kills nobody).
            if cls == "trigger_hurt" and any(overlaps(b, h) for b in boxes for h in have):
                found["extra"].append("%s#%d %s: behind inert filter %s, imported anyway" % (
                    cls, idx, name or "-", e.get("filtername")))
            continue
        for box in boxes:
            if min(box[1][i] - box[0][i] for i in range(3)) < 2.0 and key == "water":
                continue    # a sheet, not a volume (bsp_mechanics skips it too)
            if not any(overlaps(box, h) for h in have):
                found["missing"].append("%s#%d %s: no %s box at %s" % (
                    cls, idx, name or "-", key, [round(v) for v in box[0]]))
                break
    tele = sum(1 for e in ents if e.get("classname") == "trigger_teleport")
    audit = manifest.get("teleport_audit")
    if audit is None:
        if tele:
            found["teleports"].append("no teleport_audit for %d trigger_teleports (regenerate)" % tele)
    else:
        if "teleports" in audit and audit["teleports"] != tele:
            found["teleports"].append("audit counts %s, BSP has %d" % (audit.get("teleports"), tele))
        for b in audit.get("broken", []):
            found["teleports"].append("broken: %s" % (b,))
    drop = collections.Counter(
        e.get("classname", "") for e in ents
        if e.get("classname", "").startswith(DROPPED_PREFIXES) or e.get("classname", "") in DROPPED + STILL)
    return found, drop, wired, delayed, gated_n


def find_sources(dirs):
    idx = {}
    for d in dirs:
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".bsp"):
                    idx.setdefault(f.lower(), os.path.join(root, f))
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--godot", default=os.path.expanduser("~/godot"))
    ap.add_argument("--src", action="append")
    ap.add_argument("--json")
    ap.add_argument("-v", action="store_true", help="every finding, not the first three per kind")
    a = ap.parse_args(argv)
    src = a.src or [os.path.join(os.path.dirname(os.path.realpath(a.godot)), "mapsrc", "maps"),
                    os.path.join(a.godot, "inspirations")]
    idx = find_sources(src)
    report, fails, unfound = {}, 0, 0
    total_drop, total_maps = collections.Counter(), collections.Counter()
    for repo in a.repos:
        root = repo if os.sep in repo else os.path.join(a.godot, repo)
        maps = os.path.join(root, "maps")
        for mid in sorted(os.listdir(maps)) if os.path.isdir(maps) else []:
            path = os.path.join(maps, mid, mid + ".json")
            try:
                with open(path) as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                continue
            if "respawn_volumes" not in manifest and "mechanics" not in manifest:
                continue
            bsp_path = idx.get((manifest.get("source") or mid + ".bsp").lower())
            if not bsp_path:
                print("skip %s/%s: source %s not found" % (os.path.basename(root), mid, manifest.get("source")))
                unfound += 1
                continue
            bsp = Bsp(bsp_path)
            bsp.load()
            found, drop, wired, delayed, gated = diff_map(bsp, manifest)
            total_drop.update(drop)
            total_maps.update(drop.keys())
            bad = {k: v for k, v in found.items() if v}
            fails += bool(bad)
            report["%s/%s" % (os.path.basename(root), mid)] = {
                "findings": bad, "dropped": dict(drop), "outputs": wired, "delayed_outputs": delayed,
                "gated_triggers": gated}
            line = "FAIL" if bad else "ok  "
            print("%s %s/%s %s dropped %d logic entities, %d outputs (%d delayed), %d gated triggers" % (
                line, os.path.basename(root), mid,
                " ".join("%s=%d" % (k, len(v)) for k, v in sorted(bad.items())),
                sum(drop.values()), wired, delayed, gated))
            for k, v in sorted(bad.items()):
                for t in v if a.v else v[:3]:
                    print("     %-9s %s" % (k, t))
    print("dropped logic, by class (entities in maps; * = kept as still geometry):")
    for cls, n in total_drop.most_common():
        print("  %-28s %6d in %d maps" % (cls + (" *" if cls in STILL else ""), n, total_maps[cls]))
    print("%d maps, %d with findings, %d without a source BSP" % (len(report), fails, unfound))
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"maps": report, "dropped": dict(total_drop)}, f, indent=1, sort_keys=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
