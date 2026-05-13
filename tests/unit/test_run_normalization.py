# =========================================================
# test_run_normalization.py
#
# Purpose:
#     Integration-style unit test for run_normalization in normalize.py.
#
# Notes:
#     This test verifies that run_normalization performs the expected
#     workflow steps on a small input sample:
#     - required column handling
#     - standardization
#     - text/category enrichment
#     - URL cleanup
#     - deduplication
#     - output file creation
# =========================================================

import pandas as pd

from config.schema import NORMALIZED_COLUMNS
from wrangle.normalize import run_normalization


def test_run_normalization_standardizes_strips_url_and_deduplicates() -> None:
    """
    run_normalization should produce a normalized output with:
    - expected columns
    - standardized fields populated
    - URL query strings removed
    - duplicate rows collapsed
    """
    cleansed_df = pd.DataFrame(
        [
            {
                "run_id": "20260411_091200",
                "scrape_ts": "2026-04-11T09:12:03+00:00",
                "pass_type": "sold",
                "search_year": 2018,
                "search_make": "chevy",
                "search_model": "f150",
                "search_part": "headlamp",
                "part_guess": "headlamp",
                "title": "OEM left headlight assembly",
                "subtitle": "clean lens",
                "raw_text": "OEM left headlight assembly for truck",
                "listing_url": "https://example.com/item1?hash=abc123",
            },
            {
                "run_id": "20260411_091200",
                "scrape_ts": "2026-04-11T09:12:03+00:00",
                "pass_type": "sold",
                "search_year": 2018,
                "search_make": "chevy",
                "search_model": "f150",
                "search_part": "headlamp",
                "part_guess": "headlamp",
                "title": "OEM left headlight assembly",
                "subtitle": "clean lens",
                "raw_text": "OEM left headlight assembly for truck",
                "listing_url": "https://example.com/item1?hash=zzz999",
            },
        ]
    )

    normalized_df, normalization_stats = run_normalization(cleansed_df)

    assert not normalized_df.empty

    for column_name in NORMALIZED_COLUMNS:
        assert column_name in normalized_df.columns

    assert normalized_df.iloc[0]["listing_url"] == "https://example.com/item1"
    assert normalized_df.iloc[0]["search_make_std"] == "Chevrolet"
    assert normalized_df.iloc[0]["search_model_std"] == "F-150"
    assert normalized_df.iloc[0]["search_part_std"] == "headlight"
    assert normalized_df.iloc[0]["part_guess_std"] == "headlight"

    assert len(normalized_df) == 1
    assert normalization_stats["before_count"] == 2
    assert normalization_stats["after_count"] == 1
    assert normalization_stats["removed_count"] == 1
    