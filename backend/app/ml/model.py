"""Inference wrapper around the trained flood-risk classifier.

Loads a persisted scikit-learn / LightGBM pipeline once (lazy singleton). If no
artifact is present it transparently falls back to the weighted baseline, so the
API is always functional even before a model is trained.
"""
from __future__ import annotations

import os
from functools import lru_cache

import joblib

from app.config import settings
from app.ml.features import TileFeatures, weighted_score


class RiskModel:
    def __init__(self, pipeline=None, version: str = "weighted-v1"):
        self._pipeline = pipeline
        self.version = version

    @property
    def is_ml(self) -> bool:
        return self._pipeline is not None

    def predict(self, f: TileFeatures) -> tuple[float, float]:
        """Return (risk_score 0..100, confidence 0..1)."""
        if self._pipeline is None:
            score = weighted_score(f)
            # Confidence from how far the score sits from the decision midpoint.
            conf = 0.55 + 0.35 * abs(score - 50) / 50
            return score, round(conf, 3)
        proba = float(self._pipeline.predict_proba([f.vector()])[0][1])
        score = round(proba * 100, 1)
        conf = round(0.6 + 0.4 * abs(proba - 0.5) * 2, 3)
        return score, conf


@lru_cache
def get_model() -> RiskModel:
    path = settings.model_path
    if os.path.exists(path):
        try:
            bundle = joblib.load(path)
            return RiskModel(bundle["pipeline"], bundle.get("version", "ml-v1"))
        except Exception:
            pass
    return RiskModel(None, "weighted-v1")
