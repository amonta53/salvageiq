# =========================================================
# test_wrangle_smoke.py
# Smoke test for the cleanse → normalize wrangle flow
#
# Purpose:
# Verify the wrangle pipeline can accept a raw DataFrame,
# normalize listing fields, deduplicate rows, and return
# the expected structure — without any file I/O.
# =========================================================

import pandas as pd

from wrangle.cleanse import run_cleansing
from wrangle.normalize import run_normalization


def test_wrangle_smoke() -> None:
    """
    Verify the full cleanse → normalize flow works end-to-end on
    a small in-memory DataFrame.

    What this checks:
    - run_cleansing accepts a raw DataFrame and returns a cleansed one
    - run_normalization standardizes make/model/part fields
    - Duplicate listing URLs collapse after canonicalization
    - Output contains the expected standardized columns
    """
    raw_df = pd.DataFrame(
        [
            {
                "run_id": "test-run",
                "scrape_ts": "2026-04-10 10:00:00",
                "pass_type": "sold",
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "alternator",
                "search_url": "https://www.ebay.com/sch/i.html?_nkw=alternator",
                "search_page": 1,
                "title": "2018 Toyota Camry Alternator OEM",
                "price_raw": "$125.00",
                "subtitle": "Free shipping",
                "listing_url": "https://www.ebay.com/itm/12345?_trkparms=abc",
                "raw_text": "2018 Toyota Camry Alternator OEM Free shipping",
            },
            {
                # Same listing URL (different query string) — should deduplicate
                "run_id": "test-run",
                "scrape_ts": "2026-04-10 10:00:00",
                "pass_type": "sold",
                "search_year": 2018,
                "search_make": "TOYOTA",
                "search_model": "camry",
                "search_part": "alt",
                "search_url": "https://www.ebay.com/sch/i.html?_nkw=alternator",
                "search_page": 1,
                "title": "2018 Toyota Camry Alternator OEM",
                "price_raw": "$125.00",
                "subtitle": "Free shipping",
                "listing_url": "https://www.ebay.com/itm/12345?_trkparms=xyz",
                "raw_text": "2018 Toyota Camry Alternator OEM Free shipping",
            },
            {
                "run_id": "test-run",
                "scrape_ts": "2026-04-10 10:00:00",
                "pass_type": "sold",
                "search_year": 2018,
                "search_make": "Toyota",
                "search_model": "Camry",
                "search_part": "headlight",
                "search_url": "https://www.ebay.com/sch/i.html?_nkw=headlight",
                "search_page": 1,
                "title": "2018 Toyota Camry Headlight Assembly",
                "price_raw": "$210.00",
                "subtitle": None,
                "listing_url": "https://www.ebay.com/itm/99999",
                "raw_text": "2018 Toyota Camry Headlight Assembly",
            },
        ]
    )

    cleansed_df = run_cleansing(raw_df)
    normalized_df, dedup_stats = run_normalization(cleansed_df)

    assert not normalized_df.empty

    # Two distinct listing URLs after query-string stripping
    assert len(normalized_df) == 2, (
        f"Expected 2 rows after dedup, got {len(normalized_df)}"
    )
    assert dedup_stats["removed_count"] == 1

    alternator_row = normalized_df.loc[
        normalized_df["listing_url"].str.contains("/itm/12345", na=False)
    ].iloc[0]

    assert alternator_row["search_make_std"] == "Toyota"
    assert alternator_row["search_model_std"] == "Camry"
    assert alternator_row["search_part_std"] == "alternator"

    headlight_row = normalized_df.loc[
        normalized_df["listing_url"].str.contains("/itm/99999", na=False)
    ].iloc[0]

    assert headlight_row["search_part_std"] == "headlight"
