#!/usr/bin/env python3
"""io_coverage -- the map logic each converted map's players can set off, and what of it the runtime does not run.

Per map, from its source .bsp (the mapsrc store's `arena/<id>`, as check_teleports.py finds it):

    chains   every output chain a player starts (a button, a trigger, a game_ui, a door they touch),
             followed through the outputs it fires; a chain is `broken` when one of its hops sends an
             input the target's runtime component does not answer (gsbsp.inputs, read from gs-map's
             GDScript) or reaches a class gs-map only approximates or ignores (gsbsp.fidelity)
    gaps     the map's gameplay_lost (gsbsp.fidelity): unsupported classes, unimplemented inputs,
             parented volumes and the rest, one key per kind and class (`input_unimplemented:phys_thruster.Activate`)

Then every gap ranked by the maps it touches and the player chains it breaks, so the next runtime
work is the one that fixes most maps. tools/io_known.json in the map repository is the ratchet: a
map fails when it gains a gap the list does not record for it, or when a recorded gap is gone (shrink
the list with --write). Reads gs-map's io/ from $GS_MAP_DIR (else the sibling checkout): point it at
the branch whose runtime you are measuring.

    tools/io_coverage.py                   every map, the ranking and the ratchet (what CI runs)
    tools/io_coverage.py surf_mesa ...     these maps
    tools/io_coverage.py -v                each map's broken chains, hop by hop
    tools/io_coverage.py --write           record the current gaps as the ratchet
    tools/io_coverage.py --json FILE       the whole result as JSON

This is the shared copy; a map repository runs it through its own tools/io_coverage.py launcher.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

from gsbsp import fidelity, inputs, movers  # noqa: E402
from check_teleports import source_of, Bsp  # noqa: E402
import check_playable as cp  # noqa: E402

# Entities a player sets off by pressing, touching or walking in; their outputs start a chain.
STARTS = ("func_button", "func_rot_button", "momentary_rot_button", "trigger_multiple", "trigger_once",
          "trigger_teleport", "trigger_push", "trigger_hurt", "game_ui", "func_door", "func_door_rotating",
          "prop_door_rotating", "func_breakable", "func_physbox", "prop_physics", "trigger_look", "trigger_proximity")
DEPTH = 12


def gap_key(lost):
    """`volume_parented:trigger_hurt#1674 -> balling_1` -> `volume_parented:trigger_hurt`; `(ignored)` and ` x5` tails dropped."""
    kind, _, what = lost.partition(":")
    what = re.sub(r"\s*\(.*\)$", "", what)
    what = re.sub(r"#\d+.*$", "", what)
    what = re.sub(r"\s+x\d+$", "", what)
    return "%s:%s" % (kind, what.strip())


def chains(bsp, links, status):
    """[{start, hops: ['class.Input'], broken: ['class.Input' gap hops]}] for every chain a player starts."""
    by_from = collections.defaultdict(list)
    for k in links:
        by_from[k["from"]].append(k)
    out = []
    for i, e in enumerate(bsp.entities):
        cls = e.get("classname", "")
        if cls not in STARTS or not by_from.get(i):
            continue
        hops, broken, seen, todo = [], [], {i}, [(i, 0)]
        while todo:
            at, depth = todo.pop(0)
            for k in by_from.get(at, ()):
                for j in k["to"]:
                    c = bsp.entities[j].get("classname", "")
                    hop = "%s.%s" % (c, k["input"])
                    hops.append(hop)
                    if k["input"].lower() not in inputs.implemented(c):
                        broken.append("input_unimplemented:" + hop)
                    elif status.get(c, "implemented") != "implemented":
                        broken.append("class_unsupported:" + c)
                    if j not in seen and depth + 1 < DEPTH:
                        seen.add(j)
                        todo.append((j, depth + 1))
        name = e.get("targetname") or "#%d" % i
        out.append({"start": "%s %s" % (cls, name), "hops": hops, "broken": sorted(set(broken))})
    return out


def measure(bsp):
    links = movers.links(bsp)
    fid = fidelity.findings(bsp)
    gaps = collections.Counter(gap_key(l) for l in fidelity.gameplay_lost(fid))
    return {"gaps": dict(sorted(gaps.items())), "chains": chains(bsp, links, fid["classes"])}


def main(argv=None, root=None):
    """root is the map repository (maps/ and tools/io_known.json); default the current directory."""
    root = Path(root or ".").resolve()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--maps-dir", default=str(root / "maps"))
    ap.add_argument("--known", default=str(root / "tools" / "io_known.json"))
    ap.add_argument("--store", default=os.environ.get("GS_MAPSRC_STORE", str(Path.home() / "mapsrc" / "store")))
    ap.add_argument("--src", default="", help="DIR/<id>/<id>.bsp when the store has no arena/<id>")
    ap.add_argument("--top", type=int, default=20, help="gaps shown in the ranking (0 = all)")
    ap.add_argument("--write", action="store_true", help="record the current gaps in --known")
    ap.add_argument("--json", default="", help="write the per-map result and ranking here")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    maps_dir, store = Path(a.maps_dir), Path(a.store)
    src = Path(a.src) if a.src else None
    ids = a.maps or cp.map_ids(maps_dir)
    known = json.loads(Path(a.known).read_text()) if Path(a.known).is_file() else {}
    per, failed, held = {}, 0, 0
    for mid in ids:
        path = source_of(mid, store, src)
        if path is None:
            print("FAIL %s: no source .bsp (store arena/%s or --src)" % (mid, mid))
            failed += 1
            continue
        bsp = Bsp(str(path))
        bsp.load()
        r = per[mid] = measure(bsp)
        broken = [c for c in r["chains"] if c["broken"]]
        info = "%d player chains, %d broken, %d gaps" % (len(r["chains"]), len(broken), len(r["gaps"]))
        have, want = set(r["gaps"]), known.get(mid)
        if a.write:
            print("rec  %s: %s" % (mid, info))
        elif want is None and not have:
            print("ok   %s: %s" % (mid, info))
        elif want is not None and have == set(want):
            held += 1
            print("known %s: %s" % (mid, info))
        else:
            failed += 1
            new, gone = sorted(have - set(want or ())), sorted(set(want or ()) - have)
            print("FAIL %s: %s;%s%s" % (mid, info, " new " + ", ".join(new) if new else "",
                                       " fixed (shrink io_known.json with --write) " + ", ".join(gone) if gone else ""))
        if a.verbose:
            for c in broken:
                print("       %s -> %s  [%s]" % (c["start"], " ".join(c["hops"][:8]), ", ".join(c["broken"])))
    rank = collections.defaultdict(lambda: {"maps": 0, "uses": 0, "chains": 0})
    for mid, r in per.items():
        for g, n in r["gaps"].items():
            rank[g]["maps"] += 1
            rank[g]["uses"] += n
        for c in r["chains"]:
            for g in c["broken"]:
                rank[g]["chains"] += 1
    order = sorted(rank.items(), key=lambda kv: (-kv[1]["maps"], -kv[1]["chains"], -kv[1]["uses"], kv[0]))
    print("gaps by maps affected (maps, player chains broken, uses):")
    for g, s in order[:a.top or None]:
        print("  %3d %4d %5d  %s" % (s["maps"], s["chains"], s["uses"], g))
    if a.write:
        Path(a.known).write_text(json.dumps({m: sorted(r["gaps"]) for m, r in sorted(per.items()) if r["gaps"]},
                                            indent=1, sort_keys=True) + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps({"maps": per, "ranking": [dict(s, gap=g) for g, s in order]}, indent=1))
    print("io_coverage: %d maps, %d ok, %d known, %d failed" % (len(ids), len(ids) - failed - held, held, failed))
    return 1 if failed and not a.write else 0


if __name__ == "__main__":
    sys.exit(main())
