# =========================================================
# test_analyze_smoke.py
# Smoke tests for analysis controller flow
#
# Purpose:
# Verify that analyze.py accepts DataFrames, runs the analysis layer,
# applies final output mapping, and returns the expected structure.
# =========================================================

import pandas as pd

from analysis.analyze import run_analysis


# =========================================================
# Test config stub
# =========================================================
class DummyConfig:
    confidence_active_target = 10
    confidence_sold_target = 10
    confidence_sold_weight = 0.7
    confidence_active_weight = 0.3
    confidence_max_score = 1.0
    stale_snapshot_hours = 48
    low_sample_total_threshold = 5
    very_low_sold_threshold = 3
    top_n_parts = 10

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
# 1. run_analysis smoke test
# =========================================================
def test_run_analysis_returns_expected_structure() -> None:
    """
    Verify the analysis controller accepts DataFrames, builds the
    analysis summary, and returns the expected in-memory structure.
    """
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

    config = DummyConfig()

    result = run_analysis(
        sold_df=sold_df,
        active_df=active_df,
        config=config,
    )

    assert "analysis_df" in result
    assert "top_ranked_df" in result
    assert "full_ranked_df" in result

    output_df = result["analysis_df"]

    assert len(output_df) == 1
    assert output_df.loc[0, "year"] == 2018
    assert output_df.loc[0, "make"] == "Toyota"
    assert output_df.loc[0, "model"] == "Camry"
    assert output_df.loc[0, "part"] == "alternator"
    assert output_df.loc[0, "sold_count"] == 2
    assert output_df.loc[0, "active_count"] == 3
    assert output_df.loc[0, "median_price"] == 110.0
    assert output_df.loc[0, "avg_price"] == 110.0
    assert output_df.loc[0, "str"] == 0.4
    assert output_df.loc[0, "confidence_score"] > 0.0
    assert output_df.loc[0, "opportunity_score"] > 0.0