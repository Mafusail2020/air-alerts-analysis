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
import io
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
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
# Actual CSV columns (official_data_en.csv, verified 2026-06-20):
#   oblast, raion, hromada, level, started_at, finished_at, source
# No id or alert_type columns — both are synthesised during normalisation.
#
# The CSV `oblast` column uses Ukrainian administrative names in Latin
# transliteration ("Kyivska oblast", "Odeska oblast") — NOT English names.
# These are mapped to English GeoJSON name_en values below so that Parquet
# oblast_name values are click-compatible with the choropleth map.
_CSV_REQUIRED_COLS: frozenset[str] = frozenset({"oblast", "started_at", "finished_at", "level"})

# Explicit mapping: raw CSV oblast value → canonical GeoJSON name_en.
# GeoJSON name_en is the source of truth because it is the value Plotly
# returns in on_select events when the user clicks a region.
# "Kiev" and "Odessa" are corrected to modern spellings ("Kyiv", "Odesa")
# by map.py's _load_geojson() so both sides stay in sync.
_VADIMKIN_TO_CANONICAL: dict[str, str] = {
    # Ukrainian administrative name → canonical English
    "Cherkaska oblast":      "Cherkasy Oblast",
    "Chernihivska oblast":   "Chernihiv Oblast",
    "Chernivetska oblast":   "Chernivtsi Oblast",
    "Dnipropetrovska oblast":"Dnipropetrovsk Oblast",
    "Donetska oblast":       "Donetsk Oblast",
    "Ivano-Frankivska oblast":"Ivano-Frankivsk Oblast",
    "Kharkivska oblast":     "Kharkiv Oblast",
    "Khersonska oblast":     "Kherson Oblast",
    "Khmelnytska oblast":    "Khmelnytskyi Oblast",
    "Kirovohradska oblast":  "Kirovohrad Oblast",
    "Kyivska oblast":        "Kyiv Oblast",
    "Luhanska oblast":       "Luhansk Oblast",
    "Lvivska oblast":        "Lviv Oblast",
    "Mykolaivska oblast":    "Mykolaiv Oblast",
    "Odeska oblast":         "Odesa Oblast",
    "Poltavska oblast":      "Poltava Oblast",
    "Rivnenska oblast":      "Rivne Oblast",
    "Sumska oblast":         "Sumy Oblast",
    "Ternopilska oblast":    "Ternopil Oblast",
    "Vinnytska oblast":      "Vinnytsia Oblast",
    "Volynska oblast":       "Volyn Oblast",
    "Zakarpatska oblast":    "Zakarpattia Oblast",
    "Zaporizka oblast":      "Zaporizhia Oblast",
    "Zhytomyrska oblast":    "Zhytomyr Oblast",
    # Kyiv City — no GeoJSON polygon, kept in data for analytics
    "Kyiv City":             "Kyiv City",
    "m. Kyiv":               "Kyiv City",
    # Legacy English short names (guard against dataset rollback)
    "Cherkasy":              "Cherkasy Oblast",
    "Chernihiv":             "Chernihiv Oblast",
    "Chernivtsi":            "Chernivtsi Oblast",
    "Dnipropetrovsk":        "Dnipropetrovsk Oblast",
    "Donetsk":               "Donetsk Oblast",
    "Ivano-Frankivsk":       "Ivano-Frankivsk Oblast",
    "Kharkiv":               "Kharkiv Oblast",
    "Kherson":               "Kherson Oblast",
    "Khmelnytskyi":          "Khmelnytskyi Oblast",
    "Kirovohrad":            "Kirovohrad Oblast",
    "Kyiv":                  "Kyiv Oblast",
    "Luhansk":               "Luhansk Oblast",
    "Lviv":                  "Lviv Oblast",
    "Mykolaiv":              "Mykolaiv Oblast",
    "Odesa":                 "Odesa Oblast",
    "Poltava":               "Poltava Oblast",
    "Rivne":                 "Rivne Oblast",
    "Sumy":                  "Sumy Oblast",
    "Ternopil":              "Ternopil Oblast",
    "Vinnytsia":             "Vinnytsia Oblast",
    "Volyn":                 "Volyn Oblast",
    "Zakarpattia":           "Zakarpattia Oblast",
    "Zaporizhzhia":          "Zaporizhia Oblast",
    "Zhytomyr":              "Zhytomyr Oblast",
}


