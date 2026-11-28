#!/usr/bin/env python3
"""check_control_points -- the control points of a converted map can be played: valid data, on a floor, reachable by both teams, and each side starts at its own end.

Reads the converted map (maps/<id>/<id>.json and the collision block of <id>.bin) of every map that
has `control_points`. Control points are not nav destinations in the game's graph, so this builds a
small walking graph of its own (64-unit cells, steps up to a jump, any fall except into a pit, teleports
followed) and adds each point's capture disc as a target. Per map it fails when:

    schema         a point without id/order/position/radius, a duplicate id or order, an owner that is not '', red or blue
    few_points     the map lists the `cp` mode but has fewer than 2 points, or no tagged spawns for one team
    in_solid       the point's origin (or the standing height above it) is inside solid
    no_floor       no floor within --max-drop under the point: nothing to stand on
    radius         the capture radius is below --min-radius (a player cannot stand in it) or above --max-radius
    unreachable    a team's spawns do not reach the point's disc on the walking graph (`unreachable_red`, `unreachable_blue`)
    wrong_side     a point owned by a team is over 1.25 times as far from its spawns as from the other team's
    ends           both teams are nearest the same point, or blue (the low orders) is nearest a higher order than red

    tools/check_control_points.py                    every map with control points (what CI runs)
    tools/check_control_points.py cp_station ...     these maps
    tools/check_control_points.py -v                 list every problem

A map the search could not finish inside --nodes cells reports `inconclusive` (a warning, not a failure).
A map listed in tools/control_points_known.json with exactly the failure counts it records is `known`;
the list can only shrink by a fix. This is the shared copy; a map repository runs it through its own
tools/check_control_points.py launcher.
"""
import argparse
import heapq
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import check_playable as cp  # noqa: E402
import check_spawns as cs  # noqa: E402

UP = cp.UP
CELL = 64.0           # walking graph cell, map units
JUMP = 56.0           # highest step up the graph takes (a jump)
HEAD = 60.0           # standing clearance above the floor
CHEST = 36.0
WRONG_SIDE = 1.25     # an owned point is wrong when the owner's spawns are this much farther than the other side's
OWNERS = ("", "red", "blue")
KEYS = ("id", "order", "position", "radius", "owner")


def _inside(p, z):
    return all(min(z["min"][a], z["max"][a]) <= p[a] <= max(z["min"][a], z["max"][a]) for a in range(3))


