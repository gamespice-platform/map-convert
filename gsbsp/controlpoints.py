"""Control points of a map, for the shared control point mode: id, position, radius, order, owner.

One reader for both converter paths. `points()` is what `regen` writes as the world manifest's
`control_points` (metres, Godot axes, like the manifest's spawns); `orient_points` is also what the
arena importer calls. Sources are the BSP's own logic: `team_control_point` (its `point_index`, default
owner, the round's `cpr_cp_names` order) and `dod_control_point` (entity order, `point_default_owner`),
each sized by the `trigger_capture_area` / `dod_capture_area` that names it in `area_cap_point`. A
capture area that names no point entity becomes a point at the middle of its box.
"""
import math

from . import reader, units

# (class, TeamNum) to the FC team tag: TeamNum 2 is the first side and 3 the second.
TEAMSPAWN_TEAMS = {"2": "red", "3": "blue"}
SPAWN_SIDES = {"info_player_terrorist": "red", "info_player_counterterrorist": "blue",
               "info_player_axis": "red", "info_player_allies": "blue"}
DOD_OWNERS = {"1": "blue", "2": "red"}   # dod_control_point point_default_owner: 1 Allies, 2 Axis, 0 neutral
POINT_CLASSES = ("team_control_point", "dod_control_point")
AREA_CLASSES = ("trigger_capture_area", "dod_capture_area")
DEFAULT_CAPTURE_RADIUS = 192.0  # map units, when a point has no capture area
SNAP_RADIUS = 384.0             # a point with no floor under it moves to the nearest standable floor within this many map units sideways
SNAP_DOWN = 96.0                # a floor this far below the point (or less) counts as the point's own floor
SNAP_UP = 24.0                  # ... and one this far above it (a marker sunk into the floor)
MIN_CAPTURE_RADIUS = 96.0       # a capture trigger's own box can be a post (some maps measure 6 to 40): too small to stand in


def orient_points(points, spawns, by_axis=False):
    """Number the points from red's end to blue's, as the control point mode expects (red takes the
    low orders, docs/control-points.md of game-fatal-contact). The map's own order is the entity order (Day of Defeat: Source) or its master's
    list, and either runs from whichever end the mapper started at, so a map where the blue
    spawns are nearest a higher order than the red spawns has its order reversed. Maps without
    spawns of both teams keep the order they have. `by_axis` (Day of Defeat: Source, whose order is
    only the entity order) numbers the points along the line from the red spawns to the blue ones.
    Points have `position` and spawns `origin` (+ `team`) in Godot axes."""
    team = {t: [s["origin"] for s in spawns if s.get("team") == t] for t in ("red", "blue")}
    if len(points) < 2 or not team["red"] or not team["blue"]:
        return

    if by_axis:
        # The map's default owner says which side starts with the point; where most owned points sit
        # nearer the other side's spawns the owner numbers are the other way round from the spawn
        # classes (24 of 29 owned points on the 25 Day of Defeat: Source maps), so they are swapped.
        near = lambda p, t: min(math.hypot(o[0] - p["position"][0], o[2] - p["position"][2]) for o in team[t])
        owned = [p for p in points if p.get("owner") in team]
        own = sum(1 for p in owned if near(p, p["owner"]) <= near(p, "blue" if p["owner"] == "red" else "red"))
        if own * 2 < len(owned):
            for p in owned:
                p["owner"] = "blue" if p["owner"] == "red" else "red"
        b = [sum(o[i] for o in team["blue"]) / len(team["blue"]) for i in (0, 2)]
        r = [sum(o[i] for o in team["red"]) / len(team["red"]) for i in (0, 2)]
        along = lambda p: (p["position"][0] - r[0]) * (b[0] - r[0]) + (p["position"][2] - r[1]) * (b[1] - r[1])
        for rank, p in enumerate(sorted(points, key=along)):
            p["order"] = rank
        fit_owners(points)
        return

    def nearest(t):
        return min(points, key=lambda p: min(math.hypot(o[0] - p["position"][0], o[2] - p["position"][2]) for o in team[t]))

    red, blue = nearest("red"), nearest("blue")
    if blue is not red and red["order"] > blue["order"]:
        top = max(p["order"] for p in points)
        low = min(p["order"] for p in points)
        for p in points:
            p["order"] = top + low - p["order"]
    fit_owners(points)


def fit_owners(points):
    """Make the owners fit the line, which runs from red's end (lowest order) to blue's: the control point mode
    starts red on the first point and blue on the last, so neither may own the far end. A map whose owners sit the
    other way round (the team numbers of its entities against its spawns; blue's points at the low orders) has
    them swapped, and an attack/defend map that gives one team every point has the last point of the line it
    cannot hold left neutral."""
    line = sorted(points, key=lambda p: p["order"])
    n = len(line)
    if n < 2:
        return
    pos = {id(p): i / (n - 1) for i, p in enumerate(line)}
    mean = {t: [pos[id(p)] for p in line if p.get("owner") == t] for t in ("red", "blue")}
    mean = {t: sum(v) / len(v) for t, v in mean.items() if v}
    if len(mean) == 2:
        flip = mean["red"] > mean["blue"]
    elif mean:
        (t, m), = mean.items()
        flip = m > 0.5 if t == "red" else m < 0.5
    else:
        return
    if flip:
        for p in points:
            if p.get("owner") in ("red", "blue"):
                p["owner"] = "blue" if p["owner"] == "red" else "red"
    if line[0].get("owner") == "blue":
        line[0]["owner"] = ""
    if line[-1].get("owner") == "red":
        line[-1]["owner"] = ""


