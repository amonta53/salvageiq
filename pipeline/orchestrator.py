# =========================================================
# orchestrator.py
# Pipeline flow control for SalvageIQ
#
# Purpose:
# Run pipeline stages in the correct order based on config.
#
# Notes:
# - This is the traffic cop — stage logic stays in the stage modules
# - Flow: scrape (sold + active) → cleanse → normalize → analyze → rank
# =========================================================

from __future__ import annotations

import logging
import pandas as pd
from dataclasses import replace

from analysis.analyze import run_analysis
from config.scrape_config import ScrapeConfig
from scrape.runner import run_scrape
from utils.io_utils import reset_output_file
from utils.logging_utils import setup_logging
from wrangle.cleanse import run_cleansing
from wrangle.normalize import run_normalization


# =========================================================
# Setup helpers
# =========================================================

def initialize_pipeline(config: ScrapeConfig) -> logging.Logger:
    setup_logging(config.logs_dir, config.run_id)
    logger = logging.getLogger(__name__)

    if not logger.handlers and not logging.getLogger().handlers:
        raise RuntimeError("Logging setup failed. No handlers were attached.")

    logger.info("=" * 70)
    logger.info("Pipeline started | run_id=%s | mode=%s", config.run_id, config.mode)
    logger.info("=" * 70)

    return logger


def reset_pipeline_outputs(config: ScrapeConfig, logger: logging.Logger) -> None:
    if not config.reset_outputs_on_run:
        return

    logger.info("Reset flag is on — clearing old output files.")

    for path in [
        config.raw_csv_path,
        config.market_summary_csv_path,
        config.cleansed_csv_path,
        config.normalized_csv_path,
        config.eda_summary_csv_path,
        config.checkpoint_path,
        config.analysis_summary_csv_path,
        config.full_ranked_output_csv_path,
        config.top_10_output_csv_path,
    ]:
        reset_output_file(path)


def build_stage_configs(config: ScrapeConfig) -> tuple[ScrapeConfig, ScrapeConfig]:
    sold_config = replace(config, search_scope="sold")
    all_config = replace(config, search_scope="all")
    return sold_config, all_config


# =========================================================
# Stage wrappers
# =========================================================

def run_sold_scrape_stage(config: ScrapeConfig, logger: logging.Logger) -> dict:
    logger.info("Stage start | sold scrape")
    result = run_scrape(config)
    logger.info("Stage complete | sold scrape | rows_collected=%s", result.get("total_rows", 0))
    return result


def run_active_scrape_stage(config: ScrapeConfig, logger: logging.Logger) -> dict:
    logger.info("Stage start | active scrape")
    result = run_scrape(config)
    logger.info("Stage complete | active scrape | rows_collected=%s", result.get("total_rows", 0))
    return result


def run_cleansing_stage(config: ScrapeConfig, logger: logging.Logger) -> pd.DataFrame:
    logger.info("Stage start | cleansing")
    cleansed_df = run_cleansing(config.raw_csv_path, config.cleansed_csv_path)
    logger.info("Stage complete | cleansing | rows_out=%s", len(cleansed_df))
    return cleansed_df


def run_normalization_stage(config: ScrapeConfig, logger: logging.Logger):
    logger.info("Stage start | normalization")
    normalized_df, dedup_stats = run_normalization(
        config.cleansed_csv_path,
        config.normalized_csv_path,
    )
    logger.info(
        "Stage complete | normalization | rows_out=%s | duplicates_removed=%s",
        len(normalized_df),
        dedup_stats.get("removed_count", 0),
    )
    return normalized_df, dedup_stats


def run_analysis_stage(config: ScrapeConfig, logger: logging.Logger):
    logger.info("Stage start | analysis summary")
    analysis_result = run_analysis(
        sold_csv_path=config.normalized_csv_path,
        active_csv_path=config.market_summary_csv_path,
        output_csv_path=config.analysis_summary_csv_path,
        config=config,
    )
    logger.info(
        "Stage complete | analysis summary | rows_out=%s",
        len(analysis_result["analysis_df"]),
    )
    return analysis_result


# =========================================================
# Main orchestrator
# =========================================================

def run_pipeline(config: ScrapeConfig) -> None:
    """
    Run the end-to-end SalvageIQ pipeline for one configured execution.

    Flow:
    1. Initialize logging
    2. Reset output files if configured
    3. Scrape sold listings + active market snapshot (concurrent httpx)
    4. Cleanse → normalize sold listings
    5. Build analysis summary + ranked outputs
    """
    logger = initialize_pipeline(config)
    reset_pipeline_outputs(config, logger)

    sold_config, all_config = build_stage_configs(config)

    run_sold_scrape_stage(sold_config, logger)
    run_active_scrape_stage(all_config, logger)

    run_cleansing_stage(sold_config, logger)
    normalized_df, _ = run_normalization_stage(config, logger)
    analysis_result = run_analysis_stage(config, logger)

    analysis_df = analysis_result["analysis_df"]

    logger.info("=" * 70)
    logger.info(
        "Pipeline complete | run_id=%s | normalized_rows=%s | summary_rows=%s | mode=%s",
        config.run_id,
        len(normalized_df),
        len(analysis_df),
        config.mode,
    )
    logger.info("=" * 70)
