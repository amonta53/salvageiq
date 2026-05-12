# =========================================================
# net_value.py
# Phase 4 — Product-level scoring for SalvageIQ
#
# Purpose:
# Turn raw market metrics into a practical pull decision.
# The core question is always: should I pull this part?
#
# Formula:
#   estimated_net_value =
#       median_price
#       - marketplace_fee          (median_price × fee_pct)
#       - estimated_shipping_cost
#       - estimated_yard_cost
#       - labor_cost               (pull_minutes / 60 × hourly_rate)
#
# Recommendation thresholds:
#   Pull  — net >= 75 AND str >= 0.50
#   Maybe — net >= 25 AND (net < 75 OR str < 0.50 OR confidence < 0.50)
#   Skip  — everything else
# =========================================================

from __future__ import annotations

from typing import Any


# =========================================================
# Default user settings
# =========================================================

DEFAULT_USER_SETTINGS: dict[str, float] = {
    "labor_rate_per_hour": 25.0,
    "marketplace_fee_percent": 0.13,
}


# =========================================================
# Pull profiles
# Keys match the normalized part names produced by PART_ALIASES
# in config/taxonomy.py (search_part_std column).
# =========================================================

PULL_PROFILES: dict[str, dict[str, Any]] = {
    "headlight": {
        "estimated_pull_minutes": 25,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 28.0,
        "estimated_yard_cost": 40.0,
        "damage_risk_score": 3,
        "storage_size": "medium",
    },
    "tail light": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 25.0,
        "estimated_yard_cost": 30.0,
        "damage_risk_score": 2,
        "storage_size": "medium",
    },
    "mirror": {
        "estimated_pull_minutes": 15,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 20.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "radio": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 18.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "instrument cluster": {
        "estimated_pull_minutes": 25,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 22.0,
        "estimated_yard_cost": 40.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "alternator": {
        "estimated_pull_minutes": 40,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 20.0,
        "estimated_yard_cost": 45.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "starter": {
        "estimated_pull_minutes": 35,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 18.0,
        "estimated_yard_cost": 40.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "ecu": {
        "estimated_pull_minutes": 15,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 12.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "tcm": {
        "estimated_pull_minutes": 15,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 12.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "wheel": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "heavy",
        "estimated_shipping_cost": 55.0,
        "estimated_yard_cost": 20.0,
        "damage_risk_score": 1,
        "storage_size": "large",
    },
    "seat": {
        "estimated_pull_minutes": 30,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "heavy",
        "estimated_shipping_cost": 75.0,
        "estimated_yard_cost": 50.0,
        "damage_risk_score": 2,
        "storage_size": "large",
    },
    "door": {
        "estimated_pull_minutes": 60,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 150.0,
        "estimated_yard_cost": 75.0,
        "damage_risk_score": 4,
        "storage_size": "xlarge",
    },
    "fender": {
        "estimated_pull_minutes": 30,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 95.0,
        "estimated_yard_cost": 45.0,
        "damage_risk_score": 3,
        "storage_size": "large",
    },
    "hood": {
        "estimated_pull_minutes": 45,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 125.0,
        "estimated_yard_cost": 55.0,
        "damage_risk_score": 4,
        "storage_size": "xlarge",
    },
    "front bumper": {
        "estimated_pull_minutes": 45,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 125.0,
        "estimated_yard_cost": 65.0,
        "damage_risk_score": 3,
        "storage_size": "xlarge",
    },
    "rear bumper": {
        "estimated_pull_minutes": 45,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 125.0,
        "estimated_yard_cost": 65.0,
        "damage_risk_score": 3,
        "storage_size": "xlarge",
    },
    "grille": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 30.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "medium",
    },
    "window regulator": {
        "estimated_pull_minutes": 30,
        "difficulty_score": 3,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 22.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "ac compressor": {
        "estimated_pull_minutes": 45,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 25.0,
        "estimated_yard_cost": 55.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "steering wheel": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 3,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 22.0,
        "estimated_yard_cost": 30.0,
        "damage_risk_score": 2,
        "storage_size": "medium",
    },

    # ---- New parts ----

    "catalytic converter": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "medium",
        "estimated_shipping_cost": 25.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "abs module": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 15.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "bcm": {
        "estimated_pull_minutes": 15,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 12.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "ignition coil": {
        "estimated_pull_minutes": 10,
        "difficulty_score": 1,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 10.0,
        "estimated_yard_cost": 15.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "radiator": {
        "estimated_pull_minutes": 30,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "heavy",
        "estimated_shipping_cost": 45.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 3,
        "storage_size": "large",
    },
    "blower motor": {
        "estimated_pull_minutes": 25,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 15.0,
        "estimated_yard_cost": 25.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "liftgate": {
        "estimated_pull_minutes": 30,
        "difficulty_score": 3,
        "tool_complexity": "basic",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 110.0,
        "estimated_yard_cost": 55.0,
        "damage_risk_score": 3,
        "storage_size": "xlarge",
    },
    "tailgate": {
        "estimated_pull_minutes": 20,
        "difficulty_score": 2,
        "tool_complexity": "basic",
        "shipping_class": "oversized",
        "estimated_shipping_cost": 95.0,
        "estimated_yard_cost": 45.0,
        "damage_risk_score": 2,
        "storage_size": "large",
    },
    "fog light": {
        "estimated_pull_minutes": 10,
        "difficulty_score": 1,
        "tool_complexity": "basic",
        "shipping_class": "small",
        "estimated_shipping_cost": 15.0,
        "estimated_yard_cost": 20.0,
        "damage_risk_score": 2,
        "storage_size": "small",
    },
    "power steering pump": {
        "estimated_pull_minutes": 35,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 18.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 1,
        "storage_size": "small",
    },
    "strut": {
        "estimated_pull_minutes": 45,
        "difficulty_score": 4,
        "tool_complexity": "moderate",
        "shipping_class": "medium",
        "estimated_shipping_cost": 35.0,
        "estimated_yard_cost": 35.0,
        "damage_risk_score": 2,
        "storage_size": "medium",
    },
}


# =========================================================
# Net value calculation
# =========================================================

def estimate_net_value(
    median_price: float | None,
    profile: dict[str, Any],
    settings: dict[str, float] | None = None,
) -> float | None:
    """
    Estimate the net value of pulling and selling a part.

    Returns None when median_price is not available.
    """
    if median_price is None:
        return None

    s = settings or DEFAULT_USER_SETTINGS
    fee_pct    = s.get("marketplace_fee_percent", 0.13)
    hourly     = s.get("labor_rate_per_hour", 25.0)

    marketplace_fee   = median_price * fee_pct
    shipping_cost     = profile.get("estimated_shipping_cost", 0.0)
    yard_cost         = profile.get("estimated_yard_cost", 0.0)
    pull_minutes      = profile.get("estimated_pull_minutes", 0)
    labor_cost        = (pull_minutes / 60.0) * hourly

    net = median_price - marketplace_fee - shipping_cost - yard_cost - labor_cost
    return round(net, 2)


# =========================================================
# Recommendation logic
# =========================================================

def recommend(
    estimated_net_value: float | None,
    sell_through_rate: float | None,
    confidence_score: float | None,
) -> str:
    """
    Return Pull, Maybe, or Skip based on net value, STR, and confidence.
    """
    if estimated_net_value is None:
        return "Skip"

    net  = estimated_net_value
    str_ = sell_through_rate or 0.0
    conf = confidence_score or 0.0

    if net >= 75 and str_ >= 0.50:
        return "Pull"

    if net >= 25 and (net < 75 or str_ < 0.50 or conf < 0.50):
        return "Maybe"

    return "Skip"


# =========================================================
# Enrichment helper — attach net value + recommendation
# =========================================================

def enrich_item(
    item: dict[str, Any],
    settings: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Add estimated_net_value, recommendation, and pull profile metadata
    to a single ranked result item dict.

    The item dict comes from the pipeline CSV and uses the column names
    produced by ranking.py (e.g. 'part', 'median_sold_price', 'str').
    """
    part_key = (item.get("part") or item.get("part_name") or "").lower().strip()
    profile  = PULL_PROFILES.get(part_key, {})

    # median_sold_price is the column name from the CSV
    median_price = item.get("median_sold_price") or item.get("median_price")
    if median_price is not None:
        try:
            median_price = float(median_price)
        except (TypeError, ValueError):
            median_price = None

    str_val  = item.get("str") or item.get("sell_through_rate")
    conf_val = item.get("confidence_score")

    try:
        str_val  = float(str_val)  if str_val  is not None else None
    except (TypeError, ValueError):
        str_val  = None
    try:
        conf_val = float(conf_val) if conf_val is not None else None
    except (TypeError, ValueError):
        conf_val = None

    net_value = estimate_net_value(median_price, profile, settings)
    verdict   = recommend(net_value, str_val, conf_val)

    return {
        **item,
        "estimated_net_value": net_value,
        "recommendation": verdict,
        "estimated_pull_minutes": profile.get("estimated_pull_minutes"),
        "difficulty_score": profile.get("difficulty_score"),
        "shipping_class": profile.get("shipping_class"),
    }
