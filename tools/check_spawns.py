#!/usr/bin/env python3
"""check_spawns -- every spawn point of a converted map is one a player can start a round at, on the mapper's side.

Reads the converted map (maps/<id>/<id>.json and the collision block of <id>.bin) and, when there
is one, the source .bsp (the mapsrc store's `arena/<id>`, as check_teleports.py finds it). The
spawns' placement in solid, on no floor and out of bounds is check_playable.py's; this adds what
decides where a round starts. Per map it fails when:

    few            fewer than --min-spawns spawns (default 16): a full server stacks players on one spot
    team_short     a tagged team has fewer than --min-team spawns (default 4)
    in_pit         a spawn stands in a pit (RESPAWN zone): the player is sent away the moment they spawn
    in_teleport    a spawn stands in a teleport: the round starts somewhere else
    high           the floor under a spawn is more than --max-drop units down (default 96)
    facing_wall    solid within --wall units (default 32) straight ahead at eye height
    sealed         the spawn's room closes within --flood cells and holds no pit or teleport: a jail
                   (a coarse 32-unit flood; a wall thinner than that leaks, so it can miss one, never invent one)
    untagged       the source gives both sides spawns and the manifest tags none: the game splits by position
    wrong_team     a spawn's tag is not its source class's side (terrorist red, counter-terrorist blue)
    disabled_kept  a spawn the source switches off (StartDisabled / enabled 0, no logic_auto turning it on) was kept

    tools/check_spawns.py                    every map (what CI runs)
    tools/check_spawns.py surf_mesa ...      these maps
    tools/check_spawns.py -v                 list every problem

A map with no source is checked without the last three. A map listed in tools/spawns_known.json
with exactly the failure counts it records is `known`, as in check_playable.py; the list can only
shrink by a fix. This is the shared copy; a map repository runs it through its own
tools/check_spawns.py launcher.
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
import check_playable as cp  # noqa: E402
from check_teleports import source_of  # noqa: E402

UP = cp.UP
EYE = 64.0          # a standing player's eye over the spawn origin (the origin is at the feet)
CHEST = 36.0
MATCH = 64.0        # a manifest spawn is the source spawn within this many units (the importer settles them)
STEP = 32.0         # flood cell, map units
SIDES = {"info_player_terrorist": "red", "info_player_counterterrorist": "blue"}
SIDES.update({("info_player_teamspawn", "2"): "red", ("info_player_teamspawn", "3"): "blue"})
SPAWN_CLASSES = ("info_player_terrorist", "info_player_counterterrorist", "info_player_start",
                 "info_player_teamspawn", "info_player_deathmatch")
FAILS = ("few", "team_short", "in_pit", "in_teleport", "high", "facing_wall", "sealed",
         "untagged", "wrong_team", "disabled_kept")


def _inside(p, z):
    return all(min(z["min"][a], z["max"][a]) <= p[a] <= max(z["min"][a], z["max"][a]) for a in range(3))


def floor_under(m, p):
    """Height of the highest surface under p (hull tops cut exactly at p's x, z; displacements), or None."""
    best = None
    for i in m.grid.get(m._cell(p), ()):
        lo, hi = m.boxes[i]
        if not (lo[0] <= p[0] <= hi[0] and lo[2] <= p[2] <= hi[2]) or lo[UP] > p[UP] + cp.DEPTH:
            continue
        pl = m.planes.get(i)
        if pl is None:
            pl = m.planes[i] = cp.planes_of(m.hulls[i])
        top, bottom, ok = math.inf, -math.inf, True
        for nx, ny, nz, d in pl:
            r = d - nx * p[0] - nz * p[2]
            if abs(ny) < 1e-6:
                if r < -0.01:
                    ok = False
                    break
            elif ny > 0:
                top = min(top, r / ny)
            else:
                bottom = max(bottom, r / ny)
        if ok and top >= bottom - 0.01 and top <= p[UP] + cp.DEPTH and (best is None or top > best):
            best = top
    for t in m.disp_grid.get(m._cell(p), ()):
        h = _disp_height(t, p)
        if h is not None and h <= p[UP] + cp.DEPTH and (best is None or h > best):
            best = h
    return best


def _disp_height(t, p):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
    d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
    if abs(d) < 1e-9:
        return None
    l1 = ((bz - cz) * (p[0] - cx) + (cx - bx) * (p[2] - cz)) / d
    l2 = ((cz - az) * (p[0] - cx) + (ax - cx) * (p[2] - cz)) / d
    l3 = 1.0 - l1 - l2
    if min(l1, l2, l3) < -1e-6:
        return None
    return l1 * ay + l2 * by + l3 * cy


def forward(yaw):
    """The manifest's yaw (Godot degrees about +y) as a horizontal direction: 0 looks down -z."""
    r = math.radians(yaw)
    return (-math.sin(r), 0.0, -math.cos(r))


def facing_wall(m, p, yaw, reach):
    f = forward(yaw)
    for k in range(1, int(reach // 8) + 1):
        q = [p[0] + f[0] * 8 * k, p[UP] + EYE, p[2] + f[2] * 8 * k]
        if m.in_solid(q):
            return True
    return False


class Flood:
    """Air cells (STEP units, probed at chest height) reachable from a spawn; one pass per map."""

    def __init__(self, m, limit):
        self.m, self.limit, self.seen = m, limit, {}

    def open_from(self, p):
        """True when the room around p leaks past `limit` cells, the bounds or a pit or teleport."""
        start = tuple(int(math.floor(p[a] / STEP)) for a in range(3))
        if start in self.seen:
            return self.seen[start]
        todo, mine, opened = [start], {start}, False
        zones = [z for z in self.m.zones if z["kind"] in ("RESPAWN", "TELEPORT") and "min" in z]
        while todo and not opened:
            c = todo.pop()
            q = [(c[a] + 0.5) * STEP for a in range(3)]
            if self.m.out_of_bounds(q) or any(_inside(q, z) for z in zones):
                opened = True
                break
            for a in range(3):
                for s in (-1, 1):
                    n = list(c)
                    n[a] += s
                    n = tuple(n)
                    if n in mine:
                        continue
                    if n in self.seen:
                        opened = opened or self.seen[n]
                        continue
                    if self.m.in_solid([(n[b] + 0.5) * STEP for b in range(3)]):
                        continue
                    mine.add(n)
                    todo.append(n)
            if len(mine) > self.limit:
                opened = True
        for c in mine:
            self.seen[c] = opened
        return opened


def source_spawns(bsp):
    """[(godot origin, side or None, disabled)] for every spawn class the importer reads."""
    out = []
    for e in bsp.entities:
        cls = e.get("classname", "")
        if cls not in SPAWN_CLASSES:
            continue
        try:
            src = [float(v) for v in e.get("origin", "0 0 0").split()[:3]]
        except ValueError:
            continue
        side = SIDES.get(cls) or SIDES.get((cls, str(e.get("TeamNum", "")).strip()))
        out.append((list(bi.to_godot(src)), side, bi.spawn_disabled(bsp, e)))
    return out


def check(m, bsp, a):
    doc, problems = m.doc, []
    spawns = doc.get("spawns") or []
    if len(spawns) < a.min_spawns:
        problems.append(("few", "%d spawns" % len(spawns), None))
    teams = {}
    for s in spawns:
        if s.get("team"):
            teams[s["team"]] = teams.get(s["team"], 0) + 1
    for t, n in sorted(teams.items()):
        if n < a.min_team:
            problems.append(("team_short", "%s %d" % (t, n), None))
    flood = Flood(m, a.flood)
    for i, s in enumerate(spawns):
        p, what = list(s["origin"]), "spawns[%d]" % i
        feet = [p[0], p[UP] + cp.PROBES[0], p[2]]
        if m.in_solid([p[0], p[UP] + CHEST, p[2]]) or m.out_of_bounds(p):
            continue    # check_playable's
        hit = next((z for z in m.zones if z["kind"] in ("RESPAWN", "TELEPORT") and "min" in z and _inside(feet, z)), None)
        if hit is not None:
            problems.append(("in_pit" if hit["kind"] == "RESPAWN" else "in_teleport", what, p))
            continue
        fl = floor_under(m, p)
        if fl is not None and p[UP] - fl > a.max_drop:
            problems.append(("high", "%s %.0f up" % (what, p[UP] - fl), p))
        if facing_wall(m, p, s.get("yaw", 0.0), a.wall):
            problems.append(("facing_wall", what, p))
        if a.flood and not flood.open_from([p[0], p[UP] + CHEST, p[2]]):
            problems.append(("sealed", what, p))
    if bsp is not None:
        src = source_spawns(bsp)
        sides = {sd for _, sd, off in src if sd and not off}
        if sides >= {"red", "blue"} and not teams:
            problems.append(("untagged", "source has both sides", None))
        for i, s in enumerate(spawns):
            p = s["origin"]
            near = min(src, key=lambda e: math.dist((e[0][0], e[0][2]), (p[0], p[2])), default=None)
            if near is None or math.dist((near[0][0], near[0][2]), (p[0], p[2])) > MATCH:
                continue
            if teams and near[1] and s.get("team") != near[1]:
                problems.append(("wrong_team", "spawns[%d] %s, source %s" % (i, s.get("team"), near[1]), p))
            if near[2]:
                problems.append(("disabled_kept", "spawns[%d]" % i, p))
    return problems


def main(argv=None, root=None):
    """root is the map repository (maps/ and tools/spawns_known.json); default the current directory."""
    root = Path(root or ".").resolve()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("maps", nargs="*")
    ap.add_argument("--maps-dir", default=str(root / "maps"))
    ap.add_argument("--known", default=str(root / "tools" / "spawns_known.json"))
    ap.add_argument("--store", default=os.environ.get("GS_MAPSRC_STORE", str(Path.home() / "mapsrc" / "store")))
    ap.add_argument("--src", default="", help="DIR/<id>/<id>.bsp when the store has no arena/<id>")
    ap.add_argument("--min-spawns", type=int, default=16)
    ap.add_argument("--min-team", type=int, default=4)
    ap.add_argument("--max-drop", type=float, default=96.0)
    ap.add_argument("--wall", type=float, default=32.0)
    ap.add_argument("--flood", type=int, default=20000, help="cells a room may hold before it counts as open; 0 skips the flood")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    from bsp_read import Bsp
    maps_dir, store = Path(a.maps_dir), Path(a.store)
    src = Path(a.src) if a.src else None
    ids = a.maps or cp.map_ids(maps_dir)
    known = json.loads(Path(a.known).read_text()) if Path(a.known).is_file() else {}
    failed = held = 0
    for mid in ids:
        base = maps_dir / mid / mid
        try:
            m = cp.Map(mid, json.loads(base.with_suffix(".json").read_text()), base.with_suffix(".bin").read_bytes())
            bsp_path = source_of(mid, store, src)
            bsp = Bsp(str(bsp_path)).load() if bsp_path else None
        except (OSError, ValueError) as e:
            print("FAIL %s: unreadable: %s" % (mid, e))
            failed += 1
            continue
        problems = check(m, bsp, a)
        kinds = {}
        for p in problems:
            kinds[p[0]] = kinds.get(p[0], 0) + 1
        n = len(m.doc.get("spawns") or [])
        tags = sum(1 for s in m.doc.get("spawns") or [] if s.get("team"))
        info = "%d spawns, %d tagged%s" % (n, tags, "" if bsp is not None else ", no source")
        want = known.get(mid, {}).get("fails")
        if not problems and want is None:
            print("ok   %s: %s" % (mid, info))
        elif want is not None and want == kinds:
            held += 1
            print("known %s: %s (%s)" % (mid, ", ".join("%s %d" % kv for kv in sorted(kinds.items())),
                                        known[mid].get("reason", "")))
        else:
            failed += 1
            if want is not None:
                print("FAIL %s: spawns_known.json expects %s, got %s: update or remove the entry"
                      % (mid, want, kinds or "no failures"))
            else:
                print("FAIL %s: %s; %s" % (mid, info, ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
        shown = problems if a.verbose else (problems[:5] if want is None else [])
        for kind, what, at in shown:
            print("       %s %s%s" % (kind, what, "" if at is None else " at (%.0f, %.0f, %.0f)" % tuple(at)))
    print("check_spawns: %d maps, %d ok, %d known, %d failed" % (len(ids), len(ids) - failed - held, held, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
