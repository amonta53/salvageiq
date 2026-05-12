# =========================================================
# taxonomy.py
# Part taxonomy, search terms, and normalization rules.
#
# Purpose:
# - Defines the standardized part categories used across the pipeline
# - Provides include/exclude matching rules for part classification
# - Supplies raw search terms used to build marketplace queries
#
# Design Notes:
# - Search terms are not the same thing as taxonomy categories
# - Taxonomy categories should remain stable for consistent analysis
# - Include/exclude rules are used to reduce false positives
# - Category priority resolves ambiguous multi-match listings
#
# Pipeline Role:
# - scrape: uses SEARCH_PART_TERMS to generate searches
# - cleanse: extracts rough text candidates from listings
# - normalize: maps raw text into standardized categories
# - analyze: groups and ranks listings by standardized category
# =========================================================


# =========================================================
# Standard part taxonomy
# Each category contains:
# - include: terms that support a match
# - exclude: terms that should suppress a match
# =========================================================

PART_TAXONOMY = {
    # ---- Lighting ----
    "Headlight Assembly": {
        "include": ["headlight", "head lamp", "headlamp", "lh headlight", "rh headlight"],
        "exclude": ["bulb", "bulbs"],
    },
    "Tail Light Assembly": {
        "include": ["tail light", "taillight", "rear lamp"],
        "exclude": ["bulb", "bulbs"],
    },
    "Fog Light Assembly": {
        "include": ["fog light", "fog lamp", "driving light"],
        "exclude": ["bulb", "bulbs", "switch"],
    },

    # ---- Exterior body ----
    "Side Mirror": {
        "include": ["mirror", "side mirror", "door mirror", "side view mirror"],
        "exclude": ["glass", "mirror glass"],
    },
    "Door Assembly": {
        "include": ["complete door", "door assembly", "door"],
        "exclude": ["door handle", "door handles"],
    },
    "Fender": {
        "include": ["fender"],
        "exclude": ["trim", "trim piece", "trim pieces"],
    },
    "Hood": {
        "include": ["hood"],
        "exclude": ["insulation", "insulation pad", "insulation pads"],
    },
    "Front Bumper Assembly": {
        "include": ["front bumper", "bumper cover"],
        "exclude": ["sensor", "sensors"],
    },
    "Rear Bumper Assembly": {
        "include": ["rear bumper"],
        "exclude": ["sensor", "sensors"],
    },
    "Grille": {
        "include": ["grille", "front grille"],
        "exclude": ["emblem", "emblems"],
    },
    "Liftgate": {
        "include": ["liftgate", "rear hatch", "hatch", "rear gate"],
        "exclude": ["handle", "latch", "hinge", "liftgate glass", "spoiler",
                    "liftgate motor", "liftgate actuator"],
    },
    "Tailgate": {
        "include": ["tailgate"],
        "exclude": ["handle", "latch", "hinge", "tailgate cable"],
    },

    # ---- Interior ----
    "Radio / Infotainment": {
        "include": ["radio", "stereo", "infotainment", "display screen"],
        "exclude": ["wiring", "wire", "harness"],
    },
    "Instrument Cluster": {
        "include": ["cluster", "speedometer", "gauge cluster"],
        "exclude": ["individual gauge", "gauge only"],
    },
    "Seat": {
        "include": ["driver seat", "passenger seat", "rear seat", "seat"],
        "exclude": ["seat cover", "seat covers"],
    },
    "Steering Wheel": {
        "include": ["steering wheel"],
        "exclude": ["button", "buttons"],
    },

    # ---- Electronics / modules ----
    "Engine Control Module": {
        "include": ["ecm", "ecu", "pcm", "engine computer"],
        "exclude": [],
    },
    "Transmission Control Module": {
        "include": ["tcm", "transmission computer"],
        "exclude": [],
    },
    "ABS Module": {
        "include": ["abs module", "abs control module", "abs pump",
                    "anti-lock brake module", "abs unit"],
        "exclude": ["abs sensor", "abs ring", "wheel speed sensor"],
    },
    "Body Control Module": {
        "include": ["bcm", "body control module", "body module"],
        "exclude": [],
    },
    "Ignition Coil": {
        "include": ["ignition coil", "coil pack", "coil on plug"],
        "exclude": ["spark plug", "ignition wire", "distributor"],
    },

    # ---- Mechanical / drivetrain ----
    "Alternator": {
        "include": ["alternator"],
        "exclude": ["rebuild kit", "rebuild kits"],
    },
    "Starter": {
        "include": ["starter", "starter motor"],
        "exclude": ["solenoid", "solenoids"],
    },
    "AC Compressor": {
        "include": ["ac compressor", "air conditioning compressor"],
        "exclude": ["line", "lines", "hose", "hoses"],
    },
    "Power Steering Pump": {
        "include": ["power steering pump", "ps pump"],
        "exclude": ["rack", "hose", "line", "fluid", "reservoir"],
    },
    "Catalytic Converter": {
        "include": ["catalytic converter", "cat converter", "catalytic"],
        "exclude": ["oxygen sensor", "o2 sensor", "flex pipe", "header"],
    },
    "Radiator": {
        "include": ["radiator"],
        "exclude": ["hose", "cap", "flush", "overflow", "coolant tank", "reservoir"],
    },
    "Blower Motor": {
        "include": ["blower motor", "hvac blower", "heater blower"],
        "exclude": ["resistor", "blower wheel", "cage"],
    },
    "Strut / Shock": {
        "include": ["strut", "strut assembly", "shock absorber",
                    "front strut", "rear strut"],
        "exclude": ["strut mount", "spring", "bearing", "boot", "spring perch"],
    },

    # ---- Wheels ----
    "Wheel / Rim": {
        "include": ["wheel", "rim"],
        "exclude": ["tire", "tires"],
    },

    # ---- Glass / window ----
    "Window Regulator": {
        "include": ["window regulator", "power window motor", "window motor"],
        "exclude": ["switch", "switches"],
    },
}

