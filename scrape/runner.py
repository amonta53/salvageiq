# =========================================================
# runner.py
#
# Purpose:
#     Data collection stage for SalvageIQ.
#
# "sold" scope  — findSoldListings
#     1. Check sold_listings DB for data < 14 days old (fast path)
#     2. If stale/missing: scrape eBay sold-search HTML via httpx + BS4
#        (spaced by a semaphore — max 1 concurrent live scrape at a time)
#     3. Store fresh-scraped rows in sold_listings for future lookups
#
# "all" scope   — findActiveCount
#     Browse API (api.ebay.com/buy/browse/v1/item_summary/search)
#     Returns total active listing count per part.
#     All requests fire simultaneously via asyncio.gather.
#
# Auth (Browse API):
#     OAuth 2.0 Client Credentials.
#     EBAY_APP_ID  = client_id
#     EBAY_CERT_ID = client_secret
# =========================================================

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import time
from datetime import datetime, timezone

import httpx
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config.schema import MARKET_SUMMARY_COLUMNS, RAW_COLUMNS
from config.scrape_config import ScrapeConfig
from scrape.ebay_html import fetch_sold_html, make_session, parse_sold_html, warm_session
from scrape.search_builder import build_execution_key, build_search_key
from utils.io_utils import ensure_directory
from utils.logging_utils import RunLogger, format_elapsed_hhmmss

logger = logging.getLogger(__name__)

# =========================================================
# Constants
# =========================================================

_OAUTH_URL        = "https://api.ebay.com/identity/v1/oauth2/token"
_BROWSE_URL       = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_MOTORS_PARTS_CAT = "6030"
_BROWSE_TIMEOUT   = 30
_SCOPE_BROWSE     = "https://api.ebay.com/oauth/api_scope"

# One live eBay HTML scrape at a time to avoid bot detection
_sold_sem = asyncio.Semaphore(1)

# In-memory OAuth token cache: scope → (token, expiry_epoch)
_token_cache: dict[str, tuple[str, float]] = {}


# =========================================================
# OAuth (Browse API)
# =========================================================

def _credentials() -> tuple[str, str]:
    app_id  = os.environ.get("EBAY_APP_ID",  "").strip()
    cert_id = os.environ.get("EBAY_CERT_ID", "").strip()
    if not app_id:
        raise RuntimeError("EBAY_APP_ID is not set.")
    if not cert_id:
        raise RuntimeError("EBAY_CERT_ID is not set.")
    return app_id, cert_id


async def _get_token(client: httpx.AsyncClient, scope: str) -> str:
    now    = time.time()
    cached = _token_cache.get(scope)
    if cached and now < cached[1]:
        return cached[0]

    app_id, cert_id = _credentials()
    encoded = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()

    r = await client.post(
        _OAUTH_URL,
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": scope},
    )
    r.raise_for_status()
    body = r.json()

    token      = body["access_token"]
    expires_in = int(body.get("expires_in", 7200))
    _token_cache[scope] = (token, now + expires_in - 60)
    return token


# =========================================================
# Sold listings — DB-first, httpx scrape fallback
# =========================================================

async def _fetch_sold(
    client: httpx.AsyncClient,
    year: int,
    make: str,
    model: str,
    part: str,
    run_id: str,
) -> list[dict]:
    """
    Return sold listing rows for one part.

    Priority:
        1. sold_listings DB (< 14 days) — instant, no network
        2. Live eBay HTML scrape via httpx + BeautifulSoup
           (serialised through _sold_sem to stay polite)
    """
    from app.db import get_db, get_sold_listings, insert_sold_listings

    scrape_ts   = datetime.now(timezone.utc).isoformat()
    vehicle_key = f"{year}|{make}|{model}"

    # ── 1. DB fast path ──────────────────────────────────────
    with get_db() as conn:
        db_rows = get_sold_listings(conn, vehicle_key=vehicle_key, part=part, days=14)

    if db_rows:
        return [
            {
                "run_id":       run_id,
                "scrape_ts":    scrape_ts,
                "pass_type":    "sold",
                "search_year":  year,
                "search_make":  make,
                "search_model": model,
                "search_part":  part,
                "search_url":   "(db_cache)",
                "search_page":  1,
                "title":        row["title"],
                "price_raw":    row["price_raw"],
                "subtitle":     None,
                "listing_url":  row.get("listing_url") or "",
                "raw_text":     row["title"],
            }
            for row in db_rows
        ]

    # ── 2. Live scrape (serialised, Chrome TLS impersonation) ────
    async with _sold_sem:
        try:
            async with make_session() as session:
                await warm_session(session)
                html, request_url = await fetch_sold_html(
                    session, year, make, model, part
                )
            scraped = parse_sold_html(html, vehicle_key, year, make, model, part)
        except Exception as exc:
            logger.warning(
                "eBay sold scrape failed | %s %s %s | %s | %s",
                year, make, model, part, exc,
            )
            scraped = []
            request_url = ""

        if scraped:
            with get_db() as conn:
                insert_sold_listings(conn, scraped)

        # Brief jitter even inside the semaphore to space requests
        await asyncio.sleep(random.uniform(2.0, 4.0))

    return [
        {
            "run_id":       run_id,
            "scrape_ts":    scrape_ts,
            "pass_type":    "sold",
            "search_year":  year,
            "search_make":  make,
            "search_model": model,
            "search_part":  part,
            "search_url":   request_url,
            "search_page":  1,
            "title":        row["title"],
            "price_raw":    row["price_raw"],
            "subtitle":     None,
            "listing_url":  row.get("listing_url") or "",
            "raw_text":     row["title"],
        }
        for row in scraped
    ]


