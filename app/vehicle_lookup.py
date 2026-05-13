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
    series: str | None = None
    body_class: str | None = None
    drive_type: str | None = None
    engine: str | None = None
    fuel_type: str | None = None
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
        source="direct",
    )


def build_vehicle_key(vehicle: VehicleIdentity) -> str:
    """
    Build a stable, lowercase cache key from a vehicle identity.

    Trim is intentionally excluded: the scraping pipeline does not
    differentiate by trim, and NHTSA decode can return inconsistent
    or absent trim values for the same VIN across calls.

    Example: 2017|chrysler|pacifica
    """
    return "|".join([
        str(vehicle.year),
        (vehicle.make or "").strip().lower(),
        (vehicle.model or "").strip().lower(),
    ])


def decode_vin_with_nhtsa(vin: str) -> VehicleIdentity:
    """
    Decode a VIN using the NHTSA vPIC API.

    Captures year/make/model/trim plus body class, drive type,
    engine, and fuel type for richer display and future fitment work.
    """
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    _WANTED = {
        "Model Year", "Make", "Model", "Trim", "Series",
        "Body Class", "Drive Type",
        "Engine Configuration", "Engine Number of Cylinders",
        "Displacement (L)",
        "Fuel Type - Primary",
    }

    results = response.json().get("Results", [])
    values = {
        row.get("Variable"): row.get("Value")
        for row in results
        if row.get("Variable") in _WANTED
        and row.get("Value") not in (None, "", "Not Applicable")
    }

    if not values.get("Model Year") or not values.get("Make") or not values.get("Model"):
        raise ValueError("VIN decoded, but year/make/model was incomplete.")

    return VehicleIdentity(
        year=int(values["Model Year"]),
        make=values["Make"].strip(),
        model=values["Model"].strip(),
        trim=values.get("Trim") or None,
        series=values.get("Series") or None,
        body_class=_normalize_body_class(values.get("Body Class")),
        drive_type=_normalize_drive_type(values.get("Drive Type")),
        engine=_compose_engine(
            values.get("Displacement (L)"),
            values.get("Engine Configuration"),
            values.get("Engine Number of Cylinders"),
        ),
        fuel_type=_normalize_fuel_type(values.get("Fuel Type - Primary")),
        source="nhtsa_vpic",
    )


# =========================================================
# Field normalizers
# =========================================================

def _compose_engine(
    displacement: str | None,
    config: str | None,
    cylinders: str | None,
) -> str | None:
    """Build a short readable engine string, e.g. '3.6L V6' or '2.0L I4'."""
    parts: list[str] = []

    if displacement:
        try:
            parts.append(f"{float(displacement):.1f}L")
        except ValueError:
            parts.append(displacement)

    if config and cylinders:
        c = cylinders.strip()
        cfg = config.upper()
        if "V" in cfg and "SHAPED" in cfg:
            parts.append(f"V{c}")
        elif "IN-LINE" in cfg or "STRAIGHT" in cfg:
            parts.append(f"I{c}")
        elif "FLAT" in cfg or "BOXER" in cfg or "OPPOSED" in cfg:
            parts.append(f"H{c}")
        elif "ROTARY" in cfg or "WANKEL" in cfg:
            parts.append("Rotary")
        else:
            parts.append(f"{c}-cyl")
    elif cylinders:
        parts.append(f"{cylinders.strip()}-cyl")

    return " ".join(parts) if parts else None


def _normalize_drive_type(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.upper()
    if "AWD" in s or "ALL-WHEEL" in s or "ALL WHEEL" in s:
        return "AWD"
    if "4WD" in s or "4X4" in s or "4-WHEEL" in s or "FOUR-WHEEL" in s:
        return "4WD"
    if "FWD" in s or "FRONT" in s:
        return "FWD"
    if "RWD" in s or "REAR" in s:
        return "RWD"
    return raw.strip()


def _normalize_body_class(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    # Map verbose NHTSA strings to short readable labels
    lower = s.lower()
    if "sport utility" in lower:
        return "SUV"
    if "pickup" in lower:
        return "Pickup"
    if "minivan" in lower or "van/minivan" in lower:
        return "Minivan"
    if "cargo van" in lower:
        return "Cargo Van"
    if "convertible" in lower:
        return "Convertible"
    if "coupe" in lower:
        return "Coupe"
    if "hatchback" in lower:
        return "Hatchback"
    if "wagon" in lower:
        return "Wagon"
    if "sedan" in lower:
        return "Sedan"
    if "crossover" in lower:
        return "Crossover"
    # Strip any trailing parenthetical (e.g. "(SUV)") for anything else
    import re
    return re.sub(r"\s*\([^)]+\)\s*$", "", s).strip() or None


def _normalize_fuel_type(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    lower = s.lower()
    if "gasoline" in lower or "petrol" in lower:
        return "Gas"
    if "diesel" in lower:
        return "Diesel"
    if "electric" in lower and "hybrid" not in lower:
        return "Electric"
    if "hybrid" in lower and "plug" in lower:
        return "Plug-in Hybrid"
    if "hybrid" in lower:
        return "Hybrid"
    if "natural gas" in lower or "cng" in lower:
        return "CNG"
    if "flex" in lower or "e85" in lower or "ethanol" in lower:
        return "Flex Fuel"
    return s
