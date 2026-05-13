# =========================================================
# runner.py
#
# Purpose:
#     Async httpx scrape runner for SalvageIQ raw listing collection.
#     Replaces Playwright with concurrent HTTP requests + BeautifulSoup parsing.
#
# Responsibilities:
#     1. Execute configured eBay searches across vehicle/part combinations
#        concurrently using asyncio.gather + a Semaphore
#     2. Extract raw listing rows and write them to the raw CSV
#     3. Capture run-level and search-level provenance fields
#     4. Support checkpoint/resume
#
# Notes:
#     - eBay search result pages are server-side rendered — no JS execution needed
#     - BeautifulSoup replaces Playwright DOM locators
#     - All searches for a given pass (sold/all) run concurrently up to
#       _MAX_CONCURRENCY simultaneous connections
#     - run_scrape() is the sync entry point; it bridges to asyncio internally
# =========================================================

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from config.extraction_rules import RESULT_ROW_SELECTORS
from config.schema import MARKET_SUMMARY_COLUMNS, RAW_COLUMNS
from config.scrape_config import ScrapeConfig
from scrape.extractors import clean_text, looks_like_junk_title
from scrape.search_builder import build_execution_key, build_search_key, build_search_url
from utils.checkpoint_utils import append_completed_search, load_completed_searches
from utils.io_utils import ensure_directory
from utils.logging_utils import RunLogger, format_elapsed_hhmmss


# =========================================================
# Constants
# =========================================================

# Concurrent requests cap — fast enough to matter, polite enough not to trigger blocks
_MAX_CONCURRENCY = 8

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# =========================================================
# Runtime stats
# =========================================================

@dataclass(slots=True)
class ScrapeStats:
    """Track basic runtime totals for a scrape run."""
    run_start: float
    total_rows: int = 0
    total_searches_run: int = 0
    total_pages_loaded: int = 0


# =========================================================
# BeautifulSoup extraction helpers
# =========================================================

def _bs_first_text(tag: Any, selectors: list[str]) -> str | None:
    """
    Return the first non-empty text match from a list of CSS selectors.

    Handles Playwright-style :has-text() pseudo-selectors by converting them
    to a manual find_all scan, since BS4 does not support that pseudo-class.
    """
    for sel in selectors:
        if ":has-text(" in sel:
            # e.g. 'span:has-text("$")' — find any matching tag whose text contains the value
            m = re.match(r'^(\w+)?:has-text\("([^"]+)"\)$', sel)
            if m:
                tag_name = m.group(1) or True
                search_text = m.group(2)
                for el in tag.find_all(tag_name):
                    t = clean_text(el.get_text())
                    if t and search_text in t:
                        return t
            continue

        try:
            el = tag.select_one(sel)
            if el:
                t = clean_text(el.get_text())
                if t:
                    return t
        except Exception:
            continue

    return None


def _bs_first_attr(tag: Any, selectors: list[str], attr: str) -> str | None:
    """Return the first non-empty attribute value from a list of CSS selectors."""
    for sel in selectors:
        if ":has-text(" in sel:
            continue  # attribute extraction on :has-text is unsupported
        try:
            el = tag.select_one(sel)
            if el and el.has_attr(attr):
                val = clean_text(el[attr])
                if val:
                    return val
        except Exception:
            continue
    return None


