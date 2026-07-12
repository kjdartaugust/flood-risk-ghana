"""Guards on the real terrain/incident data and the leakage boundary.

These need no DB — they read the committed CSVs, which is exactly the point:
the risk grid is reproducible from data in the repo.
"""
from __future__ import annotations

import csv

from app.etl.terrain import TERRAIN_CSV, load_terrain, terrain_for
from app.ml.features import FEATURE_ORDER, MODEL_FEATURE_ORDER, TileFeatures
from app.services.hazard import density_at


def _rows():
    with open(TERRAIN_CSV, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_terrain_csv_loads_and_covers_accra():
    t = load_terrain()
    assert len(t) > 1000, "expected a dense Greater Accra grid"


def test_features_are_normalised():
    for r in _rows():
        for k in ("elevation_score", "slope_score", "drainage_score",
                  "imperviousness"):
            assert 0.0 <= float(r[k]) <= 1.0, f"{k} out of range in {r['h3_index']}"


def test_elevation_is_real_not_a_hotspot_proxy():
    """The old proxy made every feature a function of distance-to-hotspot.

    Real DEM has genuine relief: Accra runs from sea level to the Akwapim ridge.
    """
    elevs = {float(r["elev_m"]) for r in _rows()}
    assert max(elevs) > 100, "no real relief — is the DEM actually wired up?"


def test_open_water_is_masked_out():
    """The ocean is flat, at sea level, and 0 m above drainage — i.e. it scores
    as a perfect flood cell. It must not be in the scoring grid."""
    rows = _rows()
    water = [r for r in rows if r["is_land"] != "1"]
    assert water, "expected the Gulf of Guinea to be masked"
    for r in water:
        assert int(r["building_count"]) == 0
        assert float(r["elev_m"]) <= 2.0
    # and the land we keep must still include low-lying coastal settlements
    land = [r for r in rows if r["is_land"] == "1"]
    assert any(float(r["elev_m"]) <= 5 for r in land)


def test_hist_flood_density_is_not_a_model_feature():
    """It's a kernel over the incident records any label set comes from —
    feeding it to a fitted model is target leakage."""
    assert "hist_flood_density" in FEATURE_ORDER
    assert "hist_flood_density" not in MODEL_FEATURE_ORDER
    f = TileFeatures(0.5, 0.5, 0.5, 0.5, hist_flood_density=1.0,
                     rainfall_recent_mm=0.0)
    assert len(f.vector()) == len(FEATURE_ORDER)
    assert len(f.model_vector()) == len(MODEL_FEATURE_ORDER)
    assert 1.0 not in f.model_vector()


def test_density_falls_off_with_distance():
    events = [(5.5710, -0.2050, 5)]  # one severe incident at Circle
    on_top = density_at(5.5710, -0.2050, events)
    nearby = density_at(5.5900, -0.2050, events)
    far = density_at(5.6900, -0.1000, events)
    assert on_top > nearby > far
    assert far < 0.01
    assert density_at(5.57, -0.20, []) == 0.0


def test_measured_cells_report_as_measured():
    feats, measured = terrain_for(5.5710, -0.2050, 8)  # Circle
    assert measured is True
    assert feats["elev_m"] > 0
