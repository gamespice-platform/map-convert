#!/usr/bin/env python3
"""Batch GameBanana map fetch for the Control Point stream.

  python3 -P tools/gb_batch.py fetch <mod id>... [--root DIR]

Each mod is downloaded into a fresh <root>/<id>/ (archives untrusted: extraction only, nothing is run),
meta.json records name/author/page/licence, and the BSPs plus loose materials/models are listed in
<root>/<id>/found.json for the convert step.
"""
import argparse, datetime, time, json, os, shutil, subprocess, sys, urllib.request

API = "https://gamebanana.com/apiv11/Mod/%s?_csvProperties=_aFiles,_sName,_aSubmitter,_sLicense"
ROOT = "/home/gamedev/projects/mapsrc/incoming/gb"


def get(url, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "fc-map-batch/1.0"})
    for n in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=180).read()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(5 * (n + 1))


def extract(path, out):
    os.makedirs(out)
    if subprocess.run(["bsdtar", "-xf", path, "-C", out], stderr=subprocess.DEVNULL).returncode:
        subprocess.run(["7z", "x", "-y", "-o" + out, path], stdout=subprocess.DEVNULL)
    # some rars extract as 0-byte files with bsdtar and 7z ("Unsupported Method"); unar reads them
    if any(os.path.getsize(os.path.join(r, n)) == 0 for r, _, fs in os.walk(out) for n in fs):
        subprocess.run(["unar", "-f", "-q", "-o", out, path], stdout=subprocess.DEVNULL)


def fetch(mod, root):
    d = os.path.join(root, str(mod))
    if os.path.exists(d):
        print(mod, "exists, skipping")
        return
    meta = json.loads(get(API % mod))
    os.makedirs(os.path.join(d, "x"))
    info = {"id": int(mod), "name": meta["_sName"], "author": meta["_aSubmitter"]["_sName"],
            "page": "https://gamebanana.com/mods/%s" % mod, "licence_html": meta.get("_sLicense", "")}
    json.dump(info, open(os.path.join(d, "meta.json"), "w"), indent=1)
    for f in meta["_aFiles"]:
        name = os.path.basename(f["_sFile"])
        p = os.path.join(d, name)
        open(p, "wb").write(get(f["_sDownloadUrl"]))
        extract(p, os.path.join(d, "x", name + ".d"))
    bsps, content = [], set()
    for r, _, fs in os.walk(os.path.join(d, "x")):
        for n in fs:
            if n.lower().endswith(".bsp"):
                bsps.append(os.path.join(r, n))
            if n.lower().endswith((".vmt", ".mdl")):
                parts = r.replace("\\", "/").split("/")
                for k in ("materials", "models"):
                    if k in parts:
                        content.add("/".join(parts[:len(parts) - parts[::-1].index(k)]))
    json.dump({"bsps": bsps, "content_roots": sorted(content)}, open(os.path.join(d, "found.json"), "w"), indent=1)
    print(mod, info["name"], "|", info["author"], "|", len(bsps), "bsp", [os.path.basename(b) for b in bsps])




# ---------------------------------------------------------------- convert

CONVERT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # gs-map-convert checkout
IMPORT = os.path.join(CONVERT, "adapters/game-airdrift/bsp_import.py")
READER = "/home/gamedev/godot/game-airdrift/tools"                          # bsp_read.py, which the importer needs
ORIG_ROOT = "/home/gamedev/projects/mapsrc/orig"                            # internal _orig replicas, never in git
CONTACT = "https://github.com/zees-games/fc-dm-maps/issues"
BASE_MODES = ["ffa", "tdm", "gungame"]
CTF_MIN_WALK = 3150.0   # map units: about 60 m, the repo's rule for a capture-the-flag map