def _extract_result_count_bs(soup: BeautifulSoup) -> int | None:
    """Extract total active-listing result count from an eBay search results page."""
    try:
        el = soup.select_one("h1.srp-controls__count-heading")
        if el:
            m = re.search(r"([\d,]+)", el.get_text())
            if m:
                return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def _extract_rows_from_page(
    soup: BeautifulSoup,
    year: int,
    make: str,
    model: str,
    part: str,
    search_url: str,
    page_num: int,
    run_id: str,
    scrape_ts: str,
    pass_type: str,
) -> list[dict[str, Any]]:
    """
    Extract usable listing rows from a parsed eBay search results page.

    Returns a list of row dicts whose keys match RAW_COLUMNS.
    """
    # Try each row container selector in priority order
    item_tags: list = []
    for sel in RESULT_ROW_SELECTORS:
        item_tags = soup.select(sel)
        if item_tags:
            break

    extracted: list[dict[str, Any]] = []

    for row in item_tags:
        # --- Title ---
        title = _bs_first_text(row, [
            '[role="heading"]',
            ".s-item__title",
            "a span",
            "a",
            'div[role="heading"]',
        ])

        if looks_like_junk_title(title):
            continue

        # --- Price ---
        price_raw = _bs_first_text(row, [".s-item__price"])
        if not price_raw:
            # Fallback: any short span/div containing "$"
            for el in row.find_all(["span", "div"]):
                t = clean_text(el.get_text())
                if t and "$" in t and len(t) < 40:
                    price_raw = t
                    break

        if not title or not price_raw:
            continue

        # --- Subtitle ---
        subtitle = _bs_first_text(row, [
            ".s-item__subtitle",
            ".SECONDARY_INFO",
            ".s-item__dynamic",
            ".s-item__details",
            ".s-item__caption-section",
        ])

        # --- Listing URL ---
        listing_url = _bs_first_attr(row, ["a"], "href")

        # --- Raw text for downstream guess heuristics ---
        raw_text = clean_text(row.get_text(separator=" "))

        extracted.append({
            "run_id": run_id,
            "scrape_ts": scrape_ts,
            "pass_type": pass_type,
            "search_year": year,
            "search_make": make,
            "search_model": model,
            "search_part": part,
            "search_url": search_url,
            "search_page": page_num,
            "title": title,
            "price_raw": price_raw,
            "subtitle": subtitle,
            "listing_url": listing_url,
            "raw_text": raw_text,
        })

    return extracted


# =========================================================
# Async fetch with retry
# =========================================================

async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    logger: RunLogger,
    retries: int = 2,
) -> str | None:
    """GET a URL and return the response body. Retries on transient errors."""
    for attempt in range(1, retries + 2):
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            if attempt <= retries:
                wait = random.uniform(1.0, 2.5) * attempt
                logger.log(f"  Fetch error (attempt {attempt}): {exc} — retrying in {wait:.1f}s")
                await asyncio.sleep(wait)
            else:
                logger.log(f"  Fetch failed after {retries + 1} attempts: {url} — {exc}")
    return None


# =========================================================
# Single search coroutine
# =========================================================

async def _scrape_one_search(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    year: int,
    make: str,
    model: str,
    part: str,
    config: ScrapeConfig,
    logger: RunLogger,
) -> tuple[list[dict], dict | None, int]:
    """
    Scrape all pages for a single year/make/model/part search.

    Returns (rows, summary_row, pages_loaded) where:
    - rows is populated for 'sold' pass and empty for 'all' pass
    - summary_row is populated for 'all' pass and None for 'sold' pass
    - pages_loaded is the number of pages successfully fetched
    """
    async with sem:
        scrape_ts = datetime.now(timezone.utc).isoformat()
        rows: list[dict] = []
        summary: dict | None = None
        pages_loaded = 0

        search_key = build_search_key(year, make, model, part)
        execution_key = build_execution_key(year, make, model, part, config.search_scope)

        logger.log(f"  [{config.search_scope.upper()}] {year} {make} {model} | {part}")

        for page_num in range(1, config.max_pages_per_search + 1):
            url = build_search_url(year, make, model, part, config, page_num)

            # Small random jitter to spread out concurrent request timing
            await asyncio.sleep(random.uniform(0.05, 0.3))

            html = await _fetch(client, url, logger)
            if not html:
                break

            pages_loaded += 1
            soup = BeautifulSoup(html, "lxml")

            # ---- 'all' pass: grab result count and stop ----
            if config.search_scope == "all":
                result_count = _extract_result_count_bs(soup)
                summary = {
                    "run_id": config.run_id,
                    "scrape_ts": scrape_ts,
                    "pass_type": config.search_scope,
                    "search_key": search_key,
                    "execution_key": execution_key,
                    "search_scope": config.search_scope,
                    "search_year": year,
                    "search_make": make,
                    "search_model": model,
                    "search_part": part,
                    "search_url": url,
                    "result_count": result_count,
                    "page_count_observed": None,
                }
                logger.log(f"    Market summary: result_count={result_count}")
                break

            # ---- 'sold' pass: extract listing rows ----
            page_rows = _extract_rows_from_page(
                soup=soup,
                year=year,
                make=make,
                model=model,
                part=part,
                search_url=url,
                page_num=page_num,
                run_id=config.run_id,
                scrape_ts=scrape_ts,
                pass_type=config.search_scope,
            )

            logger.log(f"    Page {page_num}: {len(page_rows)} rows")
            rows.extend(page_rows)

            # Weak first-page guard: skip further pages when results are sparse
            if page_num == 1 and len(page_rows) < config.weak_result_skip_threshold:
                logger.log(
                    f"    Weak first page ({len(page_rows)} rows) — skipping remaining pages."
                )
                break

        return rows, summary, pages_loaded