def _flat(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


class Graph:
    """Walkable cells of one map, searched best-first from a team's spawns toward its unreached targets."""

    def __init__(self, m, max_nodes):
        self.m, self.max_nodes = m, max_nodes
        self.pits = [z for z in m.zones if z["kind"] == "RESPAWN" and "min" in z]
        self.tele = [z for z in m.zones if z["kind"] == "TELEPORT" and "min" in z and z.get("destination") is not None]

    def standable(self, x, z, y_from):
        """Floor height at (x, z) reachable from a cell at y_from (a step up or any fall), or None."""
        m = self.m
        f = cs.floor_under(m, [x, y_from + JUMP, z])
        if f is None:
            return None
        if m.in_solid([x, f + 20, z]) or m.in_solid([x, f + HEAD, z]) or m.out_of_bounds([x, f, z]):
            return None
        if any(_inside([x, f + 8, z], pz) for pz in self.pits):
            return None
        return f

    def search(self, starts, targets):
        """(indexes of the targets reached, complete) for the cells reachable from `starts` [(x, y, z)]."""
        m = self.m
        seen, heap, reached = set(), [], set()
        left = set(range(len(targets)))

        def push(x, f, z):
            key = (int(math.floor(x / CELL)), int(math.floor(z / CELL)), int(math.floor(f / 24.0)))
            if key in seen:
                return
            seen.add(key)
            h = min((_flat((x, 0, z), targets[i]["position"]) for i in left), default=0)
            heapq.heappush(heap, (h, x, f, z))

        for s in starts:
            f = cs.floor_under(m, [s[0], s[1] + 8, s[2]])
            if f is not None:
                push(s[0], f, s[2])
        n = 0
        while heap and left:
            _, x, f, z = heapq.heappop(heap)
            n += 1
            if n > self.max_nodes:
                return reached, False
            for i in list(left):
                t = targets[i]
                if _flat((x, 0, z), t["position"]) <= max(t["radius"], 64.0) and abs(f - t["position"][UP]) <= 128:
                    reached.add(i)
                    left.discard(i)
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, nz = x + dx * CELL, z + dz * CELL
                nf = self.standable(nx, nz, f)
                if nf is None or nf > f + JUMP or m.in_solid([(x + nx) / 2, max(f, nf) + 20, (z + nz) / 2]):
                    continue
                push(nx, nf, nz)
            for zone in self.tele:
                if _inside([x, f + 8, z], zone):
                    d = zone["destination"]
                    df = cs.floor_under(m, [d[0], d[1] + 8, d[2]])
                    if df is not None:
                        push(d[0], df, d[2])
        return reached, not left


def check(m, a):
    """([(kind, what, at)], complete) for one map."""
    doc, problems = m.doc, []
    pts = doc.get("control_points") or []
    spawns = doc.get("spawns") or []
    team = {t: [s for s in spawns if s.get("team") == t] for t in ("red", "blue")}
    if "cp" in (doc.get("modes") or []) and (len(pts) < 2 or not team["red"] or not team["blue"]):
        problems.append(("few_points", "%d points, spawns red %d blue %d" % (len(pts), len(team["red"]), len(team["blue"])), None))
    ids, orders = set(), set()
    for i, p in enumerate(pts):
        bad = [k for k in KEYS if k not in p]
        if bad:
            problems.append(("schema", "points[%d] lacks %s" % (i, ",".join(bad)), None))
            continue
        if p["owner"] not in OWNERS:
            problems.append(("schema", "points[%d] owner %r" % (i, p["owner"]), p["position"]))
        if p["id"] in ids or p["order"] in orders:
            problems.append(("schema", "points[%d] duplicate id/order %s/%s" % (i, p["id"], p["order"]), p["position"]))
        ids.add(p["id"])
        orders.add(p["order"])
    pts = [p for p in pts if all(k in p for k in KEYS)]
    for p in pts:
        pos = p["position"]
        what = "point %s" % p["id"]
        if p["radius"] < a.min_radius or p["radius"] > a.max_radius:
            problems.append(("radius", "%s radius %.1f" % (what, p["radius"]), pos))
        if m.in_solid([pos[0], pos[UP] + CHEST, pos[2]]):
            problems.append(("in_solid", what, pos))
            continue
        fl = cs.floor_under(m, [pos[0], pos[UP] + 8, pos[2]])
        if fl is None or pos[UP] - fl > a.max_drop:
            problems.append(("no_floor", "%s %s" % (what, "no floor" if fl is None else "%.0f up" % (pos[UP] - fl)), pos))
    if not pts or not team["red"] or not team["blue"]:
        return problems, True
    complete = True
    g = Graph(m, a.nodes)
    for t in ("red", "blue"):
        reached, done = g.search([s["origin"] for s in team[t]], pts)
        complete = complete and done
        for i, p in enumerate(pts):
            if i not in reached and done:
                problems.append(("unreachable_" + t, "point %s unreachable from %s spawns" % (p["id"], t), p["position"]))
    near = {t: {p["id"]: min(_flat(s["origin"], p["position"]) for s in team[t]) for p in pts} for t in team}
    for p in pts:
        if p["owner"] in team:
            other = "blue" if p["owner"] == "red" else "red"
            if near[p["owner"]][p["id"]] > near[other][p["id"]] * WRONG_SIDE:
                problems.append(("wrong_side", "point %s owned by %s is nearer the %s spawns" % (p["id"], p["owner"], other), p["position"]))
    if len(pts) >= 2:
        rank = {p["id"]: i for i, p in enumerate(sorted(pts, key=lambda p: p["order"]))}
        first = {t: min(pts, key=lambda p: near[t][p["id"]])["id"] for t in team}
        if first["red"] == first["blue"]:
            problems.append(("ends", "both teams are nearest point %s" % first["red"], None))
        elif rank[first["blue"]] > rank[first["red"]]:
            problems.append(("ends", "blue spawns nearest point %s, past red's %s: the order runs the wrong way" % (first["blue"], first["red"]), None))
    return problems, complete


def main(argv=None, root=None):
    """root is the map repository (maps/ and tools/control_points_known.json); default the current directory."""
    root = Path(root or ".").resolve()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--maps-dir", default=str(root / "maps"))
    ap.add_argument("--known", default=str(root / "tools" / "control_points_known.json"))
    ap.add_argument("--min-radius", type=float, default=48.0)
    ap.add_argument("--max-radius", type=float, default=640.0)
    ap.add_argument("--max-drop", type=float, default=128.0)
    ap.add_argument("--nodes", type=int, default=60000, help="walking cells a search may visit before it is inconclusive")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    maps_dir = Path(a.maps_dir)
    known = json.loads(Path(a.known).read_text()) if Path(a.known).is_file() else {}
    ids = a.maps or cp.map_ids(maps_dir)
    failed = held = checked = unsure = 0
    for mid in ids:
        base = maps_dir / mid / mid
        try:
            doc = json.loads(base.with_suffix(".json").read_text())
            if not doc.get("control_points"):
                continue
            m = cp.Map(mid, doc, base.with_suffix(".bin").read_bytes())
        except (OSError, ValueError) as e:
            print("FAIL %s: unreadable: %s" % (mid, e))
            failed += 1
            continue
        checked += 1
        problems, complete = check(m, a)
        kinds = {}
        for p in problems:
            kinds[p[0]] = kinds.get(p[0], 0) + 1
        info = "%d points" % len(doc["control_points"])
        if not complete:
            unsure += 1
            info += ", reach inconclusive"
        want = known.get(mid, {}).get("fails")
        if not problems and want is None:
            print("ok   %s: %s" % (mid, info))
        elif want is not None and want == kinds:
            held += 1
            print("known %s: %s (%s)" % (mid, ", ".join("%s %d" % kv for kv in sorted(kinds.items())), known[mid].get("reason", "")))
        else:
            failed += 1
            if want is not None:
                print("FAIL %s: control_points_known.json expects %s, got %s: update or remove the entry" % (mid, want, kinds or "no failures"))
            else:
                print("FAIL %s: %s; %s" % (mid, info, ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
        shown = problems if a.verbose else (problems[:6] if want is None else [])
        for kind, what, at in shown:
            print("       %s %s%s" % (kind, what, "" if at is None else " at (%.0f, %.0f, %.0f)" % tuple(at)))
    print("check_control_points: %d maps, %d ok, %d known, %d failed, %d inconclusive" % (checked, checked - failed - held, held, failed, unsure))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