def run_import(repo, mapid):
    env = dict(os.environ, PYTHONPATH=READER, GSBSP_PATH=CONVERT)
    r = subprocess.run([sys.executable, "-P", IMPORT, "sources/%s.bsp" % mapid, "maps", "--id", mapid,
                        "--zones-dir", "zones"], cwd=repo, env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("import failed for %s:\n%s" % (mapid, (r.stdout + r.stderr)[-1500:]))
    return json.load(open(os.path.join(repo, "maps", mapid, mapid + ".json")))


def derive(man):
    """(modes, flag_spawns) from an imported manifest: cp when it has control points and both teams spawn,
    ctf when the two team spawn groups are far enough apart."""
    modes = list(BASE_MODES)
    flags = []
    spawns = man.get("spawns", [])
    side = {t: [s for s in spawns if s.get("team") == t] for t in ("red", "blue")}
    pts = man.get("control_points", [])
    if len(pts) >= 2 and side["red"] and side["blue"]:
        modes.append("cp")
    if side["red"] and side["blue"]:
        def centre(t):
            ps = [s["position"] if "position" in s else s["origin"] for s in side[t]]
            return [sum(p[i] for p in ps) / len(ps) for i in range(3)]
        cr, cb = centre("red"), centre("blue")
        if ((cr[0] - cb[0]) ** 2 + (cr[2] - cb[2]) ** 2) ** 0.5 >= CTF_MIN_WALK:
            modes.append("ctf")
            # a flag at the point nearest each team's spawns (godot axes -> map axes: x, -z, y)
            for t, c in (("red", cr), ("blue", cb)):
                src = min(pts, key=lambda p: (p["position"][0] - c[0]) ** 2 + (p["position"][2] - c[2]) ** 2)["position"] if pts else c
                flags.append({"team": t, "origin_src": [src[0], -src[2], src[1]], "yaw_src": 0})
    return modes, flags


def convert(mod, mapid, repo, bsp_name=None, surf=False):
    src = os.path.join(ROOT, str(mod))
    meta = json.load(open(os.path.join(src, "meta.json")))
    found = json.load(open(os.path.join(src, "found.json")))
    bsps = found["bsps"]
    if bsp_name:
        bsps = [b for b in bsps if os.path.basename(b).lower() == bsp_name.lower()]
    if not bsps:
        raise SystemExit("%s: no bsp found" % mod)
    os.makedirs(os.path.join(repo, "sources"), exist_ok=True)
    shutil.copyfile(bsps[0], os.path.join(repo, "sources", mapid + ".bsp"))
    page = meta["page"]
    credit = "%s (GameBanana %s)" % (meta["author"], mod)
    doc = {"id": mapid, "author": credit,
           "attribution": {"author": meta["author"], "source": page, "archive": os.path.basename(bsps[0]),
                           "recorded": datetime.date.today().isoformat()},
           "notes": "Control point map for game-fatal-contact: team spawns become red/blue spawns and control points "
                    "and resupply are kept as markers. Textures and models are free replacements; published as a "
                    "credited community map with a removal offer.",
           "kind": "arena", "movement": "walk", "modes": BASE_MODES}
    if surf:    # a combat surf map: kind arena without a movement key is surfed (FcImportedMaps.movement_of)
        del doc["movement"]
        doc["notes"] = ("Combat surf map for game-fatal-contact (owner's Surf Combat list): the map's own spawns; "
                        "teleports that only a map event enables are not run; textures and models are free "
                        "replacements; published as a credited community map with a removal offer.")
        doc["kind_why"] = "A combat surf map: built to fight on rather than to time. 'arena' marks it for game-fatal-contact's deathmatch."
    zp = os.path.join(repo, "zones", mapid + ".json")
    if os.path.exists(zp):    # keep the per-map rules (conditional_teleports, round_teleports...) a re-run must not lose
        for k, v in json.load(open(zp)).items():
            doc.setdefault(k, v)
    json.dump(doc, open(zp, "w"), indent=1, ensure_ascii=False)
    man = run_import(repo, mapid)
    modes, flags = derive(man)
    if surf:
        modes, flags = list(BASE_MODES), []
    doc["modes"] = modes
    if flags:
        doc["flag_spawns"] = flags
    json.dump(doc, open(zp, "w"), indent=1, ensure_ascii=False)
    man = run_import(repo, mapid)
    # maps.json and licence.json rows (the README credits rows are written by `readme`)
    mp = os.path.join(repo, "maps.json")
    mj = json.load(open(mp))
    mj["maps"] = [m for m in mj["maps"] if m["id"] != mapid] + [{
        "id": mapid, "author": credit, "source": page,
        "licence": "credited-community-map exception, textures and models replaced with free ones",
        "published": True, "modes": modes}]
    json.dump(mj, open(mp, "w"), indent=2, ensure_ascii=False)
    lp = os.path.join(repo, "licence.json")
    lj = json.load(open(lp))
    lj = [e for e in lj if e.get("paths") != ["maps/" + mapid]] + [{
        "paths": ["maps/" + mapid], "licence": "none stated" if surf else "CC-BY-NC-ND-4.0", "exception": "credited-community-map",
        "title": meta["name"], "author": meta["author"], "source_url": page, "removal_contact": CONTACT}]
    json.dump(lj, open(lp, "w"), indent=2, ensure_ascii=False)
    print(mapid, "modes", modes, "points", len(man.get("control_points", [])), "spawns", len(man.get("spawns", [])))


def orig(mod, mapid, repo):
    """Internal unedited replica: regen with the map's own textures and models, outside git."""
    src = os.path.join(ROOT, str(mod))
    found = json.load(open(os.path.join(src, "found.json")))
    stem = mapid.replace("-", "_").lower()
    out = os.path.join(ORIG_ROOT, mapid + "_orig")
    os.makedirs(out, exist_ok=True)
    stores = os.path.join(repo, ".stores")
    if not os.path.isdir(stores):    # a maps repo without the lock-store layout keeps its libraries beside the maps
        stores = repo
    cmd = ["heavy", "--", "timeout", "1800", sys.executable, "-P", os.path.join(CONVERT, "bsp.py"), "regen",
           "arena/" + mapid, "--out", os.path.join(out, mapid + "_orig"),
           "--pbr-store", os.path.join(stores, "pbr-library"), "--model-store", os.path.join(stores, "model-library"),
           "--name", mapid + "_orig", "--orig-textures", "--orig-models"]
    for c in found["content_roots"]:
        cmd += ["--orig-content", c]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(mapid, "_orig exit", r.returncode, (r.stdout + r.stderr)[-300:].replace("\n", " | "))
    return r.returncode


def readme(repo):
    """Modes rows (cp maps) and credits rows for every map in maps.json that the README does not list yet."""
    p = os.path.join(repo, "README.md")
    s = open(p).read()
    names = {"ffa": "free-for-all", "gungame": "gun game", "snipers": "snipers", "tdm": "team deathmatch",
             "cp": "control points", "ctf": "capture the flag"}
    head, credits = s.split("| Map | Author | Source | Licence |\n| --- | --- | --- | --- |\n")
    for m in json.load(open(os.path.join(repo, "maps.json")))["maps"]:
        modes = m.get("modes", [])
        if "cp" in modes and "| `%s` |" % m["id"] not in head:
            row = "| `%s` | %s |\n" % (m["id"], ", ".join(names[x] for x in names if x in modes))
            head = head.replace("| every other map |", row + "| every other map |", 1)
        if "| `%s` |" % m["id"] not in credits:
            author = m["author"].split(" (GameBanana")[0]
            credits = credits.replace("\nIf you made one", "| `%s` | %s | %s | CC BY-NC-ND 4.0 |\n\nIf you made one" % (m["id"], author, m["source"]), 1) \
                if "\n\nIf you made one" not in credits else credits.replace("\n\nIf you made one", "\n| `%s` | %s | %s | CC BY-NC-ND 4.0 |\n\nIf you made one" % (m["id"], author, m["source"]), 1)
    open(p, "w").write(head + "| Map | Author | Source | Licence |\n| --- | --- | --- | --- |\n" + credits)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "convert", "orig", "readme"])
    ap.add_argument("ids", nargs="*", help="fetch: mod ids; convert/orig: <mod id> <map id>; readme: none")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--repo", default="/home/gamedev/godot/fc-dm-maps", help="the fc-dm-maps checkout to write into")
    ap.add_argument("--surf", action="store_true", help="convert: a combat surf map (surfed, not walked; fc-surf-dm-maps)")
    ap.add_argument("--bsp", default=None, help="BSP file name when an archive holds several")
    a = ap.parse_args()
    ROOT = a.root
    os.makedirs(a.root, exist_ok=True)
    if a.cmd == "fetch":
        for m in a.ids:
            try:
                fetch(m, a.root)
            except Exception as err:  # a failed mod must not leave a half directory that a rerun would skip
                shutil.rmtree(os.path.join(a.root, str(m)), ignore_errors=True)
                print(m, "FAILED", err)
    elif a.cmd == "convert":
        convert(a.ids[0], a.ids[1], a.repo, a.bsp, a.surf)
    elif a.cmd == "orig":
        sys.exit(orig(a.ids[0], a.ids[1], a.repo))
    else:
        readme(a.repo)
