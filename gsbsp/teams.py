"""Every combat map hosts free-for-all, team deathmatch and gun game; this is how a map with no sides gets them.

`split_sides` gives each spawn of a map whose mapper tagged none a side: the two farthest-apart spawns seed an axis,
every spawn is ranked along it and the first half is red, the second blue. Opposite ends of the map start on opposite
sides, so a team is never spawned beside the other. It is deterministic, depends on positions only (not on units) and
is the one rule the importer and `tools/check_modes.py` share.
"""
import math

REQUIRED_MODES = ("ffa", "tdm", "gungame")
# Fewest spawns a side may have before its team spawns on top of itself (check_spawns' --min-team).
MIN_TEAM = 4


def merge_modes(listed):
    """The modes a map hosts: what its zones file lists, with every required mode added after it."""
    out = list(listed or [])
    out += [m for m in REQUIRED_MODES if m not in out]
    return out


def split_sides(points):
    """Sides ("red", "blue" or "" for a shared middle spawn) for [x, y, z] spawn positions, in the order given.

    The same cut as game-fatal-contact's `FcMapImported.split_spawns_for_teams`, so the tags written here are the ones the
    game derived at run time: the first anchor is the spawn furthest from the centroid, the second the furthest from the
    first, spawns are ranked by distance to the first minus distance to the second and the list is split at the median.
    """
    n = len(points)
    if n < 2:
        return [""] * n
    mean = [sum(p[a] for p in points) / n for a in range(3)]
    first = 0
    for i in range(n):
        if math.dist(points[i], mean) ** 2 > math.dist(points[first], mean) ** 2 + 0.0001:
            first = i
    second = 0 if first != 0 else 1
    for i in range(n):
        if math.dist(points[i], points[first]) ** 2 > math.dist(points[second], points[first]) ** 2 + 0.0001:
            second = i
    order = sorted(range(n), key=lambda i: (math.dist(points[i], points[first]) - math.dist(points[i], points[second]), i))
    sides = [""] * n
    half = n // 2
    for rank, i in enumerate(order):
        if rank < half:
            sides[i] = "red"
        elif rank >= n - half:
            sides[i] = "blue"
    return sides
