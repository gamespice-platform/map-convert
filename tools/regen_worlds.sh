#!/bin/bash
# Store each map's source .bsp and rebuild its world for a converted-maps repository.
#   [SRC=dir] [GAME=arena] tools/regen_worlds.sh <maps repo> [map ids...]
# Credit comes from <maps repo>/maps.json (id, author, source) or else maps/<id>/licence.json.
# A map with a <maps repo>/rules/<id>/ directory (textures.tsv, free_textures.tsv ...) gets it as its map tier (--map-rules).
# An existing world keeps its spawns, skin_materials, surfaces and texture licence; props and model rows are rebuilt (tools/keep_world_fields.py).
# Run the arena import first when maps/<id>/<id>.json exists: its settled spawns replace the world's (tools/sync_world_spawns.py).
# Default ids: every maps/<id>. Writes worlds/<id>/<id>.*; art stores are <repo>/.stores/{pbr,model}-library when
# .stores exists (the GameSpice Bootstrap lock-store layout the committed manifests point at), else <repo>/{pbr,model}-library.
set -u
# HEAVY= (empty) runs the regen unqueued, for a box without heavy (gpu.sh py).
HERE="$(cd "$(dirname "$0")" && pwd)"
BSP="${GSBSP_PATH:-$HERE/..}/bsp.py"
ROOT="$(cd "${1:?usage: regen_worlds.sh <maps repo> [ids...]}" && pwd)"; shift
SRC="${SRC:-$ROOT/sources}"; GAME="${GAME:-arena}"
STORES="$ROOT"; [ -d "$ROOT/.stores" ] && STORES="$ROOT/.stores"
ids=("$@"); [ ${#ids[@]} -eq 0 ] && ids=($(ls "$ROOT/maps"))
rc=0
for m in "${ids[@]}"; do
    # A map id is hyphenated (cp-orange-x3) while its source BSP may keep the underscores (cp_orange_x3.bsp).
    f="$(find "$SRC/" -maxdepth 2 \( -iname "*$m.bsp" -o -iname "*${m//-/_}.bsp" \) | head -1)"
    # No source file named for the id: the lossless store may already hold it as <game>/<id> (a map stored once, e.g. from a versioned archive name). store_alias.py prefers the hashed <game>/<id>~<hash> entry to the bare alias and refuses an entry whose source is no BSP.
    entry=""
    if [ -z "$f" ]; then
        entry="$(python3 -P "$HERE/store_alias.py" "${GSBSP_STORE:-$HOME/mapsrc/store}" "$GAME/$m")"
        [ -z "$entry" ] && { echo "$m NO SOURCE"; rc=1; continue; }
    fi
    read -r author page < <(python3 -P -c 'import json,sys
r,m=sys.argv[1:3]
try:
    for e in json.load(open(r+"/maps.json"))["maps"]:
        if e["id"]==m: print(e.get("author","unknown").replace(" ","_"), e.get("source","-").replace(" ","_")); sys.exit()
except Exception: pass
try:
    for e in json.load(open(r+"/maps/"+m+"/licence.json")):
        if e.get("author") and e.get("source_url"): print(e["author"].replace(" ","_"), e["source_url"]); sys.exit()
except Exception: pass
print("unknown -")' "$ROOT" "$m")
    # The regen below names the entry by the file's hash, not <game>/<name>: a second, different file of the same name (a cut-off first extraction) keeps the name in the store and made a whole map convert empty.
    [ -n "$f" ] && python3 -P "$BSP" store "$f" --game "$GAME" --author "${author//_/ }" --page "${page//_/ }" --licence "none stated" --no-share-check "credited with removal on request" > /dev/null 2>&1
    mkdir -p "$ROOT/worlds/$m"
    # A regen rebuilds spawns, skin materials, surfaces and texture credit from raw BSP and the current rules; an existing world keeps its own.
    keep=""; [ -f "$ROOT/worlds/$m/$m.json" ] && { keep="${TMPDIR:-/tmp}/keep-$m.json"; cp "$ROOT/worlds/$m/$m.json" "$keep"; }
    ${HEAVY-heavy --} timeout 1800 python3 -P "$BSP" regen "${entry:-$(sha256sum "$f" | cut -c1-16)}" --out "$ROOT/worlds/$m/$m" --pbr-store "$STORES/pbr-library" --model-store "$STORES/model-library" $([ -f "$ROOT/maps/$m/$m.json" ] && echo --tier-manifest "$ROOT/maps/$m/$m.json") $([ -d "$ROOT/rules/$m" ] && echo --map-rules "$ROOT/rules/$m") > "${TMPDIR:-/tmp}/regen-$m.log" 2>&1 < /dev/null
    r=$?; [ $r -ne 0 ] && rc=1
    # the world's spawns are the arena importer's settled ones (on the floor, facing open space, 16 a team), not the raw BSP entities
    [ $r -eq 0 ] && [ -f "$ROOT/maps/$m/$m.json" ] && python3 -P "$HERE/sync_world_spawns.py" "$ROOT/maps/$m/$m.json" "$ROOT/worlds/$m/$m.json" > /dev/null
    [ -n "$keep" ] && { [ $r -eq 0 ] && python3 -P "$HERE/keep_world_fields.py" "$keep" "$ROOT/worlds/$m/$m.json" > /dev/null; rm -f "$keep"; }
    echo "$m exit $r"
done
exit $rc
