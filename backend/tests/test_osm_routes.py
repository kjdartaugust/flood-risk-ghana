"""Trotro routes from OpenStreetMap: joining each relation's road pieces into
one line, and the bundle the app ships with. No network: OSRM is faked."""
from __future__ import annotations

from app.etl import osm_routes as osm

# Nodes along a made-up road, 0.001 degrees (~110 m) apart: (id, lng, lat).
N = {i: (i, -0.2 + i * 0.001, 5.6) for i in range(1, 30)}


def piece(*ids):
    return [N[i] for i in ids]


def ids(path):
    return [n[0] for n in path]


def test_pieces_join_whichever_way_each_was_drawn():
    path, gaps = osm.stitch([piece(1, 2, 3), piece(5, 4, 3), piece(5, 6)])
    assert ids(path) == [1, 2, 3, 4, 5, 6] and gaps == []


def test_a_first_piece_drawn_backwards_is_turned_round():
    path, gaps = osm.stitch([piece(3, 2, 1), piece(3, 4)])
    assert ids(path) == [1, 2, 3, 4] and gaps == []


def test_a_roundabout_is_driven_only_as_far_as_the_exit():
    # In at 2, round 10 -> 11, out along 11 -> 20: not the whole circle.
    ring = piece(2, 10, 11, 12, 2)
    path, gaps = osm.stitch([piece(1, 2), ring, piece(11, 20)])
    assert ids(path) == [1, 2, 10, 11, 20] and gaps == []


def test_pieces_that_dont_meet_are_measured_as_a_gap():
    path, gaps = osm.stitch([piece(1, 2), piece(12, 13)])
    assert ids(path) == [1, 2, 12, 13]
    [(at, metres)] = gaps
    assert at == 2 and 1000 < metres < 1200  # ten nodes, about 110 m each


def test_gaps_are_driven_by_road_and_unfillable_long_ones_drop_the_route():
    path, gaps = osm.stitch([piece(1, 2), piece(12, 13)])
    detour = [(9.0, 9.0)]

    coords, filled = osm.mend(path, gaps, route=lambda a, b: [a, *detour, b])
    assert coords[2] == detour[0] and filled > 1000

    assert osm.mend(path, gaps, route=lambda a, b: None) is None


def test_a_short_gap_the_router_cant_fill_is_kept_as_is():
    # 2 -> 3 is ~110 m: a straight line that short is just the same road.
    path, gaps = osm.stitch([piece(1, 2), piece(3, 4)])
    coords, filled = osm.mend(path, gaps, route=lambda a, b: None)
    assert len(coords) == 4 and filled == 0


def _relation(rid, frm, to, members, network="trô trô"):
    return {"type": "relation", "id": rid,
            "tags": {"network": network, "from": frm, "to": to, "ref": "7",
                     "name": f"Trotro 7 : {frm} → {to}"},
            "members": [{"type": "way", "ref": w, "role": ""} for w in members]
                       + [{"type": "node", "ref": 1, "role": "platform"}]}


def _way(wid, *nodes):
    return {"type": "way", "id": wid, "nodes": list(nodes),
            "geometry": [{"lon": N[n][1], "lat": N[n][2]} for n in nodes]}


def test_one_line_per_pair_of_termini_from_its_cleaner_direction():
    osm_answer = {"elements": [
        _way(100, 1, 2, 3), _way(101, 3, 4, 5), _way(102, 20, 21),
        # Outbound joins up; the way back has a 1.5 km hole in it.
        _relation(9, "Kaneshie", "Dome /Ashongman", [100, 101]),
        _relation(8, "Dome /Ashongman", "Kaneshie", [102, 100]),
        # A city bus service mapped alongside: not a trotro.
        _relation(5, "Kasoa", "Accra CMB", [100], network="City Electric Bus") | {
            "tags": {"network": "City Electric Bus", "from": "Kasoa",
                     "to": "Accra CMB", "name": "Kasoa- Accra CMB"}},
    ]}
    features, stats = osm.build_lines(osm_answer, route=lambda a, b: None)
    [line] = features
    assert line["properties"] == {
        # The lowest relation id of the two directions, so it can't change
        # with whichever direction is kept.
        "osm_id": "8", "ref": "7", "from": "Kaneshie", "to": "Dome / Ashongman"}
    assert len(line["geometry"]["coordinates"]) >= 2
    assert stats["relations"] == 2


def test_the_bundle_is_accras_trotro_network():
    features = osm.load_bundle()
    assert len(features) >= 250
    ids_ = [f["properties"]["osm_id"] for f in features]
    assert len(set(ids_)) == len(ids_)
    for f in features:
        coords = f["geometry"]["coordinates"]
        assert len(coords) >= 2
        assert all(-0.6 < lng < 0.2 and 5.4 < lat < 6.0 for lng, lat in coords)
        assert f["properties"]["from"] and f["properties"]["to"]


def test_route_rows_have_stable_ids_and_plain_names():
    row = osm._row({"properties": {"osm_id": "7460874", "ref": "290",
                                   "from": "Dansoman Last Stop", "to": "Kaneshie"},
                    "geometry": {"coordinates": [[-0.25, 5.54], [-0.24, 5.56]]}})
    assert row["id"] == "osm-7460874"
    assert row["name"] == "Dansoman Last Stop – Kaneshie"
    assert row["geom"] == "SRID=4326;LINESTRING(-0.25 5.54,-0.24 5.56)"
