#!/usr/bin/env python3 -P
"""Copy the arena importer's settled spawns into a regenerated world.

    tools/sync_world_spawns.py <maps/<id>/<id>.json> <worlds/<id>/<id>.json>

`bsp.py regen` takes spawns straight from the BSP entities; the arena importer (adapters/game-airdrift/bsp_import.py
`settle_spawns`) lowers floating spawns onto the floor, turns wall-facing ones and pads a team to 16. This replaces the world's
`spawns` with that settled list (origin / 52.5 = metres, same axes; classname, targetname and disabled kept from the world
spawn of the same team where one exists), so the world a player loads and what check_spawns tests agree.
"""
import json
import sys

SCALE = 0.01905
CLASS = {"red": "info_player_terrorist", "blue": "info_player_counterterrorist"}


def sync(maps_doc, world_doc):
    src = maps_doc.get("spawns") or []
    if not src:
        return 0
    old = world_doc.get("spawns", [])
    by_team = {}
    for s in old:
        by_team.setdefault(s.get("team"), []).append(s)
    out = []
    used = {}
    for s in src:
        team = s.get("team", "any")
        pool = by_team.get(team) or old[:1]
        i = used.get(team, 0)
        used[team] = i + 1
        base = pool[min(i, len(pool) - 1)] if pool else {}
        out.append({"at": [round(v * SCALE, 4) for v in s["origin"]], "classname": base.get("classname", CLASS.get(team, "info_player_start")),
                    "disabled": base.get("disabled", False) if "disabled" in base else None, "targetname": base.get("targetname", ""),
                    "team": team, "yaw": s.get("yaw", 0.0)})
    for o in out:
        if o["disabled"] is None:
            del o["disabled"]
    world_doc["spawns"] = out
    return len(out)


if __name__ == "__main__":
    m, w = sys.argv[1:3]
    md, wd = json.load(open(m)), json.load(open(w))
    n = sync(md, wd)
    if n:
        json.dump(wd, open(w, "w"), separators=(",", ":"), sort_keys=True)
    print(f"{w}: {n} spawns")
