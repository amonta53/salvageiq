# =========================================================
# test_aggregation_smoke.py
# Smoke tests for analysis aggregation logic
#
# Purpose:
# Make sure grouped sold + active analysis runs cleanly and
# returns the core metrics we expect.
# =========================================================

import pandas as pd
import pytest

from analysis.aggregation import (
    build_active_summary,
    build_analysis_summary,
    build_sold_summary,
    validate_columns,
)


# =========================================================
# Test data setup
# =========================================================
class DummyConfig:
    """ Bare minimum config stub for aggregation tests."""

    confidence_active_target = 10
    confidence_sold_target = 10
    confidence_sold_weight = 0.7
    confidence_active_weight = 0.3
    confidence_max_score = 1.0
    confidence_min_sample_flag = 3
    stale_snapshot_hours = 48
    low_sample_total_threshold = 5
    very_low_sold_threshold = 3

    sold_column_map = {
        "year": "search_year",
        "make": "search_make",
        "model": "search_model",
        "part": "search_part_std",
        "price": "price_clean",
        "timestamp": "scrape_ts",
    }

    active_column_map = {
        "year": "search_year",
        "make": "search_make",
        "model": "search_model",
        "part": "search_part",
        "active_count": "active_count",
        "timestamp": "scrape_ts",
    }


# =========================================================
# validate_columns smoke test
# =========================================================
def test_validate_columns_raises_for_missing_column() -> None:
    """ Makes sure we fail fast when required columns are missing. """

    df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
            }
        ]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_columns(
            df,
            ["search_year", "search_make", "search_model"],
            "sold_df",
        )

    assert "search_model" in str(exc_info.value)


# =========================================================
#  build_analysis_summary smoke test
# =========================================================
def test_build_analysis_summary_smoke() -> None:
    """
    Happy path test for full analysis pipeline.

    What this checks:
    - sold and active join correctly
    - STR is calculated correctly
    - confidence score is present
    - opportunity score is present
    - parts stay isolated from each other

    Failure here usually means:
    - Grouping keys are wrong
    - Join is off (most common)
    - Calculation formulas are broken
    """

    config = DummyConfig()

    sold_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 100.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 120.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "headlight",
                "price_clean": 80.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
        ]
    )

    active_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "alternator",
                "active_count": 3,
                "scrape_ts": "2026-04-11 12:00:00",
            },
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "headlight",
                "active_count": 1,
                "scrape_ts": "2026-04-11 12:00:00",
            },
        ]
    )

    result = build_analysis_summary(sold_df, active_df, config)

    assert len(result) == 2

    alternator_row = result[result["part"] == "alternator"].iloc[0]
    headlight_row = result[result["part"] == "headlight"].iloc[0]

    assert alternator_row["sold_count"] == 2
    assert alternator_row["active_count"] == 3
    assert alternator_row["median_sold_price"] == 110.0
    assert alternator_row["str"] == 0.4
    assert alternator_row["confidence_score"] > 0.0
    assert alternator_row["opportunity_score"] > 0.0

    assert headlight_row["sold_count"] == 1
    assert headlight_row["active_count"] == 1
    assert headlight_row["median_sold_price"] == 80.0
    assert headlight_row["str"] == 0.5
    assert headlight_row["confidence_score"] > 0.0
    assert headlight_row["opportunity_score"] > 0.0


# =========================================================
# validate sold summary grouping logic
# =========================================================
def test_build_sold_summary_groups_correctly() -> None:
    """
    Verifies sold-side aggregation behavior.

    What matters here:
    - Rows collapse correctly by vehicle + part
    - Counts are accurate
    - Median price is used (not mean)
    - Latest scrape_ts is carried forward

    If this fails, your downstream analysis is garbage,
    even if everything else "runs fine".
    """

    config = DummyConfig()

    sold_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 100.0,
                "scrape_ts": "2026-04-11 09:00:00",
            },
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 120.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
        ]
    )

    result = build_sold_summary(sold_df, config)

    assert len(result) == 1
    assert result.loc[0, "year"] == 2018
    assert result.loc[0, "make"] == "Toyota"
    assert result.loc[0, "model"] == "Camry"
    assert result.loc[0, "part"] == "alternator"
    assert result.loc[0, "sold_count"] == 2
    assert result.loc[0, "median_sold_price"] == 110.0
    assert result.loc[0, "mean_sold_price"] == 110.0
    assert result.loc[0, "min_sold_price"] == 100.0
    assert result.loc[0, "max_sold_price"] == 120.0
    assert result.loc[0, "sold_timestamp"] == "2026-04-11 10:00:00"


