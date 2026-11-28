#!/usr/bin/env python3
"""Every map of a combat maps repository hosts free-for-all, team deathmatch and gun game, and its README says which else.

    tools/check_modes.py                 check every map and that the README modes table is current (what CI runs)
    tools/check_modes.py --write         rewrite the README modes table from zones/<id>.json
    tools/check_modes.py -v              also list the maps held by tools/modes_known.json

A map fails when it has no zones/<id>.json, when its `modes` (and the delivered manifest's, where maps/ is committed) miss ffa, tdm or gungame, or when its world manifest cannot give two
teams of --min-team spawns: its own red and blue tags count, otherwise the spawns are cut by position (gsbsp/teams.py, the cut the
game makes at run time). The importer writes the three modes into every arena manifest by default (bsp_import.py), so a zones file
lists them too (and what it adds: cp, ctf, snipers). Failures not fixed yet are held in tools/modes_known.json as {id: reason} and a held
map that now passes fails the run, so the file only shrinks. The README table sits between the `<!-- modes:start -->` and
`<!-- modes:end -->` lines, one row per set of modes. Each repository's tools/check_modes.py launches this like check_spawns.py.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from gsbsp import teams  # noqa: E402

NAMES = {"ffa": "free-for-all", "tdm": "team deathmatch", "gungame": "gun game", "snipers": "snipers",
         "cp": "control points", "ctf": "capture the flag"}
ORDER = ("ffa", "gungame", "snipers", "tdm", "cp", "ctf")
START, END = "<!-- modes:start -->", "<!-- modes:end -->"


def load(path):
    return json.loads(Path(path).read_text())


def map_ids(root):
    ids = {p.stem for p in (root / "zones").glob("*.json")} if (root / "zones").is_dir() else set()
    if (root / "maps.json").is_file():
        ids |= {e["id"] for e in load(root / "maps.json")["maps"]}
    return sorted(ids)


def problems(root, mid, min_team):
    out = []
    zone = root / "zones" / (mid + ".json")
    if not zone.is_file():
        return ["no zones/%s.json (the importer would not know it is a combat map)" % mid]
    modes = load(zone).get("modes") or []
    out += ["modes miss %s" % m for m in teams.REQUIRED_MODES if m not in modes]
    man = root / "maps" / mid / (mid + ".json")
    if man.is_file():
        have = load(man).get("modes") or []
        out += ["delivered manifest modes miss %s" % m for m in teams.REQUIRED_MODES if m not in have]
    world = root / "worlds" / mid / (mid + ".json")
    if world.is_file():
        spawns = load(world).get("spawns") or []
        live = [s for s in spawns if not s.get("disabled")]
        have = {t: sum(1 for s in live if s.get("team") == t) for t in ("red", "blue")}
        if not all(n >= min_team for n in have.values()):
            sides = teams.split_sides([s["at"] for s in live])
            have = {t: sides.count(t) for t in ("red", "blue")}
        for t, n in have.items():
            if n < min_team:
                out.append("%s has %d spawns (needs %d)" % (t, n, min_team))
    return out


def modes_table(root, ids):
    groups = {}
    for mid in ids:
        zone = root / "zones" / (mid + ".json")
        modes = tuple(sorted(set(load(zone).get("modes") or []), key=lambda m: ORDER.index(m) if m in ORDER else 99)) if zone.is_file() else ()
        groups.setdefault(modes, []).append(mid)
    base = max(groups, key=lambda k: len(groups[k]))
    rows = ["| Maps | Modes |", "| --- | --- |"]
    for modes in sorted(groups, key=lambda k: (k != base, len(k), k)):
        label = ", ".join(NAMES.get(m, m) for m in modes) or "none listed"
        who = groups[modes]
        names = "every other map (%d)" % len(who) if modes == base and len(groups) > 1 else (
            "every map (%d)" % len(who) if len(groups) == 1 else ", ".join("`%s`" % i for i in who))
        rows.append("| %s | %s |" % (names, label))
    return "\n".join([START, "<!-- written by tools/check_modes.py --write; edit zones/<id>.json instead -->", ""] + rows + ["", END])


def readme_state(root, ids):
    path = root / "README.md"
    text = path.read_text()
    want = modes_table(root, ids)
    if START in text and END in text:
        a, b = text.index(START), text.index(END) + len(END)
        return path, text[:a] + want + text[b:], text
    return path, None, text


def main(argv=None, root=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite the README modes table")
    ap.add_argument("--min-team", type=int, default=teams.MIN_TEAM)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    root = Path(root or ".").resolve()
    ids = map_ids(root)
    known_path = root / "tools" / "modes_known.json"
    known = load(known_path) if known_path.is_file() else {}
    failed = held = 0
    for mid in ids:
        found = problems(root, mid, a.min_team)
        if mid in known:
            if found:
                held += 1
                if a.v:
                    print("known %s: %s (%s)" % (mid, "; ".join(found), known[mid]))
            else:
                failed += 1
                print("FAIL %s: now passes, remove it from tools/modes_known.json" % mid)
        elif found:
            failed += 1
            print("FAIL %s: %s" % (mid, "; ".join(found)))
    for mid in sorted(set(known) - set(ids)):
        failed += 1
        print("FAIL %s: in tools/modes_known.json but not a map" % mid)
    path, new, old = readme_state(root, [m for m in ids])
    if new is None:
        failed += 1
        print("FAIL README.md: no %s ... %s block for the modes table" % (START, END))
    elif new != old:
        if a.write:
            path.write_text(new)
            print("README.md modes table written")
        else:
            failed += 1
            print("FAIL README.md: modes table is out of date (run tools/check_modes.py --write)")
    print("check_modes: %d maps, %d ok, %d known, %d failed" % (len(ids), len(ids) - failed - held if failed < len(ids) else 0, held, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
