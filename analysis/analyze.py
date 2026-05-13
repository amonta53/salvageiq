# =========================================================
# analyze.py
# Controller for the analysis stage
#
# Purpose:
# Load prepared data, run the analysis layer, write outputs,
# and hand results back to the main pipeline.
# =========================================================
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from analysis.aggregation import build_analysis_summary
from analysis.ranking import build_ranked_outputs
from config.schema import ANALYSIS_EXPORT_RENAME_MAP, ANALYSIS_OUTPUT_COLUMNS


# =========================================================
# Run analysis stage
# =========================================================
def run_analysis(
    sold_df: pd.DataFrame,
    active_df: pd.DataFrame,
    config: Any,
) -> dict[str, Any]:
    """
    Run the analysis stage on in-memory sold and active DataFrames.

    Parameters
    ----------
    sold_df : pd.DataFrame
        Normalized sold listing rows (output of run_normalization).
    active_df : pd.DataFrame
        Active market snapshot rows (output of active scrape pass).
    config : Any
        Pipeline config with confidence scoring and ranking settings.

    Returns
    -------
    dict with keys:
        "analysis_df"     — formatted analysis summary DataFrame
        "top_ranked_df"   — top-N ranked parts per vehicle
        "full_ranked_df"  — all ranked parts per vehicle

    High-level flow:
    1. Build combined analysis summary (metrics + scoring)
    2. Format for downstream use
    3. Generate ranked outputs (top parts per vehicle)
    4. Return all results in memory
    """
    logger = logging.getLogger(__name__)

    logger.info("=" * 70)
    logger.info("Analysis stage start")
    logger.info("=" * 70)
    logger.info(
        "Input | sold_rows=%s | active_rows=%s",
        len(sold_df),
        len(active_df),
    )

    # ---------------------------------------------------------
    # 1. Build analysis summary (core metrics + scoring)
    # ---------------------------------------------------------
    logger.info("Building analysis summary")

    analysis_df = build_analysis_summary(
        sold_df=sold_df,
        active_df=active_df,
        config=config,
    )

    logger.info("Analysis summary built | rows=%s", len(analysis_df))

    # ---------------------------------------------------------
    # 2. Format analysis summary
    # ---------------------------------------------------------
    analysis_export_df = analysis_df.rename(columns=ANALYSIS_EXPORT_RENAME_MAP)
    analysis_export_df = analysis_export_df.reindex(columns=ANALYSIS_OUTPUT_COLUMNS)

    # ---------------------------------------------------------
    # 3. Generate ranked outputs (final product layer)
    # ---------------------------------------------------------
    logger.info("Generating ranked outputs | top_n=%s", config.top_n_parts)
    logger.info("Ranking input columns: %s", sorted(analysis_df.columns.tolist()))

    full_ranked_df, top_ranked_df = build_ranked_outputs(
        analysis_df=analysis_df,
        top_n=config.top_n_parts,
    )

    logger.info(
        "Ranked outputs built | full_rows=%s | top_rows=%s",
        len(full_ranked_df),
        len(top_ranked_df),
    )

    return {
        "analysis_df": analysis_export_df,
        "top_ranked_df": top_ranked_df,
        "full_ranked_df": full_ranked_df,
    }