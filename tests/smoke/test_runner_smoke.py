# =========================================================
# test_runner_smoke.py
# Smoke test for SalvageIQ runner execution.
#
# Purpose:
# - Verifies that run_scrape() can execute with the tiny
#   "test" runtime config without crashing
# - Confirms a minimal run returns the expected stats shape
#
# Notes:
# - This is not a correctness test for scrape results
# - This is only meant to prove the runner starts, loops,
#   and exits cleanly under a tiny config
# =========================================================

from pathlib import Path
import pytest 

from config.config_builder import build_scrape_config
from scrape.runner import run_scrape

@pytest.mark.integration
def test_runner_smoke() -> None:
    print("Starting runner smoke test...")

    config = build_scrape_config(mode="test")

    # -----------------------------------------------------
    # Override file outputs so the smoke test writes to a
    # temporary sandbox location instead of your real data
    # folders.
    # -----------------------------------------------------
    #with tempfile.TemporaryDirectory() as tmpdir:
    #    tmp_path = Path(tmpdir)

    # Redirect runs_dir so logs land in the test artifact folder, not data/runs/
    tmp_path = Path("tests/_artifacts/runner_smoke")
    tmp_path.mkdir(parents=True, exist_ok=True)
    config.runs_dir = tmp_path

    config.enable_resume = False

    raw_df, market_df, stats = run_scrape(config)

    # -------------------------------------------------
    # Basic execution assertions
    # -------------------------------------------------
    import pandas as pd

    assert isinstance(raw_df, pd.DataFrame), "run_scrape() raw_df must be a DataFrame"
    assert isinstance(market_df, pd.DataFrame), "run_scrape() market_df must be a DataFrame"
    assert isinstance(stats, dict), "run_scrape() stats must be a dict"
    assert "total_rows" in stats, "Missing total_rows in stats"
    assert "total_searches_run" in stats, "Missing total_searches_run in stats"
    assert "total_pages_loaded" in stats, "Missing total_pages_loaded in stats"

    assert isinstance(stats["total_rows"], int), "total_rows must be an int"
    assert isinstance(stats["total_searches_run"], int), "total_searches_run must be an int"
    assert isinstance(stats["total_pages_loaded"], int), "total_pages_loaded must be an int"

    # -------------------------------------------------
    # For test mode, we expect exactly one search:
    # 1 year x 1 vehicle x 1 part
    # -------------------------------------------------
    assert stats["total_searches_run"] == 1, (
        f"Expected exactly 1 search in test mode, got {stats['total_searches_run']}"
    )

    # We expect at least one page load attempt in test mode
    assert stats["total_pages_loaded"] >= 1, "Expected at least 1 page load"

    # Log file should be created in runs_dir/<run_id>/outputs/logs/
    log_file = config.scrape_log_path
    assert log_file.exists(), f"Expected scrape log file to be created at {log_file}"

    print("Runner smoke test passed.")


if __name__ == "__main__":
    test_runner_smoke()