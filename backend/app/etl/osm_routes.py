"""Accra's trotro routes, from OpenStreetMap.

Accra's trotro network is mapped in OSM as public-transport routes: one
relation per direction, listing the roads it drives and its stops, tagged with
the union branch that runs it. `build` fetches them once, joins each relation's
road pieces into one line, keeps one direction per pair of termini, and writes
`data/trotro_routes.geojson`, which is committed. Seeding loads that file, so a
deploy never waits on Overpass, which is often too busy to answer.

    python -m app.etl.osm_routes build                    # fetch from Overpass
    python -m app.etl.osm_routes build --from saved.json  # a saved Overpass answer

Route data (c) OpenStreetMap contributors, under the ODbL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import time
from collections import defaultdict
from pathlib import Path

import httpx
from shapely.geometry import LineString
from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.etl.osm_terrain import OVERPASS, UA
from app.models import AlertSubscription, RouteAlert, TrotroRoute

log = logging.getLogger("etl.osm_routes")

BUNDLE = Path(__file__).resolve().parents[2] / "data" / "trotro_routes.geojson"

# The main Overpass server is often at capacity; these mirrors carry the same data.
MIRRORS = (
    OVERPASS,
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# Every route relation in the region, then each road they use, once. Asking for
# the relations' geometry directly repeats a shared trunk road in every route
# that drives it: more than the mirrors will send before timing out.
QUERY = """
[out:json][timeout:300];
area["name"="Greater Accra Region"]->.a;
relation["route"~"^(bus|minibus|share_taxi)$"](area.a)->.r;
.r out body;
way(r.r);
out geom;
"""

# About 5 m: nothing you can see on a street map, and far fewer points to send.
SIMPLIFY_DEG = 0.00005

# A few relations have a road piece missing. OSRM, a free router over the
# same OSM roads, gives the drivable way between the two loose ends. Build
# time only.
OSRM = "https://router.project-osrm.org/route/v1/driving/"
FILL_FROM_M = 50
# A gap we can't fill and is longer than this would be a straight line through
# houses: leave that route out rather than draw it wrong.
MAX_GAP_M = 300

# (node id, lng, lat)
Node = tuple[int, float, float]


def is_trotro(tags: dict) -> bool:
    """Trotro lines, not the few city bus services mapped alongside them."""
    return (tags.get("network") == "trô trô"
            or tags.get("name", "").lower().startswith("trotro"))


def _metres(a: Node, b: Node) -> float:
    lat = math.radians((a[2] + b[2]) / 2)
    dx = math.radians(b[1] - a[1]) * math.cos(lat)
    dy = math.radians(b[2] - a[2])
    return 6_371_000 * math.hypot(dx, dy)


def _pieces(rel: dict, ways: dict[int, dict]) -> list[list[Node]]:
    """The roads a relation drives, in order; stops and platforms left out."""
    out = []
    for m in rel.get("members", []):
        if m["type"] != "way" or m.get("role", "") not in ("", "forward", "backward"):
            continue
        w = ways.get(m["ref"])
        if w and len(w.get("nodes", [])) >= 2:
            out.append([(n, g["lon"], g["lat"])
                        for n, g in zip(w["nodes"], w["geometry"], strict=True)])
    return out


def _arc(ring: list[Node], start: int, end_ids: set[int]) -> list[Node]:
    """Round a closed way (a roundabout) in its own direction, from the node we
    entered at to the first node the next road leaves from."""
    nodes = ring[:-1]  # first and last are the same node
    ids = [n[0] for n in nodes]
    i = ids.index(start)
    arc = [nodes[i]]
    for k in range(1, len(nodes)):
        node = nodes[(i + k) % len(nodes)]
        arc.append(node)
        if node[0] in end_ids:
            return arc
    return [nodes[i]]  # the next road doesn't touch it: pass straight through


def stitch(pieces: list[list[Node]]) -> tuple[list[Node], list[tuple[int, float]]]:
    """Join a route's road pieces, in member order, into one path.

    Returns the path and its gaps: where it had to jump between pieces that
    don't meet, as (index of the node landed on, metres). Empty for a clean
    relation."""
    if not pieces:
        return [], []
    first = pieces[0]
    if len(pieces) > 1:
        # Point the first road at the second.
        ends = {pieces[1][0][0], pieces[1][-1][0]}
        if first[0][0] in ends and first[-1][0] not in ends:
            first = first[::-1]
    path: list[Node] = list(first)
    gaps: list[tuple[int, float]] = []
    for k, piece in enumerate(pieces[1:], start=1):
        end = path[-1][0]
        ids = {n[0] for n in piece}
        if piece[0][0] == piece[-1][0] and end in ids:
            after = pieces[k + 1] if k + 1 < len(pieces) else []
            path += _arc(piece, end, {n[0] for n in after})[1:]
            continue
        if piece[0][0] == end:
            path += piece[1:]
        elif piece[-1][0] == end:
            path += piece[::-1][1:]
        elif len(path) == len(first) and path[0][0] in (piece[0][0], piece[-1][0]):
            # We guessed the first road's direction wrong: turn it round.
            path.reverse()
            path += piece[1:] if piece[0][0] == path[-1][0] else piece[::-1][1:]
        else:
            flip = _metres(path[-1], piece[-1]) < _metres(path[-1], piece[0])
            near = piece[::-1] if flip else piece
            gaps.append((len(path), _metres(path[-1], near[0])))
            path += near
    return path, gaps


LngLat = tuple[float, float]


def road_between(a: LngLat, b: LngLat) -> list[LngLat] | None:
    """The drivable way from a to b, by OSRM; None if there isn't a sensible
    one."""
    try:
        r = httpx.get(f"{OSRM}{a[0]},{a[1]};{b[0]},{b[1]}",
                      params={"overview": "full", "geometries": "geojson"},
                      headers=UA, timeout=30)
        r.raise_for_status()
        route = r.json()["routes"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        log.warning("OSRM %s -> %s: %s", a, b, e)
        return None
    finally:
        time.sleep(1)  # the public server asks for at most one request a second
    straight = _metres((0, *a), (0, *b))
    if route["distance"] > 3 * straight + 500:
        return None  # a detour round something, not the missing stretch of road
    return [tuple(c) for c in route["geometry"]["coordinates"]]


def mend(path: list[Node], gaps: list[tuple[int, float]], route=road_between,
         ) -> tuple[list[LngLat], float] | None:
    """The path as (lng, lat), with its gaps driven along real roads. Returns the
    metres filled that way, or None if a long gap couldn't be filled."""
    coords = [(lng, lat) for _, lng, lat in path]
    filled = 0.0
    for at, metres in reversed(gaps):  # back to front, so earlier indices hold
        if metres < FILL_FROM_M:
            continue
        road = route(coords[at - 1], coords[at])
        if road is None:
            if metres > MAX_GAP_M:
                return None
            continue
        coords[at:at] = road[1:-1]
        filled += metres
    return coords, filled


