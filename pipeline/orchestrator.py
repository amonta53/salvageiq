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

# dataclasses.replace used by build_stage_configs — keep this import


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

    logger.info("Reset flag is on — clearing checkpoint.")

    # Pipeline data is all in-memory now; only the checkpoint file persists on disk.
    reset_output_file(config.checkpoint_path)


def build_stage_configs(config: ScrapeConfig) -> tuple[ScrapeConfig, ScrapeConfig]:
    sold_config = replace(config, search_scope="sold")
    all_config = replace(config, search_scope="all")
    return sold_config, all_config


# =========================================================
# Stage wrappers
# =========================================================

def run_sold_scrape_stage(
    config: ScrapeConfig, logger: logging.Logger
) -> tuple[pd.DataFrame, dict]:
    logger.info("Stage start | sold scrape")
    raw_df, _market_df, stats = run_scrape(config)
    logger.info("Stage complete | sold scrape | rows_collected=%s", stats.get("total_rows", 0))
    return raw_df, stats


def run_active_scrape_stage(
    config: ScrapeConfig, logger: logging.Logger
) -> tuple[pd.DataFrame, dict]:
    logger.info("Stage start | active scrape")
    _raw_df, market_df, stats = run_scrape(config)
    logger.info("Stage complete | active scrape | rows_collected=%s", stats.get("total_rows", 0))
    return market_df, stats


def run_cleansing_stage(
    raw_df: pd.DataFrame, logger: logging.Logger
) -> pd.DataFrame:
    logger.info("Stage start | cleansing")
    cleansed_df = run_cleansing(raw_df)
    logger.info("Stage complete | cleansing | rows_out=%s", len(cleansed_df))
    return cleansed_df


def run_normalization_stage(
    cleansed_df: pd.DataFrame, logger: logging.Logger
) -> tuple[pd.DataFrame, dict]:
    logger.info("Stage start | normalization")
    normalized_df, dedup_stats = run_normalization(cleansed_df)
    logger.info(
        "Stage complete | normalization | rows_out=%s | duplicates_removed=%s",
        len(normalized_df),
        dedup_stats.get("removed_count", 0),
    )
    return normalized_df, dedup_stats


def run_analysis_stage(
    normalized_df: pd.DataFrame,
    market_df: pd.DataFrame,
    config: ScrapeConfig,
    logger: logging.Logger,
) -> dict:
    logger.info("Stage start | analysis summary")
    analysis_result = run_analysis(
        sold_df=normalized_df,
        active_df=market_df,
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

def run_pipeline(config: ScrapeConfig) -> dict:
    """
    Run the end-to-end SalvageIQ pipeline for one configured execution.

    All data flows in memory — no intermediate CSV files are written.
    Only the log file (and optional checkpoint) are written to disk.

    Flow:
    1. Initialize logging
    2. Reset checkpoint if configured
    3. Scrape sold listings + active market snapshot (concurrent httpx)
    4. Cleanse → normalize sold listings
    5. Build analysis summary + ranked outputs

    Returns
    -------
    dict with keys:
        "analysis_df"    — formatted analysis summary
        "top_ranked_df"  — top-N ranked parts per vehicle
        "full_ranked_df" — all ranked parts per vehicle
    """
    logger = initialize_pipeline(config)
    reset_pipeline_outputs(config, logger)

    sold_config, all_config = build_stage_configs(config)

    raw_df, _sold_stats = run_sold_scrape_stage(sold_config, logger)
    market_df, _active_stats = run_active_scrape_stage(all_config, logger)

    cleansed_df = run_cleansing_stage(raw_df, logger)
    normalized_df, _ = run_normalization_stage(cleansed_df, logger)
    analysis_result = run_analysis_stage(normalized_df, market_df, config, logger)

    logger.info("=" * 70)
    logger.info(
        "Pipeline complete | run_id=%s | normalized_rows=%s | summary_rows=%s | mode=%s",
        config.run_id,
        len(normalized_df),
        len(analysis_result["analysis_df"]),
        config.mode,
    )
    logger.info("=" * 70)

    return analysis_result