# =========================================================
# Category priority
# Used when a listing matches multiple categories.
# Higher-priority categories win.
# =========================================================
CATEGORY_PRIORITY = [
    # Modules first — most specific, least ambiguous
    "Engine Control Module",
    "Transmission Control Module",
    "ABS Module",
    "Body Control Module",
    "Ignition Coil",
    "Instrument Cluster",
    "Radio / Infotainment",
    # Mechanical
    "Alternator",
    "Starter",
    "AC Compressor",
    "Power Steering Pump",
    "Catalytic Converter",
    "Radiator",
    "Blower Motor",
    "Strut / Shock",
    # Lighting
    "Headlight Assembly",
    "Tail Light Assembly",
    "Fog Light Assembly",
    # Exterior body
    "Side Mirror",
    "Fender",
    "Hood",
    "Front Bumper Assembly",
    "Rear Bumper Assembly",
    "Grille",
    "Liftgate",
    "Tailgate",
    "Door Assembly",
    # Interior
    "Seat",
    "Steering Wheel",
    # Other
    "Wheel / Rim",
    "Window Regulator",
]

# =========================================================
# Special module term sets
# Used for direct matching or override logic where needed.
# =========================================================
ECM_TERMS = {"ecm", "ecu", "pcm", "engine computer"}
TCM_TERMS = {"tcm", "transmission computer"}
ABS_TERMS = {"abs module", "abs control module", "abs pump", "anti-lock brake module"}
BCM_TERMS = {"bcm", "body control module", "body module"}

# =========================================================
# Search part terms
# Raw query terms used to build marketplace searches.
# These are intentionally simpler than taxonomy categories.
# =========================================================
SEARCH_PART_TERMS = [
    # Lighting
    "headlight",
    "tail light",
    "fog light",
    # Exterior body
    "mirror",
    "door",
    "fender",
    "hood",
    "front bumper",
    "rear bumper",
    "grille",
    "liftgate",
    "tailgate",
    # Interior
    "radio",
    "instrument cluster",
    "seat",
    "steering wheel",
    # Electronics / modules
    "ecm",
    "tcm",
    "abs module",
    "body control module",
    "ignition coil",
    # Mechanical
    "alternator",
    "starter",
    "ac compressor",
    "power steering pump",
    "catalytic converter",
    "radiator",
    "blower motor",
    "strut",
    # Wheels / glass
    "wheel",
    "window regulator",
]

