# =========================================================
# db.py
# SQLite persistence layer for SalvageIQ
# =========================================================

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "data" / "salvageiq.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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


def init_db() -> None:
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS part_pull_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_name TEXT NOT NULL UNIQUE,
                estimated_pull_minutes INTEGER NOT NULL,
                difficulty_score INTEGER NOT NULL,
                tool_complexity TEXT NOT NULL,
                shipping_class TEXT NOT NULL,
                estimated_shipping_cost REAL,
                estimated_yard_cost REAL,
                damage_risk_score INTEGER,
                storage_size TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_key TEXT NOT NULL UNIQUE,
                year INTEGER NOT NULL,
                make TEXT NOT NULL,
                model TEXT NOT NULL,
                trim TEXT,
                engine TEXT,
                body_class TEXT,
                drive_type TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS result_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_key TEXT NOT NULL,
                window_days INTEGER NOT NULL DEFAULT 90,
                source TEXT NOT NULL DEFAULT 'ebay',
                status TEXT NOT NULL DEFAULT 'pending',
                scraped_at TEXT,
                created_at TEXT NOT NULL,
                cache_expires_at TEXT,
                part_profile_version TEXT DEFAULT '1.0',
                FOREIGN KEY(vehicle_key) REFERENCES vehicles(vehicle_key)
            );

            CREATE TABLE IF NOT EXISTS result_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_set_id INTEGER NOT NULL,
                part_name TEXT NOT NULL,
                sold_count INTEGER,
                active_count INTEGER,
                sell_through_rate REAL,
                median_price REAL,
                opportunity_score REAL,
                estimated_net_value REAL,
                recommendation TEXT,
                confidence_score REAL,
                vehicle_rank INTEGER,
                estimated_pull_minutes INTEGER,
                difficulty_score INTEGER,
                shipping_class TEXT,
                FOREIGN KEY(result_set_id) REFERENCES result_sets(id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                vehicle_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress_message TEXT,
                progress_percent INTEGER DEFAULT 0,
                result_set_id INTEGER,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK(id = 1),
                labor_rate_per_hour REAL NOT NULL DEFAULT 25.0,
                marketplace_fee_percent REAL NOT NULL DEFAULT 0.13,
                default_shipping_adjustment REAL NOT NULL DEFAULT 0.0,
                risk_tolerance TEXT NOT NULL DEFAULT 'medium'
            );
        """)
        _migrate(conn)
        _seed_pull_profiles(conn)
        _seed_user_settings(conn)


# =========================================================
# Utility
# =========================================================

def _migrate(conn: sqlite3.Connection) -> None:
    """
    Additive schema migrations for existing databases.
    SQLite supports ADD COLUMN but not IF NOT EXISTS, so we catch the
    OperationalError that fires when the column already exists.
    """
    new_columns = [
        ("result_items", "estimated_pull_minutes", "INTEGER"),
        ("result_items", "difficulty_score",        "INTEGER"),
        ("result_items", "shipping_class",          "TEXT"),
        ("vehicles",     "series",                  "TEXT"),
        ("vehicles",     "fuel_type",               "TEXT"),
    ]
    for table, column, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists


def _seed_pull_profiles(conn: sqlite3.Connection) -> None:
    """
    Upsert pull profiles from net_value.py into the DB.

    Uses INSERT OR IGNORE so existing rows are left untouched and
    newly added profiles are inserted automatically on each startup.
    """
    from app.net_value import PULL_PROFILES

    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT OR IGNORE INTO part_pull_profiles (
            part_name, estimated_pull_minutes, difficulty_score,
            tool_complexity, shipping_class, estimated_shipping_cost,
            estimated_yard_cost, damage_risk_score, storage_size, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _seed_user_settings(conn: sqlite3.Connection) -> None:
    """Insert the default settings row if it doesn't exist yet."""
    conn.execute(
        """
        INSERT OR IGNORE INTO user_settings (id, labor_rate_per_hour, marketplace_fee_percent,
            default_shipping_adjustment, risk_tolerance)
        VALUES (1, 25.0, 0.13, 0.0, 'medium')
        """
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


# =========================================================
# Vehicles
# =========================================================

def upsert_vehicle(
    conn: sqlite3.Connection,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vehicle_key) DO UPDATE SET
            trim       = COALESCE(excluded.trim,       vehicles.trim),
            series     = COALESCE(excluded.series,     vehicles.series),
            body_class = COALESCE(excluded.body_class, vehicles.body_class),
            drive_type = COALESCE(excluded.drive_type, vehicles.drive_type),
            engine     = COALESCE(excluded.engine,     vehicles.engine),
            fuel_type  = COALESCE(excluded.fuel_type,  vehicles.fuel_type)
        """,
        (vehicle_key, year, make, model, trim, series,
         body_class, drive_type, engine, fuel_type, _now()),
    )


# =========================================================
# Result sets
# =========================================================

def create_result_set(
    conn: sqlite3.Connection,
    *,
    vehicle_key: str,
    window_days: int = 90,
    source: str = "ebay",
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO result_sets (vehicle_key, window_days, source, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (vehicle_key, window_days, source, _now()),
    )
    return cursor.lastrowid


def complete_result_set(conn: sqlite3.Connection, result_set_id: int, expires_days: int = 14) -> None:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=expires_days)).isoformat()
    conn.execute(
        """
        UPDATE result_sets
        SET status = 'completed', scraped_at = ?, cache_expires_at = ?
        WHERE id = ?
        """,
        (now.isoformat(), expires, result_set_id),
    )


def get_fresh_result_set(
    conn: sqlite3.Connection,
    vehicle_key: str,
    window_days: int = 90,
) -> dict | None:
    now = _now()
    row = conn.execute(
        """
        SELECT * FROM result_sets
        WHERE vehicle_key = ?
          AND window_days = ?
          AND status = 'completed'
          AND cache_expires_at > ?
        ORDER BY scraped_at DESC
        LIMIT 1
        """,
        (vehicle_key, window_days, now),
    ).fetchone()
    return _row_to_dict(row)


def get_most_recent_result_set(
    conn: sqlite3.Connection,
    vehicle_key: str,
    window_days: int = 90,
) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM result_sets
        WHERE vehicle_key = ?
          AND window_days = ?
          AND status = 'completed'
        ORDER BY scraped_at DESC
        LIMIT 1
        """,
        (vehicle_key, window_days),
    ).fetchone()
    return _row_to_dict(row)