# =========================================================
# Async orchestration
# =========================================================

async def _run_scrape_async(
    config: ScrapeConfig,
    logger: RunLogger,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """
    Core async implementation: build all search tasks, run them concurrently,
    collect results, and return DataFrames in memory.
    """
    completed_searches = (
        load_completed_searches(config.checkpoint_path) if config.enable_resume else set()
    )

    # Build the full list of (year, make, model, part) tuples to search
    tasks: list[tuple[int, str, str, str]] = []
    for make, models in config.make_model_map.items():
        for model in models:
            for year in range(config.start_year, config.end_year + 1):
                for part in config.parts:
                    execution_key = build_execution_key(
                        year, make, model, part, config.search_scope
                    )
                    if config.enable_resume and execution_key in completed_searches:
                        continue
                    tasks.append((year, make, model, part))

    logger.log(f"Search tasks: {len(tasks)} (scope={config.search_scope})")

    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0) as client:
        coroutines = [
            _scrape_one_search(sem, client, year, make, model, part, config, logger)
            for year, make, model, part in tasks
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Collect results and write to CSV
    all_rows: list[dict] = []
    all_summaries: list[dict] = []
    total_pages = 0

    for i, result in enumerate(results):
        year, make, model, part = tasks[i]

        if isinstance(result, Exception):
            logger.log(f"  Exception for {year} {make} {model} | {part}: {result}")
            continue

        rows, summary, pages = result
        all_rows.extend(rows)
        total_pages += pages

        if summary:
            all_summaries.append(summary)

        # Checkpoint each completed search
        if config.enable_resume:
            execution_key = build_execution_key(
                year, make, model, part, config.search_scope
            )
            append_completed_search(config.checkpoint_path, execution_key)

    raw_df = (
        pd.DataFrame(all_rows).reindex(columns=RAW_COLUMNS)
        if all_rows
        else pd.DataFrame(columns=RAW_COLUMNS)
    )
    market_df = (
        pd.DataFrame(all_summaries).reindex(columns=MARKET_SUMMARY_COLUMNS)
        if all_summaries
        else pd.DataFrame(columns=MARKET_SUMMARY_COLUMNS)
    )
    stats = {
        "total_rows": len(all_rows),
        "total_searches_run": len(tasks),
        "total_pages_loaded": total_pages,
    }
    return raw_df, market_df, stats


# =========================================================
# Public entry point (sync, for orchestrator compatibility)
# =========================================================

def run_scrape(config: ScrapeConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """
    Run the raw scrape stage and return results in memory.

    This is the sync entry point called by the pipeline orchestrator.
    It bridges to the async implementation via asyncio.run().

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, dict]
        raw_df:    Sold listing rows (RAW_COLUMNS schema)
        market_df: Active market snapshot rows (MARKET_SUMMARY_COLUMNS schema)
        stats:     {"total_rows", "total_searches_run", "total_pages_loaded"}

    Flow:
    1. Create logs directory and open run logger
    2. Resume prior checkpoint if enabled
    3. Run all part searches concurrently with bounded parallelism
    4. Return collected DataFrames and stats (no CSV I/O)
    """
    run_start = time.time()

    # Only the logs directory needs to exist — all data stays in memory
    ensure_directory(config.logs_dir)

    logger = RunLogger(config.scrape_log_path)

    logger.log("=" * 72)
    logger.log("STARTING SCRAPE RUN  [async httpx]")
    logger.log(f"Run ID:  {config.run_id}")
    logger.log(f"Scope:   {config.search_scope}")
    logger.log(f"Log:     {config.scrape_log_path}")
    logger.log("=" * 72)

    raw_df, market_df, totals = asyncio.run(_run_scrape_async(config, logger))

    elapsed = format_elapsed_hhmmss(time.time() - run_start)
    logger.log("=" * 72)
    logger.log(
        f"SCRAPE COMPLETE | Run ID={config.run_id} | "
        f"Rows={totals['total_rows']} | "
        f"Searches={totals['total_searches_run']} | "
        f"Pages={totals['total_pages_loaded']} | "
        f"Elapsed={elapsed}"
    )
    logger.log("=" * 72)

    return raw_df, market_df, totals
