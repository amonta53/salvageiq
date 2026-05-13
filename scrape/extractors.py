# =========================================================
# extractors.py
# Low-level text and field extraction helpers for scraped eBay rows.
#
# Purpose:
# - Cleans raw text values pulled from the DOM
# - Extracts common listing fields such as title, price, subtitle, and URL
# - Applies lightweight guess logic for condition, years, part type, and vehicle info
#
# Notes:
# - These helpers are intentionally defensive because scrape HTML is messy
# - These guesses are helpful, but they’re not truth. We can't treat them like they are. 
# - Price ranges currently return None to avoid skewing downstream price analysis
# =========================================================
from __future__ import annotations

import re
from typing import Any

from config.extraction_rules import (
    CONDITION_PATTERNS,
    JUNK_TITLE_MARKERS,
    PART_GUESS_PATTERNS,
    PART_NUMBER_PATTERNS,
    VEHICLE_GUESS_MAKES,
    VEHICLE_GUESS_MODELS,
)

# =========================================================
# Basic text helpers
# =========================================================


def clean_text(value: Any) -> str | None:
    """Normalize whitespace and return a stripped string or None."""
    if value is None:
        return None

    value = re.sub(r"\s+", " ", str(value)).strip()
    return value if value else None



def clean_price(value: str | None) -> float | None:
    """Extract a single scalar price from text when possible."""
    if not value:
        return None

    normalized = value.replace(",", "").strip().lower()

    # Treat ranges as ambiguous instead of silently taking the low value.
    range_match = re.findall(r"\$?(\d+(?:\.\d{1,2})?)", normalized)
    if len(range_match) >= 2 and any(token in normalized for token in [" to ", "-", "–"]):
        return None

    if range_match:
        return float(range_match[0])

    return None




# =========================================================
# Domain guess helpers
# =========================================================


def extract_condition(text: str | None) -> str | None:
    """Guess a normalized condition label from listing text."""
    if not text:
        return None

    lowered = text.lower()
    for label, pattern in CONDITION_PATTERNS:
        if re.search(pattern, lowered):
            return label

    return None



def extract_part_number(text: str | None) -> str | None:
    """Extract a likely OEM or aftermarket part number from text."""
    if not text:
        return None

    for pattern in PART_NUMBER_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).upper()

    return None



def extract_years(text: str | None) -> str | None:
    """Extract distinct vehicle years mentioned in text."""
    if not text:
        return None

    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    if not years:
        return None

    return ", ".join(sorted(set(years)))



def extract_year_range(text: str | None) -> str | None:
    """Extract a simple year range such as 2012-2015."""
    if not text:
        return None

    match = re.search(r"\b((?:19|20)\d{2})\s*[-/]\s*((?:19|20)\d{2})\b", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    return None



def extract_vehicle_guess(text: str | None) -> str | None:
    """Make a lightweight make/model guess from listing text."""
    if not text:
        return None

    lowered = text.lower()
    make_found = next((m for m in VEHICLE_GUESS_MAKES if re.search(rf"\b{re.escape(m)}\b", lowered)), None)
    model_found = next((m for m in VEHICLE_GUESS_MODELS if re.search(rf"\b{re.escape(m)}\b", lowered)), None)

    if make_found and model_found:
        return f"{make_found.title()} {model_found.title()}"
    if make_found:
        return make_found.title()
    if model_found:
        return model_found.title()

    return None



def extract_part_guess(text: str | None) -> str | None:
    """Make a lightweight part guess from listing text."""
    if not text:
        return None

    lowered = text.lower()
    matches: list[str] = []

    for canonical, pattern_list in PART_GUESS_PATTERNS.items():
        for pattern in pattern_list:
            if re.search(pattern, lowered):
                matches.append(canonical)
                break

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "ambiguous"

    return None



def extract_sold_date_guess(raw_text: str | None) -> str | None:
    """Extract a likely sold date from raw listing text."""
    if not raw_text:
        return None

    match = re.search(r"\b(?:Sold\s+)?([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\b", raw_text)
    return match.group(1) if match else None



def extract_shipping_text(raw_text: str | None) -> str | None:
    """Extract a compact shipping label when present."""
    if not raw_text:
        return None

    match = re.search(
        r"(Free shipping|Local pickup|(?:\$\d+(?:\.\d{1,2})?)\s+shipping)",
        raw_text,
        flags=re.IGNORECASE,
    )
    return clean_text(match.group(1)) if match else None



def looks_like_junk_title(title: str | None) -> bool:
    """Return True when the title looks like non-listing noise."""
    if not title:
        return True

    lowered = title.lower().strip()
    return any(marker in lowered for marker in JUNK_TITLE_MARKERS)