def _clean(name: str) -> str:
    """'Dome /Ashongman Estates' -> 'Dome / Ashongman Estates'."""
    return " / ".join(p.strip() for p in name.split("/")).strip()


def build_lines(osm: dict, route=road_between) -> tuple[list[dict], dict]:
    """One GeoJSON feature per trotro line, from an Overpass answer to QUERY.

    Each line is mapped once per direction. Flooding doesn't care which way you
    ride, so keep the direction that joined up best."""
    ways = {e["id"]: e for e in osm["elements"] if e["type"] == "way"}
    rels = [e for e in osm["elements"]
            if e["type"] == "relation" and is_trotro(e.get("tags", {}))]

    # Both directions of a line, keyed by its two termini.
    lines: dict[frozenset, list] = defaultdict(list)
    for rel in rels:
        tags = rel["tags"]
        frm, to = _clean(tags.get("from", "")), _clean(tags.get("to", ""))
        if not frm or not to:
            continue
        path, gaps = stitch(_pieces(rel, ways))
        if len(path) >= 2:
            lines[frozenset((frm.lower(), to.lower()))].append(
                (sum(m for _, m in gaps), -len(path), rel, path, gaps))

    features, dropped = [], []
    for directions in lines.values():
        gap, _, rel, path, gaps = min(directions, key=lambda d: (d[0], d[1]))
        tags = rel["tags"]
        mended = mend(path, gaps, route)
        if mended is None:
            dropped.append((tags.get("name"), round(gap)))
            continue
        coords, filled = mended
        line = LineString(coords).simplify(SIMPLIFY_DEG)
        props = {
            # The lowest relation id of the line's directions: stable whichever
            # direction a rebuild happens to keep.
            "osm_id": str(min(d[2]["id"] for d in directions)),
            "ref": tags.get("ref"),
            "from": _clean(tags["from"]),
            "to": _clean(tags["to"]),
        }
        if filled:
            props["filled_m"] = round(filled)  # driven by OSRM, not mapped
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "LineString",
                "coordinates": [[round(x, 5), round(y, 5)] for x, y in line.coords],
            },
        })
    features.sort(key=lambda f: int(f["properties"]["osm_id"]))
    stats = {"relations": len(rels), "lines": len(lines), "kept": len(features),
             "dropped": dropped}
    return features, stats


def fetch_overpass() -> dict:
    """QUERY's answer, from whichever Overpass server has room."""
    errors = []
    for url in MIRRORS:
        try:
            r = httpx.post(url, data={"data": QUERY}, headers=UA, timeout=400)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Overpass %s: %s", url, e)
            errors.append(f"{url}: {e}")
    raise RuntimeError("every Overpass server failed:\n" + "\n".join(errors))


