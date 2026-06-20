"""Hybrid ingestion script — run independently of the Streamlit dashboard.

Data sources:
  PRIMARY  — Vadimkin/ukrainian-air-raid-sirens-dataset GitHub CSV
             Full 4-year history, daily updated, no rate limits.
  SECONDARY — alerts.in.ua API (app.py only, for live alert status).
             NOT used here for historical data.

Pipeline:
  1. CsvFetcher.fetch()         — download + schema-normalize the CSV
  2. CsvFetcher.filter_delta()  — skip rows already in cache (by max started_at)
  3. AlertCleaner.clean()       — impute open-ended events, compute durations
  4. store.append_raw()         — write/deduplicate → data/historical_alerts.parquet
  5. aggregator.compute_rollups() — rewrite data/cache/alerts_agg.parquet
  6. predictor.retrain_models() — rewrite data/cache/model_*.pkl
  7. store.write_last_ingest_ts() — update high-water mark

Note on permanent outliers:
  The Vadimkin dataset explicitly excludes Luhansk (permanent since 2022-04-04)
  and Crimea (permanent since 2022-12-10). The is_permanent_outlier flag in
  cleaner.py will never fire on this source — kept for safety with future sources.

Usage:
  python ingest.py            # delta load (only new rows since last run)
  python ingest.py --full     # force full reload and rewrite cache
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.cache import store
from src.pipeline import aggregator, cleaner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("ingest")

# ── Vadimkin dataset column map → internal schema ────────────────────────────
# Source: github.com/Vadimkin/ukrainian-air-raid-sirens-dataset
# English CSV columns (official_data_en.csv):
#   id, location_uid, location_oblast, location_raion, location_type,
#   started_at, finished_at, calculated_duration_seconds, alert_type, ...
_CSV_COLUMN_MAP: dict[str, str] = {
    "id": "id",
    "location_uid": "location_uid",
    "location_oblast": "region_name",   # always Oblast-level label
    "location_raion": "raion_name",     # null for pre-Dec-2025 records
    "location_type": "region_type",     # "oblast" | "raion"
    "started_at": "started_at",
    "finished_at": "finished_at",
    "alert_type": "alert_type",
}

# Max duration cap for open-ended alerts — matches cleaner.MAX_IMPUTE_HOURS
_MAX_IMPUTE_HOURS: int = 24

KYIV_TZ = "Europe/Kyiv"


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class IngestionConfig:
    csv_url: str = (
        "https://raw.githubusercontent.com/Vadimkin/"
        "ukrainian-air-raid-sirens-dataset/main/datasets/official_data_en.csv"
    )
    historical_path: Path = field(default_factory=lambda: store.HISTORICAL_PATH)
    agg_path: Path = field(default_factory=lambda: store.AGG_PATH)
    force_full: bool = False
    csv_read_timeout: int = 120   # seconds; large file


# ── CSV fetcher ────────────────────────────────────────────────────────────────

class CsvFetcher:
    """Downloads and schema-normalizes the Vadimkin GitHub CSV."""

    def __init__(self, config: IngestionConfig) -> None:
        self._config = config

    def fetch(self) -> pd.DataFrame:
        log.info("Downloading CSV from %s", self._config.csv_url)
        try:
            df = pd.read_csv(
                self._config.csv_url,
                dtype=str,             # read all as string; parse types below
                low_memory=False,
                storage_options={"timeout": self._config.csv_read_timeout},
            )
        except Exception as exc:
            log.error("CSV download failed: %s", exc)
            raise

        log.info("Downloaded %d rows, columns: %s", len(df), list(df.columns))
        return self._normalize_schema(df)

    def _normalize_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename CSV columns to internal names, parse timestamps, drop unknowns."""
        missing = [c for c in _CSV_COLUMN_MAP if c not in df.columns]
        if missing:
            raise ValueError(
                f"CSV schema mismatch — expected columns not found: {missing}\n"
                f"Actual columns: {list(df.columns)}"
            )

        df = df.rename(columns=_CSV_COLUMN_MAP)
        keep = list(_CSV_COLUMN_MAP.values())
        df = df[[c for c in keep if c in df.columns]].copy()

        # Parse timestamps — CSV stores UTC ISO strings
        for col in ("started_at", "finished_at"):
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

        # Numeric id
        df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")

        # Normalise alert_type to lowercase for consistency
        df["alert_type"] = df["alert_type"].str.lower().fillna("unknown")

        # The Vadimkin dataset provides location_oblast on every row regardless
        # of location_type, so oblast_name is directly available — no mapper needed.
        df["oblast_name"] = df["region_name"].str.strip()
        df["mapping_source"] = "direct"
        df["oblast_id"] = df["oblast_name"].map(
            {v: k for k, v in _OBLAST_NAME_TO_ID.items()}
        ).astype("Int16")

        # raion_id is not an integer code in this dataset — leave nullable
        df["raion_id"] = pd.array([pd.NA] * len(df), dtype="Int16")

        return df.dropna(subset=["id", "started_at", "oblast_name"])

    def filter_delta(self, df: pd.DataFrame, since: datetime | None) -> pd.DataFrame:
        """Return only rows newer than `since`. If since is None, return all."""
        if since is None or self._config.force_full:
            log.info("Full load — processing all %d rows", len(df))
            return df
        cutoff = pd.Timestamp(since).tz_convert("UTC")
        delta = df[df["started_at"] > cutoff]
        log.info(
            "Delta load — %d new rows since %s (of %d total)",
            len(delta), since.isoformat(), len(df),
        )
        return delta


