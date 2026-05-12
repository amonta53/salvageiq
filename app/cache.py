# =========================================================
# cache.py
# Cache lookup and freshness logic for SalvageIQ
# =========================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import get_db, get_fresh_result_set, get_most_recent_result_set


FRESH_DAYS = 14       # return immediately, no refresh
USABLE_DAYS = 30      # return immediately + trigger background refresh
# beyond USABLE_DAYS: expired, start new scrape


def check_cache(vehicle_key: str, window_days: int = 90) -> dict:
    """
    Check whether a recent result set exists for this vehicle.

    Returns a dict with:
        cache_status: fresh | usable_stale | expired | missing
        result_set_id: int | None
        scraped_at: str | None
        items: list (populated for fresh/usable_stale)
    """
    with get_db() as conn:
        fresh = get_fresh_result_set(conn, vehicle_key, window_days)
        if fresh:
            return {
                "cache_status": "fresh",
                "result_set_id": fresh["id"],
                "scraped_at": fresh["scraped_at"],
                "cache_expires_at": fresh["cache_expires_at"],
            }

        recent = get_most_recent_result_set(conn, vehicle_key, window_days)
        if recent and recent["scraped_at"]:
            scraped_at = datetime.fromisoformat(recent["scraped_at"])
            age_days = (datetime.now(timezone.utc) - scraped_at).days
            if age_days <= USABLE_DAYS:
                return {
                    "cache_status": "usable_stale",
                    "result_set_id": recent["id"],
                    "scraped_at": recent["scraped_at"],
                    "cache_expires_at": recent.get("cache_expires_at"),
                }
            else:
                return {
                    "cache_status": "expired",
                    "result_set_id": recent["id"],
                    "scraped_at": recent["scraped_at"],
                    "cache_expires_at": recent.get("cache_expires_at"),
                }

    return {
        "cache_status": "missing",
        "result_set_id": None,
        "scraped_at": None,
        "cache_expires_at": None,
    }
