# =========================================================
# runner.py
#
# Purpose:
#     eBay Finding API runner for SalvageIQ raw listing collection.
#     Replaces the former Playwright/BeautifulSoup scraper.
#
# Responsibilities:
#     1. Execute all part searches via the eBay Finding API
#     2. "sold" scope  → findCompletedItems, all 31 parts simultaneously
#     3. "all"  scope  → findItemsAdvanced,  all 31 parts simultaneously
#     4. Return the same raw_df / market_df schemas as the old scraper
#        so the downstream cleanse → normalize → analyze stages are unchanged
#
# Notes:
#     - No semaphore needed. Authenticated API calls are not subject to
#       bot-detection, so all requests for a scope fire at the same time
#       via asyncio.gather.
#     - EBAY_APP_ID must be set in the environment (or .env file).
#     - Category 6030 = eBay Motors > Parts & Accessories — keeps results
#       automotive and avoids noise from unrelated categories.
# =========================================================

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars may already be set by the shell

from config.schema import MARKET_SUMMARY_COLUMNS, RAW_COLUMNS
from config.scrape_config import ScrapeConfig
from scrape.search_builder import build_execution_key, build_search_key
from utils.io_utils import ensure_directory
from utils.logging_utils import RunLogger, format_elapsed_hhmmss

logger = logging.getLogger(__name__)

# =========================================================
# Constants
# =========================================================

_FINDING_API_URL    = "https://svcs.ebay.com/services/search/FindingService/v1"
_MOTORS_PARTS_CAT   = "6030"   # eBay Motors > Parts & Accessories
_API_SERVICE_VER    = "1.13.0"
_REQUEST_TIMEOUT    = 30        # seconds per individual request


# =========================================================
# URL builder
# =========================================================

def _build_url(params: dict) -> str:
    """
    Build a Finding API URL with parentheses kept literal in parameter names.

    httpx's params= kwarg percent-encodes '(' and ')' by default, turning
    itemFilter(0).name into itemFilter%280%29.name — which eBay rejects with
    a 500.  Building the query string manually with safe='()' avoids this.
    """
    qs = "&".join(
        f"{quote(str(k), safe='()')}={quote(str(v), safe='()')}"
        for k, v in params.items()
    )
    return f"{_FINDING_API_URL}?{qs}"


# =========================================================
# App ID
# =========================================================

def _app_id() -> str:
    aid = os.environ.get("EBAY_APP_ID", "").strip()
    if not aid:
        raise RuntimeError(
            "EBAY_APP_ID is not set. "
            "Add it to your .env file or environment before running."
        )
    return aid


# =========================================================
# Keyword builder
# =========================================================

def _keywords(year: int, make: str, model: str, part: str) -> str:
    return f"{year} {make} {model} {part}"


# =========================================================
# Sold listings — findCompletedItems
# =========================================================

async def _fetch_sold(
    client: httpx.AsyncClient,
    app_id: str,
    year: int,
    make: str,
    model: str,
    part: str,
    run_id: str,
) -> list[dict]:
    """
    Fetch sold/completed listings for one part.

    Returns a list of row dicts matching RAW_COLUMNS.
    """
    params = {
        "OPERATION-NAME":          "findCompletedItems",
        "SERVICE-VERSION":         _API_SERVICE_VER,
        "SECURITY-APPNAME":        app_id,
        "RESPONSE-DATA-FORMAT":    "JSON",
        "keywords":                _keywords(year, make, model, part),
        "categoryId":              _MOTORS_PARTS_CAT,
        "itemFilter(0).name":      "SoldItemsOnly",
        "itemFilter(0).value":     "true",
        "paginationInput.entriesPerPage": "100",
        "sortOrder":               "EndTimeSoonest",
    }

    scrape_ts = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    try:
        r = await client.get(_build_url(params))
        r.raise_for_status()
        data = r.json()
        request_url = str(r.url)
    except Exception as exc:
        logger.warning("findCompletedItems failed | %s %s %s | %s | %s", year, make, model, part, exc)
        return rows

    try:
        items = (
            data["findCompletedItemsResponse"][0]
                ["searchResult"][0]
                .get("item", [])
        )
    except (KeyError, IndexError):
        return rows

    for item in items:
        try:
            title     = item["title"][0]
            price_val = item["sellingStatus"][0]["currentPrice"][0]["__value__"]
            price_raw = f"${float(price_val):.2f}"
            url       = item.get("viewItemURL", [""])[0]
        except (KeyError, IndexError, ValueError, TypeError):
            continue

        rows.append({
            "run_id":       run_id,
            "scrape_ts":    scrape_ts,
            "pass_type":    "sold",
            "search_year":  year,
            "search_make":  make,
            "search_model": model,
            "search_part":  part,
            "search_url":   request_url,
            "search_page":  1,
            "title":        title,
            "price_raw":    price_raw,
            "subtitle":     None,
            "listing_url":  url,
            "raw_text":     title,
        })

    return rows


# =========================================================
# Active listing count — findItemsAdvanced
# =========================================================

