# =========================================================
# analysis/trend.py
#
# Price trend detection from historical sold_listings data.
#
# Method:
#   Compare median sold price over the last 30 days vs. the
#   prior 30 days (days 31–60).  Requires ≥ 3 data points in
#   each window for a statistically meaningful signal.
#
#   > +5%  → "up"      (price rising — seller's market)
#   < -5%  → "down"    (price falling — oversupplied / low demand)
#   ± 5%   → "neutral" (stable)
#   < 3 pts in recent window → "new" (insufficient history)
# =========================================================

from __future__ import annotations

import re
import statistics
from datetime import datetime, timedelta, timezone


# =========================================================
# Internal helpers
# =========================================================

def _parse_price(price_raw: str | None) -> float | None:
    if not price_raw:
        return None
    match = re.search(r"[\d,]+\.?\d*", price_raw.replace("$", ""))
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            pass
    return None


# =========================================================
# Public API
# =========================================================

def compute_trend(listings: list[dict]) -> dict:
    """
    Compute a price trend from a list of sold_listings rows.

    Each row must have at minimum:
        price_raw  (str)  — e.g. "$145.00"
        scraped_at (str)  — ISO-8601 datetime string

    Returns a dict:
        direction    str          "up" | "neutral" | "down" | "new"
        pct_change   float|None   e.g. 14.2 means +14.2%
        current_avg  float|None   median price in last 30 days
        prior_avg    float|None   median price in prior 30 days
    """
    now           = datetime.now(timezone.utc)
    recent_cutoff = (now - timedelta(days=30)).isoformat()
    prior_cutoff  = (now - timedelta(days=60)).isoformat()

    recent_prices: list[float] = []
    prior_prices:  list[float] = []

    for row in listings:
        ts    = row.get("scraped_at", "")
        price = _parse_price(row.get("price_raw"))
        if price is None or price <= 0:
            continue

        if ts >= recent_cutoff:
            recent_prices.append(price)
        elif ts >= prior_cutoff:
            prior_prices.append(price)

    _no_signal: dict = {
        "direction":   "new",
        "pct_change":  None,
        "current_avg": None,
        "prior_avg":   None,
    }

    if len(recent_prices) < 3:
        return _no_signal

    current_avg = statistics.median(recent_prices)

    if len(prior_prices) < 3:
        # Recent data exists but no prior window to compare against
        return {**_no_signal, "current_avg": round(current_avg, 2)}

    prior_avg = statistics.median(prior_prices)

    if prior_avg == 0:
        return {**_no_signal, "current_avg": round(current_avg, 2)}

    pct_change = (current_avg - prior_avg) / prior_avg * 100

    if pct_change > 5.0:
        direction = "up"
    elif pct_change < -5.0:
        direction = "down"
    else:
        direction = "neutral"

    return {
        "direction":   direction,
        "pct_change":  round(pct_change, 1),
        "current_avg": round(current_avg, 2),
        "prior_avg":   round(prior_avg, 2),
    }
