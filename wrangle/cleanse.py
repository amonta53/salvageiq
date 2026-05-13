# =========================================================
# cleanse.py
#
# Purpose:
#     Transform raw scraped listing data into a cleaner, more structured
#     dataset that is ready for downstream validation, classification,
#     and analysis.
#
# High-level responsibilities:
#     1. Load the raw extract CSV
#     2. Normalize text-heavy fields
#     3. Build a combined text field for extractor logic
#     4. Derive cleansed / guessed attributes
#     5. Write the cleansed dataset to disk
#
# Notes:
#     - This step does not try to fully validate business rules.
#       It focuses on cleanup and lightweight validation.
#     - Extracted values are intentionally labeled as "guess" where
#       pproximation parsing is being used.
# =========================================================
from __future__ import annotations

import pandas as pd

from scrape.extractors import (
    clean_price,
    clean_text,
    extract_condition,
    extract_part_guess,
    extract_part_number,
    extract_shipping_text,
    extract_sold_date_guess,
    extract_vehicle_guess,
    extract_year_range,
    extract_years,
)
# =========================================================
# DATA CLEANSING
# =========================================================


def run_cleansing(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Run the cleansing step on a raw scraped listing DataFrame.

    Parameters
    ----------
    raw_df : pd.DataFrame
        Raw listing rows from the scraper (RAW_COLUMNS schema).

    Returns
    -------
    pd.DataFrame
        Cleansed DataFrame with derived fields appended.

    Processing overview
    -------------------
    1. Normalize key text columns used in parsing.
    2. Build a combined text blob from title, subtitle, and raw_text.
    3. Apply extractor functions to derive structured fields such as:
       - cleaned price
       - condition guess
       - sold date guess
       - shipping text
       - vehicle guess
       - part guess
       - part number guess
       - year range guess
       - explicit years found
    """
    df = raw_df.copy()

    if df.empty:
        return df

    required_text_columns = ["title", "subtitle", "listing_url", "raw_text", "price_raw"]
    for column_name in required_text_columns:
        if column_name in df.columns:
            df[column_name] = df[column_name].map(clean_text)

    # Build a combined text field for use in extractors that look across multiple fields
    combined_series = (
        df[["title", "subtitle", "raw_text"]]
        .fillna("")
        .agg(" | ".join, axis=1)
        .str.strip(" |")
    )

    # Normalize and extract fields using the combined text and raw price
    df["price_clean"] = df["price_raw"].map(clean_price)
    df["condition_guess"] = combined_series.map(extract_condition)
    df["sold_date_guess"] = df["raw_text"].map(extract_sold_date_guess)
    df["shipping_text"] = df["raw_text"].map(extract_shipping_text)
    df["vehicle_guess"] = combined_series.map(extract_vehicle_guess)
    df["part_guess"] = combined_series.map(extract_part_guess)
    df["part_number_guess"] = combined_series.map(extract_part_number)
    df["year_range_guess"] = combined_series.map(extract_year_range)
    df["years_found"] = combined_series.map(extract_years)

    return df
