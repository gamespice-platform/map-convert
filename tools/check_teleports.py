#!/usr/bin/env python3
"""check_teleports -- every trigger_teleport of a map, resolved in the source, lands where the converted map sends it.

Reads the source .bsp and, when there is one, the converted map (maps/<id>/<id>.json and the
collision block of <id>.bin). For each `trigger_teleport` it resolves the destination the way
Source does (case-insensitive targetname, an `info_teleport_destination` first, else any point
entity, else a brush entity's origin), puts both the trigger's brushes and that destination
through the importer's own transform (bsp_import.to_godot), and fails a map when:

    null_target        a teleport with no target (which Source never fires) is a pit
    unresolved         one whose target names nothing is a pit
    at_origin          its destination is the world origin (an unset point)
    no_landing         the importer finds nowhere clear to put the player
    in_solid           the landing is inside a brush (source) or a collision hull (converted)
    no_floor           nothing at all is under the landing in the converted map
    wrong_destination  the pit at the trigger's centre sends somewhere no live teleport there
                       sends, directly or through the teleports its landing stands in
    gated_pit          a teleport that starts disabled (and no logic_auto leaves on) is a pit:
                       it fires from the first second though the map switches it on later

`ambiguous` is reported, never failed: two teleports that are both on, overlap and send to
different places, which Source resolves by touch order (surf_10x_final's 232/233).

    tools/check_teleports.py                        every map in maps/ (what CI runs)
    tools/check_teleports.py surf_10x_final ...     these maps
    tools/check_teleports.py --originals DIR        also every surf_*.bsp under DIR/<id>/<id>.bsp, source checks only
    tools/check_teleports.py -v                     list every problem

The source of map <id> is the mapsrc store's `arena/<id>` (`$GS_MAPSRC_STORE`, default
~/mapsrc/store, as regen_worlds.sh stores it), else `--src DIR/<id>/<id>.bsp`. A map listed in
tools/teleports_known.json with exactly the failure counts it records is `known`, as in
check_playable.py; the list can only shrink by a fix.

This is the shared copy; a map repository runs it through its own tools/check_teleports.py launcher.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "adapters" / "game-airdrift"), str(ROOT), str(HERE)]
os.environ.setdefault("GSBSP_PATH", str(ROOT))
for _reader in (os.environ.get("AIRDRIFT_TOOLS", ""), str(ROOT.parent / "game-airdrift" / "tools"),
                "/home/gamedev/godot/game-airdrift/tools"):
    if _reader and (Path(_reader) / "bsp_read.py").is_file():
        sys.path.append(_reader)
        break

import bsp_import as bi  # noqa: E402
import bsp_mechanics  # noqa: E402
import check_playable as cp  # noqa: E402
from bsp_read import Bsp  # noqa: E402

FAILS = ("null_target", "unresolved", "at_origin", "no_landing", "in_solid", "no_floor",
         "wrong_destination", "gated_pit")
SAME = 2.0


def _inside(p, lo, hi):
    return all(min(lo[a], hi[a]) <= p[a] <= max(lo[a], hi[a]) for a in range(3))


def _close(a, b):
    return a is not None and b is not None and math.dist(a, b) <= SAME


def _landing(src):
    g = list(bi.to_godot(src))
    g[cp.UP] += bi.DESTINATION_LIFT
    return g


def first_pit(zones, p):
    """The zone a player whose feet are at p is caught by in the game: the first RESPAWN pit."""
    for z in zones:
        if z.get("kind") == "RESPAWN" and z.get("destination") is not None and _inside(p, z["min"], z["max"]):
            return z
    return None


def triggers(bsp, z):
    """[{i, e, name, gated, boxes, sends: [godot landings this teleport may give]}] for every trigger_teleport."""
    out = []
    for i, e in enumerate(bsp.entities):
        if e.get("classname") != "trigger_teleport":
            continue
        target = e.get("target", "").strip()
        t = {"i": i, "e": e, "gated": bsp_mechanics._starts_off(bsp, e), "target": target,
             "name": "%s -> %s" % (e.get("targetname", "") or "#%d" % i, target or "(none)"),
             "boxes": [box for _b, _o, box in bi.brush_boxes_indexed(bsp, e)], "src": None, "sends": []}
        dests = z.destinations(target) if target else []
        if dests:
            t["src"] = dests[0][0]
            t["sends"].append(_landing(dests[0][0]))
            moved = z.sends(e)[0]
            if moved is not None:
                t["sends"].append(_landing(moved))
            t["moved"] = moved
        out.append(t)
    return out


def _touches(src, box):
    """Whether a standing player hull (32 x 32 x 72) with its feet at src overlaps a trigger box."""
    lo, hi = box
    return all(lo[a] - 16.0 <= src[a] <= hi[a] + 16.0 for a in range(2)) and lo[2] - 72.0 <= src[2] <= hi[2]


def _reach(ts):
    """Each teleport's landings plus every landing it chains on to: a player put inside another live
    teleport is sent on by it at once, in Source as in the importer."""
    live = [o for o in ts if o["sends"] and not o["gated"]]
    for t in ts:
        reach, todo, seen = list(t["sends"]), [t], {t["i"]}
        while todo and len(seen) < 64:
            cur = todo.pop()
            for at in (cur["src"], cur.get("moved")):
                if at is None:
                    continue
                for o in live:
                    if o["i"] not in seen and any(_touches(at, b) for b in o["boxes"]):
                        seen.add(o["i"])
                        reach.extend(o["sends"])
                        todo.append(o)
        t["reach"] = reach


def check_map(bsp, m=None):
    """[(kind, what, at)] for one source map; m is the converted check_playable.Map, or None."""
    z = bi.Zoner(bsp)
    ts = triggers(bsp, z)
    _reach(ts)
    problems = []
    for t in ts:
        if t["src"] is None:
            # Source does nothing with a teleport whose target names nothing (surf_29_12_06's
            # `g1`.. are only other teleports' destinations), so the converted map must not either.
            if m is not None and not t["gated"]:
                for lo, hi in t["boxes"]:
                    c = [(lo[a] + hi[a]) / 2 for a in range(3)]
                    pit = first_pit(m.zones, list(bi.to_godot(c)))
                    live = [o for o in ts if o["sends"] and not o["gated"] and any(_inside(c, a, b) for a, b in o["boxes"])]
                    if pit is not None and not any(_close(pit["destination"], s) for o in live for s in o["reach"]):
                        problems.append(("null_target" if not t["target"] else "unresolved", t["name"], pit["destination"]))
                        break
            continue
        if all(abs(v) < 1.0 for v in t["src"]):
            problems.append(("at_origin", t["name"], t["sends"][0]))
            continue
        if t["moved"] is None:
            problems.append(("no_landing", t["name"], t["sends"][0]))
            continue
        if z.stuck(t["moved"], bi.DESTINATION_LIFT):
            problems.append(("in_solid", t["name"] + " (source)", t["sends"][-1]))
        if m is None:
            continue
        land = t["sends"][-1]
        if any(m.in_solid([land[a] + (lift if a == cp.UP else 0.0) for a in range(3)]) for lift in cp.PROBES):
            problems.append(("in_solid", t["name"], land))
        elif not m.has_floor(land):
            problems.append(("no_floor", t["name"], land))
        for lo, hi in t["boxes"]:
            c = [(lo[a] + hi[a]) / 2 for a in range(3)]
            g = list(bi.to_godot(c))
            pit = first_pit(m.zones, g)
            if pit is None:
                continue    # dropped on purpose (dead, conditional, sealed...) or trimmed off
            to = pit["destination"]
            here = [o for o in ts if o["sends"] and any(_inside(c, a, b) for a, b in o["boxes"])]
            live = [o for o in here if not o["gated"]]
            if t["gated"]:
                if any(_close(to, s) for s in t["reach"]) and not any(_close(to, s) for o in live for s in o["reach"]):
                    problems.append(("gated_pit", t["name"], g))
                continue
            if not any(_close(to, s) for o in live for s in o["reach"]):
                problems.append(("wrong_destination", t["name"], to))
            elif len({tuple(round(v) for v in o["src"]) for o in live}) > 1:
                problems.append(("ambiguous", t["name"], to))
            break
    return problems


def source_of(mid, store, src):
    idx = store / "index.json"
    if idx.is_file():
        h = json.loads(idx.read_text()).get("arena/" + mid)
        if h and (store / h / "source.bsp").is_file():
            return store / h / "source.bsp"
    p = src / mid / (mid + ".bsp") if src else None
    return p if p and p.is_file() else None


def main(argv=None, root=None):
    root = Path(root or ".").resolve()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--maps-dir", default=str(root / "maps"))
    ap.add_argument("--known", default=str(root / "tools" / "teleports_known.json"))
    ap.add_argument("--store", default=os.environ.get("GS_MAPSRC_STORE", str(Path.home() / "mapsrc" / "store")))
    ap.add_argument("--src", default="", help="DIR/<id>/<id>.bsp when the store has no arena/<id>")
    ap.add_argument("--originals", default="", help="also check every surf_* source under DIR/<id>/<id>.bsp")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    maps_dir, store = Path(a.maps_dir), Path(a.store)
    src = Path(a.src) if a.src else None
    ids = a.maps or (cp.map_ids(maps_dir) if maps_dir.is_dir() else [])
    known = json.loads(Path(a.known).read_text()) if Path(a.known).is_file() else {}
    jobs = [(mid, source_of(mid, store, src), maps_dir / mid / mid) for mid in ids]
    if a.originals and not a.maps:
        orig = Path(a.originals)
        jobs += [("original/" + d.name, d / (d.name + ".bsp"), None) for d in sorted(orig.iterdir())
                 if d.name.startswith("surf_") and (d / (d.name + ".bsp")).is_file()]
    failed = held = 0
    for mid, bsp_path, base in jobs:
        if bsp_path is None:
            print("FAIL %s: no source .bsp (store arena/%s or --src)" % (mid, mid))
            failed += 1
            continue
        m = None
        try:
            bsp = Bsp(str(bsp_path))
            bsp.load()
            if base is not None:
                m = cp.Map(mid, json.loads(base.with_suffix(".json").read_text()), base.with_suffix(".bin").read_bytes())
        except (OSError, ValueError) as e:
            print("FAIL %s: unreadable: %s" % (mid, e))
            failed += 1
            continue
        problems = check_map(bsp, m)
        n = sum(1 for e in bsp.entities if e.get("classname") == "trigger_teleport")
        fails = [p for p in problems if p[0] in FAILS]
        kinds = {}
        for p in fails:
            kinds[p[0]] = kinds.get(p[0], 0) + 1
        note = sum(1 for p in problems if p[0] == "ambiguous")
        extra = ", %d ambiguous" % note if note else ""
        want = known.get(mid, {}).get("fails")
        if not fails and want is None:
            print("ok   %s: %d teleports%s" % (mid, n, extra))
        elif want is not None and want == kinds:
            held += 1
            print("known %s: %s (%s)" % (mid, ", ".join("%s %d" % kv for kv in sorted(kinds.items())),
                                        known[mid].get("reason", "")))
        else:
            failed += 1
            if want is not None:
                print("FAIL %s: teleports_known.json expects %s, got %s: update or remove the entry"
                      % (mid, want, kinds or "no failures"))
            else:
                print("FAIL %s: %d teleports, %s%s" % (mid, n, ", ".join("%s %d" % kv for kv in sorted(kinds.items())), extra))
        shown = problems if a.verbose else (fails[:5] if want is None else [])
        for kind, what, at in shown:
            print("       %s %s%s" % (kind, what, "" if at is None else " at (%.0f, %.0f, %.0f)" % tuple(at)))
    print("check_teleports: %d maps, %d ok, %d known, %d failed" % (len(jobs), len(jobs) - failed - held, held, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
