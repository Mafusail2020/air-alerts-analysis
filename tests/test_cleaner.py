"""Tests for src/pipeline/cleaner.py"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.pipeline.cleaner import (
    MAX_IMPUTE_HOURS,
    PERMANENT_OUTLIER_OBLASTS,
    resolve_anomalies,
)

_UTC = timezone.utc
_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=_UTC)


def _make_df(**overrides) -> pd.DataFrame:
    base = {
        "id": [1],
        "oblast_name": ["Kyiv Oblast"],
        "started_at": [datetime(2025, 1, 1, 8, 0, tzinfo=_UTC)],
        "finished_at": [datetime(2025, 1, 1, 9, 0, tzinfo=_UTC)],
        "alert_type": ["air_raid"],
        "mapping_source": ["direct"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestPermanentOutlierFlagging:
    def test_luhansk_flagged(self):
        df = _make_df(oblast_name=["Luhansk Oblast"])
        result = resolve_anomalies(df, set(), _NOW)
        assert result["is_permanent_outlier"].all()

    def test_crimea_flagged(self):
        df = _make_df(oblast_name=["Autonomous Republic of Crimea"])
        result = resolve_anomalies(df, set(), _NOW)
        assert result["is_permanent_outlier"].all()

    def test_regular_oblast_not_flagged(self):
        df = _make_df(oblast_name=["Lviv Oblast"])
        result = resolve_anomalies(df, set(), _NOW)
        assert not result["is_permanent_outlier"].any()

    def test_outlier_duration_is_nan(self):
        df = _make_df(oblast_name=["Luhansk Oblast"])
        result = resolve_anomalies(df, set(), _NOW)
        assert pd.isna(result["duration_seconds"].iloc[0])


class TestOpenEndedImputation:
    def test_active_alert_capped_at_ingest_ts(self):
        df = _make_df(id=[42], finished_at=[None])
        result = resolve_anomalies(df, active_alert_ids={42}, ingest_ts=_NOW)
        row = result.iloc[0]
        assert row["is_open_ended"] is True
        assert row["end_time_resolved"].replace(tzinfo=_UTC) == _NOW

    def test_inactive_open_ended_capped_at_max_hours(self):
        start = datetime(2025, 6, 1, 10, 0, tzinfo=_UTC)
        df = _make_df(id=[99], started_at=[start], finished_at=[None])
        result = resolve_anomalies(df, active_alert_ids=set(), ingest_ts=_NOW)
        expected_end = start + timedelta(hours=MAX_IMPUTE_HOURS)
        resolved = result["end_time_resolved"].iloc[0]
        if hasattr(resolved, "to_pydatetime"):
            resolved = resolved.to_pydatetime()
        assert abs((resolved - expected_end).total_seconds()) < 1

    def test_normal_event_preserves_end_time(self):
        end = datetime(2025, 3, 10, 15, 30, tzinfo=_UTC)
        df = _make_df(finished_at=[end])
        result = resolve_anomalies(df, set(), _NOW)
        assert not result["is_open_ended"].iloc[0]


class TestDurationCalculation:
    def test_duration_computed_correctly(self):
        start = datetime(2025, 5, 1, 8, 0, tzinfo=_UTC)
        end = datetime(2025, 5, 1, 9, 30, tzinfo=_UTC)
        df = _make_df(started_at=[start], finished_at=[end])
        result = resolve_anomalies(df, set(), _NOW)
        assert abs(result["duration_seconds"].iloc[0] - 5400.0) < 1

    def test_duration_clamped_to_max(self):
        start = datetime(2025, 1, 1, 0, 0, tzinfo=_UTC)
        df = _make_df(id=[5], started_at=[start], finished_at=[None])
        result = resolve_anomalies(df, active_alert_ids=set(), ingest_ts=_NOW)
        max_seconds = MAX_IMPUTE_HOURS * 3600
        assert result["duration_seconds"].iloc[0] <= max_seconds

    def test_duration_never_negative(self):
        start = datetime(2025, 5, 1, 9, 0, tzinfo=_UTC)
        end = datetime(2025, 5, 1, 8, 0, tzinfo=_UTC)  # end before start (bad data)
        df = _make_df(started_at=[start], finished_at=[end])
        result = resolve_anomalies(df, set(), _NOW)
        assert result["duration_seconds"].iloc[0] >= 0