def write_bundle(features: list[dict], path: Path = BUNDLE) -> None:
    doc = {
        "type": "FeatureCollection",
        "attribution": "Route data (c) OpenStreetMap contributors, ODbL 1.0. "
                       "https://www.openstreetmap.org/copyright",
        "built": dt.date.today().isoformat(),
        "features": features,
    }
    # One feature per line keeps rebuilds reviewable as a diff.
    body = ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":"))
                      for f in features)
    head = json.dumps({k: v for k, v in doc.items() if k != "features"},
                      ensure_ascii=False)
    path.write_text(head[:-1] + ',"features":[\n' + body + "\n]}\n", encoding="utf-8")


def load_bundle(path: Path = BUNDLE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"]


def _row(feature: dict) -> dict:
    p = feature["properties"]
    coords = feature["geometry"]["coordinates"]
    return {
        "id": f"osm-{p['osm_id']}",
        "osm_id": p["osm_id"],
        "ref": p.get("ref"),
        "name": f"{p['from']} – {p['to']}",
        "from_stop": p["from"],
        "to_stop": p["to"],
        "geom": "SRID=4326;LINESTRING(" + ",".join(f"{x} {y}" for x, y in coords) + ")",
    }


async def sync_routes(db: AsyncSession, features: list[dict] | None = None) -> list[str]:
    """Make trotro_routes match the bundled lines. Returns the ids it wrote.

    Runs on every boot, so it writes only what changed: a line that is new,
    renamed or reshaped (by point count). Routes no longer in the bundle go,
    with their alerts and anyone's subscription to them."""
    features = load_bundle() if features is None else features
    rows = {r["id"]: r for r in map(_row, features)}
    want = {f"osm-{f['properties']['osm_id']}":
            (rows[f"osm-{f['properties']['osm_id']}"]["name"],
             len(f["geometry"]["coordinates"]))
            for f in features}
    have = {rid: (name, n) for rid, name, n in (await db.execute(
        select(TrotroRoute.id, TrotroRoute.name, func.ST_NPoints(TrotroRoute.geom))
    )).all()}

    gone = [rid for rid in have if rid not in want]
    changed = [rid for rid in want if have.get(rid) != want[rid]]
    if gone:
        await db.execute(delete(RouteAlert).where(RouteAlert.route_id.in_(gone)))
        subs = await db.execute(
            delete(AlertSubscription).where(AlertSubscription.route_id.in_(gone)))
        await db.execute(delete(TrotroRoute).where(TrotroRoute.id.in_(gone)))
        log.info("retired %d routes, and %d alert subscriptions to them",
                 len(gone), subs.rowcount)
    if changed:
        # One statement for all of them: the database is an ocean away.
        stmt = insert(TrotroRoute.__table__)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={c: stmt.excluded[c]
                  for c in ("osm_id", "ref", "name", "from_stop", "to_stop", "geom")})
        await db.execute(stmt, [rows[rid] for rid in changed])
    await db.commit()
    log.info("routes: %d in the bundle, %d written, %d retired",
             len(rows), len(changed), len(gone))
    return changed


async def set_baselines(db: AsyncSession, ids: list[str] | None = None) -> None:
    """Each route's worst tile within 400 m: how bad it can get on that route
    in heavy rain. All routes when `ids` is None (the grid was rebuilt)."""
    if ids is not None and not ids:
        return
    stmt = text(
        """
        UPDATE trotro_routes r SET baseline_risk = COALESCE((
          SELECT MAX(t.risk_score) FROM risk_tiles t
          -- the box first, so the distance check only sees nearby tiles
          WHERE t.centroid_lng BETWEEN ST_XMin(r.geom) - 0.005
                                   AND ST_XMax(r.geom) + 0.005
            AND t.centroid_lat BETWEEN ST_YMin(r.geom) - 0.005
                                   AND ST_YMax(r.geom) + 0.005
            AND ST_DWithin(
                  ST_SetSRID(ST_MakePoint(t.centroid_lng, t.centroid_lat),
                             4326)::geography,
                  r.geom::geography, 400)
        ), 0)
        """ + ("" if ids is None else "WHERE r.id IN :ids")
    )
    if ids is None:
        await db.execute(stmt)
    else:
        await db.execute(stmt.bindparams(bindparam("ids", expanding=True)),
                         {"ids": ids})
    await db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["build"])
    p.add_argument("--from", dest="src", type=Path,
                   help="a saved Overpass answer to QUERY")
    args = p.parse_args()
    osm = (json.loads(args.src.read_text(encoding="utf-8")) if args.src
           else fetch_overpass())
    features, stats = build_lines(osm)
    write_bundle(features)
    points = sum(len(f["geometry"]["coordinates"]) for f in features)
    log.info("%d trotro relations -> %d lines, %d kept (%d points), wrote %s",
             stats["relations"], stats["lines"], stats["kept"], points, BUNDLE)
    for f in features:
        if "filled_m" in f["properties"]:
            p = f["properties"]
            log.info("  filled %d m by road: %s - %s", p["filled_m"], p["from"], p["to"])
    for name, gap in stats["dropped"]:
        log.info("  dropped (gap %d m): %s", gap, name)


if __name__ == "__main__":
    main()