def get_result_set_by_id(conn: sqlite3.Connection, result_set_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM result_sets WHERE id = ?", (result_set_id,)
    ).fetchone()
    return _row_to_dict(row)


# =========================================================
# Result items
# =========================================================

def insert_result_items(
    conn: sqlite3.Connection,
    result_set_id: int,
    items: list[dict[str, Any]],
) -> None:
    conn.executemany(
        """
        INSERT INTO result_items (
            result_set_id, part_name, sold_count, active_count,
            sell_through_rate, median_price, opportunity_score,
            estimated_net_value, recommendation, confidence_score, vehicle_rank,
            estimated_pull_minutes, difficulty_score, shipping_class
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            )
            for item in items
        ],
    )


def get_result_items(conn: sqlite3.Connection, result_set_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM result_items WHERE result_set_id = ? ORDER BY vehicle_rank ASC",
        (result_set_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# Jobs
# =========================================================

def create_job(conn: sqlite3.Connection, *, job_id: str, vehicle_key: str) -> None:
    conn.execute(
        """
        INSERT INTO jobs (id, vehicle_key, status, progress_percent, created_at)
        VALUES (?, ?, 'queued', 0, ?)
        """,
        (job_id, vehicle_key, _now()),
    )


def update_job(
    conn: sqlite3.Connection,
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
        fields.append("status = ?")
        values.append(status)
        if status == "running":
            fields.append("started_at = ?")
            values.append(_now())
        elif status in ("completed", "failed"):
            fields.append("completed_at = ?")
            values.append(_now())

    if progress_message is not None:
        fields.append("progress_message = ?")
        values.append(progress_message)

    if progress_percent is not None:
        fields.append("progress_percent = ?")
        values.append(progress_percent)

    if result_set_id is not None:
        fields.append("result_set_id = ?")
        values.append(result_set_id)

    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)

    if not fields:
        return

    values.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def get_recent_searches(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
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
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# User settings
# =========================================================

def get_user_settings(conn: sqlite3.Connection) -> dict:
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
    conn: sqlite3.Connection,
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
        fields.append("labor_rate_per_hour = ?")
        values.append(labor_rate_per_hour)
    if marketplace_fee_percent is not None:
        fields.append("marketplace_fee_percent = ?")
        values.append(marketplace_fee_percent)
    if default_shipping_adjustment is not None:
        fields.append("default_shipping_adjustment = ?")
        values.append(default_shipping_adjustment)
    if risk_tolerance is not None:
        fields.append("risk_tolerance = ?")
        values.append(risk_tolerance)

    if fields:
        conn.execute(
            f"UPDATE user_settings SET {', '.join(fields)} WHERE id = 1",
            values,
        )

    return get_user_settings(conn)
