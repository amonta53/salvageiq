# =========================================================
# scrape/ebay_html.py
#
# Shared eBay sold-listing HTML scraper.
# Used by both the background crawler (app/crawler.py) and
# the on-demand fallback in runner.py.
#
# Strategy:
#   GET ebay.com/sch/i.html?LH_Complete=1&LH_Sold=1 with realistic
#   browser headers via httpx, parse the result list with BeautifulSoup.
#   Requests are spaced by the caller (crawler adds 2-4s jitter;
#   runner uses a semaphore to serialise on-demand live scrapes).
# =========================================================

from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession
    _CURL = True
except ImportError:
    AsyncSession = None  # type: ignore[assignment, misc]
    _CURL = False
    logger.warning(
        "curl-cffi not installed — eBay HTML scraping disabled. "
        "Run: pip install curl-cffi"
    )

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False
    logger.warning(
        "beautifulsoup4 not installed — eBay HTML scraping disabled. "
        "Run: pip install beautifulsoup4"
    )

# Chrome version to impersonate for TLS fingerprint matching
_IMPERSONATE = "chrome124"

# =========================================================
# Constants
# =========================================================

EBAY_SOLD_URL  = "https://www.ebay.com/sch/i.html"
_MOTORS_CAT    = "6030"
REQUEST_TIMEOUT = 20

# curl_cffi sets correct browser headers automatically.
# Additional headers passed here layer on top of what curl_cffi provides.
HEADERS: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.ebay.com/",
}


# =========================================================
# Parsers
# =========================================================

def parse_price(raw: str | None) -> float | None:
    """Extract a dollar value from a raw price string like '$145.00'."""
    if not raw:
        return None
    # Handle price ranges like "$12.50 to $145.00" — take the first
    match = re.search(r"[\d,]+\.?\d*", raw.replace("$", ""))
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            pass
    return None


def parse_sold_date(raw: str | None) -> str | None:
    """
    Parse eBay's sold date string to ISO date.
    Handles: "Sold  Dec 15, 2024", "Sold Jan 5, 2025"
    """
    if not raw:
        return None
    match = re.search(r"(\w{3}\s+\d{1,2},\s+\d{4})", raw)
    if match:
        try:
            dt = datetime.strptime(match.group(1), "%b %d, %Y")
            return dt.date().isoformat()
        except ValueError:
            pass
    return None


# =========================================================
# HTML parsing
# =========================================================

def parse_sold_html(
    html: str,
    vehicle_key: str,
    year: int,
    make: str,
    model: str,
    part: str,
) -> list[dict]:
    """
    Parse an eBay sold-search results page.

    eBay's current markup (2025+) uses li.s-card elements with:
        div.s-card__title     — listing title
        span.s-card__price    — sold price (green, "positive" class)
        div.s-card__caption   — "Sold  May 14, 2026"
        a.s-card__link        — listing URL (href)

    Returns a list of row dicts ready for insert_sold_listings().
    Returns [] if BeautifulSoup is not installed or no items are found.
    """
    if not _BS4:
        return []

    soup       = BeautifulSoup(html, "html.parser")
    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for card in soup.find_all("li", class_=lambda c: c and "s-card" in c):
        # Skip "Shop on eBay" ghost/ad cards
        title_el = card.select_one(".s-card__title")
        if not title_el:
            continue
        title = title_el.get_text(separator=" ", strip=True)
        if not title or "Shop on eBay" in title:
            continue

        # Price — look for the span with s-card__price class (sold = green = "positive")
        price_el  = card.select_one("span.s-card__price")
        price_raw = price_el.get_text(strip=True) if price_el else None
        if not price_raw or parse_price(price_raw) is None:
            continue

        # Listing URL
        link_el = card.select_one("a.s-card__link")
        url     = link_el.get("href", "") if link_el else ""

        # Sold date — "Sold  May 14, 2026"
        date_el   = card.select_one(".s-card__caption")
        sold_date = parse_sold_date(date_el.get_text(strip=True) if date_el else None)

        rows.append({
            "vehicle_key":  vehicle_key,
            "search_year":  year,
            "search_make":  make,
            "search_model": model,
            "search_part":  part,
            "title":        title,
            "price_raw":    price_raw,
            "listing_url":  url,
            "sold_date":    sold_date,
            "scraped_at":   scraped_at,
        })

    return rows


# =========================================================
# Async fetch
# =========================================================

def make_session() -> "AsyncSession":
    """
    Create a curl_cffi AsyncSession that impersonates Chrome's TLS fingerprint.
    eBay inspects the TLS handshake (JA3 fingerprint) — plain httpx is fingerprinted
    as a bot and returns 403.  curl_cffi reproduces Chrome's exact TLS signature.

    verify=False handles networks that perform SSL inspection (corporate proxies,
    home routers with MITM certs) which would otherwise cause curl error 60.
    """
    if not _CURL:
        raise RuntimeError(
            "curl-cffi is required for eBay HTML scraping. Run: pip install curl-cffi"
        )
    return AsyncSession(impersonate=_IMPERSONATE, verify=False)


async def warm_session(session: "AsyncSession") -> None:
    """
    Visit eBay's homepage to acquire session cookies before searching.
    eBay requires a valid cookie session or it returns 403 on search pages.
    Non-fatal — proceeds even if the warm-up request fails.
    """
    try:
        await session.get("https://www.ebay.com/", headers={"Accept-Language": "en-US,en;q=0.9"})
    except Exception:
        pass


async def fetch_sold_html(
    session: "AsyncSession",
    year: int,
    make: str,
    model: str,
    part: str,
) -> tuple[str, str]:
    """
    Fetch the eBay sold-search HTML for one part.

    *session* must be a curl_cffi AsyncSession (see make_session()).
    Call warm_session(session) once per session before the first search.
    Returns (html_text, request_url).
    Raises an error on non-2xx responses.
    """
    params = {
        "_nkw":        f"{year} {make} {model} {part}",
        "LH_Complete": "1",
        "LH_Sold":     "1",
        "_sacat":      _MOTORS_CAT,
        "_ipg":        "60",
    }
    r = await session.get(EBAY_SOLD_URL, params=params, headers=HEADERS)
    r.raise_for_status()
    return r.text, str(r.url)
