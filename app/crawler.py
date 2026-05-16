# =========================================================
# app/crawler.py
#
# Background sold-listing crawler for SalvageIQ.
#
# Runs as a continuous asyncio task alongside the FastAPI server.
# Cycles through all vehicles in the DB, scraping eBay sold listings
# for each part with 2–4 second random jitter between requests.
#
# Stores results in sold_listings table. The runner's _fetch_sold()
# checks this table first; the crawler keeps it warm so most user
# requests never need to touch eBay directly.
#
# Crawl cadence:
#   Any vehicle whose sold data is > 14 days old is re-crawled.
#   After the full vehicle list is processed the loop starts over,
#   sleeping 60 s if there's nothing stale to crawl.
# =========================================================

from __future__ import annotations

import asyncio
import logging
import random

from app.db import (
    get_db,
    get_vehicles_for_crawl,
    insert_sold_listings,
    upsert_crawl_status,
)
from scrape.ebay_html import fetch_sold_html, make_session, parse_sold_html, warm_session

logger = logging.getLogger(__name__)

_DELAY_MIN =  2.0   # seconds between part requests (minimum)
_DELAY_MAX =  4.0   # seconds between part requests (maximum)
_INTER_VEH = (5.0, 10.0)  # pause range between vehicles


# =========================================================
# Single-vehicle crawl
# =========================================================

async def crawl_vehicle(
    vehicle_key: str,
    year: int,
    make: str,
    model: str,
    parts: list[str],
) -> None:
    """
    Crawl all *parts* for one vehicle, inserting results into sold_listings.
    Requests are spaced with random jitter to stay under bot-detection radar.
    Updates crawl_status when finished.
    """
    total_listings = 0

    async with make_session() as session:
        await warm_session(session)   # establish eBay cookie session once

        for idx, part in enumerate(parts):
            try:
                html, _ = await fetch_sold_html(session, year, make, model, part)
                rows     = parse_sold_html(html, vehicle_key, year, make, model, part)
            except Exception as exc:
                logger.warning(
                    "Crawler | %s | %s | fetch error: %s", vehicle_key, part, exc
                )
                rows = []

            if rows:
                with get_db() as conn:
                    insert_sold_listings(conn, rows)
                total_listings += len(rows)

            logger.debug(
                "Crawler | %s | %s | %d listings", vehicle_key, part, len(rows)
            )

            # Jitter delay — skip after the last part
            if idx < len(parts) - 1:
                await asyncio.sleep(random.uniform(_DELAY_MIN, _DELAY_MAX))

    with get_db() as conn:
        upsert_crawl_status(
            conn,
            vehicle_key=vehicle_key,
            parts_scraped=len(parts),
            total_listings=total_listings,
        )

    logger.info(
        "Crawler complete | %s | %d listings across %d parts",
        vehicle_key, total_listings, len(parts),
    )


# =========================================================
# Continuous crawler loop
# =========================================================

async def run_crawler() -> None:
    """
    Continuous background loop.  Started as an asyncio Task by api.py on startup.

    Picks up vehicles whose sold data is missing or > 14 days old,
    crawls them one at a time, then sleeps 60 s if nothing is left to do.
    """
    # Import here to avoid circular imports at module load time
    from config.taxonomy import SEARCH_PART_TERMS

    logger.info("Background crawler started — cycling every 14 days per vehicle")

    while True:
        try:
            with get_db() as conn:
                vehicles = get_vehicles_for_crawl(conn)

            if not vehicles:
                logger.debug("Crawler: nothing stale — sleeping 60 s")
                await asyncio.sleep(60)
                continue

            for v in vehicles:
                logger.info("Crawler: starting %s", v["vehicle_key"])
                try:
                    await crawl_vehicle(
                        vehicle_key=v["vehicle_key"],
                        year=v["year"],
                        make=v["make"],
                        model=v["model"],
                        parts=list(SEARCH_PART_TERMS),
                    )
                except asyncio.CancelledError:
                    raise   # propagate shutdown signal
                except Exception as exc:
                    logger.warning(
                        "Crawler: error on %s — %s", v["vehicle_key"], exc
                    )

                # Brief pause between vehicles
                await asyncio.sleep(random.uniform(*_INTER_VEH))

        except asyncio.CancelledError:
            logger.info("Background crawler shutting down")
            return
        except Exception as exc:
            logger.error("Crawler loop error: %s — retrying in 30 s", exc)
            await asyncio.sleep(30)
