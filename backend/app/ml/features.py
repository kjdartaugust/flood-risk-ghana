"""Feature engineering shared by the weighted baseline, training and inference.

A tile's flood risk rises with: low elevation, flat slope (poor runoff), poor
drainage, high imperviousness (built-up), dense historical flooding, and recent
rainfall. Each raw feature is normalised to 0..1 (higher = more flood-prone)
before it hits either the weighted score or the ML model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

FEATURE_ORDER = [
    "elevation_score",
    "slope_score",
    "drainage_score",
    "imperviousness",
    "hist_flood_density",
    "rainfall_recent_norm",
]

# What a *fitted* model is allowed to see. `hist_flood_density` is a kernel over
# the recorded flood incidents — the very records any label set is built from —
# so feeding it to a classifier is target leakage: the model would score high
# wherever we already know it flooded, and validate beautifully against itself.
# It stays in FEATURE_ORDER because the transparent baseline is a hand-specified
# index, not something fitted to those labels, and there "we have seen this flood
# before" is legitimate evidence.
MODEL_FEATURE_ORDER = [f for f in FEATURE_ORDER if f != "hist_flood_density"]


@dataclass
class TileFeatures:
    elevation_score: float       # 0=high ground, 1=low-lying
    slope_score: float           # 0=steep, 1=flat
    drainage_score: float        # 0=well drained, 1=poor drainage
    imperviousness: float        # 0=vegetated, 1=fully paved
    hist_flood_density: float    # 0=none nearby, 1=hotspot
    rainfall_recent_mm: float    # raw mm over lookback window

    @property
    def rainfall_recent_norm(self) -> float:
        # 0 mm → 0, ~80 mm (heavy Accra downpour) → ~1, saturating.
        return min(self.rainfall_recent_mm / 80.0, 1.0)

    def _as_dict(self) -> dict[str, float]:
        d = asdict(self)
        d["rainfall_recent_norm"] = self.rainfall_recent_norm
        return d

    def vector(self) -> list[float]:
        """Full feature vector, in FEATURE_ORDER — for the weighted baseline."""
        d = self._as_dict()
        return [float(d[k]) for k in FEATURE_ORDER]

    def model_vector(self) -> list[float]:
        """Leakage-free vector, in MODEL_FEATURE_ORDER — for a fitted model."""
        d = self._as_dict()
        return [float(d[k]) for k in MODEL_FEATURE_ORDER]


# Weights for the transparent baseline score (must sum to 1.0). Chosen from
# flood-hydrology priors; the ML model learns its own weights from labels.
BASELINE_WEIGHTS = {
    "elevation_score": 0.26,
    "slope_score": 0.14,
    "drainage_score": 0.20,
    "imperviousness": 0.14,
    "hist_flood_density": 0.16,
    "rainfall_recent_norm": 0.10,
}


def weighted_score(f: TileFeatures) -> float:
    """Transparent weighted geospatial score in 0..100."""
    d = dict(zip(FEATURE_ORDER, f.vector(), strict=False))
    s = sum(BASELINE_WEIGHTS[k] * d[k] for k in BASELINE_WEIGHTS)
    return round(100.0 * s, 1)


def band(score: float) -> str:
    if score < 20:
        return "low"
    if score < 40:
        return "moderate"
    if score < 60:
        return "high"
    if score < 80:
        return "severe"
    return "extreme"


def advice(score: float, hotspot: str | None) -> str:
    b = band(score)
    base = {
        "low": "Low flood risk. Standard drainage precautions are sufficient.",
        "moderate": ("Moderate risk. Check drainage and avoid ground-floor "
                     "storage of valuables."),
        "high": ("High risk. Elevate structures, verify insurance, avoid "
                 "building in gutter paths."),
        "severe": ("Severe risk. Building/living here needs serious flood "
                   "mitigation; reconsider."),
        "extreme": ("Extreme risk zone. Known flood plain — strongly "
                    "reconsider purchase/build."),
    }[b]
    if hotspot and score >= 40:
        base += f" Near the {hotspot} flood hotspot."
    return base
