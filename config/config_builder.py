# =========================================================
# config_builder.py
# Build runtime ScrapeConfig objects by named mode.
# =========================================================

from __future__ import annotations

from config.scrape_config import ScrapeConfig


def build_scrape_config(mode: str = "full") -> ScrapeConfig:
    """
    Build a runtime ScrapeConfig for the requested mode.

    Modes:
    - full  — all configured vehicles, full year range (slow)
    - mini  — 1 vehicle, 2 years, 2 parts — quick pipeline check
    - test  — 1 vehicle, 1 year, 1 part — fast smoke test
    """
    mode = mode.lower().strip()

    if mode == "test":
        return ScrapeConfig(
            mode="test",
            start_year=2019,
            end_year=2019,
            parts=["alternator"],
            supported_vehicles=[
                {"year_range": (2012, 2020), "make": "Toyota", "model": "Camry"}
            ],
            max_pages_per_search=1,
        )

    if mode == "mini":
        return ScrapeConfig(
            mode="mini",
            start_year=2018,
            end_year=2019,
            parts=["alternator", "headlight"],
            supported_vehicles=[
                {"year_range": (2012, 2020), "make": "Toyota", "model": "Camry"}
            ],
            max_pages_per_search=2,
        )

    # Default: full run
    return ScrapeConfig(mode="full")