async def _fetch_active(
    client: httpx.AsyncClient,
    app_id: str,
    year: int,
    make: str,
    model: str,
    part: str,
    run_id: str,
) -> dict:
    """
    Fetch active listing count for one part.

    Returns a single row dict matching MARKET_SUMMARY_COLUMNS.
    """
    params = {
        "OPERATION-NAME":          "findItemsAdvanced",
        "SERVICE-VERSION":         _API_SERVICE_VER,
        "SECURITY-APPNAME":        app_id,
        "RESPONSE-DATA-FORMAT":    "JSON",
        "keywords":                _keywords(year, make, model, part),
        "categoryId":              _MOTORS_PARTS_CAT,
        "paginationInput.entriesPerPage": "1",   # only need the total count
    }

    scrape_ts   = datetime.now(timezone.utc).isoformat()
    search_key  = build_search_key(year, make, model, part)
    exec_key    = build_execution_key(year, make, model, part, "all")
    total: int  = 0

    try:
        r = await client.get(_build_url(params))
        r.raise_for_status()
        data  = r.json()
        total = int(
            data["findItemsAdvancedResponse"][0]
                ["paginationOutput"][0]
                ["totalEntries"][0]
        )
    except Exception as exc:
        logger.warning("findItemsAdvanced failed | %s %s %s | %s | %s", year, make, model, part, exc)

    return {
        "run_id":               run_id,
        "scrape_ts":            scrape_ts,
        "pass_type":            "all",
        "search_key":           search_key,
        "execution_key":        exec_key,
        "search_scope":         "all",
        "search_year":          year,
        "search_make":          make,
        "search_model":         model,
        "search_part":          part,
        "search_url":           _FINDING_API_URL,
        "result_count":         total,
        "page_count_observed":  1,
    }


# =========================================================
# Async core
# =========================================================

async def _run_api_async(
    config: ScrapeConfig,
    run_logger: RunLogger,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Fire all requests for the current scope in parallel, return DataFrames.

    "sold" scope — all 31 findCompletedItems calls simultaneously
    "all"  scope — all 31 findItemsAdvanced  calls simultaneously
    """
    aid = _app_id()

    # Build (year, make, model, part) task list from config
    tasks: list[tuple[int, str, str, str]] = [
        (year, make, model, part)
        for make, models in config.make_model_map.items()
        for model in models
        for year in range(config.start_year, config.end_year + 1)
        for part in config.parts
    ]

    run_logger.log(
        f"eBay API | scope={config.search_scope} | "
        f"{len(tasks)} requests firing in parallel"
    )

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:

        if config.search_scope == "sold":
            coros = [
                _fetch_sold(client, aid, y, mk, mo, p, config.run_id)
                for y, mk, mo, p in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            all_rows: list[dict] = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    y, mk, mo, p = tasks[i]
                    run_logger.log(f"  ERROR | {y} {mk} {mo} | {p}: {res}")
                else:
                    all_rows.extend(res)
                    y, mk, mo, p = tasks[i]
                    run_logger.log(f"  {y} {mk} {mo} | {p}: {len(res)} sold")

            raw_df = (
                pd.DataFrame(all_rows).reindex(columns=RAW_COLUMNS)
                if all_rows
                else pd.DataFrame(columns=RAW_COLUMNS)
            )
            market_df = pd.DataFrame(columns=MARKET_SUMMARY_COLUMNS)
            stats = {
                "total_rows": len(all_rows),
                "total_searches_run": len(tasks),
                "total_pages_loaded": len(tasks),
            }

        else:  # "all" scope — active counts
            coros = [
                _fetch_active(client, aid, y, mk, mo, p, config.run_id)
                for y, mk, mo, p in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            all_summaries: list[dict] = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    y, mk, mo, p = tasks[i]
                    run_logger.log(f"  ERROR | {y} {mk} {mo} | {p}: {res}")
                else:
                    all_summaries.append(res)
                    y, mk, mo, p = tasks[i]
                    run_logger.log(
                        f"  {y} {mk} {mo} | {p}: {res['result_count']} active"
                    )

            raw_df    = pd.DataFrame(columns=RAW_COLUMNS)
            market_df = (
                pd.DataFrame(all_summaries).reindex(columns=MARKET_SUMMARY_COLUMNS)
                if all_summaries
                else pd.DataFrame(columns=MARKET_SUMMARY_COLUMNS)
            )
            stats = {
                "total_rows": 0,
                "total_searches_run": len(tasks),
                "total_pages_loaded": len(tasks),
            }

    return raw_df, market_df, stats


# =========================================================
# Public entry point — sync, matches orchestrator contract
# =========================================================

def run_scrape(config: ScrapeConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Run the eBay Finding API data collection stage.

    Sync entry point called by the pipeline orchestrator.
    Bridges to the async implementation via asyncio.run().

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, dict]
        raw_df:    Sold listing rows (RAW_COLUMNS schema)   — sold scope only
        market_df: Active market rows (MARKET_SUMMARY_COLUMNS) — all scope only
        stats:     {"total_rows", "total_searches_run", "total_pages_loaded"}
    """
    run_start = time.time()
    ensure_directory(config.logs_dir)
    run_logger = RunLogger(config.scrape_log_path)

    run_logger.log("=" * 72)
    run_logger.log("STARTING DATA COLLECTION  [eBay Finding API]")
    run_logger.log(f"Run ID:  {config.run_id}")
    run_logger.log(f"Scope:   {config.search_scope}")
    run_logger.log(f"Log:     {config.scrape_log_path}")
    run_logger.log("=" * 72)

    raw_df, market_df, totals = asyncio.run(_run_api_async(config, run_logger))

    elapsed = format_elapsed_hhmmss(time.time() - run_start)
    run_logger.log("=" * 72)
    run_logger.log(
        f"COLLECTION COMPLETE | "
        f"Rows={totals['total_rows']} | "
        f"Searches={totals['total_searches_run']} | "
        f"Elapsed={elapsed}"
    )
    run_logger.log("=" * 72)

    return raw_df, market_df, totals
