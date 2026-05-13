# =========================================================
# main.py
# CLI entry point for the SalvageIQ pipeline.
#
# Usage:
#   python main.py          # full run
#   python main.py mini     # quick pipeline check (1 vehicle, 2 parts, 2 years)
#   python main.py test     # smoke test (1 vehicle, 1 part, 1 year)
# =========================================================

from __future__ import annotations

import logging
import sys

from config.config_builder import build_scrape_config
from pipeline.orchestrator import run_pipeline


if __name__ == "__main__":
    selected_mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    try:
        config = build_scrape_config(mode=selected_mode)
        run_pipeline(config)
    except Exception:
        logging.exception("Pipeline failed")
        raise
