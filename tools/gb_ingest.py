#!/usr/bin/env python3
"""Download a GameBanana mod and extract it into a fresh incoming/gb/<id>/ directory.

  python3 -P tools/gb_ingest.py <mod id>... [--root /home/gamedev/projects/mapsrc/incoming/gb]

Writes <root>/<id>/meta.json (name, author, page url, licence text) and <root>/<id>/x/ (the archive contents), and prints the BSPs found.
Archives are untrusted: extraction is 7z into the new directory only; nothing is run from it.
"""
import argparse, json, os, subprocess, sys, urllib.request

API = "https://gamebanana.com/apiv11/Mod/%s?_csvProperties=_aFiles,_sName,_aSubmitter,_sLicense,_sProfileUrl"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gs-map-convert-ingest"})
    return urllib.request.urlopen(req, timeout=120).read()

def ingest(mod, root):
    d = os.path.join(root, str(mod))
    if os.path.exists(d):
        print(mod, "exists, skipping"); return
    meta = json.loads(get(API % mod))
    os.makedirs(os.path.join(d, "x"))
    info = {"id": mod, "name": meta["_sName"], "author": meta["_aSubmitter"]["_sName"],
            "page": "https://gamebanana.com/mods/%s" % mod, "licence_html": meta.get("_sLicense", "")}
    json.dump(info, open(os.path.join(d, "meta.json"), "w"), indent=1)
    for f in meta["_aFiles"]:
        name = os.path.basename(f["_sFile"])
        p = os.path.join(d, name)
        open(p, "wb").write(get(f["_sDownloadUrl"]))
        out = os.path.join(d, "x", name + ".d")
        os.makedirs(out)
        # bsdtar reads every RAR variant the 7z build here refuses; 7z covers zip/7z/gma-less cases.
        if subprocess.run(["bsdtar", "-xf", p, "-C", out], stderr=subprocess.DEVNULL).returncode:
            subprocess.run(["7z", "x", "-y", "-o" + out, p], stdout=subprocess.DEVNULL)
    for r, _, fs in os.walk(os.path.join(d, "x")):
        for n in fs:
            if n.lower().endswith(".bsp"):
                print(mod, info["name"], info["author"], os.path.join(r, n))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("ids", nargs="+")
    ap.add_argument("--root", default="/home/gamedev/projects/mapsrc/incoming/gb")
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    for m in a.ids: ingest(m, a.root)
