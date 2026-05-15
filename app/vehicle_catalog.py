# =========================================================
# vehicle_catalog.py
# Async NHTSA makes/models catalog with SQLite caching
#
# Why async + httpx?
#   For models we fire two NHTSA calls in parallel with
#   asyncio.gather — the year-specific endpoint and the
#   generic fallback — then take whichever returns results.
#   This eliminates the sequential fallback penalty.
# =========================================================

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.db import get_catalog_cache, get_db, set_catalog_cache

logger = logging.getLogger(__name__)

NHTSA_BASE     = "https://vpic.nhtsa.dot.gov/api/vehicles"
CARQUERY_BASE  = "https://www.carqueryapi.com/api/0.3"
CACHE_TTL_DAYS = 30

# In-process memory cache — survives for the lifetime of the worker
_makes_cache: list[str] | None = None
_models_cache: dict[str, list[str]] = {}
_trims_cache:  dict[str, list[str]] = {}


async def fetch_makes() -> list[str]:
    """
    Return sorted Passenger Car makes from NHTSA.

    Cache hierarchy:
    1. In-process memory (instant)
    2. SQLite (fast local read, survives restarts)
    3. NHTSA HTTP call (network, ~300 ms, cached on return)
    """
    global _makes_cache
    if _makes_cache is not None:
        return _makes_cache

    with get_db() as conn:
        cached = get_catalog_cache(conn, cache_type="makes", make=None, year=None)
    if cached is not None:
        _makes_cache = cached
        return _makes_cache

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{NHTSA_BASE}/GetMakesForVehicleType/Passenger Car?format=json")
        r.raise_for_status()

    makes = sorted({m["MakeName"] for m in r.json().get("Results", []) if m.get("MakeName")})

    with get_db() as conn:
        set_catalog_cache(conn, cache_type="makes", make=None, year=None, data=makes)

    _makes_cache = makes
    return makes


async def fetch_models(make: str, year: int) -> list[str]:
    """
    Return sorted models for a given make+year from NHTSA.

    Fires two requests in parallel via asyncio.gather:
      - year-specific endpoint  (most precise)
      - generic make endpoint   (fallback — older/obscure makes)
    Whichever returns results wins; if both do, year-specific takes
    priority (it's a subset that's usually more accurate).
    """
    mem_key = f"{year}|{make.lower()}"
    if mem_key in _models_cache:
        return _models_cache[mem_key]

    with get_db() as conn:
        cached = get_catalog_cache(conn, cache_type="models", make=make, year=year)
    if cached is not None:
        _models_cache[mem_key] = cached
        return cached

    year_url    = f"{NHTSA_BASE}/GetModelsForMakeYear/make/{make}/modelyear/{year}?format=json"
    generic_url = f"{NHTSA_BASE}/GetModelsForMake/{make}?format=json"

    async with httpx.AsyncClient(timeout=20) as client:
        year_res, generic_res = await asyncio.gather(
            client.get(year_url),
            client.get(generic_url),
            return_exceptions=True,
        )

    models: list[str] = []

    if not isinstance(year_res, Exception) and year_res.is_success:
        models = [m["Model_Name"] for m in year_res.json().get("Results", []) if m.get("Model_Name")]

    if not models:
        if not isinstance(generic_res, Exception) and generic_res.is_success:
            models = [m["Model_Name"] for m in generic_res.json().get("Results", []) if m.get("Model_Name")]

    models = sorted(set(models))

    with get_db() as conn:
        set_catalog_cache(conn, cache_type="models", make=make, year=year, data=models)

    _models_cache[mem_key] = models
    return models


async def fetch_trims(make: str, model: str, year: int) -> list[str]:
    """
    Return sorted trim/package levels for a given make+model+year.

    Uses the CarQuery API (free, no key required), which holds trim-level
    data for most passenger vehicles sold in the US.  Falls back to an
    empty list gracefully — the UI keeps the trim field as a free-text
    input so users can still type a trim manually.

    Cache hierarchy:
    1. In-process memory (instant)
    2. SQLite (survives restarts, 30-day TTL)
    3. CarQuery HTTP call (~200 ms, cached on return)
    """
    mem_key = f"{year}|{make.lower()}|{model.lower()}"
    if mem_key in _trims_cache:
        return _trims_cache[mem_key]

    with get_db() as conn:
        cached = get_catalog_cache(conn, cache_type="trims", make=make, model=model, year=year)
    if cached is not None:
        _trims_cache[mem_key] = cached
        return cached

    # CarQuery accepts lowercase make names as IDs
    params = {
        "cmd":         "getTrims",
        "year":        str(year),
        "make":        make.lower(),
        "model":       model,
        "sold_in_us":  "1",
    }

    trims: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(CARQUERY_BASE, params=params)
            r.raise_for_status()
            data = r.json()

        trims = sorted({
            t["model_trim"]
            for t in data.get("Trims", [])
            if t.get("model_trim", "").strip()
        })
    except Exception as exc:
        logger.warning("CarQuery trims failed | %s %s %s | %s", year, make, model, exc)

    with get_db() as conn:
        set_catalog_cache(conn, cache_type="trims", make=make, model=model, year=year, data=trims)

    _trims_cache[mem_key] = trims
    return trims
