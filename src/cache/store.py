"""Typed Parquet read/write wrappers.

Paths:
  HISTORICAL_PATH  data/historical_alerts.parquet   — cleaned full history (ingest.py)
  AGG_PATH         data/cache/alerts_agg.parquet    — pre-computed rollups
  META_PATH        data/cache/meta.json             — ingest high-water mark
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]  # project root
CACHE_DIR = _ROOT / "data" / "cache"
HISTORICAL_PATH = _ROOT / "data" / "historical_alerts.parquet"   # primary cleaned store
AGG_PATH = CACHE_DIR / "alerts_agg.parquet"
META_PATH = CACHE_DIR / "meta.json"


def _ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORICAL_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Raw alerts ──────────────────────────────────────────────────────────────

RAW_SCHEMA = pa.schema(
    [
        pa.field("alert_id", pa.string()),
        pa.field("oblast_name", pa.string()),
        pa.field("oblast_id", pa.int16()),
        pa.field("raion_id", pa.int16()),
        pa.field("start_time", pa.timestamp("us", tz="UTC")),
        pa.field("end_time_raw", pa.timestamp("us", tz="UTC")),
        pa.field("end_time_resolved", pa.timestamp("us", tz="UTC")),
        pa.field("duration_seconds", pa.float32()),
        pa.field("alert_type", pa.string()),
        pa.field("is_open_ended", pa.bool_()),
        pa.field("is_permanent_outlier", pa.bool_()),
        pa.field("mapping_source", pa.string()),
        pa.field("ingest_ts", pa.timestamp("us", tz="UTC")),
    ]
)


def _df_to_raw_table(df: pd.DataFrame, ingest_ts: datetime) -> pa.Table:
    """Coerce a cleaned pipeline DataFrame into the canonical raw schema."""
    out = pd.DataFrame(
        {
            "alert_id": df["id"].astype(str),
            "oblast_name": df["oblast_name"].astype(str),
            "oblast_id": pd.array(df["oblast_id"], dtype="Int16"),
            "raion_id": pd.array(df.get("raion_id", pd.NA), dtype="Int16"),
            "start_time": pd.to_datetime(df["started_at"], utc=True),
            "end_time_raw": pd.to_datetime(df["end_time_raw"], utc=True),
            "end_time_resolved": pd.to_datetime(df["end_time_resolved"], utc=True),
            "duration_seconds": df["duration_seconds"].astype("float32"),
            "alert_type": df["alert_type"].astype(str),
            "is_open_ended": df["is_open_ended"].astype(bool),
            "is_permanent_outlier": df["is_permanent_outlier"].astype(bool),
            "mapping_source": df["mapping_source"].astype(str),
            "ingest_ts": ingest_ts.astimezone(timezone.utc),
        }
    )
    return pa.Table.from_pandas(out, schema=RAW_SCHEMA, safe=False)


def append_raw(df: pd.DataFrame, ingest_ts: datetime) -> None:
    """Append cleaned records to historical_alerts.parquet (creates if absent)."""
    _ensure_dirs()
    new_table = _df_to_raw_table(df, ingest_ts)

    if HISTORICAL_PATH.exists():
        existing = pq.read_table(HISTORICAL_PATH)
        combined = pa.concat_tables([existing, new_table])
        # Deduplicate on alert_id — last write wins
        combined_df = combined.to_pandas()
        combined_df = combined_df.drop_duplicates(subset=["alert_id"], keep="last")
        combined = pa.Table.from_pandas(combined_df, schema=RAW_SCHEMA, safe=False)
    else:
        combined = new_table

    pq.write_table(combined, HISTORICAL_PATH, compression="snappy")
    log.info("Wrote %d rows to %s", len(combined), HISTORICAL_PATH)


def read_raw(oblast_name: str | None = None) -> pd.DataFrame:
    """Read historical_alerts.parquet, optionally filtered by oblast."""
    if not HISTORICAL_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(HISTORICAL_PATH)
    if oblast_name:
        df = df[df["oblast_name"] == oblast_name]
    return df


# ── Aggregated rollups ───────────────────────────────────────────────────────

def write_agg(df: pd.DataFrame) -> None:
    _ensure_dirs()
    df.to_parquet(AGG_PATH, index=False, compression="snappy")
    log.info("Wrote aggregation to %s (%d rows)", AGG_PATH, len(df))


def read_agg(oblast_name: str | None = None) -> pd.DataFrame:
    if not AGG_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(AGG_PATH)
    if oblast_name:
        df = df[df["oblast_name"] == oblast_name]
    return df


# ── Ingest metadata ──────────────────────────────────────────────────────────

def read_last_ingest_ts() -> datetime | None:
    if not META_PATH.exists():
        return None
    meta = json.loads(META_PATH.read_text())
    ts_str = meta.get("last_ingest_ts")
    if ts_str:
        return datetime.fromisoformat(ts_str)
    return None


def write_last_ingest_ts(ts: datetime) -> None:
    _ensure_dirs()
    meta = {"last_ingest_ts": ts.astimezone(timezone.utc).isoformat()}
    META_PATH.write_text(json.dumps(meta, indent=2))
