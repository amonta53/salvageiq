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

    tmp_path = Path("tests/_artifacts/runner_smoke")
    tmp_path.mkdir(parents=True, exist_ok=True)

    config.output_dir = tmp_path
    config.raw_csv_path = tmp_path / "raw_test.csv"
    config.log_path = tmp_path / "runner_test.log"
    config.checkpoint_path = tmp_path / "checkpoint_test.txt"

    config.enable_resume = False

    result = run_scrape(config)

    # -------------------------------------------------
    # Basic execution assertions
    # -------------------------------------------------
    assert isinstance(result, dict), "run_scrape() must return a dict"
    assert "total_rows" in result, "Missing total_rows in runner result"
    assert "total_searches_run" in result, "Missing total_searches_run in runner result"
    assert "total_pages_loaded" in result, "Missing total_pages_loaded in runner result"

    assert isinstance(result["total_rows"], int), "total_rows must be an int"
    assert isinstance(result["total_searches_run"], int), "total_searches_run must be an int"
    assert isinstance(result["total_pages_loaded"], int), "total_pages_loaded must be an int"

    # -------------------------------------------------
    # For test mode, we expect exactly one search:
    # 1 year x 1 vehicle x 1 part
    # -------------------------------------------------
    assert result["total_searches_run"] == 1, (
        f"Expected exactly 1 search in test mode, got {result['total_searches_run']}"
    )

    # We expect at least one page load attempt in test mode
    assert result["total_pages_loaded"] >= 1, "Expected at least 1 page load"

    # Raw CSV should at least be created, even if 0 rows are scraped
    assert config.raw_csv_path.exists(), "Expected raw CSV file to be created"

    print("Runner smoke test passed.")


if __name__ == "__main__":
    test_runner_smoke()