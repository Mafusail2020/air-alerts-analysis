"""Tests for src/analytics/predictor.py"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.analytics.predictor import _build_features, predict_alert_probability

_UTC = timezone.utc


def _make_raw(n_hours: int = 200, oblast: str = "Kyiv Oblast") -> pd.DataFrame:
    """Synthetic raw DataFrame with alerts every 3 hours."""
    base = datetime(2025, 1, 1, tzinfo=_UTC)
    records = []
    for i in range(n_hours):
        if i % 3 == 0:
            start = base + timedelta(hours=i)
            records.append(
                {
                    "alert_id": str(i),
                    "oblast_name": oblast,
                    "start_time": start,
                    "end_time_resolved": start + timedelta(hours=1),
                    "duration_seconds": 3600.0,
                    "is_permanent_outlier": False,
                    "alert_type": "air_raid",
                }
            )
    return pd.DataFrame(records)


class TestBuildFeatures:
    def test_returns_dataframe_with_expected_columns(self):
        raw = _make_raw()
        features = _build_features(raw)
        assert "rolling_7d" in features.columns
        assert "target" in features.columns
        assert "hour_of_day" in features.columns

    def test_rolling_7d_nonnegative(self):
        raw = _make_raw()
        features = _build_features(raw)
        assert (features["rolling_7d"] >= 0).all()

    def test_target_is_binary(self):
        raw = _make_raw()
        features = _build_features(raw)
        assert features["target"].isin([0, 1]).all()


class TestPredictAlertProbability:
    def test_empty_oblast_returns_zero(self):
        raw = _make_raw(oblast="Lviv Oblast")
        prob = predict_alert_probability("Kharkiv Oblast", raw)
        assert prob == 0.0

    def test_probability_in_range(self):
        raw = _make_raw(n_hours=400)
        prob = predict_alert_probability("Kyiv Oblast", raw)
        assert 0.0 <= prob <= 1.0

    def test_returns_float(self):
        raw = _make_raw(n_hours=400)
        prob = predict_alert_probability("Kyiv Oblast", raw)
        assert isinstance(prob, float)
