# =========================================================
# vehicle_lookup.py
# Vehicle lookup helpers for SalvageIQ
#
# Purpose:
# Resolve vehicle input into a normalized year/make/model payload.
# Supports direct YMM input now and VIN decoding through NHTSA vPIC.
#
# Notes:
# - No secrets required
# - CarAPI can replace or supplement this later for richer trim data
# =========================================================

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import requests


@dataclass(slots=True)
class VehicleIdentity:
    """Normalized vehicle identity used by the scoring pipeline."""

    year: int
    make: str
    model: str
    trim: str | None = None
    source: str = "direct"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_vehicle_input(
    *,
    year: int | None = None,
    make: str | None = None,
    model: str | None = None,
    vin: str | None = None,
) -> VehicleIdentity:
    """
    Resolve either VIN or direct year/make/model into VehicleIdentity.

    Priority:
    1. VIN, when a 17-character VIN is supplied
    2. Direct year/make/model
    """
    clean_vin = (vin or "").strip().upper()

    if clean_vin:
        if len(clean_vin) != 17:
            raise ValueError("VIN must be 17 characters.")
        return decode_vin_with_nhtsa(clean_vin)

    if year is None or not make or not model:
        raise ValueError("Provide either a VIN or year, make, and model.")

    return VehicleIdentity(
        year=int(year),
        make=make.strip(),
        model=model.strip(),
        trim=None,
        source="direct",
    )


def build_vehicle_key(vehicle: VehicleIdentity) -> str:
    """
    Build a stable, lowercase cache key from a vehicle identity.

    Example: 2017|chrysler|pacifica|touring
    """
    parts = [
        str(vehicle.year),
        (vehicle.make or "").strip().lower(),
        (vehicle.model or "").strip().lower(),
        (vehicle.trim or "").strip().lower(),
    ]
    # strip trailing empty segment when trim is absent
    return "|".join(p for p in parts if p)


def decode_vin_with_nhtsa(vin: str) -> VehicleIdentity:
    """
    Decode a VIN using the NHTSA vPIC API.

    NHTSA is good enough for the first working model. It avoids storing API
    credentials in client-side code, which is where dreams and secrets go to die.
    """
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    results = response.json().get("Results", [])
    values = {
        row.get("Variable"): row.get("Value")
        for row in results
        if row.get("Variable") in {"Model Year", "Make", "Model", "Trim"}
    }

    if not values.get("Model Year") or not values.get("Make") or not values.get("Model"):
        raise ValueError("VIN decoded, but year/make/model was incomplete.")

    return VehicleIdentity(
        year=int(values["Model Year"]),
        make=values["Make"].strip(),
        model=values["Model"].strip(),
        trim=(values.get("Trim") or None),
        source="nhtsa_vpic",
    )
