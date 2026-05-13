# =========================================================
# normalize.py
#
# Purpose:
#     Standardize selected cleansed fields into consistent comparison
#     values for downstream grouping, classification, and analysis.
#
# Responsibilities:
#     1. Normalize make values using configured make aliases
#     2. Normalize model values using configured model aliases
#     3. Normalize part values using configured part aliases
#     4. Classify normalized/raw part text into taxonomy categories
#     5. Strip query-string noise from listing URLs
#
# Notes:
#     - Config files are the source of truth for alias vocabularies.
#     - This module applies those rules to DataFrame columns.
#     - Internal comparisons use normalized lowercase text.
# =========================================================
from __future__ import annotations

import pandas as pd
import logging

from config.taxonomy import (
    CATEGORY_PRIORITY,
    ECM_TERMS,
    PART_ALIASES,
    PART_CATEGORY_MAP,
    PART_TAXONOMY,
    TCM_TERMS,
)
from config.schema import (
    NORMALIZED_COLUMNS,
    NORMALIZATION_REQUIRED_INPUT_COLUMNS,
)
from config.vehicles import MAKE_ALIASES, MODEL_ALIASES 

logger = logging.getLogger(__name__)

def normalize_token(value: str | None) -> str:
    """
    Normalize free-text values for case-insensitive comparisons.

    Rules:
    - convert None / NaN to empty string
    - trim leading/trailing whitespace
    - lowercase for stable comparison
    - collapse repeated internal whitespace

    Examples:
        "  Head Lamp  " -> "head lamp"
        "A/C   Compressor" -> "a/c compressor"
    """
    if value is None or pd.isna(value):
        return ""

    return " ".join(str(value).strip().lower().split())

def standardize_make(value: str | None) -> str | None:
    """
    Standardize vehicle make values using configured make aliases.

    Returns the canonical configured make when an alias is found.
    Otherwise, returns the cleaned original value.
    """
    normalized_value = normalize_token(value)
    if not normalized_value:
        return None

    return MAKE_ALIASES.get(normalized_value, str(value).strip())

def standardize_model(value: str | None) -> str | None:
    """
    Standardize vehicle model values using configured model aliases.

    Returns the canonical configured model when an alias is found.
    Otherwise, returns the cleaned original value.
    """
    normalized_value = normalize_token(value)
    if not normalized_value:
        return None

    return MODEL_ALIASES.get(normalized_value, str(value).strip())


def standardize_part(value: str | None) -> str | None:
    """
    Standardize raw part text into a canonical comparison term.

    Examples:
        "taillight" -> "tail light"
        "headlamp" -> "headlight"
        "pcm" -> "ecu"

    Returns the normalized configured alias when found.
    Otherwise, returns the normalized input text.
    """
    normalized_value = normalize_token(value)
    if not normalized_value:
        return None

    return PART_ALIASES.get(normalized_value, normalized_value)

def classify_part(text: str | None, debug: bool = False) -> str | None:
    """
    Classify listing text into a standard taxonomy category.
    """
    normalized_text = normalize_token(text)
    if not normalized_text:
        if debug:
            print("[NO MATCH] <missing text>")
        return None

    # =========================================================
    # Business rule:
    # Some listings mention both ECM and TCM terms. 
    # For now, we collapse this into Engine Control Module to avoid 
    # fragmenting a very small module sample set.
    # =========================================================
    if any(term in normalized_text for term in ECM_TERMS) and any(term in normalized_text for term in TCM_TERMS):
        if debug:
            print(f"[MATCH] {normalized_text} -> Engine Control Module")
        return "Engine Control Module"

    for category in CATEGORY_PRIORITY:
        rules = PART_TAXONOMY.get(category, {})
        include_terms = rules.get("include", [])
        exclude_terms = rules.get("exclude", [])

        has_include = any(normalize_token(term) in normalized_text for term in include_terms)
        has_exclude = any(normalize_token(term) in normalized_text for term in exclude_terms)

        if has_include and not has_exclude:
            if debug:
                print(f"[MATCH] {normalized_text} -> {category}")
            return category

    if debug:
        print(f"[NO MATCH] {normalized_text}")

    return None 

def category_from_part(value: str | None) -> str | None:
    """
    Map a normalized part label to its standard taxonomy category.

    This is useful when the input is already a part-like value
    rather than a full noisy listing text blob.
    """
    standardized_part = standardize_part(value)
    if not standardized_part:
        return None

    return PART_CATEGORY_MAP.get(standardized_part)



