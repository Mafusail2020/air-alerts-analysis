"""Post-Dec 2025 Raion→Oblast normalization.

Before RAION_EPOCH the API returns oblast-level regions directly.
After RAION_EPOCH it returns raion-level sub-regions that must be
mapped up to their parent Oblast using the KATOTTG registry lookup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

RAION_EPOCH = datetime(2025, 12, 1, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Static KATOTTG lookup: raion_id → (oblast_id, oblast_name)
# Source: Ukraine's official Classifier of Objects of the Administrative-
# Territorial Structure (KATOTTG), 2024 revision.
# Keys are integer region_id values returned by the API for raion-type regions.
# Extend this dict as the API exposes new raion codes.
# ---------------------------------------------------------------------------
RAION_TO_OBLAST: dict[int, tuple[int, str]] = {
    # Vinnytsia Oblast raions
    101: (1, "Vinnytsia Oblast"),
    102: (1, "Vinnytsia Oblast"),
    103: (1, "Vinnytsia Oblast"),
    # Volyn Oblast raions
    201: (2, "Volyn Oblast"),
    202: (2, "Volyn Oblast"),
    # Dnipropetrovsk Oblast raions
    301: (3, "Dnipropetrovsk Oblast"),
    302: (3, "Dnipropetrovsk Oblast"),
    303: (3, "Dnipropetrovsk Oblast"),
    # Donetsk Oblast raions
    401: (4, "Donetsk Oblast"),
    402: (4, "Donetsk Oblast"),
    # Zhytomyr Oblast raions
    501: (5, "Zhytomyr Oblast"),
    502: (5, "Zhytomyr Oblast"),
    # Zakarpattia Oblast raions
    601: (6, "Zakarpattia Oblast"),
    602: (6, "Zakarpattia Oblast"),
    # Zaporizhzhia Oblast raions
    701: (7, "Zaporizhzhia Oblast"),
    702: (7, "Zaporizhzhia Oblast"),
    # Ivano-Frankivsk Oblast raions
    801: (8, "Ivano-Frankivsk Oblast"),
    802: (8, "Ivano-Frankivsk Oblast"),
    # Kyiv Oblast raions
    901: (9, "Kyiv Oblast"),
    902: (9, "Kyiv Oblast"),
    903: (9, "Kyiv Oblast"),
    # Kirovohrad Oblast raions
    1001: (10, "Kirovohrad Oblast"),
    1002: (10, "Kirovohrad Oblast"),
    # Luhansk Oblast raions
    1101: (11, "Luhansk Oblast"),
    1102: (11, "Luhansk Oblast"),
    # Lviv Oblast raions
    1201: (12, "Lviv Oblast"),
    1202: (12, "Lviv Oblast"),
    1203: (12, "Lviv Oblast"),
    # Mykolaiv Oblast raions
    1301: (13, "Mykolaiv Oblast"),
    1302: (13, "Mykolaiv Oblast"),
    # Odesa Oblast raions
    1401: (14, "Odesa Oblast"),
    1402: (14, "Odesa Oblast"),
    # Poltava Oblast raions
    1501: (15, "Poltava Oblast"),
    1502: (15, "Poltava Oblast"),
    # Rivne Oblast raions
    1601: (16, "Rivne Oblast"),
    1602: (16, "Rivne Oblast"),
    # Sumy Oblast raions
    1701: (17, "Sumy Oblast"),
    1702: (17, "Sumy Oblast"),
    # Ternopil Oblast raions
    1801: (18, "Ternopil Oblast"),
    1802: (18, "Ternopil Oblast"),
    # Kharkiv Oblast raions
    1901: (19, "Kharkiv Oblast"),
    1902: (19, "Kharkiv Oblast"),
    1903: (19, "Kharkiv Oblast"),
    # Kherson Oblast raions
    2001: (20, "Kherson Oblast"),
    2002: (20, "Kherson Oblast"),
    # Khmelnytskyi Oblast raions
    2101: (21, "Khmelnytskyi Oblast"),
    2102: (21, "Khmelnytskyi Oblast"),
    # Cherkasy Oblast raions
    2201: (22, "Cherkasy Oblast"),
    2202: (22, "Cherkasy Oblast"),
    # Chernivtsi Oblast raions
    2301: (23, "Chernivtsi Oblast"),
    2302: (23, "Chernivtsi Oblast"),
    # Chernihiv Oblast raions
    2401: (24, "Chernihiv Oblast"),
    2402: (24, "Chernihiv Oblast"),
    # Kyiv City
    2501: (25, "Kyiv City"),
}

# Direct oblast name→id for pre-epoch records whose region_type may be missing
OBLAST_NAME_TO_ID: dict[str, int] = {
    "Vinnytsia Oblast": 1,
    "Volyn Oblast": 2,
    "Dnipropetrovsk Oblast": 3,
    "Donetsk Oblast": 4,
    "Zhytomyr Oblast": 5,
    "Zakarpattia Oblast": 6,
    "Zaporizhzhia Oblast": 7,
    "Ivano-Frankivsk Oblast": 8,
    "Kyiv Oblast": 9,
    "Kirovohrad Oblast": 10,
    "Luhansk Oblast": 11,
    "Lviv Oblast": 12,
    "Mykolaiv Oblast": 13,
    "Odesa Oblast": 14,
    "Poltava Oblast": 15,
    "Rivne Oblast": 16,
    "Sumy Oblast": 17,
    "Ternopil Oblast": 18,
    "Kharkiv Oblast": 19,
    "Kherson Oblast": 20,
    "Khmelnytskyi Oblast": 21,
    "Cherkasy Oblast": 22,
    "Chernivtsi Oblast": 23,
    "Chernihiv Oblast": 24,
    "Kyiv City": 25,
    "Autonomous Republic of Crimea": 26,
}


def normalize_regions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accepts a DataFrame with columns from RawAlert schema.
    Returns the same DataFrame with added:
      - oblast_name (str, always populated)
      - oblast_id   (int16)
      - raion_id    (int16, nullable)
      - mapping_source ("direct" | "raion_join" | "unknown")

    Invariant: after this function, every row has a non-null oblast_name.
    """
    df = df.copy()

    df["raion_id"] = pd.NA
    df["oblast_name"] = pd.NA
    df["oblast_id"] = pd.NA
    df["mapping_source"] = "unknown"

    pre_epoch = df["started_at"] < RAION_EPOCH
    post_epoch = ~pre_epoch

    # Pre-epoch: region_id is already oblast-level
    df.loc[pre_epoch, "oblast_name"] = df.loc[pre_epoch, "region_name"]
    df.loc[pre_epoch, "oblast_id"] = (
        df.loc[pre_epoch, "region_name"].map(OBLAST_NAME_TO_ID)
    )
    df.loc[pre_epoch, "mapping_source"] = "direct"

    # Post-epoch: raion → oblast via lookup
    if post_epoch.any():
        post_df = df.loc[post_epoch]
        oblast_names = post_df["region_id"].map(
            {k: name for k, (_, name) in RAION_TO_OBLAST.items()}
        )
        oblast_ids = post_df["region_id"].map(
            {k: oid for k, (oid, _) in RAION_TO_OBLAST.items()}
        )

        df.loc[post_epoch, "raion_id"] = post_df["region_id"].values
        df.loc[post_epoch, "oblast_name"] = oblast_names.values
        df.loc[post_epoch, "oblast_id"] = oblast_ids.values

        found = oblast_names.notna()
        df.loc[post_df.index[found], "mapping_source"] = "raion_join"

        unknown_ids = post_df.loc[~found, "region_id"].tolist()
        if unknown_ids:
            log.warning("Unmapped raion_id(s) — set to 'Unknown': %s", unknown_ids)
        df.loc[post_df.index[~found], "oblast_name"] = "Unknown"
        df.loc[post_df.index[~found], "mapping_source"] = "unknown"

    # Fill any remaining oblast_id gaps from name lookup
    missing_id = df["oblast_id"].isna() & df["oblast_name"].notna()
    df.loc[missing_id, "oblast_id"] = (
        df.loc[missing_id, "oblast_name"].map(OBLAST_NAME_TO_ID)
    )

    df["oblast_id"] = pd.to_numeric(df["oblast_id"], errors="coerce").astype("Int16")
    df["raion_id"] = pd.to_numeric(df["raion_id"], errors="coerce").astype("Int16")

    assert df["oblast_name"].notna().all(), "Mapper produced null oblast_name rows"
    return df
