"""Rolling 7-day logistic regression baseline.

Trains one LogisticRegression model per oblast on historical hourly buckets.
Predicts P(alert_in_next_12h) given the rolling 7d alert count.

Pickle paths: data/cache/model_{oblast_slug}.pkl
"""

from __future__ import annotations

import logging
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = _ROOT / "data" / "cache"
ROLLING_WINDOW_HOURS = 7 * 24   # 7 days in hourly buckets
PREDICTION_HORIZON_HOURS = 12


def _oblast_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _build_features(oblast_df: pd.DataFrame) -> pd.DataFrame:
    """Resample to hourly buckets, compute rolling features and binary target."""
    df = oblast_df.copy()
    df = df.set_index(pd.to_datetime(df["start_time"], utc=True))
    hourly = df.resample("h").size().rename("alerts_in_hour")
    hourly = hourly.to_frame()

    hourly["rolling_7d"] = (
        hourly["alerts_in_hour"].rolling(ROLLING_WINDOW_HOURS, min_periods=1).sum()
    )

    # Binary target: any alert in next 12 hours
    hourly["target"] = (
        hourly["alerts_in_hour"]
        .rolling(PREDICTION_HORIZON_HOURS, min_periods=1)
        .sum()
        .shift(-PREDICTION_HORIZON_HOURS)
        .fillna(0)
        .gt(0)
        .astype(int)
    )

    hourly["hour_of_day"] = hourly.index.hour
    hourly["day_of_week"] = hourly.index.dayofweek
    return hourly.dropna()


def retrain_models(raw: pd.DataFrame) -> None:
    """Train and pickle one model per oblast (called by ingest.py)."""
    if raw.empty:
        log.warning("No data — skipping model training")
        return

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    oblasts = raw["oblast_name"].dropna().unique()

    for oblast in oblasts:
        slug = _oblast_slug(oblast)
        try:
            subset = raw[raw["oblast_name"] == oblast]
            features = _build_features(subset)
            if len(features) < 100:
                log.debug("Skipping %s — too few samples (%d)", oblast, len(features))
                continue

            X = features[["rolling_7d", "hour_of_day", "day_of_week"]].values
            y = features["target"].values

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            model = LogisticRegression(max_iter=500, random_state=42)
            model.fit(X_scaled, y)

            artifact = {"model": model, "scaler": scaler}
            model_path = MODEL_DIR / f"model_{slug}.pkl"
            with open(model_path, "wb") as f:
                pickle.dump(artifact, f)

            log.info("Trained model for %s → %s", oblast, model_path)
        except Exception as exc:
            log.warning("Failed to train model for %s: %s", oblast, exc)


def predict_alert_probability(
    oblast_name: str,
    raw: pd.DataFrame,
) -> float:
    """
    Returns P(alert in next 12h) for the given oblast.
    Falls back to naive frequency baseline if no pickled model exists.
    """
    slug = _oblast_slug(oblast_name)
    model_path = MODEL_DIR / f"model_{slug}.pkl"

    subset = raw[raw["oblast_name"] == oblast_name]
    if subset.empty:
        return 0.0

    features = _build_features(subset)

    if model_path.exists():
        with open(model_path, "rb") as f:
            artifact = pickle.load(f)
        model: LogisticRegression = artifact["model"]
        scaler: StandardScaler = artifact["scaler"]

        latest = features[["rolling_7d", "hour_of_day", "day_of_week"]].iloc[[-1]]
        X_scaled = scaler.transform(latest.values)
        prob = float(model.predict_proba(X_scaled)[0, 1])
        return round(prob, 4)

    # Naive fallback: rolling 7d rate
    if features.empty:
        return 0.0
    rolling = float(features["rolling_7d"].iloc[-1])
    return round(min(rolling / ROLLING_WINDOW_HOURS, 1.0), 4)
