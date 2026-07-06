"""Unit tests for the risk feature/scoring logic (no DB needed)."""
from app.ml.features import (
    BASELINE_WEIGHTS,
    TileFeatures,
    advice,
    band,
    weighted_score,
)
from app.ml.model import RiskModel
from app.services.geo import latlng_to_cell, nearest_hotspot


def _tile(**kw) -> TileFeatures:
    base = dict(elevation_score=0.5, slope_score=0.5, drainage_score=0.5,
                imperviousness=0.5, hist_flood_density=0.5, rainfall_recent_mm=0.0)
    base.update(kw)
    return TileFeatures(**base)


def test_weights_sum_to_one():
    assert abs(sum(BASELINE_WEIGHTS.values()) - 1.0) < 1e-9


def test_higher_features_raise_score():
    low = weighted_score(_tile(elevation_score=0.0, drainage_score=0.0,
                               hist_flood_density=0.0, imperviousness=0.0,
                               slope_score=0.0))
    high = weighted_score(_tile(elevation_score=1.0, drainage_score=1.0,
                                hist_flood_density=1.0, imperviousness=1.0,
                                slope_score=1.0))
    assert high > low
    assert 0 <= low <= 100 and 0 <= high <= 100


def test_rainfall_normalisation_saturates():
    assert _tile(rainfall_recent_mm=200).rainfall_recent_norm == 1.0
    assert _tile(rainfall_recent_mm=0).rainfall_recent_norm == 0.0


def test_bands_are_ordered():
    assert band(10) == "low"
    assert band(30) == "moderate"
    assert band(50) == "high"
    assert band(70) == "severe"
    assert band(90) == "extreme"


def test_advice_mentions_hotspot_when_high():
    txt = advice(75, "Kaneshie")
    assert "Kaneshie" in txt


def test_weighted_fallback_model_confidence_bounds():
    m = RiskModel(None)
    score, conf = m.predict(_tile(elevation_score=1.0))
    assert 0 <= score <= 100
    assert 0.5 <= conf <= 1.0


def test_nearest_hotspot_kaneshie():
    name, dist = nearest_hotspot(5.5620, -0.2360)
    assert name == "Kaneshie"
    assert dist < 1.0


def test_h3_cell_is_stable():
    a = latlng_to_cell(5.5620, -0.2360, 8)
    b = latlng_to_cell(5.5621, -0.2361, 8)
    assert a == b  # nearby points share the same res-8 cell