# =========================================================
#  validate default active count behavior
# =========================================================
def test_build_active_summary_preserves_active_snapshot_rows() -> None:
    """
    Verify active summary keeps row-level active snapshot records and
    standardizes the column names used for the downstream join.

    Why this matters:
    Active market data is already summarized upstream. This function is
    not aggregating again. It is only validating, selecting, and renaming
    the active-side fields needed by the analysis layer.
    """
    config = DummyConfig()

    active_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "toyota",
                "search_model": "camry",
                "search_part": "alternator",
                "active_count": 3,
                "scrape_ts": "2026-04-10 10:00:00",
            },
            {
                "search_year": 2018,
                "search_make": "toyota",
                "search_model": "camry",
                "search_part": "alternator",
                "active_count": 5,
                "scrape_ts": "2026-04-11 10:00:00",
            },
        ]
    )

    result = build_active_summary(active_df, config)

    assert len(result) == 2

    assert list(result.columns) == [
        "year",
        "make",
        "model",
        "part",
        "active_count",
        "timestamp",
    ]

    older_row = result.loc[result["timestamp"] == "2026-04-10 10:00:00"].iloc[0]
    newer_row = result.loc[result["timestamp"] == "2026-04-11 10:00:00"].iloc[0]

    assert older_row["year"] == 2018
    assert older_row["make"] == "toyota"
    assert older_row["model"] == "camry"
    assert older_row["part"] == "alternator"
    assert older_row["active_count"] == 3

    assert newer_row["active_count"] == 5


# =========================================================
#  Missing active rows default to zero
# =========================================================
def test_build_analysis_summary_defaults_missing_active_count_to_zero() -> None:
    """
    If sold exists and active does not, active_count should fall back to 0.
    """
    config = DummyConfig()

    sold_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 100.0,
                "scrape_ts": "2026-04-11 10:00:00",
            }
        ]
    )

    active_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "headlight",
                "active_count": 2,
                "scrape_ts": "2026-04-11 12:00:00",
            }
        ]
    )

    result = build_analysis_summary(sold_df, active_df, config)

    assert len(result) == 1
    assert result.loc[0, "part"] == "alternator"
    assert result.loc[0, "active_count"] == 0
    assert result.loc[0, "str"] == 1.0


# =========================================================
#  validate join isolation across vehicle keys
# =========================================================
def test_build_analysis_summary_joins_on_full_vehicle_key() -> None:
    """
    Makes sure joins include YEAR as part of the key.

    This is subtle but critical:
    Same part across different years should NOT share active counts.

    If this fails:
    - You're under/over counting inventory
    - STR becomes unreliable
    - Results look "reasonable" but are wrong
    """

    config = DummyConfig()

    sold_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 100.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
            {
                "search_year": 2019,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part_std": "alternator",
                "price_clean": 150.0,
                "scrape_ts": "2026-04-11 10:00:00",
            },
        ]
    )

    active_df = pd.DataFrame(
        [
            {
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "alternator",
                "active_count": 3,
                "scrape_ts": "2026-04-11 12:00:00",
            }
        ]
    )

    result = build_analysis_summary(sold_df, active_df, config)

    row_2018 = result[result["year"] == 2018].iloc[0]
    row_2019 = result[result["year"] == 2019].iloc[0]

    assert row_2018["active_count"] == 3
    assert row_2019["active_count"] == 0