# =========================================================
# Part aliases
# Raw term -> normalized comparison term
# =========================================================
PART_ALIASES = {
    # Headlight
    "headlight": "headlight",
    "head lamp": "headlight",
    "headlamp": "headlight",
    "lh headlight": "headlight",
    "rh headlight": "headlight",

    # Tail light
    "tail light": "tail light",
    "taillight": "tail light",
    "rear lamp": "tail light",

    # Fog light
    "fog light": "fog light",
    "fog lamp": "fog light",
    "driving light": "fog light",

    # Mirror
    "mirror": "mirror",
    "side mirror": "mirror",
    "door mirror": "mirror",
    "side view mirror": "mirror",

    # Door
    "complete door": "door",
    "door assembly": "door",
    "door": "door",

    # Body panels
    "fender": "fender",
    "hood": "hood",

    # Bumpers
    "front bumper": "front bumper",
    "bumper cover": "front bumper",
    "rear bumper": "rear bumper",

    # Grille
    "grille": "grille",
    "front grille": "grille",

    # Liftgate / tailgate
    "liftgate": "liftgate",
    "rear hatch": "liftgate",
    "hatch": "liftgate",
    "rear gate": "liftgate",
    "tailgate": "tailgate",

    # Interior electronics
    "radio": "radio",
    "stereo": "radio",
    "infotainment": "radio",
    "display screen": "radio",

    "instrument cluster": "instrument cluster",
    "cluster": "instrument cluster",
    "speedometer": "instrument cluster",
    "gauge cluster": "instrument cluster",

    # Seats
    "driver seat": "seat",
    "passenger seat": "seat",
    "rear seat": "seat",
    "seat": "seat",

    # Steering
    "steering wheel": "steering wheel",

    # Control modules
    "ecm": "ecu",
    "pcm": "ecu",
    "ecu": "ecu",
    "engine computer": "ecu",

    "tcm": "tcm",
    "transmission computer": "tcm",

    "abs module": "abs module",
    "abs control module": "abs module",
    "abs pump": "abs module",
    "anti-lock brake module": "abs module",
    "abs unit": "abs module",

    "bcm": "bcm",
    "body control module": "bcm",
    "body module": "bcm",

    "ignition coil": "ignition coil",
    "coil pack": "ignition coil",
    "coil on plug": "ignition coil",

    # Mechanical
    "alternator": "alternator",

    "starter": "starter",
    "starter motor": "starter",

    "ac compressor": "ac compressor",
    "a/c compressor": "ac compressor",
    "air conditioning compressor": "ac compressor",

    "power steering pump": "power steering pump",
    "ps pump": "power steering pump",

    "catalytic converter": "catalytic converter",
    "cat converter": "catalytic converter",
    "catalytic": "catalytic converter",

    "radiator": "radiator",

    "blower motor": "blower motor",
    "hvac blower": "blower motor",
    "heater blower": "blower motor",

    "strut": "strut",
    "strut assembly": "strut",
    "shock absorber": "strut",
    "front strut": "strut",
    "rear strut": "strut",

    # Wheels / glass
    "wheel": "wheel",
    "rim": "wheel",

    "window regulator": "window regulator",
    "power window motor": "window regulator",
    "window motor": "window regulator",
}

# =========================================================
# Part to Category mapping
# Normalized alias -> taxonomy category name
# =========================================================
PART_CATEGORY_MAP = {
    # Lighting
    "headlight": "Headlight Assembly",
    "tail light": "Tail Light Assembly",
    "fog light": "Fog Light Assembly",
    # Exterior body
    "mirror": "Side Mirror",
    "door": "Door Assembly",
    "fender": "Fender",
    "hood": "Hood",
    "front bumper": "Front Bumper Assembly",
    "rear bumper": "Rear Bumper Assembly",
    "grille": "Grille",
    "liftgate": "Liftgate",
    "tailgate": "Tailgate",
    # Interior
    "radio": "Radio / Infotainment",
    "instrument cluster": "Instrument Cluster",
    "seat": "Seat",
    "steering wheel": "Steering Wheel",
    # Electronics / modules
    "ecu": "Engine Control Module",
    "tcm": "Transmission Control Module",
    "abs module": "ABS Module",
    "bcm": "Body Control Module",
    "ignition coil": "Ignition Coil",
    # Mechanical
    "alternator": "Alternator",
    "starter": "Starter",
    "ac compressor": "AC Compressor",
    "power steering pump": "Power Steering Pump",
    "catalytic converter": "Catalytic Converter",
    "radiator": "Radiator",
    "blower motor": "Blower Motor",
    "strut": "Strut / Shock",
    # Wheels / glass
    "wheel": "Wheel / Rim",
    "window regulator": "Window Regulator",
}
