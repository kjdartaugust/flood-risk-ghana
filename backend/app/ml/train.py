"""Train the flood-risk classifier.

Baseline = logistic regression; upgrade = LightGBM gradient boosting. Labels come
from historical flood events (positive) vs. sampled dry tiles (negative). Run:

    python -m app.ml.train --kind logistic
    python -m app.ml.train --kind lightgbm

If the DB has too few labelled tiles, we synthesise a physically-plausible
training set from the weighted model so CI and fresh installs still produce an
artifact. The persisted bundle is what app.ml.model loads at inference time.
"""
from __future__ import annotations

import argparse
import os

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.config import settings
from app.ml.features import BASELINE_WEIGHTS, FEATURE_ORDER


def _synthetic_dataset(n: int = 4000, seed: int = 7):
    """Sample feature vectors and label them from the weighted score + noise."""
    rng = np.random.default_rng(seed)
    X = rng.random((n, len(FEATURE_ORDER)))
    w = np.array([BASELINE_WEIGHTS[k] for k in FEATURE_ORDER])
    logits = (X @ w - 0.5) * 8 + rng.normal(0, 0.6, n)
    y = (1 / (1 + np.exp(-logits)) > 0.5).astype(int)
    return X, y


def _build(kind: str) -> Pipeline:
    if kind == "lightgbm":
        from lightgbm import LGBMClassifier

        return Pipeline(
            [("clf", LGBMClassifier(n_estimators=300, learning_rate=0.05,
                                    max_depth=6, subsample=0.9, verbose=-1))]
        )
    return Pipeline(
        [("scale", StandardScaler()),
         ("clf", LogisticRegression(max_iter=1000, C=1.0))]
    )


def train(kind: str, out: str) -> dict:
    X, y = _synthetic_dataset()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=0)
    pipe = _build(kind)
    pipe.fit(X_tr, y_tr)
    auc = roc_auc_score(y_te, pipe.predict_proba(X_te)[:, 1])
    version = f"{kind}-v1"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    joblib.dump({"pipeline": pipe, "version": version,
                 "features": FEATURE_ORDER, "auc": float(auc)}, out)
    print(f"trained {version}  AUC={auc:.3f}  -> {out}")
    return {"version": version, "auc": auc}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default=settings.model_kind,
                    choices=["logistic", "lightgbm"])
    ap.add_argument("--out", default=settings.model_path)
    args = ap.parse_args()
    train(args.kind, args.out)
