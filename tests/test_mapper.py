"""Tests for src/pipeline/mapper.py"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.pipeline.mapper import RAION_EPOCH, RAION_TO_OBLAST, normalize_regions

_UTC = timezone.utc
_PRE = datetime(2025, 6, 1, tzinfo=_UTC)   # before raion epoch
_POST = datetime(2026, 1, 1, tzinfo=_UTC)  # after raion epoch


def _make_df(**overrides) -> pd.DataFrame:
    base = {
        "id": [1],
        "region_id": [9],
        "region_name": ["Kyiv Oblast"],
        "region_type": ["oblast"],
        "started_at": [_PRE],
        "finished_at": [None],
        "alert_type": ["air_raid"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestPreEpochMapping:
    def test_uses_region_name_directly(self):
        df = _make_df(region_name=["Lviv Oblast"], started_at=[_PRE])
        result = normalize_regions(df)
        assert result["oblast_name"].iloc[0] == "Lviv Oblast"

    def test_mapping_source_is_direct(self):
        df = _make_df(started_at=[_PRE])
        result = normalize_regions(df)
        assert result["mapping_source"].iloc[0] == "direct"

    def test_raion_id_is_null_pre_epoch(self):
        df = _make_df(started_at=[_PRE])
        result = normalize_regions(df)
        assert pd.isna(result["raion_id"].iloc[0])


class TestPostEpochMapping:
    def test_known_raion_maps_to_correct_oblast(self):
        raion_id = 901
        expected_oblast = RAION_TO_OBLAST[raion_id][1]
        df = _make_df(region_id=[raion_id], region_type=["raion"], started_at=[_POST])
        result = normalize_regions(df)
        assert result["oblast_name"].iloc[0] == expected_oblast

    def test_known_raion_source_is_raion_join(self):
        raion_id = 1201
        df = _make_df(region_id=[raion_id], region_type=["raion"], started_at=[_POST])
        result = normalize_regions(df)
        assert result["mapping_source"].iloc[0] == "raion_join"

    def test_unknown_raion_becomes_unknown(self):
        df = _make_df(region_id=[99999], region_type=["raion"], started_at=[_POST])
        result = normalize_regions(df)
        assert result["oblast_name"].iloc[0] == "Unknown"
        assert result["mapping_source"].iloc[0] == "unknown"


class TestInvariant:
    def test_oblast_name_never_null(self):
        rows = [
            {"id": 1, "region_id": 9, "region_name": "Kyiv Oblast", "region_type": "oblast",
             "started_at": _PRE, "finished_at": None, "alert_type": "air_raid"},
            {"id": 2, "region_id": 901, "region_name": "Kyiv Raion", "region_type": "raion",
             "started_at": _POST, "finished_at": None, "alert_type": "air_raid"},
            {"id": 3, "region_id": 99999, "region_name": "Unknown Raion", "region_type": "raion",
             "started_at": _POST, "finished_at": None, "alert_type": "air_raid"},
        ]
        df = pd.DataFrame(rows)
        result = normalize_regions(df)
        assert result["oblast_name"].notna().all()