def _normalize_oblast_name(raw: str) -> str | None:
    """Map a raw CSV oblast value to canonical GeoJSON name_en.

    Returns None for unrecognised values so the row can be dropped cleanly.
    """
    name = raw.strip()
    if name in _VADIMKIN_TO_CANONICAL:
        return _VADIMKIN_TO_CANONICAL[name]
    # Autonomous Republic of Crimea — excluded from Vadimkin but guard anyway
    if "Krym" in name or "Crimea" in name:
        return "Autonomous Republic of Crimea"
    return None

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
            # Use httpx (certifi-backed SSL) instead of pd.read_csv(url) which
            # uses urllib and fails on macOS Python 3.10 due to missing CA certs.
            with httpx.Client(timeout=self._config.csv_read_timeout, follow_redirects=True) as client:
                resp = client.get(self._config.csv_url)
                resp.raise_for_status()
            df = pd.read_csv(io.BytesIO(resp.content), dtype=str, low_memory=False)
        except Exception as exc:
            log.error("CSV download failed: %s", exc)
            raise

        log.info("Downloaded %d rows, columns: %s", len(df), list(df.columns))
        return self._normalize_schema(df)

    def _normalize_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map actual CSV columns to internal schema and synthesise missing fields."""
        missing = _CSV_REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV schema mismatch — required columns absent: {sorted(missing)}\n"
                f"Actual columns: {list(df.columns)}"
            )

        df = df.copy()

        # Parse timestamps — CSV stores UTC ISO strings
        for col in ("started_at", "finished_at"):
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

        # Synthesise a stable integer id: hash of (oblast, started_at string).
        # Reproducible across runs so deduplication in store.append_raw() works.
        # hash_pandas_object returns uint64; view bits as int64 to avoid safe-cast
        # overflow (uint64 values > 2^63 cannot be safely cast to signed Int64).
        hash_u64 = pd.util.hash_pandas_object(
            df[["oblast", "started_at"]].astype(str), index=False
        ).to_numpy()
        df["id"] = pd.array(hash_u64.view(np.int64), dtype="Int64")

        # All records in this dataset are air raid siren events.
        df["alert_type"] = "air_raid"

        # Map raw CSV oblast values to canonical GeoJSON name_en strings.
        # Returns None for unrecognised names; those rows are dropped by dropna below.
        df["oblast_name"] = df["oblast"].apply(_normalize_oblast_name)
        df["region_type"] = df["level"].str.strip()
        df["mapping_source"] = "direct"

        name_to_id = {v: k for k, v in _OBLAST_NAME_TO_ID.items()}
        df["oblast_id"] = df["oblast_name"].map(name_to_id).astype("Int16")

        unmapped = df["oblast_id"].isna().sum()
        if unmapped:
            unknown = df.loc[df["oblast_id"].isna(), "oblast_name"].unique().tolist()
            log.warning("%d rows have unrecognised oblast names: %s", unmapped, unknown)

        # raion_id not available as integer in this dataset
        df["raion_id"] = pd.NA
        df["raion_id"] = df["raion_id"].astype("Int16")

        return df.dropna(subset=["id", "started_at", "oblast_name"])

    def filter_delta(self, df: pd.DataFrame, since: datetime | None) -> pd.DataFrame:
        """Return only rows newer than `since`. If since is None, return all."""
        if since is None or self._config.force_full:
            log.info("Full load — processing all %d rows", len(df))
            return df
        ts = pd.Timestamp(since)
        cutoff = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
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

        # Duration — computed before deduplication; recalculated after merge
        raw_seconds = (
            df["end_time_resolved"] - pd.to_datetime(df["started_at"], utc=True)
        ).dt.total_seconds()

        max_seconds = _MAX_IMPUTE_HOURS * 3600.0
        df["duration_seconds"] = raw_seconds.clip(lower=0, upper=max_seconds).astype("float32")

        # Collapse overlapping alert windows per oblast.
        # The dataset emits separate rows for oblast-, raion-, and hromada-level
        # alerts for the same underlying event. Keeping all rows inflates both
        # frequency counts and duration sums. _merge_overlapping_intervals reduces
        # each cluster of overlapping intervals to the single covering window,
        # then recomputes duration from the (potentially extended) end_time_resolved.
        before = len(df)
        df = self._merge_overlapping_intervals(df)
        dropped = before - len(df)
        if dropped:
            log.info("Deduplication merged %d sub-level rows into parent intervals", dropped)

        return df

    @staticmethod
    def _merge_overlapping_intervals(df: pd.DataFrame) -> pd.DataFrame:
        """Collapse overlapping alert windows per oblast into covering intervals.

        Algorithm (vectorised sweep-line, O(n log n) due to sort):
          1. Within each oblast group, sort ascending by start_time; break ties
             by level priority (oblast > raion > hromada) so the highest-level
             row survives as the representative.
          2. Mark a new interval block wherever a row's start_time exceeds the
             cumulative-maximum end_time of all preceding rows in the group.
          3. Within each block, extend end_time_resolved to the block maximum
             so the surviving row covers all merged rows.
          4. Keep only the first (highest-priority) row per block via
             drop_duplicates; recompute duration_seconds from the final window.
        """
        if df.empty:
            return df

        _LEVEL_ORDER = {"oblast": 0, "raion": 1, "hromada": 2}
        parts: list[pd.DataFrame] = []

        for _, grp in df.groupby("oblast_name", sort=False):
            g = grp.copy()

            # Sort: earlier start first; higher administrative level wins on ties
            g["_prio"] = g["region_type"].map(_LEVEL_ORDER).fillna(99).astype(int)
            g = (
                g.sort_values(["started_at", "_prio"])
                .drop(columns=["_prio"])
                .reset_index(drop=True)
            )

            # Cumulative max of all previous end_time_resolved values.
            # At position i this equals max(end[0..i-1]) — the farthest any
            # already-started interval extends before row i begins.
            prev_max_end = g["end_time_resolved"].shift(1).cummax()

            # A new disjoint block begins where this row starts AFTER the
            # running maximum end.  The first row always starts a new block.
            is_new_block = g["started_at"] > prev_max_end
            is_new_block.iloc[0] = True
            g["_block"] = is_new_block.cumsum()

            # Extend every row's end_time_resolved to its block's maximum,
            # then keep only the first (highest-priority) row per block.
            g["end_time_resolved"] = g.groupby("_block")["end_time_resolved"].transform("max")
            survivors = (
                g.drop_duplicates(subset="_block", keep="first")
                .drop(columns=["_block"])
                .reset_index(drop=True)
            )

            parts.append(survivors)

        merged = pd.concat(parts, ignore_index=True)

        # Recompute duration — end_time_resolved may have been extended
        merged["duration_seconds"] = (
            (merged["end_time_resolved"] - merged["started_at"])
            .dt.total_seconds()
            .clip(lower=0, upper=_MAX_IMPUTE_HOURS * 3600.0)
            .astype("float32")
        )
        return merged


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
    7: "Zaporizhia Oblast",
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
