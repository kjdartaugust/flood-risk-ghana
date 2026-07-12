"""Train and *honestly* evaluate the flood-risk model.

    python -m app.ml.train --kind logistic
    python -m app.ml.train --kind lightgbm

What changed, and why it matters:

The previous version sampled random feature vectors, labelled them with
`BASELINE_WEIGHTS`, and reported AUC≈0.92. That number measured whether logistic
regression can recover a linear function it was handed. It can. It said nothing
about flooding.

This version:

* **Real features** — from `data/accra_terrain.csv` (Copernicus DEM + OSM), not
  a distance-to-hotspot proxy.
* **Real labels** — from `data/accra_flood_incidents.csv`: communities recorded
  as flooded in the 3 June 2015 Accra disaster, geocoded against OSM. Cells near
  a reported community are positive; cells far from every one are negative; the
  ring between is dropped rather than guessed at.
* **No leakage** — `hist_flood_density` is a kernel over those same incidents,
  so it is excluded from the fitted model (see `MODEL_FEATURE_ORDER`).
* **Spatially-blocked CV** — folds are grouped by H3 res-5 parent cell. Flood
  risk is strongly spatially autocorrelated; a random split puts a cell's own
  neighbours in the training set and inflates AUC toward the meaningless.
* **A baseline to beat** — the transparent weighted index is scored on the exact
  same folds. If the fitted model can't beat it, we say so instead of shipping it.

Read `docs/DATA.md` for what this label set is and, more importantly, is not.
"""
from __future__ import annotations

import argparse
import csv
import os

import h3
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.config import settings
from app.ml.features import (
    BASELINE_WEIGHTS,
    FEATURE_ORDER,
    MODEL_FEATURE_ORDER,
    TileFeatures,
)
from app.services.geo import haversine_km

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "data")
TERRAIN_CSV = os.path.normpath(os.path.join(DATA, "accra_terrain.csv"))
INCIDENTS_CSV = os.path.normpath(os.path.join(DATA, "accra_flood_incidents.csv"))

# A cell centroid within this of a reported-flooded community is a positive.
POS_KM = 1.0
# Beyond this from *every* reported community, a cell is a negative. Cells in
# the annulus between are ambiguous — a report names a neighbourhood, not a
# polygon — so we drop them rather than inventing a boundary.
NEG_KM = 3.0
# Spatial CV blocks: H3 res 5 ≈ 8 km across, comfortably larger than NEG_KM.
BLOCK_RES = 5


def _load_terrain() -> list[dict]:
    with open(TERRAIN_CSV, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load_incidents() -> list[tuple[float, float]]:
    with open(INCIDENTS_CSV, encoding="utf-8") as fh:
        return [
            (float(r["lat"]), float(r["lng"]))
            for r in csv.DictReader(fh)
            if r["flood_reported"] == "1"
        ]


def build_dataset():
    """Return (X_model, X_full, y, groups, feature rows) over labelled cells."""
    terrain, incidents = _load_terrain(), _load_incidents()
    Xm, Xf, y, groups = [], [], [], []
    for r in terrain:
        if r["is_land"] != "1":
            continue  # open water is not a flood-risk question
        lat, lng = float(r["centroid_lat"]), float(r["centroid_lng"])
        d = min(haversine_km((lat, lng), inc) for inc in incidents)
        if d <= POS_KM:
            label = 1
        elif d >= NEG_KM:
            label = 0
        else:
            continue  # ambiguous ring — excluded, not guessed
        # rainfall is a live signal, zero in the static grid; it stays in the
        # vector so train/inference shapes match, and simply carries no weight.
        f = TileFeatures(
            elevation_score=float(r["elevation_score"]),
            slope_score=float(r["slope_score"]),
            drainage_score=float(r["drainage_score"]),
            imperviousness=float(r["imperviousness"]),
            hist_flood_density=0.0,
            rainfall_recent_mm=0.0,
        )
        Xm.append(f.model_vector())
        Xf.append(f.vector())
        y.append(label)
        groups.append(h3.cell_to_parent(r["h3_index"], BLOCK_RES))
    return (np.array(Xm), np.array(Xf), np.array(y), np.array(groups))


def _baseline_scores(X_full: np.ndarray) -> np.ndarray:
    w = np.array([BASELINE_WEIGHTS[k] for k in FEATURE_ORDER])
    return X_full @ w


def _build(kind: str) -> Pipeline:
    if kind == "lightgbm":
        from lightgbm import LGBMClassifier

        return Pipeline(
            [("clf", LGBMClassifier(n_estimators=200, learning_rate=0.05,
                                    max_depth=4, subsample=0.9, verbose=-1))]
        )
    return Pipeline(
        [("scale", StandardScaler()),
         ("clf", LogisticRegression(max_iter=1000, C=1.0))]
    )


def cross_validate(kind: str, Xm, Xf, y, groups) -> tuple[float, float]:
    """Spatially-blocked CV AUC for (fitted model, weighted baseline)."""
    n_splits = min(5, len(set(groups)))
    gkf = GroupKFold(n_splits=n_splits)
    model_auc, base_auc = [], []
    for tr, te in gkf.split(Xm, y, groups):
        if len(set(y[te])) < 2 or len(set(y[tr])) < 2:
            continue  # a block with only one class can't be scored
        pipe = _build(kind)
        pipe.fit(Xm[tr], y[tr])
        model_auc.append(roc_auc_score(y[te], pipe.predict_proba(Xm[te])[:, 1]))
        base_auc.append(roc_auc_score(y[te], _baseline_scores(Xf[te])))
    if not model_auc:
        raise RuntimeError("no spatial fold had both classes — labels too sparse")
    return float(np.mean(model_auc)), float(np.mean(base_auc))


def train(kind: str, out: str) -> dict:
    Xm, Xf, y, groups = build_dataset()
    pos, neg, blocks = int(y.sum()), int((y == 0).sum()), len(set(groups))
    print(f"labelled cells: {pos} positive / {neg} negative "
          f"across {blocks} spatial blocks")

    model_auc, base_auc = cross_validate(kind, Xm, Xf, y, groups)
    print(f"spatially-blocked CV AUC:  model({kind}) = {model_auc:.3f}  |  "
          f"weighted baseline = {base_auc:.3f}")
    if model_auc <= base_auc:
        print("NOTE: the fitted model does not beat the transparent baseline on "
              "this label set. The API will keep using whichever is configured; "
              "the baseline is the honest default.")

    pipe = _build(kind)
    pipe.fit(Xm, y)
    version = f"{kind}-v2"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    joblib.dump({
        "pipeline": pipe,
        "version": version,
        "features": MODEL_FEATURE_ORDER,
        "cv_auc": float(model_auc),
        "baseline_cv_auc": float(base_auc),
        "cv": f"GroupKFold on H3 res-{BLOCK_RES} blocks",
        "n_pos": pos,
        "n_neg": neg,
    }, out)
    print(f"saved {version} -> {out}")
    return {"version": version, "cv_auc": model_auc, "baseline_cv_auc": base_auc}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default=settings.model_kind,
                    choices=["logistic", "lightgbm"])
    ap.add_argument("--out", default=settings.model_path)
    args = ap.parse_args()
    train(args.kind, args.out)
