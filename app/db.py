# =========================================================
# db.py
# PostgreSQL persistence layer for SalvageIQ
# =========================================================

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("America/Chicago")

import psycopg2
import psycopg2.extras

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# =========================================================
# Connection adapter
# =========================================================

class _PGConn:
    """
    Thin adapter that gives psycopg2 connections the same
    .execute() / .executemany() surface as sqlite3.Connection.

    Every .execute() call opens a fresh RealDictCursor so rows are
    returned as plain dicts.  The caller never touches raw psycopg2
    cursors directly.
    """

    def __init__(self, raw: "psycopg2.extensions.connection") -> None:
        self._raw = raw

    def execute(self, sql: str, params: Any = ()) -> "psycopg2.extensions.cursor":
        cur = self._raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, params_seq: Any) -> None:
        cur = self._raw.cursor()
        cur.executemany(sql, params_seq)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def _connect() -> _PGConn:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:password@localhost:5432/salvageiq",
    )
    # Railway sometimes gives postgres:// — psycopg2 requires postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    raw = psycopg2.connect(url)
    return _PGConn(raw)


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =========================================================
# Schema creation
# =========================================================

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS part_pull_profiles (
        id                      SERIAL PRIMARY KEY,
        part_name               TEXT NOT NULL UNIQUE,
        estimated_pull_minutes  INTEGER NOT NULL,
        difficulty_score        INTEGER NOT NULL,
        tool_complexity         TEXT NOT NULL,
        shipping_class          TEXT NOT NULL,
        estimated_shipping_cost REAL,
        estimated_yard_cost     REAL,
        damage_risk_score       INTEGER,
        storage_size            TEXT,
        created_at              TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vehicles (
        id          SERIAL PRIMARY KEY,
        vehicle_key TEXT NOT NULL UNIQUE,
        year        INTEGER NOT NULL,
        make        TEXT NOT NULL,
        model       TEXT NOT NULL,
        trim        TEXT,
        series      TEXT,
        engine      TEXT,
        body_class  TEXT,
        drive_type  TEXT,
        fuel_type   TEXT,
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_sets (
        id                   SERIAL PRIMARY KEY,
        vehicle_key          TEXT NOT NULL,
        window_days          INTEGER NOT NULL DEFAULT 90,
        source               TEXT NOT NULL DEFAULT 'ebay',
        status               TEXT NOT NULL DEFAULT 'pending',
        scraped_at           TEXT,
        created_at           TEXT NOT NULL,
        cache_expires_at     TEXT,
        part_profile_version TEXT DEFAULT '1.0'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_items (
        id                     SERIAL PRIMARY KEY,
        result_set_id          INTEGER NOT NULL,
        part_name              TEXT NOT NULL,
        sold_count             INTEGER,
        active_count           INTEGER,
        sell_through_rate      REAL,
        median_price           REAL,
        opportunity_score      REAL,
        estimated_net_value    REAL,
        recommendation         TEXT,
        confidence_score       REAL,
        vehicle_rank           INTEGER,
        estimated_pull_minutes INTEGER,
        difficulty_score       INTEGER,
        shipping_class         TEXT,
        trend_direction        TEXT,
        trend_pct              REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id               TEXT PRIMARY KEY,
        vehicle_key      TEXT NOT NULL,
        status           TEXT NOT NULL DEFAULT 'queued',
        progress_message TEXT,
        progress_percent INTEGER DEFAULT 0,
        result_set_id    INTEGER,
        error_message    TEXT,
        created_at       TEXT NOT NULL,
        started_at       TEXT,
        completed_at     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        id                          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        labor_rate_per_hour         REAL NOT NULL DEFAULT 25.0,
        marketplace_fee_percent     REAL NOT NULL DEFAULT 0.13,
        default_shipping_adjustment REAL NOT NULL DEFAULT 0.0,
        risk_tolerance              TEXT NOT NULL DEFAULT 'medium'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vehicle_catalog_cache (
        cache_type TEXT NOT NULL,
        make       TEXT,
        model      TEXT,
        year       INTEGER,
        data       TEXT NOT NULL,
        cached_at  TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        PRIMARY KEY (cache_type, make, model, year)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sold_listings (
        id           SERIAL PRIMARY KEY,
        vehicle_key  TEXT    NOT NULL,
        search_year  INTEGER NOT NULL,
        search_make  TEXT    NOT NULL,
        search_model TEXT    NOT NULL,
        search_part  TEXT    NOT NULL,
        title        TEXT    NOT NULL,
        price_raw    TEXT    NOT NULL,
        listing_url  TEXT,
        sold_date    TEXT,
        scraped_at   TEXT    NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sold_vk_part
        ON sold_listings (vehicle_key, search_part, scraped_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_status (
        vehicle_key     TEXT PRIMARY KEY,
        last_crawled_at TEXT,
        parts_scraped   INTEGER DEFAULT 0,
        total_listings  INTEGER DEFAULT 0,
        updated_at      TEXT NOT NULL
    )
    """,
]


def init_db() -> None:
    with get_db() as conn:
        for stmt in _SCHEMA_STATEMENTS:
            conn.execute(stmt)
        _migrate(conn)
        _seed_pull_profiles(conn)
        _seed_user_settings(conn)


# =========================================================
# Migrations (additive — safe to run on every startup)
# =========================================================

def _migrate(conn: _PGConn) -> None:
    """
    ADD COLUMN IF NOT EXISTS is idempotent in PostgreSQL 9.6+,
    so no try/except needed.
    """
    new_columns = [
        ("result_items", "estimated_pull_minutes", "INTEGER"),
        ("result_items", "difficulty_score",        "INTEGER"),
        ("result_items", "shipping_class",          "TEXT"),
        ("result_items", "trend_direction",         "TEXT"),
        ("result_items", "trend_pct",               "REAL"),
        ("vehicles",     "series",                  "TEXT"),
        ("vehicles",     "fuel_type",               "TEXT"),
    ]
    for table, column, col_type in new_columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
        )


# =========================================================
# Seed helpers
# =========================================================

def _seed_pull_profiles(conn: _PGConn) -> None:
    from app.net_value import PULL_PROFILES

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO part_pull_profiles (
            part_name, estimated_pull_minutes, difficulty_score,
            tool_complexity, shipping_class, estimated_shipping_cost,
            estimated_yard_cost, damage_risk_score, storage_size, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (part_name) DO NOTHING
        """,
        [
            (
                part_name,
                p["estimated_pull_minutes"],
                p["difficulty_score"],
                p["tool_complexity"],
                p["shipping_class"],
                p.get("estimated_shipping_cost"),
                p.get("estimated_yard_cost"),
                p.get("damage_risk_score"),
                p.get("storage_size"),
                now,
            )
            for part_name, p in PULL_PROFILES.items()
        ],
    )


def _seed_user_settings(conn: _PGConn) -> None:
    conn.execute(
        """
        INSERT INTO user_settings
            (id, labor_rate_per_hour, marketplace_fee_percent,
             default_shipping_adjustment, risk_tolerance)
        VALUES (1, 25.0, 0.13, 0.0, 'medium')
        ON CONFLICT (id) DO NOTHING
        """
    )


# =========================================================
# Utility
# =========================================================

def _now() -> str:
    return datetime.now(_TZ).isoformat()


def _row_to_dict(row: Any) -> dict | None:
    """Convert a RealDictRow (or None) to a plain dict."""
    return dict(row) if row else None


# =========================================================
# Vehicles
# =========================================================

def upsert_vehicle(
    conn: _PGConn,
    *,
    vehicle_key: str,
    year: int,
    make: str,
    model: str,
    trim: str | None = None,
    series: str | None = None,
    body_class: str | None = None,
    drive_type: str | None = None,
    engine: str | None = None,
    fuel_type: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO vehicles (
            vehicle_key, year, make, model, trim, series,
            body_class, drive_type, engine, fuel_type, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (vehicle_key) DO UPDATE SET
            trim       = COALESCE(EXCLUDED.trim,       vehicles.trim),
            series     = COALESCE(EXCLUDED.series,     vehicles.series),
            body_class = COALESCE(EXCLUDED.body_class, vehicles.body_class),
            drive_type = COALESCE(EXCLUDED.drive_type, vehicles.drive_type),
            engine     = COALESCE(EXCLUDED.engine,     vehicles.engine),
            fuel_type  = COALESCE(EXCLUDED.fuel_type,  vehicles.fuel_type)
        """,
        (vehicle_key, year, make, model, trim, series,
         body_class, drive_type, engine, fuel_type, _now()),
    )


# =========================================================
# Result sets
# =========================================================

def create_result_set(
    conn: _PGConn,
    *,
    vehicle_key: str,
    window_days: int = 90,
    source: str = "ebay",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO result_sets (vehicle_key, window_days, source, status, created_at)
        VALUES (%s, %s, %s, 'pending', %s)
        RETURNING id
        """,
        (vehicle_key, window_days, source, _now()),
    )
    return cur.fetchone()["id"]


def complete_result_set(conn: _PGConn, result_set_id: int, expires_days: int = 14) -> None:
    from datetime import timedelta
    now     = datetime.now(_TZ)
    expires = (now + timedelta(days=expires_days)).isoformat()
    conn.execute(
        """
        UPDATE result_sets
        SET status = 'completed', scraped_at = %s, cache_expires_at = %s
        WHERE id = %s
        """,
        (now.isoformat(), expires, result_set_id),
    )


def get_fresh_result_set(
    conn: _PGConn,
    vehicle_key: str,
    window_days: int = 90,
) -> dict | None:
    now = _now()
    row = conn.execute(
        """
        SELECT * FROM result_sets
        WHERE vehicle_key = %s
          AND window_days = %s
          AND status = 'completed'
          AND cache_expires_at > %s
        ORDER BY scraped_at DESC
        LIMIT 1
        """,
        (vehicle_key, window_days, now),
    ).fetchone()
    return _row_to_dict(row)


def get_most_recent_result_set(
    conn: _PGConn,
    vehicle_key: str,
    window_days: int = 90,
) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM result_sets
        WHERE vehicle_key = %s
          AND window_days = %s
          AND status = 'completed'
        ORDER BY scraped_at DESC
        LIMIT 1
        """,
        (vehicle_key, window_days),
    ).fetchone()
    return _row_to_dict(row)


def get_result_set_by_id(conn: _PGConn, result_set_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM result_sets WHERE id = %s", (result_set_id,)
    ).fetchone()
    return _row_to_dict(row)


# =========================================================
# Result items
# =========================================================

def insert_result_items(
    conn: _PGConn,
    result_set_id: int,
    items: list[dict[str, Any]],
) -> None:
    conn.executemany(
        """
        INSERT INTO result_items (
            result_set_id, part_name, sold_count, active_count,
            sell_through_rate, median_price, opportunity_score,
            estimated_net_value, recommendation, confidence_score, vehicle_rank,
            estimated_pull_minutes, difficulty_score, shipping_class,
            trend_direction, trend_pct
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                result_set_id,
                item.get("part") or item.get("part_name"),
                item.get("sold_count"),
                item.get("active_count"),
                item.get("str") or item.get("sell_through_rate"),
                item.get("median_sold_price") or item.get("median_price"),
                item.get("opportunity_score"),
                item.get("estimated_net_value"),
                item.get("recommendation"),
                item.get("confidence_score"),
                item.get("vehicle_rank"),
                item.get("estimated_pull_minutes"),
                item.get("difficulty_score"),
                item.get("shipping_class"),
                item.get("trend_direction"),
                item.get("trend_pct"),
            )
            for item in items
        ],
    )


def get_result_items(conn: _PGConn, result_set_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM result_items WHERE result_set_id = %s ORDER BY vehicle_rank ASC",
        (result_set_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# Jobs
# =========================================================

def create_job(conn: _PGConn, *, job_id: str, vehicle_key: str) -> None:
    conn.execute(
        """
        INSERT INTO jobs (id, vehicle_key, status, progress_percent, created_at)
        VALUES (%s, %s, 'queued', 0, %s)
        """,
        (job_id, vehicle_key, _now()),
    )


def update_job(
    conn: _PGConn,
    job_id: str,
    *,
    status: str | None = None,
    progress_message: str | None = None,
    progress_percent: int | None = None,
    result_set_id: int | None = None,
    error_message: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []

    if status is not None:
        fields.append("status = %s")
        values.append(status)
        if status == "running":
            fields.append("started_at = %s")
            values.append(_now())
        elif status in ("completed", "failed"):
            fields.append("completed_at = %s")
            values.append(_now())

    if progress_message is not None:
        fields.append("progress_message = %s")
        values.append(progress_message)

    if progress_percent is not None:
        fields.append("progress_percent = %s")
        values.append(progress_percent)

    if result_set_id is not None:
        fields.append("result_set_id = %s")
        values.append(result_set_id)

    if error_message is not None:
        fields.append("error_message = %s")
        values.append(error_message)

    if not fields:
        return

    values.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = %s", values)


def get_job(conn: _PGConn, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    return _row_to_dict(row)


def get_recent_searches(conn: _PGConn, limit: int = 15) -> list[dict]:
    """
    Return the most recent completed result set per vehicle, newest first.
    Joins vehicles so we have display-friendly year/make/model.
    """
    rows = conn.execute(
        """
        SELECT
            v.year, v.make, v.model, v.trim,
            v.vehicle_key,
            rs.id          AS result_set_id,
            rs.scraped_at,
            rs.cache_expires_at
        FROM vehicles v
        INNER JOIN result_sets rs
            ON rs.vehicle_key = v.vehicle_key
           AND rs.id = (
               SELECT id FROM result_sets
               WHERE vehicle_key = v.vehicle_key
                 AND status = 'completed'
               ORDER BY scraped_at DESC
               LIMIT 1
           )
        ORDER BY rs.scraped_at DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# Vehicle catalog cache
# =========================================================

def get_catalog_cache(
    conn: _PGConn,
    *,
    cache_type: str,
    make: str | None,
    model: str | None = None,
    year: int | None,
) -> list | None:
    """Return cached data list if present and not expired, else None."""
    import json as _json
    now = _now()
    # IS NOT DISTINCT FROM is the NULL-safe equality operator in PostgreSQL
    row = conn.execute(
        """
        SELECT data FROM vehicle_catalog_cache
        WHERE cache_type = %s
          AND make  IS NOT DISTINCT FROM %s
          AND model IS NOT DISTINCT FROM %s
          AND year  IS NOT DISTINCT FROM %s
          AND expires_at > %s
        """,
        (cache_type, make, model, year, now),
    ).fetchone()
    if row:
        return _json.loads(row["data"])
    return None


def set_catalog_cache(
    conn: _PGConn,
    *,
    cache_type: str,
    make: str | None,
    model: str | None = None,
    year: int | None,
    data: list,
    ttl_days: int = 30,
) -> None:
    """Upsert a catalog cache entry with a TTL."""
    import json as _json
    from datetime import timedelta
    now     = datetime.now(_TZ)
    expires = (now + timedelta(days=ttl_days)).isoformat()
    conn.execute(
        """
        INSERT INTO vehicle_catalog_cache
            (cache_type, make, model, year, data, cached_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cache_type, make, model, year) DO UPDATE SET
            data       = EXCLUDED.data,
            cached_at  = EXCLUDED.cached_at,
            expires_at = EXCLUDED.expires_at
        """,
        (cache_type, make, model, year, _json.dumps(data), now.isoformat(), expires),
    )


# =========================================================
# User settings
# =========================================================

def get_user_settings(conn: _PGConn) -> dict:
    """Return the single user settings row, falling back to defaults."""
    row = conn.execute("SELECT * FROM user_settings WHERE id = 1").fetchone()
    if row:
        return dict(row)
    return {
        "labor_rate_per_hour": 25.0,
        "marketplace_fee_percent": 0.13,
        "default_shipping_adjustment": 0.0,
        "risk_tolerance": "medium",
    }


def update_user_settings(
    conn: _PGConn,
    *,
    labor_rate_per_hour: float | None = None,
    marketplace_fee_percent: float | None = None,
    default_shipping_adjustment: float | None = None,
    risk_tolerance: str | None = None,
) -> dict:
    """Patch whichever settings fields are supplied; return the updated row."""
    fields: list[str] = []
    values: list[Any] = []

    if labor_rate_per_hour is not None:
        fields.append("labor_rate_per_hour = %s")
        values.append(labor_rate_per_hour)
    if marketplace_fee_percent is not None:
        fields.append("marketplace_fee_percent = %s")
        values.append(marketplace_fee_percent)
    if default_shipping_adjustment is not None:
        fields.append("default_shipping_adjustment = %s")
        values.append(default_shipping_adjustment)
    if risk_tolerance is not None:
        fields.append("risk_tolerance = %s")
        values.append(risk_tolerance)

    if fields:
        conn.execute(
            f"UPDATE user_settings SET {', '.join(fields)} WHERE id = 1",
            values,
        )

    return get_user_settings(conn)


# =========================================================
# Sold listings (crawler + runner shared store)
# =========================================================

def insert_sold_listings(conn: _PGConn, rows: list[dict]) -> None:
    """Bulk-insert scraped sold listing rows."""
    conn.executemany(
        """
        INSERT INTO sold_listings
            (vehicle_key, search_year, search_make, search_model,
             search_part, title, price_raw, listing_url, sold_date, scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                r["vehicle_key"],
                r["search_year"],
                r["search_make"],
                r["search_model"],
                r["search_part"],
                r["title"],
                r["price_raw"],
                r.get("listing_url"),
                r.get("sold_date"),
                r["scraped_at"],
            )
            for r in rows
        ],
    )


def get_sold_listings(
    conn: _PGConn,
    vehicle_key: str,
    part: str,
    days: int = 14,
) -> list[dict]:
    """
    Return sold listings for a vehicle+part scraped within the last *days* days.
    Used by runner.py as a DB-first cache check.
    """
    rows = conn.execute(
        """
        SELECT * FROM sold_listings
        WHERE vehicle_key = %s
          AND search_part = %s
          AND scraped_at::timestamptz >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY scraped_at DESC
        """,
        (vehicle_key, part, days),
    ).fetchall()
    return [dict(r) for r in rows]


def get_sold_listings_history(
    conn: _PGConn,
    vehicle_key: str,
    part: str,
    days: int = 60,
) -> list[dict]:
    """
    Return all sold listing history for a vehicle+part over *days* days.
    Used by trend.py to compute price direction.
    """
    rows = conn.execute(
        """
        SELECT price_raw, scraped_at, sold_date FROM sold_listings
        WHERE vehicle_key = %s
          AND search_part = %s
          AND scraped_at::timestamptz >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY scraped_at DESC
        """,
        (vehicle_key, part, days),
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# Crawl status
# =========================================================

def upsert_crawl_status(
    conn: _PGConn,
    *,
    vehicle_key: str,
    parts_scraped: int,
    total_listings: int,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO crawl_status
            (vehicle_key, last_crawled_at, parts_scraped, total_listings, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (vehicle_key) DO UPDATE SET
            last_crawled_at = EXCLUDED.last_crawled_at,
            parts_scraped   = EXCLUDED.parts_scraped,
            total_listings  = EXCLUDED.total_listings,
            updated_at      = EXCLUDED.updated_at
        """,
        (vehicle_key, now, parts_scraped, total_listings, now),
    )


def get_crawl_status(conn: _PGConn, vehicle_key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM crawl_status WHERE vehicle_key = %s", (vehicle_key,)
    ).fetchone()
    return _row_to_dict(row)


def seed_catalog_vehicles(
    conn: _PGConn,
    vehicles: list[dict],
    year_start: int,
    year_end: int,
) -> int:
    """
    Insert seed vehicles into the vehicles table (ON CONFLICT DO NOTHING).
    Covers every make/model across the given year range.
    Returns the number of new rows inserted.
    """
    rows = [
        (
            f"{year}|{v['make']}|{v['model']}",
            year,
            v["make"],
            v["model"],
            _now(),
        )
        for v in vehicles
        for year in range(year_start, year_end + 1)
    ]
    before = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()["count"]
    conn.executemany(
        """
        INSERT INTO vehicles (vehicle_key, year, make, model, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (vehicle_key) DO NOTHING
        """,
        rows,
    )
    after = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()["count"]
    return after - before


def get_vehicles_for_crawl(conn: _PGConn, limit: int = 50) -> list[dict]:
    """
    Return vehicles that need crawling — never crawled or last crawled > 14 days ago.
    Sorted oldest-first so the most stale vehicles are prioritized.
    """
    rows = conn.execute(
        """
        SELECT v.vehicle_key, v.year, v.make, v.model
        FROM vehicles v
        LEFT JOIN crawl_status cs ON cs.vehicle_key = v.vehicle_key
        WHERE cs.last_crawled_at IS NULL
           OR cs.last_crawled_at::timestamptz < NOW() - INTERVAL '14 days'
        ORDER BY cs.last_crawled_at ASC NULLS FIRST
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