# =========================================================
# Active listing count — Browse API
# =========================================================

async def _fetch_active(
    client: httpx.AsyncClient,
    year: int,
    make: str,
    model: str,
    part: str,
    run_id: str,
) -> dict:
    """
    Fetch the current active listing count for one part via the Browse API.
    Returns a single row dict matching MARKET_SUMMARY_COLUMNS.
    """
    scrape_ts  = datetime.now(timezone.utc).isoformat()
    search_key = build_search_key(year, make, model, part)
    exec_key   = build_execution_key(year, make, model, part, "all")
    total: int = 0

    try:
        token = await _get_token(client, _SCOPE_BROWSE)
        r = await client.get(
            _BROWSE_URL,
            params={
                "q":            f"{year} {make} {model} {part}",
                "category_ids": _MOTORS_PARTS_CAT,
                "limit":        "1",
            },
            headers={
                "Authorization":           f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
        )
        r.raise_for_status()
        total = int(r.json().get("total", 0))
    except Exception as exc:
        logger.warning(
            "Browse API failed | %s %s %s | %s | %s",
            year, make, model, part, exc,
        )

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
        "search_url":           _BROWSE_URL,
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
    Execute the data collection pass for the current scope.

    sold — _fetch_sold() per part (DB-first; live scrape serialised by semaphore)
    all  — _fetch_active() per part (Browse API, all in parallel)
    """
    tasks: list[tuple[int, str, str, str]] = [
        (year, make, model, part)
        for make, models in config.make_model_map.items()
        for model in models
        for year in range(config.start_year, config.end_year + 1)
        for part in config.parts
    ]

    run_logger.log(
        f"Data collection | scope={config.search_scope} | {len(tasks)} parts"
    )

    async with httpx.AsyncClient(timeout=_BROWSE_TIMEOUT) as client:

        if config.search_scope == "sold":
            # Gather fires all coroutines; the semaphore inside _fetch_sold
            # ensures live scrapes are serialised while DB hits are instant.
            coros   = [
                _fetch_sold(client, y, mk, mo, p, config.run_id)
                for y, mk, mo, p in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            all_rows: list[dict] = []
            for i, res in enumerate(results):
                y, mk, mo, p = tasks[i]
                if isinstance(res, Exception):
                    run_logger.log(f"  ERROR | {y} {mk} {mo} | {p}: {res}")
                else:
                    all_rows.extend(res)
                    src = "db" if res and res[0]["search_url"] == "(db_cache)" else "live"
                    run_logger.log(f"  {y} {mk} {mo} | {p}: {len(res)} listings [{src}]")

            raw_df = (
                pd.DataFrame(all_rows).reindex(columns=RAW_COLUMNS)
                if all_rows
                else pd.DataFrame(columns=RAW_COLUMNS)
            )
            market_df = pd.DataFrame(columns=MARKET_SUMMARY_COLUMNS)
            stats = {
                "total_rows":         len(all_rows),
                "total_searches_run": len(tasks),
                "total_pages_loaded": len(tasks),
            }

        else:  # "all" scope — active counts, fully parallel
            coros   = [
                _fetch_active(client, y, mk, mo, p, config.run_id)
                for y, mk, mo, p in tasks
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            all_summaries: list[dict] = []
            for i, res in enumerate(results):
                y, mk, mo, p = tasks[i]
                if isinstance(res, Exception):
                    run_logger.log(f"  ERROR | {y} {mk} {mo} | {p}: {res}")
                else:
                    all_summaries.append(res)
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
                "total_rows":         0,
                "total_searches_run": len(tasks),
                "total_pages_loaded": len(tasks),
            }

    return raw_df, market_df, stats


# =========================================================
# Public entry point
# =========================================================

def run_scrape(config: ScrapeConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Run the data collection stage.

    Sync entry point called by the pipeline orchestrator.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, dict]
        raw_df:    Sold listing rows (RAW_COLUMNS)          — sold scope only
        market_df: Active market rows (MARKET_SUMMARY_COLUMNS) — all scope only
        stats:     {"total_rows", "total_searches_run", "total_pages_loaded"}
    """
    run_start = time.time()
    ensure_directory(config.logs_dir)
    run_logger = RunLogger(config.scrape_log_path)

    run_logger.log("=" * 72)
    run_logger.log("STARTING DATA COLLECTION")
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
