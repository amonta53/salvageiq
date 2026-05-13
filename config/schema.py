# =========================================================
# schema.py
# Shared CSV column contracts for the SalvageIQ pipeline.
#
# Purpose:
# - Defines expected columns for raw, cleansed, normalized, and summary outputs
# - Keeps pipeline stages aligned on a common contract
#
# Notes:
# - Raw columns should match scrape output exactly
# - Downstream stages may append columns, but should not rename them casually
# - If scrape output changes, update this file first
# =========================================================

# =========================================================
# Raw scrape output
# =========================================================
RAW_COLUMNS = [
    "run_id",
    "scrape_ts",
    "pass_type", 
    "search_year",
    "search_make",
    "search_model",
    "search_part",
    "search_url",
    "search_page",
    "title",
    "price_raw",
    "subtitle",
    "listing_url",
    "raw_text",
]

# =========================================================
# Cleansed output
# =========================================================
CLEANSED_COLUMNS = RAW_COLUMNS + [
    "price_clean",
    "condition_guess",
    "sold_date_guess",
    "shipping_text",
    "vehicle_guess",
    "part_guess",
    "part_number_guess",
    "year_range_guess",
    "years_found",
]

# =========================================================
# Normalized output
# =========================================================
NORMALIZATION_REQUIRED_INPUT_COLUMNS = [
    "search_make",
    "search_model",
    "search_part",
    "part_guess",
    "title",
    "subtitle",
    "raw_text",
    "listing_url",
]

NORMALIZATION_DERIVED_COLUMNS = [
    "search_make_std",
    "search_model_std",
    "search_part_std",
    "part_guess_std",
    "search_part_category",
    "part_guess_category",
    "part_category_from_text",
]

NORMALIZED_COLUMNS = CLEANSED_COLUMNS + NORMALIZATION_DERIVED_COLUMNS

# =========================================================
# Analysis summary output
# =========================================================

ANALYSIS_EXPORT_RENAME_MAP = {
    "median_sold_price": "median_price",
    "mean_sold_price": "avg_price",
    "min_sold_price": "min_price",
    "max_sold_price": "max_price",
}

ANALYSIS_OUTPUT_COLUMNS = [
    "year",
    "make",
    "model",
    "part",
    "sold_count",
    "active_count",
    "total_count",
    "median_price",
    "avg_price",
    "min_price",
    "max_price",
    "str",
    "confidence_score",
    "opportunity_score",
    "sold_timestamp",
    "active_timestamp",
    "time_diff_hours",
    "stale_snapshot_flag",
    "low_sample_flag",
    "very_low_sold_flag",
]

# =========================================================
# MARKET SUMMARY SCHEMA
# =========================================================

MARKET_SUMMARY_COLUMNS = [
    "run_id",
    "scrape_ts",
    "pass_type", 
    "search_key",
    "execution_key",
    "search_scope",
    "search_year",
    "search_make",
    "search_model",
    "search_part",
    "search_url",
    "result_count",
    "page_count_observed"
]

# =========================================================
# Analysis column roles
# =========================================================

SOLD_COLUMN_MAP = {
    "run_id": "run_id",
    "timestamp": "scrape_ts",
    "title": "title",
    "price": "price_clean",
    "part": "search_part_std",
    "year": "search_year",
    "make": "search_make",
    "model": "search_model",
}

ACTIVE_COLUMN_MAP = {
    "run_id": "run_id", 
    "timestamp": "scrape_ts",
    "part": "search_part",
    "active_count": "result_count",
    "year": "search_year",
    "make": "search_make",
    "model": "search_model",
}

# =========================================================
# Ranking output columns
# =========================================================
RANKED_OUTPUT_COLUMNS = [
    "year",
    "make",
    "model",
    "vehicle_key",
    "part",
    "median_sold_price",
    "str",
    "sold_count",
    "active_count",
    "confidence_score",
    "opportunity_score",
    "vehicle_rank",
]

RANKED_DERIVED_COLUMNS = [
    "vehicle_key", 
    "vehicle_rank",
]