def team_spawns(bsp, scale=units.VISUAL, y0=0.0):
    """The map's two-sided player spawns, {origin (Godot axes, metres), team}: `info_player_teamspawn` by
    TeamNum and the terrorist/counter-terrorist and axis/allies classes. A spawn the map starts disabled is left out,
    unless that would leave a team with none (attack/defend maps such as Gold Rush enable one side's spawns by
    stage logic; the disabled ones still say where that side starts)."""
    on, off = [], []
    for e in bsp.entities:
        c = e.get("classname", "")
        side = TEAMSPAWN_TEAMS.get(str(e.get("TeamNum", "")).strip()) if c == "info_player_teamspawn" else SPAWN_SIDES.get(c)
        if side is None:
            continue
        spawn = {"origin": _at(reader.entity_vec(e), scale, y0), "team": side}
        (off if str(e.get("StartDisabled", "0")).strip() == "1" else on).append(spawn)
    have = {s["team"] for s in on}
    return on + [s for s in off if s["team"] not in have]


def _at(p, scale, y0):
    return [round(p[0] * scale, 4), round(p[2] * scale - y0, 4), round(-p[1] * scale, 4)]


def _area_boxes(bsp):
    """area_cap_point -> (radius, centre) in map units, from the capture area's brush box."""
    out = {}
    for e in bsp.entities:
        model = e.get("model", "")
        if e.get("classname") not in AREA_CLASSES or not e.get("area_cap_point") or not model.startswith("*"):
            continue
        try:
            lo, hi = bsp.model_bounds(int(model[1:]))
        except (ValueError, IndexError):
            continue
        o = reader.entity_vec(e)
        lo, hi = [lo[i] + o[i] for i in range(3)], [hi[i] + o[i] for i in range(3)]
        out.setdefault(e["area_cap_point"], (max(hi[0] - lo[0], hi[1] - lo[1]) / 2.0, [(lo[i] + hi[i]) / 2.0 for i in range(3)]))
    return out


def snap_to_floor(bsp, found):
    """`found` is [(target, index, name, owner, origin in map units)]: a point whose origin floats in a pit, sits in a wall or
    hangs over nothing is moved to the nearest standable floor within SNAP_RADIUS (by construction, so the point is always
    one a player can stand on); points that already have a floor under them are left where the mapper put them."""
    from . import audit
    tops = audit.floors(bsp)
    cells = {}
    for (x, y, z), *_ in tops:
        cells.setdefault((int(x // 64), int(y // 64)), []).append((x, y, z))

    def near(x, y, r):
        reach = int(r // 64) + 1
        for cx in range(int(x // 64) - reach, int(x // 64) + reach + 1):
            for cy in range(int(y // 64) - reach, int(y // 64) + reach + 1):
                for t in cells.get((cx, cy), ()):
                    d = math.hypot(t[0] - x, t[1] - y)
                    if d <= r:
                        yield d, t

    out = []
    for target, index, name, owner, pos in found:
        x, y, z = pos
        if any(-SNAP_DOWN <= t[2] - z <= SNAP_UP for d, t in near(x, y, audit.GRID)):
            out.append((target, index, name, owner, pos))
            continue
        best = min(near(x, y, SNAP_RADIUS), key=lambda dt: dt[0] + abs(dt[1][2] - z), default=None)
        out.append((target, index, name, owner, list(best[1]) if best else pos))
    return out


def points(bsp, spawns=None, scale=units.VISUAL, y0=0.0, snap=None):
    """The map's control points, ordered from red's end: [{id, index, name, owner, position, origin, radius, order}], metres in
    Godot axes (`radius` too: at least MIN_CAPTURE_RADIUS map units). `spawns` is `team_spawns` by default."""
    areas = _area_boxes(bsp)
    found = []
    dod = False
    for e in bsp.entities:
        c = e.get("classname")
        if c not in POINT_CLASSES or "origin" not in e:
            continue
        if c == "dod_control_point":
            dod = True
            owner = DOD_OWNERS.get(str(e.get("point_default_owner", "")).strip(), "")
            index, name = len(found), e.get("point_printname") or e.get("point_name", "")
        else:
            owner = TEAMSPAWN_TEAMS.get(str(e.get("point_default_owner", "")).strip(), "")
            try:
                index = int(float(e.get("point_index", 0) or 0))
            except ValueError:
                index = len(found)
            name = e.get("point_printname", "")
        found.append((e.get("targetname", ""), index, name, owner, reader.entity_vec(e)))
    # a capture area that names no point entity is the point (area order)
    if snap is None:
        snap = hasattr(bsp, "brushes")
    if snap and found:
        found = snap_to_floor(bsp, found)
    named = {t for t, *_ in found}
    for target, (_r, centre) in areas.items():
        if target not in named:
            found.append((target, len(found), target, "", centre))
    listed = []
    for e in bsp.entities:
        if e.get("classname") == "team_control_point_round" and e.get("cpr_cp_names"):
            listed = e["cpr_cp_names"].split()
            break
    out = []
    for target, index, name, owner, pos in found:
        at = _at(pos, scale, y0)
        radius = max(areas.get(target, (DEFAULT_CAPTURE_RADIUS,))[0], MIN_CAPTURE_RADIUS)
        out.append({"id": index, "index": index, "name": name, "owner": owner, "position": at, "origin": list(at),
                    "radius": round(radius * scale, 4), "order": listed.index(target) if target in listed else index})
    if len({p["id"] for p in out}) < len(out):   # an index two entities share: entity order instead
        for n, p in enumerate(out):
            p["id"] = p["index"] = p["order"] = n
    orient_points(out, team_spawns(bsp, scale, y0) if spawns is None else spawns, by_axis=not listed and dod)
    out.sort(key=lambda p: (p["order"], p["index"]))
    for rank, p in enumerate(out):   # orders from several rounds' lists and indices leave gaps: rank them
        p["order"] = rank
    return out