# ── Alert cleaner (CSV-specific) ──────────────────────────────────────────────

class AlertCleaner:
    """
    Resolves open-ended events and computes durations.

    Luhansk / Crimea note:
      Vadimkin excludes these permanently-active regions, so is_permanent_outlier
      will always be False here. The flag is set anyway for schema compatibility.
    """

    def clean(self, df: pd.DataFrame, ingest_ts: datetime) -> pd.DataFrame:
        df = df.copy()
        ingest_utc = pd.Timestamp(ingest_ts.astimezone(timezone.utc))

        # is_permanent_outlier — always False for Vadimkin data (kept for schema compat)
        df["is_permanent_outlier"] = False

        # Preserve raw end time before imputation
        df["end_time_raw"] = df["finished_at"]
        df["is_open_ended"] = df["end_time_raw"].isna()

        open_mask = df["is_open_ended"]
        if open_mask.any():
            log.info("Imputing %d open-ended events", open_mask.sum())

        df["end_time_resolved"] = df["end_time_raw"].copy()

        # Recent open-ended (within last 12h): likely still active → cap at ingest_ts
        recently_started = (
            open_mask
            & (df["started_at"] >= ingest_utc - pd.Timedelta(hours=12))
        )
        df.loc[recently_started, "end_time_resolved"] = ingest_utc

        # Old open-ended: clear anomaly → cap at start + MAX_IMPUTE_HOURS
        old_open = open_mask & ~recently_started
        df.loc[old_open, "end_time_resolved"] = (
            df.loc[old_open, "started_at"] + pd.Timedelta(hours=_MAX_IMPUTE_HOURS)
        )

        df["end_time_resolved"] = pd.to_datetime(df["end_time_resolved"], utc=True)

        # Duration — always computed last, after all time values are resolved
        raw_seconds = (
            df["end_time_resolved"] - pd.to_datetime(df["started_at"], utc=True)
        ).dt.total_seconds()

        max_seconds = _MAX_IMPUTE_HOURS * 3600.0
        df["duration_seconds"] = raw_seconds.clip(lower=0, upper=max_seconds).astype("float32")

        return df


# ── Pipeline orchestrator ─────────────────────────────────────────────────────

class IngestionPipeline:
    """End-to-end ingest coordinator."""

    def __init__(self, config: IngestionConfig) -> None:
        self._config = config
        self._fetcher = CsvFetcher(config)
        self._cleaner = AlertCleaner()

    def run(self) -> None:
        ingest_ts = datetime.now(timezone.utc)
        log.info("Ingest started at %s", ingest_ts.isoformat())

        # ── 1–2. Fetch + delta filter ────────────────────────────────────────
        raw_df = self._fetcher.fetch()
        since = None if self._config.force_full else store.read_last_ingest_ts()
        delta_df = self._fetcher.filter_delta(raw_df, since)

        if delta_df.empty:
            log.info("No new records to process — cache is up to date")
            store.write_last_ingest_ts(ingest_ts)
            return

        # ── 3. Clean ─────────────────────────────────────────────────────────
        cleaned = self._cleaner.clean(delta_df, ingest_ts)
        log.info("Cleaned %d records", len(cleaned))

        # ── 4. Write historical Parquet ──────────────────────────────────────
        store.append_raw(cleaned, ingest_ts)

        # ── 5. Recompute rollups ─────────────────────────────────────────────
        log.info("Recomputing aggregation rollups...")
        full_history = store.read_raw()
        if not full_history.empty:
            agg_df = aggregator.compute_rollups(full_history)
            store.write_agg(agg_df)

        # ── 6. Retrain models ────────────────────────────────────────────────
        try:
            from src.analytics.predictor import retrain_models
            log.info("Retraining predictive models...")
            retrain_models(full_history)
        except Exception as exc:
            log.warning("Model retraining failed (non-fatal): %s", exc)

        # ── 7. High-water mark ───────────────────────────────────────────────
        store.write_last_ingest_ts(ingest_ts)
        log.info(
            "Ingest complete — %d new records written. High-water mark: %s",
            len(cleaned), ingest_ts.isoformat(),
        )


# ── Oblast name → ID (mirrors mapper.py; kept local to avoid import dependency)

_OBLAST_NAME_TO_ID: dict[int, str] = {
    1: "Vinnytsia Oblast",
    2: "Volyn Oblast",
    3: "Dnipropetrovsk Oblast",
    4: "Donetsk Oblast",
    5: "Zhytomyr Oblast",
    6: "Zakarpattia Oblast",
    7: "Zaporizhzhia Oblast",
    8: "Ivano-Frankivsk Oblast",
    9: "Kyiv Oblast",
    10: "Kirovohrad Oblast",
    11: "Luhansk Oblast",
    12: "Lviv Oblast",
    13: "Mykolaiv Oblast",
    14: "Odesa Oblast",
    15: "Poltava Oblast",
    16: "Rivne Oblast",
    17: "Sumy Oblast",
    18: "Ternopil Oblast",
    19: "Kharkiv Oblast",
    20: "Kherson Oblast",
    21: "Khmelnytskyi Oblast",
    22: "Cherkasy Oblast",
    23: "Chernivtsi Oblast",
    24: "Chernihiv Oblast",
    25: "Kyiv City",
    26: "Autonomous Republic of Crimea",
}


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Ukrainian air raid alert history from Vadimkin CSV dataset"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force full reload — ignore last ingest timestamp",
    )
    args = parser.parse_args()

    config = IngestionConfig(force_full=args.full)
    pipeline = IngestionPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
