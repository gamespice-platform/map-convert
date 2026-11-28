#!/usr/bin/env python3 -P
"""Turn a world's spawns that face a nearby wall toward the most open direction.

    tools/face_world_spawns.py <worlds/<id>/<id>.json> [--near 4.0] [--check]

`bsp.py regen` copies each spawn's yaw from the BSP entity; a map whose spawns carry no angle (every yaw 0 in Source, -90
here) drops players with their nose in a wall. This reads the world's own solid hulls (no source BSP needed), and for each
spawn whose straight-ahead clearance at eye height is under --near metres tries 16 yaws and keeps the one with the longest
clearance (only when it is at least 1.5 times better). Rewrites the json in place; --check only reports, exit 1 if any
spawn would turn. Axes and units as the manifest: Godot, metres, yaw degrees about +y, 0 looks down -z.
"""
import argparse
import gzip
import json
import math
import struct
import sys
from pathlib import Path

EYE, MAXD, STEP = 1.22, 20.0, 0.25


class Solids:
    def __init__(self, doc, blob):
        self.hulls = []
        for h in doc.get("hulls", []):
            if h.get("kind") != "solid" or h.get("entity") is not None:
                continue
            pts = struct.unpack_from("<%df" % (3 * h["point_count"]), blob, h["point_offset"])
            xs, ys, zs = pts[0::3], pts[1::3], pts[2::3]
            pl = struct.unpack_from("<%df" % (4 * h["plane_count"]), blob, h["plane_offset"])
            self.hulls.append(((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)),
                               [pl[i:i + 4] for i in range(0, len(pl), 4)]))
        self.cell = {}
        for i, (lo, hi, _) in enumerate(self.hulls):
            for cx in range(int(lo[0] // 8), int(hi[0] // 8) + 1):
                for cz in range(int(lo[2] // 8), int(hi[2] // 8) + 1):
                    self.cell.setdefault((cx, cz), []).append(i)

    def solid(self, p):
        for i in self.cell.get((int(p[0] // 8), int(p[2] // 8)), ()):
            lo, hi, pl = self.hulls[i]
            if all(lo[a] <= p[a] <= hi[a] for a in range(3)) and all(
                    q[0] * p[0] + q[1] * p[1] + q[2] * p[2] - q[3] <= 0 for q in pl):
                return True
        return False

    def clearance(self, at, yaw):
        r = math.radians(yaw)
        f = (-math.sin(r), -math.cos(r))
        d = STEP
        while d <= MAXD:
            if self.solid((at[0] + f[0] * d, at[1] + EYE, at[2] + f[1] * d)):
                return d
            d += STEP
        return MAXD


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("world")
    ap.add_argument("--near", type=float, default=4.0)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    path = Path(a.world)
    doc = json.loads(path.read_text())
    solids = Solids(doc, gzip.decompress((path.parent / doc["bin"]["file"]).read_bytes()))
    turned = 0
    for s in doc.get("spawns", []):
        cur = solids.clearance(s["at"], s["yaw"])
        if cur >= a.near:
            continue
        best = max(((solids.clearance(s["at"], y), y) for y in (k * 22.5 - 180.0 for k in range(16))))
        if best[0] >= cur * 1.5:
            s["yaw"] = best[1]
            turned += 1
    print("%s: %d of %d spawns turned toward open space" % (path.stem, turned, len(doc.get("spawns", []))))
    if turned and not a.check:
        path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")))
    return 1 if (turned and a.check) else 0


if __name__ == "__main__":
    sys.exit(main())
