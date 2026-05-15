# =========================================================
# api.py
# FastAPI entry point for SalvageIQ
# =========================================================

from __future__ import annotations

import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.cache import check_cache
from app.db import (
    create_job,
    get_db,
    get_job,
    get_recent_searches,
    get_result_items,
    get_result_set_by_id,
    get_user_settings,
    init_db,
    update_user_settings,
    upsert_vehicle,
)
from app.salvage_service import SalvageIQRequest, run_vehicle_analysis
from app.vehicle_catalog import fetch_makes, fetch_models, fetch_trims
from app.vehicle_lookup import build_vehicle_key, normalize_vehicle_input


app = FastAPI(title="SalvageIQ", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


# =========================================================
# Health
# =========================================================

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# =========================================================
# Vehicle catalog (makes / models)
# =========================================================

@app.get("/api/vehicles/makes")
async def list_makes() -> dict:
    """Return all Passenger Car makes, cached from NHTSA."""
    makes = await fetch_makes()
    return {"makes": makes}


@app.get("/api/vehicles/models")
async def list_models(make: str, year: int) -> dict:
    """
    Return models for a given make + year.
    Fires two NHTSA calls in parallel (year-specific + generic fallback).
    """
    models = await fetch_models(make=make, year=year)
    return {"models": models}


@app.get("/api/vehicles/trims")
async def list_trims(make: str, model: str, year: int) -> dict:
    """
    Return trim/package levels for a given make + model + year.
    Sourced from CarQuery API, cached in SQLite (30-day TTL).
    Returns an empty list if no data is available — UI falls back to free text.
    """
    trims = await fetch_trims(make=make, model=model, year=year)
    return {"trims": trims}


# =========================================================
# Search
# =========================================================

class SearchRequest(BaseModel):
    vin: str | None = Field(default=None, max_length=17)
    year: int | None = Field(default=None, ge=1975, le=2035)
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    engine: str | None = None
    top_n: int = Field(default=10, ge=1, le=25)
    max_pages_per_search: int = Field(default=2, ge=1, le=5)
    window_days: int = Field(default=90, ge=30, le=365)


@app.post("/api/search")
def search(payload: SearchRequest, background_tasks: BackgroundTasks) -> dict:
    """
    Check cache and either return cached results or start an async scrape job.
    """
    try:
        vehicle = normalize_vehicle_input(
            year=payload.year,
            make=payload.make,
            model=payload.model,
            vin=payload.vin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vehicle_key = build_vehicle_key(vehicle)

    with get_db() as conn:
        upsert_vehicle(
            conn,
            vehicle_key=vehicle_key,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            series=vehicle.series,
            body_class=vehicle.body_class,
            drive_type=vehicle.drive_type,
            engine=vehicle.engine,
            fuel_type=vehicle.fuel_type,
        )

    cache = check_cache(vehicle_key, payload.window_days)

    if cache["cache_status"] == "fresh":
        with get_db() as conn:
            items = get_result_items(conn, cache["result_set_id"])
        return {
            "mode": "cache",
            "cache_status": "fresh",
            "scraped_at": cache["scraped_at"],
            "cache_expires_at": cache["cache_expires_at"],
            "result_set_id": cache["result_set_id"],
            "vehicle": vehicle.to_dict(),
            "items": items,
        }

    if cache["cache_status"] == "usable_stale":
        with get_db() as conn:
            items = get_result_items(conn, cache["result_set_id"])
        job_id = _start_job(vehicle_key, payload, vehicle, background_tasks)
        return {
            "mode": "cache",
            "cache_status": "usable_stale",
            "scraped_at": cache["scraped_at"],
            "cache_expires_at": cache["cache_expires_at"],
            "result_set_id": cache["result_set_id"],
            "refresh_job_id": job_id,
            "vehicle": vehicle.to_dict(),
            "items": items,
        }

    # expired or missing — start a new scrape job
    job_id = _start_job(vehicle_key, payload, vehicle, background_tasks)
    return {
        "mode": "job",
        "cache_status": cache["cache_status"],
        "job_id": job_id,
        "status": "queued",
        "vehicle": vehicle.to_dict(),
    }


def _start_job(vehicle_key, payload, vehicle, background_tasks) -> str:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    with get_db() as conn:
        create_job(conn, job_id=job_id, vehicle_key=vehicle_key)

    request = SalvageIQRequest(
        year=vehicle.year,
        make=vehicle.make,
        model=vehicle.model,
        vin=None,
        top_n=payload.top_n,
        max_pages_per_search=payload.max_pages_per_search,
        window_days=payload.window_days,
    )
    background_tasks.add_task(run_vehicle_analysis, job_id, vehicle_key, request)
    return job_id


# =========================================================
# Job status
# =========================================================

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> dict:
    with get_db() as conn:
        job = get_job(conn, job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    return {
        "job_id": job["id"],
        "status": job["status"],
        "progress_percent": job["progress_percent"] or 0,
        "progress_message": job["progress_message"] or "",
        "result_set_id": job["result_set_id"],
        "error_message": job["error_message"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
    }


# =========================================================
# Results
# =========================================================

@app.get("/api/results/{result_set_id}")
def get_results(result_set_id: int) -> dict:
    with get_db() as conn:
        rs = get_result_set_by_id(conn, result_set_id)
        if not rs:
            raise HTTPException(status_code=404, detail="Result set not found.")
        items = get_result_items(conn, result_set_id)

    return {
        "result_set_id": result_set_id,
        "vehicle_key": rs["vehicle_key"],
        "scraped_at": rs["scraped_at"],
        "cache_expires_at": rs["cache_expires_at"],
        "source": rs["source"],
        "items": items,
    }


# =========================================================
# User settings
# =========================================================

class SettingsUpdate(BaseModel):
    labor_rate_per_hour: float | None = Field(default=None, ge=0, le=500,
        description="Your hourly labor rate in dollars.")
    marketplace_fee_percent: float | None = Field(default=None, ge=0, le=0.5,
        description="Marketplace fee as a decimal (e.g. 0.13 for 13%).")
    default_shipping_adjustment: float | None = Field(default=None, ge=-1.0, le=1.0,
        description="Multiplier adjustment applied to estimated shipping costs.")
    risk_tolerance: str | None = Field(default=None,
        description="low | medium | high — shifts Pull/Maybe thresholds.")


# =========================================================
# History
# =========================================================

@app.get("/api/history")
def get_history(limit: int = 15) -> dict:
    with get_db() as conn:
        searches = get_recent_searches(conn, limit=limit)
    return {"searches": searches}


# =========================================================
# User settings
# =========================================================

@app.get("/api/settings")
def get_settings() -> dict:
    with get_db() as conn:
        return get_user_settings(conn)


@app.patch("/api/settings")
def patch_settings(payload: SettingsUpdate) -> dict:
    with get_db() as conn:
        return update_user_settings(
            conn,
            labor_rate_per_hour=payload.labor_rate_per_hour,
            marketplace_fee_percent=payload.marketplace_fee_percent,
            default_shipping_adjustment=payload.default_shipping_adjustment,
            risk_tolerance=payload.risk_tolerance,
        )


app.mount("/assets", StaticFiles(directory="assets"), name="assets")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
