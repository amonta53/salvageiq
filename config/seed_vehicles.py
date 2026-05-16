# =========================================================
# config/seed_vehicles.py
#
# Curated list of the 50 most common salvage yard vehicles.
# On startup, the app seeds the vehicles table with every
# make/model across a 25-year window so the background crawler
# proactively builds sold-listing history before anyone searches.
#
# Ranking basis: US fleet size, salvage yard pull frequency,
# and eBay Parts transaction volume.
# =========================================================

from __future__ import annotations

SEED_VEHICLES: list[dict[str, str]] = [

    # ── Ford ──────────────────────────────────────────────
    {"make": "Ford",       "model": "F-150"},
    {"make": "Ford",       "model": "Explorer"},
    {"make": "Ford",       "model": "Escape"},
    {"make": "Ford",       "model": "Fusion"},
    {"make": "Ford",       "model": "Mustang"},
    {"make": "Ford",       "model": "Edge"},
    {"make": "Ford",       "model": "Focus"},
    {"make": "Ford",       "model": "Expedition"},
    {"make": "Ford",       "model": "Ranger"},

    # ── Chevrolet ─────────────────────────────────────────
    {"make": "Chevrolet",  "model": "Silverado 1500"},
    {"make": "Chevrolet",  "model": "Impala"},
    {"make": "Chevrolet",  "model": "Malibu"},
    {"make": "Chevrolet",  "model": "Equinox"},
    {"make": "Chevrolet",  "model": "Tahoe"},
    {"make": "Chevrolet",  "model": "Suburban"},
    {"make": "Chevrolet",  "model": "Colorado"},
    {"make": "Chevrolet",  "model": "Traverse"},

    # ── GMC ───────────────────────────────────────────────
    {"make": "GMC",        "model": "Sierra 1500"},
    {"make": "GMC",        "model": "Yukon"},
    {"make": "GMC",        "model": "Terrain"},
    {"make": "GMC",        "model": "Acadia"},

    # ── Dodge / Ram / Jeep / Chrysler ─────────────────────
    {"make": "Dodge",      "model": "Ram 1500"},
    {"make": "Dodge",      "model": "Charger"},
    {"make": "Dodge",      "model": "Challenger"},
    {"make": "Dodge",      "model": "Durango"},
    {"make": "Dodge",      "model": "Grand Caravan"},
    {"make": "Jeep",       "model": "Grand Cherokee"},
    {"make": "Jeep",       "model": "Wrangler"},
    {"make": "Jeep",       "model": "Cherokee"},
    {"make": "Jeep",       "model": "Compass"},
    {"make": "Chrysler",   "model": "300"},

    # ── Honda ─────────────────────────────────────────────
    {"make": "Honda",      "model": "Civic"},
    {"make": "Honda",      "model": "Accord"},
    {"make": "Honda",      "model": "CR-V"},
    {"make": "Honda",      "model": "Pilot"},

    # ── Toyota ────────────────────────────────────────────
    {"make": "Toyota",     "model": "Camry"},
    {"make": "Toyota",     "model": "Corolla"},
    {"make": "Toyota",     "model": "Tacoma"},
    {"make": "Toyota",     "model": "Tundra"},
    {"make": "Toyota",     "model": "Highlander"},
    {"make": "Toyota",     "model": "RAV4"},

    # ── Nissan ────────────────────────────────────────────
    {"make": "Nissan",     "model": "Altima"},
    {"make": "Nissan",     "model": "Sentra"},
    {"make": "Nissan",     "model": "Rogue"},
    {"make": "Nissan",     "model": "Frontier"},

    # ── Hyundai / Kia ─────────────────────────────────────
    {"make": "Hyundai",    "model": "Sonata"},
    {"make": "Hyundai",    "model": "Elantra"},
    {"make": "Kia",        "model": "Sorento"},
    {"make": "Kia",        "model": "Soul"},

    # ── Subaru ────────────────────────────────────────────
    {"make": "Subaru",     "model": "Outback"},
    {"make": "Subaru",     "model": "Forester"},
]
