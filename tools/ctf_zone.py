#!/usr/bin/env python3
"""Write a map's zones/<id>.json (credit, kind, modes, ctf flag_spawns) from its source BSP.

  python3 -P tools/ctf_zone.py <bsp> --id ctf-x --author A --page URL [--zones-dir zones] [--cp]

Flag layout: an item_teamflag with TeamNum 2/3 is that team's flag (red/blue); neutral ones (TeamNum 0) are
assigned by distance to each team's spawns, nearest to red = red, nearest to blue = blue, the rest dropped.
Modes: ffa, tdm, gungame, snipers always; ctf when two flags came out; cp when the map has control points.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import gsbsp.reader as reader

def vec(s, n=3):
    p = [float(x) for x in (s or "").split()]
    return (p + [0.0] * n)[:n]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("bsp")
    ap.add_argument("--id", required=True); ap.add_argument("--author", required=True); ap.add_argument("--page", required=True)
    ap.add_argument("--zones-dir", default="zones"); ap.add_argument("--note", default="")
    a = ap.parse_args()
    b = reader.Bsp(path=a.bsp)
    b.load()
    ents = b.entities
    spawns = {2: [], 3: []}
    flags, cps = [], 0
    for e in ents:
        c = e.get("classname", "")
        if c == "info_player_teamspawn" and int(e.get("TeamNum", 0) or 0) in spawns:
            spawns[int(e["TeamNum"])].append(vec(e.get("origin")))
        elif c == "item_teamflag":
            flags.append(e)
        elif c in ("team_control_point", "team_control_point_master"):
            cps += c == "team_control_point"
    def centre(ps):
        return [sum(p[i] for p in ps) / len(ps) for i in range(3)] if ps else None
    cen = {t: centre(p) for t, p in spawns.items()}
    def d2(p, c):
        return sum((p[i] - c[i]) ** 2 for i in range(3)) if c else 1e18
    out = {}
    for e in flags:
        o = vec(e.get("origin")); team = int(e.get("TeamNum", 0) or 0)
        if team not in (2, 3):
            team = 2 if d2(o, cen[2]) < d2(o, cen[3]) else 3
            score = min(d2(o, cen[2]), d2(o, cen[3]))
        else:
            score = 0
        name = "red" if team == 2 else "blue"
        if name not in out or score < out[name][0]:
            out[name] = (score, {"team": name, "origin_src": o, "yaw_src": vec(e.get("angles"))[1]})
    spawn_flags = [out[t][1] for t in ("red", "blue") if t in out]
    modes = ["ffa", "gungame", "snipers", "tdm"]
    if len(spawn_flags) == 2: modes.append("ctf")
    if cps >= 2: modes.append("cp")
    z = {"id": a.id,
         "author": a.author,
         "attribution": {"author": a.author, "source": a.page, "archive": os.path.basename(a.bsp), "recorded": "2026-11-28"},
         "notes": a.note or "Team fortress community map for game-fatal-contact: team spawns become red/blue spawns, flags and capture zones become the capture-the-flag layout. Textures and models are free replacements; published as a credited community map with a removal offer.",
         "kind": "arena", "kind_why": "A team map played as deathmatch, team deathmatch and capture the flag: built to fight on rather than to time.",
         "movement": "walk", "modes": modes}
    if spawn_flags: z["flag_spawns"] = spawn_flags
    os.makedirs(a.zones_dir, exist_ok=True)
    json.dump(z, open(os.path.join(a.zones_dir, a.id + ".json"), "w"), indent=1); print(a.id, modes, "red/blue spawns", len(spawns[2]), len(spawns[3]), "cp", cps)

main()