# =========================================================
# Deduplicate listing-level records to prevent inflated counts.
#
# Rationale:
# - eBay surfaces the same listing across multiple search queries
# - Without deduplication, listing_count and sold_count can be inflated
#
# Strategy:
# - Primary key: normalized listing_url (query strings removed upstream)
# - Fallback: title + price + search context (only when URL missing)
#
# Tradeoffs:
# - URL-based dedup is reliable but not perfect for relisted items
# - Fallback is conservative to avoid over-collapsing distinct listings
#
# Notes:
# - Logging added to track deduplication impact on dataset size
# - Returns deduplicated DataFrame and summary stats for monitoring
# =========================================================

def deduplicate_listings(df: pd.DataFrame) -> pd.DataFrame:
    work_df = df.copy()

    required_cols = ["listing_url"]
    missing = [col for col in required_cols if col not in work_df.columns]
    if missing:
        raise ValueError(f"Missing required columns for deduplication: {missing}")

    before_count = len(work_df)

    work_df["listing_url"] = work_df["listing_url"].replace("", pd.NA)
    work_df["title"] = work_df["title"].replace("", pd.NA)

    with_url = work_df[work_df["listing_url"].notna()].copy()
    without_url = work_df[work_df["listing_url"].isna()].copy()

    with_url = with_url.drop_duplicates(subset=["listing_url"], keep="first")

    if not without_url.empty:
        fallback_cols = [
            "title",
            "price",
            "search_make_std",
            "search_model_std",
            "search_part_std",
        ]
        available_cols = [col for col in fallback_cols if col in without_url.columns]
        without_url = without_url.drop_duplicates(subset=available_cols, keep="first")

    deduped_df = pd.concat([with_url, without_url], ignore_index=True)

    after_count = len(deduped_df)
    removed_count = before_count - after_count
    removed_rate = removed_count / before_count if before_count else 0

    logger.info(
        "[DEDUP] %s -> %s (%s removed, %.1f%%)",
        before_count,
        after_count,
        removed_count,
        removed_rate * 100,
    )

    return deduped_df, {
    "before_count": before_count,
    "after_count": after_count,
    "removed_count": removed_count,
    "removed_rate": removed_rate,
}



def run_normalization(cleansed_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Run the normalization step on a cleansed listing DataFrame.

    Parameters
    ----------
    cleansed_df : pd.DataFrame
        Output from run_cleansing().

    Returns
    -------
    tuple[pd.DataFrame, dict]
        normalized_df: Standardized and deduplicated DataFrame.
        dedup_stats:   {"removed_count", "removed_rate", ...}

    Processing overview
    -------------------
    1. Ensure expected input columns exist.
    2. Standardize make, model, and part fields.
    3. Classify part text into stable taxonomy categories.
    4. Remove query-string suffixes from listing URLs.
    5. Deduplicate listings.
    """
    # =========================================================
    # Stage 1: Validate and pad input
    # =========================================================
    df = cleansed_df.copy()

    # Ensure normalization can run even if upstream optional columns
    # are missing from the cleansed dataset.
    for column_name in NORMALIZATION_REQUIRED_INPUT_COLUMNS:
        if column_name not in df.columns:
            df[column_name] = pd.NA

    if df.empty:
        return df.reindex(columns=NORMALIZED_COLUMNS), {"removed_count": 0, "removed_rate": 0.0}
    
    # =========================================================
    # Stage 2: Standardization (make, model, part)
    # =========================================================
    df["search_make_std"] = df["search_make"].map(standardize_make)
    df["search_model_std"] = df["search_model"].map(standardize_model)
    df["search_part_std"] = df["search_part"].map(standardize_part)
    df["part_guess_std"] = df["part_guess"].map(standardize_part)

    # =========================================================
    # Stage 3: Part classification (taxonomy mapping)
    # ========================================================= 
    df["search_part_category"] = df["search_part"].map(category_from_part)
    df["part_guess_category"] = df["part_guess"].map(category_from_part)

    # =========================================================
    # Stage 4: Text-based classification enrichment
    # =========================================================
    combined_text = (
        df[["title", "subtitle", "raw_text"]]
        .fillna("")
        .agg(" | ".join, axis=1)
        .str.strip(" |")
    )

    df["part_category_from_text"] = combined_text.map(classify_part)

    # =========================================================
    # Stage 5: URL normalization
    # =========================================================
    df["listing_url"] = (
        df["listing_url"]
        .astype("string")
        .str.replace(r"\?.*$", "", regex=True)
    )

    # =========================================================
    # Stage 6: Column alignment
    # =========================================================
    df = df.reindex(columns=NORMALIZED_COLUMNS)

    # =========================================================
    # Stage 7: Deduplication
    # =========================================================
    df, dedup_stats = deduplicate_listings(df)

    return df, dedup_stats
