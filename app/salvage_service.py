# =========================================================
# salvage_service.py
# Application service layer for SalvageIQ
# =========================================================

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from config.config_builder import build_scrape_config
from config.taxonomy import SEARCH_PART_TERMS
from pipeline.orchestrator import run_pipeline

from app.db import (
    complete_result_set,
    create_result_set,
    get_db,
    insert_result_items,
    update_job,
)
from app.net_value import enrich_item

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SalvageIQRequest:
    """User-facing lookup request."""

    year: int | None = None
    make: str | None = None
    model: str | None = None
    vin: str | None = None
    top_n: int = 10
    max_pages_per_search: int = 2
    window_days: int = 90


def run_vehicle_analysis(
    job_id: str,
    vehicle_key: str,
    request: SalvageIQRequest,
) -> None:
    """
    Background task: run the full pipeline, update job progress, and persist results.
    """

    def progress(message: str, percent: int) -> None:
        try:
            with get_db() as conn:
                update_job(
                    conn,
                    job_id,
                    progress_message=message,
                    progress_percent=percent,
                )
        except Exception:
            logger.warning("Failed to write job progress for %s", job_id)

    try:
        with get_db() as conn:
            update_job(conn, job_id, status="running", progress_message="Starting scrape job...", progress_percent=5)

        config = build_scrape_config(mode="full")
        config.start_year = request.year
        config.end_year = request.year
        config.supported_vehicles = [
            {
                "year_range": (request.year, request.year),
                "make": request.make,
                "model": request.model,
            }
        ]
        config.parts = SEARCH_PART_TERMS.copy()
        config.max_pages_per_search = request.max_pages_per_search
        config.top_n_parts = request.top_n
        config.run_hypothesis_test = False
        config.reset_outputs_on_run = True
        config.enable_resume = False
        config.make_model_map = {request.make: [request.model]}

        progress("Scraping sold listings...", 15)
        run_pipeline(config)
        progress("Scoring results...", 80)

        top_path = config.top_10_output_csv_path
        ranked_parts = [enrich_item(item) for item in _load_ranked_parts(top_path)]

        progress("Saving results...", 90)
        with get_db() as conn:
            result_set_id = create_result_set(conn, vehicle_key=vehicle_key)
            insert_result_items(conn, result_set_id, ranked_parts)
            complete_result_set(conn, result_set_id)
            update_job(
                conn,
                job_id,
                status="completed",
                progress_message="Complete.",
                progress_percent=100,
                result_set_id=result_set_id,
            )

    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        try:
            with get_db() as conn:
                update_job(
                    conn,
                    job_id,
                    status="failed",
                    error_message=str(exc),
                    progress_message="Job failed.",
                )
        except Exception:
            pass


def _load_ranked_parts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Ranked output was not created: {path}")
    df = pd.read_csv(path)
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")
